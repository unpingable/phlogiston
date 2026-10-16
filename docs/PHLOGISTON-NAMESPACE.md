# Phlogiston-owned community Lexicons

The 2026-10-03 owner decision selects `app.phlogiston.community.*` under the
product domain `phlogiston.app`. Juche and neutral.zone are not canonical
Phlogiston identity/authority. PN0 in BUILD.md authorizes only this namespace
correction; record shapes and semantics remain unchanged.

Authority: `community.phlogiston.app`. DNS: `_lexicon.community.phlogiston.app`
TXT `did=<dedicated schema-authority DID>`. Proposed dedicated handle:
`lexicon.phlogiston.app`, on the already-used Bluesky hosting service; actual
assigned DID/PDS follows approved enrollment. No account or TXT is created by
this source change. Publication collection/scope and the five-field exact
manifest acceptance contract are unchanged.

All eight canonical document hashes necessarily change with their IDs. These
are SHA-256 of the existing publisher's stable JSON encoding, without a newline:

| NSID | SHA-256 |
| --- | --- |
| `app.phlogiston.community.admission` | `fe9b1a8bdf4b60e7b7cb588b862c624e7ee71f70bb77c1a4a723d8a3d8baedd9` |
| `app.phlogiston.community.memberAction` | `549ef10d92c04dbf5b020003bcbd62c8edc9e2eb0397268cbf85e23898038fe1` |
| `app.phlogiston.community.modAction` | `e7879aed2706e35a65ebf97cd5c94fdd3c8e4f54cb84e00a5d821c704f94915f` |
| `app.phlogiston.community.profile` | `e1c9a1e30aefab5f579bef2cc2caa069fe1c102a2692776b47f96db32b537d3a` |
| `app.phlogiston.community.replyAction` | `0353e6f3c8af0c7760952009eff377966009600ea32bbd147fea2e5b69070bdb` |
| `app.phlogiston.community.replyAdmission` | `4f8e4cd50d9f39768a04ec281d26cc02bfceb5796d7752e0f8f4a27606aef6e1` |
| `app.phlogiston.community.replyPolicy` | `5f8b5a724339d0893b6612bb0ac656e305eb117b390459c6773f09215b8c7332` |
| `app.phlogiston.community.submit` | `0d1cb4ed8b80a77332904f24ed701d8731950f491999dbbf46ff7c604b6d3c96` |

The publisher and packaged Python model contain the same documents. Current
collections, OAuth contribution scopes, deployment verification and fixtures
use the product-owned names; the current model refuses old record types.
Old manifests/acceptances cannot bind the new IDs or digests.

Public old prototype records in the controlled community actor are preserved;
no published canonical schema records, authority TXT or named external
compatibility consumer was recovered. Historical signed CAR and qualification
receipts remain exact evidence. Their generic proof tests do not confer legacy
runtime acceptance. The previous artifact is retained, but its acceptance does
not transfer to a rebuilt namespace-corrected artifact.

No schema redesign, alias support, user-state migration, PDS change or community
activation is introduced. Host-loss reconstruction is the current zero-user
scope; no off-site recovery-key or total-site-loss requirement is added.
