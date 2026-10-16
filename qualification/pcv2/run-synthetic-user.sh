#!/usr/bin/env bash
# Isolated PCV2 synthetic-user qualification: bring-up, driver, teardown.
# Everything is loopback or a Docker user-defined bridge with loopback-only
# published ports; all state lives in one mktemp directory that is removed on
# exit. No production identity, PDS, DID, DNS, TLS trust or room is touched.
set -Eeuo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
receipt="$root/qualification/pcv2/evidence/synthetic-user-$(date -u +%Y%m%d).json"
while test "$#" -gt 0; do
  case "$1" in
    --receipt) receipt=$2; shift 2;;
    *) echo "usage: $0 [--receipt /abs/path.json]" >&2; exit 64;;
  esac
done
case "$receipt" in /*) ;; *) echo "receipt path must be absolute" >&2; exit 64;; esac
python=${PCV2_PYTHON:-/data/git/atproto-nutrition/atproto-community/.venv/bin/python}
test -x "$python" || { echo "python with communitywatch deps not found at $python (set PCV2_PYTHON)" >&2; exit 65; }
# The run qualifies community-live's locked dependency tree only: refuse a
# node_modules borrowed from the sibling juniper-live package.
modules=$(readlink -f "$root/apps/community-live/node_modules" || true)
test -n "$modules" -a -d "$modules" || { echo "apps/community-live/node_modules is missing; run pnpm install --frozen-lockfile there" >&2; exit 65; }
case "/$modules/" in
  */juniper-live/*) echo "apps/community-live/node_modules resolves into apps/juniper-live ($modules); install from apps/community-live/pnpm-lock.yaml with pnpm install --frozen-lockfile" >&2; exit 65;;
esac
image='ghcr.io/bluesky-social/pds@sha256:d155af1c906d7848e7dea9d59a8a7def065a04b77aa98ae56ea05a8d4eadb63a'
# community-policy must present a different OS UID than the web peer on the
# communityd socket, so the driver runs it as UID+1 inside this base image
# with the host's /usr (and so the interpreter behind $python) mounted
# read-only; the image only supplies the root filesystem skeleton.
policy_image=${PCV2_POLICY_IMAGE:-ubuntu:24.04}
policy_python=$(readlink -f "$python")
case "$policy_python" in /usr/*) ;; *) echo "the python behind $python ($policy_python) is not under /usr; the policy worker container cannot run it" >&2; exit 65;; esac
docker image inspect "$policy_image" >/dev/null 2>&1 || { echo "policy worker base image $policy_image is not present locally (set PCV2_POLICY_IMAGE)" >&2; exit 65; }
run="pcv2-synthetic-$$"
scratch=$(mktemp -d /tmp/pcv2-synthetic-user-XXXXXX)
chmod 700 "$scratch"
net="$run-net"; plc="$run-identity"
declare -A pds=([community]="$run-pds-community" [participant]="$run-pds-participant" [moderator]="$run-pds-moderator")
cleanup() {
  for name in "${pds[@]}"; do docker rm -f "$name" >/dev/null 2>&1 || true; done
  docker rm -f "$plc" >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
  for role in community participant moderator; do
    test -d "$scratch/pds-$role" || continue
    docker run --rm --network none --entrypoint sh --mount type=bind,source="$scratch/pds-$role",target=/state "$image" -c "chown -R $(id -u):$(id -g) /state" >/dev/null 2>&1 || true
  done
  rm -rf "$scratch"
}
trap cleanup EXIT

# Three free loopback ports. PDS 0.5.34 fixes its public URL to
# http://localhost:<PDS_PORT> in dev mode, so each container listens on its
# published host port number and is published on both loopback literals.
read -r port_community port_participant port_moderator < <("$python" - <<'PY'
import socket
ports = []
sockets = []
for _ in range(3):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); ports.append(s.getsockname()[1]); sockets.append(s)
for s in sockets: s.close()
print(*ports)
PY
)

# Self-signed loopback certificate for the room webhook stand-in; the notify
# process trusts it through SSL_CERT_FILE only.
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 2 \
  -keyout "$scratch/webhook-key.pem" -out "$scratch/webhook-cert.pem" \
  -subj "/CN=pcv2 synthetic room" -addext "subjectAltName=IP:127.0.0.1" >/dev/null 2>&1

docker network create "$net" >/dev/null
docker run -d --name "$plc" --network "$net" --network-alias identity -p 127.0.0.1::2582 \
  --read-only --tmpfs /tmp --mount type=bind,source="$root/qualification/pcv2/identity-stub.js",target=/identity-stub.js,readonly \
  --entrypoint node "$image" /identity-stub.js >/dev/null
start_pds() {
  local role=$1 port=$2 keyhex=$3
  mkdir "$scratch/pds-$role"
  docker run -d --name "${pds[$role]}" --network "$net" -p "127.0.0.1:$port:$port" -p "[::1]:$port:$port" \
    --read-only --tmpfs /tmp --mount type=bind,source="$scratch/pds-$role",target=/app/data \
    -e PDS_HOSTNAME=localhost -e "PDS_PORT=$port" -e PDS_DEV_MODE=true \
    -e PDS_DATA_DIRECTORY=/app/data -e PDS_BLOBSTORE_DISK_LOCATION=/app/data/blocks \
    -e PDS_INVITE_REQUIRED=false -e PDS_CRAWLERS= -e PDS_DID_PLC_URL=http://identity:2582 \
    -e "PDS_PLC_ROTATION_KEY_K256_PRIVATE_KEY_HEX=$keyhex" \
    -e "PDS_JWT_SECRET=synthetic-$role-jwt-not-production" \
    -e "PDS_ADMIN_PASSWORD=synthetic-$role-admin-password" "$image" >/dev/null
}
start_pds community "$port_community" 0000000000000000000000000000000000000000000000000000000000000001
start_pds participant "$port_participant" 0000000000000000000000000000000000000000000000000000000000000002
start_pds moderator "$port_moderator" 0000000000000000000000000000000000000000000000000000000000000003
for attempt in $(seq 1 40); do
  ok=1
  for port in "$port_community" "$port_participant" "$port_moderator"; do
    curl -sf "http://127.0.0.1:$port/xrpc/_health" >/dev/null 2>&1 || ok=0
  done
  test "$ok" = 1 && break
  test "$attempt" != 40 || { echo "PDS containers did not become healthy" >&2; exit 1; }
  sleep 1
done
plc_port=$(docker port "$plc" 2582/tcp | sed -n 's/.*://p' | head -1)

mkdir -p "$(dirname "$receipt")"
export PCV2_ROOT="$root" PCV2_SCRATCH="$scratch/run" PCV2_PLC="http://127.0.0.1:$plc_port"
export PCV2_PDS_COMMUNITY="http://localhost:$port_community" PCV2_PDS_PARTICIPANT="http://localhost:$port_participant" PCV2_PDS_MODERATOR="http://localhost:$port_moderator"
export PCV2_PDS_IMAGE="$image" PCV2_RECEIPT="$receipt" PCV2_PYTHON="$python"
export PCV2_POLICY_IMAGE="$policy_image" PCV2_POLICY_PYTHON="$policy_python"
export PCV2_TLS_CERT="$scratch/webhook-cert.pem" PCV2_TLS_KEY="$scratch/webhook-key.pem"
export PCV2_SOURCE_COMMIT="$(git -C "$root" rev-parse HEAD)$(git -C "$root" diff --quiet HEAD -- apps/community-live packages qualification || echo '-dirty')"
mkdir -m 700 "$scratch/run"
status=0
node "$root/qualification/pcv2/driver.mjs" || status=$?
if test -n "${PCV2_KEEP_LOGS:-}"; then
  mkdir -p "$PCV2_KEEP_LOGS" && cp -r "$scratch/run/logs" "$PCV2_KEEP_LOGS/" 2>/dev/null || true
fi
test -s "$receipt"
exit "$status"
