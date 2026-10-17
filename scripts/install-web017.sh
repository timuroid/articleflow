#!/usr/bin/env bash
# Install a checked Web 017 release without changing the existing reverse proxy.
set -euo pipefail

if [[ $EUID -ne 0 || $# -ne 1 ]]; then
  echo 'Usage as root: install-web017.sh /path/to/articleflow-web-017.tar.gz' >&2
  exit 2
fi
archive=$(realpath "$1")
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 "$root/scripts/audit_web_release.py" "$archive" >/dev/null
digest=$(sha256sum "$archive" | awk '{print $1}')
release="/opt/articleflow/releases/${digest:0:16}"
if [[ -e /opt/articleflow/current || -e "$release" || -e /etc/systemd/system/articleflow.service ]]; then
  echo 'An ArticleFlow installation already exists; inspect it before updating.' >&2
  exit 3
fi
if ss -ltn | awk '{print $4}' | grep -Eq '(^|:)8769$'; then
  echo 'Port 8769 is already in use.' >&2
  exit 3
fi

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv python3-pip fontconfig >/dev/null
if ! id articleflow >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/articleflow --shell /usr/sbin/nologin articleflow
fi
install -d -m 0755 /opt/articleflow/releases
install -d -o articleflow -g articleflow -m 0700 /var/lib/articleflow
install -d -m 0755 "$release"
tar -xzf "$archive" -C "$release" --strip-components=1
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -m pip install --no-cache-dir "$release[web]" >/dev/null
ln -s "$release" /opt/articleflow/current
cat >/etc/systemd/system/articleflow.service <<'UNIT'
[Unit]
Description=ArticleFlow Web 017 local review
After=network.target

[Service]
Type=simple
User=articleflow
Group=articleflow
WorkingDirectory=/opt/articleflow/current
Environment=ARTICLEFLOW_DATA_DIR=/var/lib/articleflow
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=/opt/articleflow/current/.venv/bin/uvicorn articleflow.web017:create_app --factory --host 127.0.0.1 --port 8769 --workers 1 --no-access-log
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/articleflow

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now articleflow >/dev/null
for _ in {1..20}; do
  if curl --fail --silent http://127.0.0.1:8769/healthz >/dev/null; then
    echo "Installed release ${digest:0:16}; service healthy on loopback."
    exit 0
  fi
  sleep 1
done
echo 'Service did not become healthy; inspect systemctl status articleflow.' >&2
exit 4
