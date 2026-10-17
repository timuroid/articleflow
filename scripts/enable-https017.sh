#!/usr/bin/env bash
# Add one Caddy site. Existing site blocks and listeners are preserved.
set -euo pipefail

if [[ $EUID -ne 0 || $# -ne 1 || ! "$1" =~ ^[a-z0-9][a-z0-9.-]+[a-z0-9]$ ]]; then
  echo 'Usage as root: enable-https017.sh fully.qualified.domain' >&2
  exit 2
fi
domain=$1
site=/etc/caddy/articleflow.caddy
main=/etc/caddy/Caddyfile
password_file=/root/articleflow-http-password
if [[ ! -f "$main" || -e "$site" ]] || grep -Fq "$domain" "$main" /etc/caddy/service-atlas.caddy 2>/dev/null; then
  echo 'Caddy configuration is missing or the site already exists; inspect manually.' >&2
  exit 3
fi
if ! systemctl is-active --quiet caddy || ! systemctl is-active --quiet articleflow; then
  echo 'Caddy and ArticleFlow must be active before adding the site.' >&2
  exit 3
fi
if [[ ! -f "$password_file" ]]; then
  umask 077
  openssl rand -base64 32 >"$password_file"
fi
chmod 0600 "$password_file"
hash=$(caddy hash-password <"$password_file")
backup="/root/articleflow-Caddyfile-$(date -u +%Y%m%dT%H%M%SZ).bak"
install -m 0600 "$main" "$backup"
cat >"$site" <<SITE
$domain {
    encode zstd gzip
    basicauth {
        owner $hash
    }
    reverse_proxy 127.0.0.1:8769
}
SITE
chown root:caddy "$site"
chmod 0640 "$site"
printf '\nimport %s\n' "$site" >>"$main"
if ! caddy validate --config "$main" >/dev/null; then
  cp "$backup" "$main"
  rm "$site"
  echo 'Caddy validation failed; original configuration restored.' >&2
  exit 4
fi
if ! systemctl reload caddy; then
  cp "$backup" "$main"
  rm "$site"
  systemctl reload caddy || true
  echo 'Caddy reload failed; original configuration restored.' >&2
  exit 4
fi
echo "Caddy site added for $domain. Credential is stored in $password_file (root only)."
