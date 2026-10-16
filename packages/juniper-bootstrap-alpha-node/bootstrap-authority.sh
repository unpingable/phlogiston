#!/bin/sh
set -eu

package=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository=$(git -C "$package" rev-parse --show-toplevel)
runtime=$(mktemp -d /tmp/juniper-bootstrap-authority.XXXXXX)

cleanup() {
    case "$runtime" in
        /tmp/juniper-bootstrap-authority.*) rm -rf -- "$runtime" ;;
        *) printf '%s\n' 'juniper_bootstrap_cleanup_refused' >&2 ;;
    esac
}
trap cleanup EXIT HUP INT TERM

export JUNIPER_BOOTSTRAP_RUNTIME_DIR="$runtime"
export JUNIPER_BOOTSTRAP_CALLBACK_ORIGIN=http://127.0.0.1:8765
export JUNIPER_BOOTSTRAP_LEXICON_DIR="$repository/packages/community-space-wire/src/community_space_wire/lexicons"

cd "$package"
printf '%s\n' 'Authorize the short-lived Lexicon URL printed below immediately.'
node --import tsx src/worker.ts auth-listen lexicons authority.juniper-pds.sp00ky.net
node --import tsx src/worker.ts publish-lexicons
printf '%s\n' 'Authorize the short-lived Space URL printed below immediately.'
node --import tsx src/worker.ts auth-listen space authority.juniper-pds.sp00ky.net
node --import tsx src/worker.ts create-space
