"""One-pass semantic planner with a persistent, locked OpenRouter budget.

No network call is made on import. A separately provisioned checkpoint and
private prompt are mandatory. Curl receives credentials over stdin, never argv.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .docx_engine import DocumentError
from .structure017 import SLOTS


def save_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def read_key(path):
    import re
    text = path.read_text().strip()
    if text.startswith("sk-or-"):
        key = text
    else:
        match = re.search(r'^OPENROUTER_API_KEY\s*=\s*["\x27]?([^\s"\x27]+)', text, re.M)
        key = match.group(1) if match else ""
    if not re.fullmatch(r"sk-or-v1-[a-zA-Z0-9]+", key):
        raise DocumentError("OPENROUTER_KEY_INVALID")
    return key


def api(key, endpoint, body=None):
    if endpoint not in {"key", "credits", "models", "chat/completions"}:
        raise DocumentError("PROVIDER_ENDPOINT_INVALID")
    config = 'url = "https://openrouter.ai/api/v1/' + endpoint + '"\n'
    config += 'header = "Authorization: Bearer ' + key + '"\n'
    config += 'header = "Content-Type: application/json"\n'
    if body is not None:
        # curl configuration escaping, not shell quoting. No shell involved.
        encoded = json.dumps(body, ensure_ascii=False).replace("\\", "\\\\").replace('"', '\\"')
        config += 'data = "' + encoded + '"\n'
    result = subprocess.run(["curl", "--silent", "--show-error", "--max-time", "180" if body else "30",
                             "--write-out", "\n%{http_code}", "--config", "-"], input=config,
                            capture_output=True, text=True)
    if result.returncode:
        raise DocumentError("PROVIDER_TRANSPORT_ERROR")
    raw, status = result.stdout.rsplit("\n", 1)
    try:
        data = json.loads(raw)
    except ValueError:
        raise DocumentError("PROVIDER_JSON_ERROR") from None
    return int(status), data


def account(key):
    status, info = api(key, "key")
    cstatus, credit = api(key, "credits")
    if status != 200 or cstatus != 200:
        raise DocumentError("BALANCE_CHECK_FAILED")
    d, c = info["data"], credit["data"]
    remaining = Decimal(str(c["total_credits"])) - Decimal(str(c["total_usage"]))
    limits = [remaining]
    if d.get("limit_remaining") is not None:
        limits.append(Decimal(str(d["limit_remaining"])))
    if d.get("effective_budget"):
        limits.append(Decimal(str(d["effective_budget"]["remaining_usd"])))
    return {"usage_usd": str(d["usage"]), "available_usd": str(min(limits)),
            "at": datetime.now(timezone.utc).isoformat()}


def initialize_checkpoint(key_file, ledger, cap):
    """Explicit provisioning only. Never overwrite/reset an existing ledger."""
    if ledger.exists():
        raise DocumentError("LEDGER_ALREADY_EXISTS")
    state = account(read_key(key_file))
    cap = Decimal(str(cap))
    if not cap.is_finite() or cap <= 0 or cap > Decimal(state["available_usd"]):
        raise DocumentError("INVALID_BUDGET")
    save_private(ledger, {"schema": "budget-checkpoint-019", "baseline": state,
                         "additional_cap_usd": str(cap), "historical_attempts_available": False,
                         "attempts": []})
    return state


def validate_plan(plan, blocks, contexts):
    if not isinstance(plan, dict) or set(plan) != {"blocks"} or not isinstance(plan["blocks"], list):
        raise DocumentError("MODEL_PLAN_SCHEMA")
    ids = [b["id"] for b in blocks]
    rows = plan["blocks"]
    if len(rows) != len(ids) or any(not isinstance(b, dict) or set(b) != {"id", "role", "context"} for b in rows):
        raise DocumentError("MODEL_PLAN_COVERAGE")
    if [b["id"] for b in rows] != ids:
        raise DocumentError("MODEL_PLAN_COVERAGE")
    for row, source in zip(rows, blocks):
        if row["role"] not in (*SLOTS, "editorial") or row["context"] not in contexts:
            raise DocumentError("MODEL_PLAN_ROLE")
        context = row["context"]
        if context != "auto" and context.split(".")[0] != row["role"]:
            raise DocumentError("MODEL_PLAN_CONTEXT")
        if source["kind"] == "table" and (row["role"] != "body" or context not in {"auto", "body.table"}):
            raise DocumentError("TABLE_SEMANTICS_REVIEW")
    return {b["id"]: b["role"] for b in rows}, {b["id"]: b["context"] for b in rows if b["context"] != "auto"}


def plan_document(blocks, style_keys, config, run_dir):
    ledger = Path(config["ledger"])
    prompt_path = Path(config["prompt"])
    if not ledger.is_file() or not prompt_path.is_file():
        raise DocumentError("MODEL_NOT_PROVISIONED")
    contexts = sorted({"auto", "editorial"} | {k for k in style_keys if not k.startswith("__")})
    prompt = prompt_path.read_text()
    request = {"model": config["model"], "max_tokens": 4096, "stream": False,
               "provider": {"allow_fallbacks": False, "require_parameters": True},
               "reasoning": {"effort": config.get("reasoning_effort", "none"), "exclude": True},
               "messages": [{"role": "system", "content": prompt},
                            {"role": "user", "content": json.dumps({"roles": list(SLOTS)+["editorial"],
                              "contexts": contexts, "blocks": blocks}, ensure_ascii=False)}],
               "response_format": {"type": "json_object"}}
    key = read_key(Path(config["key_file"]))
    run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    save_private(run_dir / "request.json", request)
    metadata = {"model": config["model"], "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "request_sha256": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest(),
                "api_attempts": 0, "repair_calls": 0, "status": "not_sent"}
    # Serialize both reservation and actual call across processes/workers.
    fd = os.open(ledger.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(ledger.read_text())
        if state.get("read_only"):
            raise DocumentError("LEDGER_READ_ONLY")
        # The older planner has no carry-over reserve accounting. A recovered
        # epoch must only be spent through provider023 until this path supports
        # its complete budget contract.
        if state.get("schema") == "budget-recovery-036":
            raise DocumentError("LEDGER_SCHEMA_UNSUPPORTED")
        balance = account(key)
        status, models = api(key, "models")
        if status != 200:
            raise DocumentError("PRICING_UNAVAILABLE")
        model = next((m for m in models["data"] if m["id"] == config["model"]), None)
        if model is None:
            raise DocumentError("MODEL_UNAVAILABLE")
        pricing = model["pricing"]
        in_rates = [Decimal(str(pricing.get(k) or 0)) for k in ("prompt", "input_cache_read", "input_cache_write")]
        out_rates = [Decimal(pricing["completion"])]
        for override in pricing.get("overrides", []):
            in_rates.extend(Decimal(str(override.get(k) or 0)) for k in ("prompt", "input_cache_read", "input_cache_write"))
            out_rates.append(Decimal(str(override.get("completion") or pricing["completion"])))
        reserve = Decimal(len(json.dumps(request).encode()) + 4096) * max(in_rates) + Decimal(4096) * max(out_rates)
        accounted = sum((Decimal(str(a.get("cost_usd") if a.get("cost_usd") is not None else a["reserve_usd"])) for a in state["attempts"]), Decimal(0))
        provider_delta = Decimal(balance["usage_usd"]) - Decimal(state["baseline"]["usage_usd"])
        if max(accounted, provider_delta) + reserve > Decimal(state["additional_cap_usd"]) or reserve > Decimal(balance["available_usd"]):
            raise DocumentError("BUDGET_EXCEEDED")
        attempt = {"id": uuid.uuid4().hex, "at": balance["at"], "model": config["model"],
                   "reserve_usd": str(reserve), "cost_usd": None, "status": "reserved"}
        state["attempts"].append(attempt)
        save_private(ledger, state)
        start = time.monotonic()
        metadata["api_attempts"] = 1
        try:
            status, response = api(key, "chat/completions", request)
            metadata["http_status"] = status
            save_private(run_dir / "response.json", response)
            cost = response.get("usage", {}).get("cost")
            if cost is not None:
                decimal_cost = Decimal(str(cost))
                if decimal_cost.is_finite() and decimal_cost >= 0:
                    attempt["cost_usd"] = str(decimal_cost)
            if status != 200:
                raise DocumentError("PROVIDER_HTTP_" + str(status))
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise DocumentError("MODEL_INCOMPLETE")
            plan = json.loads(choice["message"]["content"])
            assignments, format_contexts = validate_plan(plan, blocks, contexts)
            save_private(run_dir / "plan.json", plan)
            attempt["status"] = "valid"
            metadata["status"] = "valid"
        except Exception as error:
            attempt["status"] = str(error) if isinstance(error, DocumentError) else "MODEL_INVALID_RESPONSE"
            metadata["status"] = attempt["status"]
        finally:
            metadata.update(cost_usd=attempt["cost_usd"], reserve_usd=attempt["reserve_usd"], seconds=time.monotonic()-start)
            save_private(ledger, state)
            save_private(run_dir / "meta.json", metadata)
    if metadata["status"] != "valid":
        raise DocumentError(metadata["status"])
    return assignments, format_contexts, metadata
