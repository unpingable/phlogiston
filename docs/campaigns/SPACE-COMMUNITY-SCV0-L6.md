# SCV0-L6 — isolated community authority transport

Status: deterministic qualification complete 2026-08-24; live actor OAuth
provisioning pending.

## Composition

```text
local OS principal
  -> communityd-spaces-alpha request validation
  -> exact per-occurrence authorization
  -> append-only occurrence consumption
  -> isolated Node OAuth process
  -> one createRecord attempt
  -> exact getRecord readback only if the result is ambiguous
```

`packages/communityd-alpha-node` is a separate dependency and runtime from the
Juniper browser. It restores only the configured community-actor OAuth session
and permits only the experimental admission/removal collections. Conversely,
the browser writer now rejects those authority collections before network
access.

The Python authority process passes a validated record over stdin. The child
returns only URI, CID, and created/existing status. It has no observer path,
public-artifact path, author action store, browser cookie, or projection code.
Neither side retries a write. Exact readback may settle a lost response; a
different existing record is a hard conflict.

## Operator OAuth provisioning

The authority worker supports two explicit, local-only provisioning steps:
`auth-start <handle>` emits an authorization URL and `auth-callback <exact-url>`
consumes the resulting loopback callback. The configured callback must be an
explicit `http://127.0.0.1:<port>` origin. This requires a deliberate operator
interaction (and normally an SSH port-forward on deployment); it is not a
remote moderation interface. State/session files remain mode 0600 below the
authority-only runtime directory.

## Refusals

Witnesses cover unsupported collection substitution, exact URI substitution,
conflicting readback, child failure/malformed or extra secret-shaped output,
cross-collection CLI input, local-principal mismatch, short-lived
authorization, and durable semantic occurrence replay. Full existing
`communityd` tests remain green.

This transport proves only which bounded authority write was attempted and
returned. It does not admit the record into projection until the observer
independently reacquires and qualifies it.
