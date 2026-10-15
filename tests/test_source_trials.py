import json
import unittest
from unittest.mock import patch

import test_catalogue as fixtures
from articleflow.context_rules import fit_rules
from articleflow.docx_engine import DocumentError, dump
from articleflow.source_trials import role_request, run_source_trials


class SourceTrialTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CatalogueTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        self.catalogue, self.registry, self.ledger = [f.root / x for x in ["models.json", "registry.json", "ledger.json"]]
        dump(self.catalogue, {"data": [{"id": "test/current", "supported_parameters": ["reasoning", "structured_outputs"],
            "context_length": 1000000, "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]})
        dump(self.registry, {"release_after": "2026-06-30", "models": [{"id": "test/current", "release_date": "2026-08-01",
            "source_type": "official_release_log", "source": "https://example.org/release"}]})
        dump(self.ledger, [])
        self.rules = f.root / "rules.json"
        pack, _ = fit_rules(f.template, f.content, f.plan, f.plan["template_sha256"])
        dump(self.rules, pack)
        self.options = dict(template_dir=f.package / "template", content_dir=f.package / "content", rules_path=self.rules,
            source=f.source, oracle_path=f.root / "NO_TARGET_ORACLE", golden_pdf=f.root / "NO_GOLDEN",
            catalogue=self.catalogue, registry=self.registry, ledger=self.ledger, key_file=None,
            output=f.root / "trials", model="test/current")

    def test_model_input_has_no_source_formatting_or_target_assignments(self):
        messages, schema = role_request(self.f.template, self.f.content)
        data = json.loads(messages[1]["content"])
        self.assertEqual(set(data), {"roles", "blocks"})
        for block in data["blocks"]:
            self.assertEqual(set(block), {"id", "text", "in_table", "atom_kinds"})
        self.assertNotIn("paragraph_style", json.dumps(messages))
        self.assertEqual(set(schema["properties"]["blocks"]["items"]["properties"]), {"id", "role"})

    def test_failed_attempt_is_kept_and_no_target_read_or_repair(self):
        with patch("articleflow.source_trials.one_model_call", return_value={"status": "invalid_model_output", "cost_usd": "0.01", "model_calls": 1}) as call:
            rows = run_source_trials(**self.options)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(rows[0]["status"], "invalid_model_output")
        self.assertFalse(rows[0]["observed_full_match"])
        self.assertFalse(rows[0]["strict_I1_pass"])
        self.assertTrue(rows[0]["source_formatting_used"])

    def test_changed_series_settings_rejected_before_api(self):
        with patch("articleflow.source_trials.one_model_call", return_value={"status": "invalid_model_output", "cost_usd": "0.01"}):
            run_source_trials(**self.options)
        with patch("articleflow.source_trials.one_model_call") as call, self.assertRaisesRegex(DocumentError, "SERIES_CONFIGURATION_CHANGED"):
            run_source_trials(**self.options, first=2, reasoning_effort="low")
        call.assert_not_called()

    def test_stale_neutral_content_rejected_before_api(self):
        content = self.f.content
        content["blocks"][0]["text"] += "changed"
        dump(self.f.package / "content/content.json", content)
        with patch("articleflow.source_trials.one_model_call") as call, self.assertRaisesRegex(DocumentError, "SOURCE_CONTENT_MISMATCH"):
            run_source_trials(**self.options)
        call.assert_not_called()
