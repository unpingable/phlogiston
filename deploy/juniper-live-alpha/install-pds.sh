#!/bin/sh
set -eu

root=/home/jbeck/juniper-alpha-pds
environment="$root/pds.env"
data="$root/data"
image_data="$root/image-data"
image='ghcr.io/bluesky-social/atproto:pds-spaces-alpha@sha256:bc8ad28e0082b3098a38ac95eb15f2d2f37392d2a287799ab7b5ab9917975e32'
container=juniper-spaces-pds-alpha

if docker container inspect "$container" >/dev/null 2>&1; then
    echo 'juniper_pds_install_refused: container already exists' >&2
    exit 1
fi
if [ -e "$environment" ]; then
    echo 'juniper_pds_install_refused: environment already exists' >&2
    exit 1
fi

umask 077
install -d -m 700 "$root" "$data" "$data/blocks" "$image_data"
{
    printf '%s\n' \
        'PDS_HOSTNAME=juniper-pds.sp00ky.net' \
        'PDS_PORT=3001' \
        'PDS_DATA_DIRECTORY=/pds' \
        'PDS_BLOBSTORE_DISK_LOCATION=/pds/blocks'
    printf 'PDS_REPO_SIGNING_KEY_K256_PRIVATE_KEY_HEX='
    openssl rand -hex 32
    printf 'PDS_PLC_ROTATION_KEY_K256_PRIVATE_KEY_HEX='
    openssl rand -hex 32
    printf 'PDS_DPOP_SECRET='
    openssl rand -hex 32
    printf 'PDS_JWT_SECRET='
    openssl rand -hex 32
    printf 'PDS_ADMIN_PASSWORD='
    openssl rand -hex 32
    printf '%s\n' \
        'PDS_DID_PLC_URL=https://plc.directory' \
        'PDS_BSKY_APP_VIEW_URL=https://api.bsky.app' \
        'PDS_BSKY_APP_VIEW_DID=did:web:api.bsky.app' \
        'PDS_CRAWLERS=' \
        'PDS_INVITE_REQUIRED=1' \
        'PDS_DISABLE_SSRF_PROTECTION=0' \
        'PDS_OAUTH_PROVIDER_NAME=Juniper Commons disposable alpha' \
        'LOG_ENABLED=1' \
        'LOG_LEVEL=info' \
        'NODE_ENV=production'
} >"$environment"
chmod 600 "$environment"

docker pull "$image" >/dev/null
docker create \
    --name "$container" \
    --network host \
    --env-file "$environment" \
    --volume "$data:/pds" \
    --volume "$image_data:/app/data" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --memory 1g \
    --cpus 1 \
    --pids-limit 256 \
    "$image" >/dev/null

printf '%s\n' 'juniper_pds_installed'
