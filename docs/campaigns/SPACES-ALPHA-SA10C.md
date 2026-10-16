# SA10c — source-host migration qualification

Status: fixture-qualified on 2026-08-21.

SA10c compares two ordered SA9c-resolution/SA9b-service-binding epochs for the
same DID and the same account-PDS or Space-host interpretation profile. A
receipt requires a distinct document, method receipt, selected origin, and a
later bounded qualification observation. It designates the successor origin
for future acquisition while retaining every named historical artifact at the
prior origin.

This proves only a bounded change between supplied identity-evidence epochs.
It does not prove global DID currentness, canonical truth, remote control,
artifact validity, rollback safety beyond the supplied ordering, standing,
authorization, or governance authority. A stale epoch cannot replace a newer
one; a different DID/profile, same-origin relabel, reused resolution, or
retroactive attribution is refused. Redirects remain governed by SA9a/SA9d-d,
and split-brain or same-revision repository states remain SA6
`insufficient_evidence`; host selection does not resolve them.

The replacement boundary is `host_migration.py`. DID-method qualification,
service interpretation, HTTP acquisition, and repository evidence remain
unchanged and independently addressable.
