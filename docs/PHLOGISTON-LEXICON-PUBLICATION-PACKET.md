# Phlogiston community Lexicon publication packet

Status: ready for a separately authorized publication ceremony. Nothing in
this packet authorizes DNS changes, OAuth enrollment, or record creation.

## Canonical authority

The only canonical documents are the eight JSON files in
`packages/community-lexicon-publisher/lexicons/` at the pinned community
source revision. `community-model` contains generated consumers; run
`python3 tools/sync_model_lexicons.py --check` before and after publication so
a hand-edited copy cannot become normative.

The permanent namespace is `app.phlogiston.community.*`, whose reverse-DNS
authority is `community.phlogiston.app`. Publication uses collection
`com.atproto.lexicon.schema`, one record per NSID with the NSID as its rkey.
The frozen document SHA-256 values below hash the publisher's stable JSON
encoding, not the newline-terminated source files. They match
`src/contract.ts` and `docs/PHLOGISTON-NAMESPACE.md` at this source revision.

| NSID | SHA-256 |
|---|---|
| `app.phlogiston.community.admission` | `fe9b1a8bdf4b60e7b7cb588b862c624e7ee71f70bb77c1a4a723d8a3d8baedd9` |
| `app.phlogiston.community.memberAction` | `549ef10d92c04dbf5b020003bcbd62c8edc9e2eb0397268cbf85e23898038fe1` |
| `app.phlogiston.community.modAction` | `e7879aed2706e35a65ebf97cd5c94fdd3c8e4f54cb84e00a5d821c704f94915f` |
| `app.phlogiston.community.profile` | `e1c9a1e30aefab5f579bef2cc2caa069fe1c102a2692776b47f96db32b537d3a` |
| `app.phlogiston.community.replyAction` | `0353e6f3c8af0c7760952009eff377966009600ea32bbd147fea2e5b69070bdb` |
| `app.phlogiston.community.replyAdmission` | `4f8e4cd50d9f39768a04ec281d26cc02bfceb5796d7752e0f8f4a27606aef6e1` |
| `app.phlogiston.community.replyPolicy` | `5f8b5a724339d0893b6612bb0ac656e305eb117b390459c6773f09215b8c7332` |
| `app.phlogiston.community.submit` | `0d1cb4ed8b80a77332904f24ed701d8731950f491999dbbf46ff7c604b6d3c96` |

## Separately authorized ceremony

1. Enroll the owner-selected dedicated `lexicon.phlogiston.app` publisher on
   the existing invite-only `phlogiston.social` PDS. Keep public registration
   closed. Record its assigned DID, resolved PDS origin and recovery custodian;
   prove `_atproto.lexicon.phlogiston.app` binds the handle to that DID. The
   account is distinct from the community actor and authors. Account
   provisioning may use the PDS administration boundary, but publication uses
   the account's normal OAuth session and repository API, not admin record
   injection.
2. Set the private `PCV0_LEXICON_RUNTIME_DIR`, explicit IPv4-loopback
   `PCV0_LEXICON_CALLBACK_ORIGIN`, and exact `PCV0_LEXICON_AUTHORITY_DID`.
3. From `packages/community-lexicon-publisher`, run
   `pnpm start -- manifest MANIFEST.json`. Review the complete manifest and
   retain its printed `manifestSha256`.
4. Produce the strict human-acceptance JSON described in the package README.
5. Publish `_lexicon.community.phlogiston.app TXT did=<authority DID>` and prove
   the configured resolver observes that exact value.
6. Run `pnpm start -- auth-listen <authority handle>`. The tool requests only
   `atproto repo:com.atproto.lexicon.schema?action=create` and refuses a DID
   mismatch.
7. Set `PCV0_LEXICON_MANIFEST`, `PCV0_LEXICON_ACCEPTANCE`, and a new
   `PCV0_LEXICON_RECEIPT`; run `pnpm start -- publish` once.
8. Verify all eight exact records by URI and CID/readback, retain the
   secret-free receipt, and rerun the generated-copy drift check.

The publisher has a pre-dispatch intent journal and reconciles an ambiguous
response by exact readback. A missing readback from an attempted operation
remains unknown and refuses another create; only exact matching readback
settles it. The journal uses atomic pathname replacement, so its ordinary
filesystem persistence is not an independently qualified power-loss claim.

## Replacement and rollback boundary

These NSIDs are permanent public protocol identifiers. There is no ordinary
"rollback" that makes a published schema disappear. Before publication, abort
by retaining the manifest and publishing nothing. After publication, preserve
the records and receipt; any compatible successor requires a separately
reviewed schema/version transition. Never overwrite a published record merely
to restore a previous application build.

Current consumers are `community-model`, community authority/projection
services, the Phlogiston adapter, fixtures, and drift tests. Application
deployment remains blocked until the published records and retained receipt
match this exact set, but publishing them does not activate an account,
community, or Phlogiston service.
