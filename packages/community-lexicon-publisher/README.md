# PCV0 supervised Lexicon publisher

This separately installed operator tool publishes the eight frozen
`app.phlogiston.community.*` Lexicons. It is not an application service and must
not be installed into the observer, browser, policy-worker, or `communityd`
runtime environments.

The JSON documents in this package's `lexicons/` directory are the canonical
source for the integrated record vocabulary. The copies packaged by
`community-model` are generated runtime resources. `tools/sync_model_lexicons.py`
updates those copies, and the contract test compares the complete inventories
and canonical JSON bytes so hand-edited drift fails qualification.

The ceremony is intentionally split:

1. Provision the recoverable schema-authority account and configure its DID.
2. Generate a manifest with `pnpm start -- manifest MANIFEST.json`.
3. Have a human review it and create the strict acceptance artifact described
   below, binding the exact `manifestSha256` printed by the command.
4. Publish `_lexicon.community.phlogiston.app TXT did=<authority DID>` and wait
   until the configured resolver observes it.
5. Authenticate interactively with `pnpm start -- auth-listen <handle>`.
6. Run `pnpm start -- publish`. The tool attempts each create once, settles an
   ambiguous result only by exact readback, and emits a secret-free receipt.

Configuration:

- `PCV0_LEXICON_RUNTIME_DIR`: private OAuth and intent-journal directory.
- `PCV0_LEXICON_CALLBACK_ORIGIN`: explicit IPv4 loopback HTTP origin.
- `PCV0_LEXICON_AUTHORITY_DID`: exact DID accepted for the OAuth session.
- `PCV0_LEXICON_MANIFEST`: reviewed manifest path (publication only).
- `PCV0_LEXICON_ACCEPTANCE`: human acceptance path (publication only).
- `PCV0_LEXICON_RECEIPT`: new receipt path (publication only).

The acceptance JSON has exactly these fields:

```json
{
  "contract": "pcv0-lexicon-publication-acceptance/1",
  "manifestSha256": "sha256:<manifest digest printed by the manifest command>",
  "authorityDid": "did:plc:<schema authority>",
  "acceptedBy": "<named human maintainer>",
  "acceptedAt": "<RFC 3339 timestamp>"
}
```

The only requested OAuth scope is
`atproto repo:com.atproto.lexicon.schema?action=create`. Session material,
callback parameters, tokens, and raw error prose are never included in the
publication receipt.
