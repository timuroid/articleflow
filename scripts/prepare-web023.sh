#!/bin/bash
set -euo pipefail
archive=$1
expected=$2
commit=$3
actual=$(sha256sum "$archive" | cut -d' ' -f1)
[[ "$actual" == "$expected" ]]
release="/opt/articleflow/releases/${actual:0:16}"
[[ ! -e "$release" ]]
mkdir -m 755 "$release"
tar -xzf "$archive" --strip-components=1 -C "$release"
python3 "$release/scripts/audit_web_release.py" "$archive" > /root/articleflow-023-release-audit.json
/opt/articleflow/current/.venv/bin/python - <<'PY' > /root/articleflow-023-constraints.txt
import importlib.metadata
for d in importlib.metadata.distributions():
 if d.metadata['Name'].lower() != 'articleflow-research': print(d.metadata['Name']+'=='+d.version)
PY
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --quiet --no-cache-dir -c /root/articleflow-023-constraints.txt "$release[web,dev]"
printf '%s' "$commit" > "$release/RELEASE_COMMIT"
chown -R root:root "$release"
printf 'Prepared %s\n' "$release"
