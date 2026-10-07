#!/usr/bin/env bash
# Provision mem0 consumer keys for pi consumers (run once per fresh install).
#
#   MEM0_ADMIN_API_KEY=... ./provision-keys.sh
#
# Creates the first admin account when the database is empty, then one
# non-admin consumer key per consumer: `pi-personal` (the personal agent) and
# `pi-fleet` (the bots container). Keys are shown ONCE — store them in
# Bitwarden (folder `pi`): items `mem0 pi` and `mem0 fleet`, password fields.
# The admin account credentials go to `mem0 admin`.
#
# Note: on this server a consumer key is not scoped to a namespace — it only
# removes admin powers (/configure, /reset, unfiltered listing) and can be
# revoked per consumer. Namespaces stay client-side.
set -euo pipefail

base="${MEM0_URL:-https://memory.sudakov.site}"
admin="${MEM0_ADMIN_API_KEY:?MEM0_ADMIN_API_KEY is required}"

request() {
  curl -fsS -H "X-API-Key: $admin" -H 'Content-Type: application/json' "$@"
}

if [ "$(request "$base/auth/setup-status" | jq -r .needsSetup)" = "true" ]; then
  password="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  request -X POST "$base/auth/register" \
    -d "{\"name\":\"denis\",\"email\":\"sudakov.denis.2007@gmail.com\",\"password\":\"$password\"}" >/dev/null
  echo "Admin account created (mem0 dashboard login) — store in Bitwarden item 'mem0 admin':"
  echo "  email:    sudakov.denis.2007@gmail.com"
  echo "  password: $password"
  echo
fi

for label in pi-personal pi-fleet; do
  key="$(request -X POST "$base/api-keys" -d "{\"label\":\"$label\"}" | jq -r .key)"
  echo "$label key: $key"
done

echo
echo "Store the two keys in Bitwarden (folder pi): 'mem0 pi' and 'mem0 fleet'."
