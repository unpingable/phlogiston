# P0 public playground profile

Implementation-only template; not deployment approval. The parent PCV0 directory is the historical qualification profile. Use this explicit `p0/` directory for the successor; never combine its files with the parent notifier/policy services.

Validate offline from the repository:

```sh
.venv/bin/python3 deploy/public-community-pcv0/validate_deployment.py validate-bundle --repository-root . --profile p0
```

The selected curator community actor and moderator and participant Bluesky participant are named in the templates; the dedicated publisher DID and campaign date remain unresolved. Both controls ship paused. `validate-campaign --ready` rejects placeholders and binds the exact eight-document manifest, human acceptance, and publication receipt at the configured paths. It does not independently query DNS or the PDS; separately verify the actual records and DNS before launch. Use the existing qualified-artifact builder after this successor passes its own suite. The historical six-service installed verification is not P0 qualification: complete [P0 installed acceptance](INSTALLED-ACCEPTANCE.md) against the actual candidate host before activation. Frozen old archives cannot implement the new profile.

## Services and identities

Only community-live, communityd, communitywatch-index and communitywatch-web run. No notification room, notifier process/credential/configuration, policy worker, or second moderator is required. The host preflight still rejects a second writer and refuses unmasked notifier/policy units for P0. Principals remain distinct.

The P0 `communityd.env.example` keeps the existing `COMMUNITYD_APP_PASSWORD` variable name, but its value is an **absolute path**, not a password. The `env_file` adapter reads that protected JSON file with exactly `identifier` and `app_password` fields, then creates a PDS session whose DID must equal the configured community actor. Keep the file outside the repository, owned by `communityd` with owner-only access; do not put credential bytes in the environment example or a receipt. The moderator's browser OAuth session does not supply this community-actor writer credential.

The sole public participant origin is https://phlogiston.app. community.phlogiston.app is DNS-only Lexicon authority. The selected curator community actor and moderator use the existing invite-only https://phlogiston.social PDS; the selected participant participant uses its distinct Bluesky PDS. The dedicated lexicon.phlogiston.app publisher also uses phlogiston.social with its own forthcoming DID. The three services explicitly select hosted Phlogiston plus Bluesky interoperability, without a Juche public fallback. Exact accepted manifest, publication/readback and fresh qualified artifact remain separate activation inputs. No account is enrolled by these files.

## Pause and recovery

Install operator-controlled regular files `/etc/atproto-community/p0-site-state` and `/etc/atproto-community/p0-admission-state`, mode0644 with service users unable to write them. Exact content `paused` or `open`, each followed by one newline; missing/invalid files fail closed. Site pause stops new app repository writes, including resume dispatch. Admission pause stops new active intake and admission. Reads, uncertain-effect readback and authenticated removal remain available; no pause cancels already committed external records.

Private decline decisions share communityd's authority journal custody; a blank observer rebuild cannot recover them. Preserve that journal and the app's reservation/intake state under the existing application host-loss backup/rehearsal procedure. OAuth secret state stays in protected service custody, never receipts or source. Record irreversibility of records already published before rollback. A read-only fallback should keep truthful coverage/source status.

## Isolated Juche test exception

The owner subsequently authorized existing Juche test accounts as temporary integration infrastructure. It is not a public fallback and never qualifies Bluesky hosting. In an isolated loopback app only, the browser may set `COMMUNITY_P0_TEST_PDS_ORIGIN=https://juche.social`; authority requires `p0_test_pds_origin` plus `allow_loopback_public_endpoints=true`; observer requires that exact origin plus `p0_isolated_test=true` and `p0_bluesky_only=true`. No other host is silently substituted. Public bundle validation rejects every test override. Use separate test state and authorized test credential custody; never relabel test receipts or copy test decisions into public state. This is account-level testing, not permission to alter the Juche PDS service.

## Required real Bluesky evidence

An isolated test using expressly authorized Bluesky-hosted accounts must demonstrate OAuth → scoped submission record write → the actual public streaming observer → bounded intake → admit/decline → anonymous rendering. The nonmoderator DID must not appear in an initial fixed observer list. Record exact DID/PDS/URI/CID, declared and granted scopes, duplicate handling, stream cursor/restart/readback, private decline custody, public removal, and application recovery. Test custom handles by DID-bound hosting, not handle suffix.

`phlogiston-p0-receipt-v1` names these checks separately from historical two-human dogfood. The receipt validator checks structure/bindings; independent review must inspect actual evidence. A Juche run or the local streaming fixture is not a passing Bluesky receipt. Without explicitly authorized test credentials, report this live check as not run. No production activation is authorized.
