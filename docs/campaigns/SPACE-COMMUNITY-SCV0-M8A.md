# SCV0-M8A — retained V0 evidence demo

Status: **implemented, deployed, and publicly qualified** (2026-08-24)

## Purpose

M7C made the product thesis legible with synthetic data. M8A exposes a
different witness: one actual non-production V0 record lifecycle retained from
the governed 2026-08-15 exercise.

```text
PDS-signed public test records
        ↓
Jetstream discovery
        ↓
independent DID/signature/MST repo verification
        ↓
retained observer store
        ↓
byte-pinned read-only historical demo
```

The page is a live HTTP process over a real retained evidence database. It is
not a live observer and not a claim about the repository's current state.

## Doctrine

> A retained verified observation is real historical evidence, not proof of
> current repository state.

The service calls itself `historical_snapshot` on its health route, binds the
exact SQLite digest at startup, and refuses to start after byte mutation. It
does not reuse the canonical AppView's current-feed routes or relax their
freshness behavior.

## Exact source

* governed evidence: V0-M7 X7 `-05`, replayed for V0-M8
* community actor: `did:plc:exampleparticipantabcdef`
* admission occurrence:
  `admit-7f024ab1227580de733032a8370324fec97c0c8e7a27ee822a24441a4471feb8`
* captured through: `2026-08-15T05:18:50.144497Z`
* retained store size: `229376` bytes
* retained store digest:
  `sha256:3b5a3d1847ff620c77800454d992dcbf83d01dde7c1c1045c48ffc3a2cd4b7e0`

The deployment receives a copy of the database only. It receives no evidence
repository, controller credential, app password, OAuth token, PDS session, or
writer configuration.

## Routes

* `/` — plain-language historical lifecycle
* `/api/v0/history` — exact receipt, record references, event outcomes, and
  explicit non-claims
* `/health` — `historical_snapshot`, never `current` or `live`

Only GET, HEAD, and OPTIONS are supported. The process opens SQLite with
`mode=ro` and computes its digest from the same path the query opens.

## What the demo establishes

For the byte-pinned captured store:

* the projection generation is complete and version-compatible;
* exact submission, admission, source, and removal references are retained;
* the source record observation and accepted community events carry the
  recorded independent verification outcomes;
* transport-only deliveries that did not qualify remain visible as refused
  evidence rather than being rewritten as success; and
* the renderer can explain the actual lifecycle without holding authority.

## Non-claims

The demo does not establish:

* current repository state or absence of newer operations;
* complete history;
* community legitimacy, membership, or standing;
* public verification of the local controller's operator authorization;
* a live SCV0 Space, Space type, credential, or writer;
* production readiness.

The PDS-signed admission establishes that the community actor's repository
contained that record in the verified state. It does not establish that every
reader should accept the actor's governance.

## Boundary and deployment

The code lives in the existing read-only `communitywatch-web` distribution and
depends only on `communitywatch` plus inert `community-model` values. It does
not import `communityd`, Spaces authentication, transport, or archive tooling.

Deployment is isolated as a rootless-in-container process managed by
`community-history-demo.service`. The image is based on pinned Python 3.12.11
image digest
`sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7`.
The container runs as UID/GID 65532 with a read-only root filesystem, no Linux
capabilities, no-new-privileges, bounded memory/CPU/PIDs, read-only config and
database mounts, and only a host-loopback port publication. Caddy reverse
proxies that port at `community.sp00ky.net`. This deliberately uses a non-PDS
hostname: the `*.juche.social` TLS boundary admits PDS account handles and must
not be weakened merely to host a demo. The exact public deployment receipt is
recorded below.

The retained database uses SQLite WAL mode. SQLite requires an adjacent shared
memory/lock file even when its database handle is read-only, so the container
provides a 1 MiB, non-executable tmpfs for those ephemeral sidecars. The exact
database remains a distinct read-only bind mount and retains its approved
digest across execution and restart.

## Public deployment receipt

Qualified at `2026-08-24T21:05:15Z`:

* URL: <https://community.sp00ky.net/>
* public history receipt:
  `sha256:f46b645d8c426b4efd6ac78bb9672741413ee36053e7a3842f1cafeda16a8a37`
* public HTML body:
  `sha256:28b8ca67fe765569a7634ea241a47826e9d87bc38b5535f5623c2a76d6fd7658`
* public JSON body:
  `sha256:5847636c77922d066a1ccd7de4b2bf6236e5c8a2c9a4fd955d6ea4e1592a34e5`
* container image:
  `sha256:0f1c1b2bf266c0bd6d2ba2557e442dfb9b55f53a493e634f2ef0cdd80693b9a3`
* container:
  `1ba705dd721065b8ffeb8dcdfea32b185269b886c98012b94e4deaad68922410`

The public HTML and JSON hashes exactly matched independent host-loopback
requests. `/health` reported `historical_snapshot` and
`currentnessClaim: false`. POST, PUT, PATCH, and DELETE each returned 405;
HEAD returned no response body and OPTIONS advertised only GET, HEAD, and
OPTIONS. The remote SQLite file matched the locally approved digest.

The container receipt retained UID/GID 65532, a read-only root filesystem,
all capabilities dropped, no-new-privileges, 256 MiB memory, 0.2 CPU, 64 PIDs,
read-only config/database mounts, no container restart policy, and only
`127.0.0.1:8138` published on the host. Systemd owns deliberate restart. No
credential, private key, app password, token, session, or writer configuration
was copied.

The initially planned `community.juche.social` host failed closed because the
PDS wildcard's on-demand TLS gate did not recognize it as an account handle.
The deployment did not weaken or bypass that gate. It selected the already
resolving non-PDS `community.sp00ky.net` boundary instead; the original PDS
hostname continues to refuse TLS issuance.

## Hostile witnesses

Tests prove that:

* a store digest mismatch refuses before binding a socket;
* a writable observer store refuses;
* mutating the store invalidates the bound digest;
* POST/PUT/PATCH/DELETE refuse;
* source text is escaped;
* currentness and governance remain explicit non-claims; and
* adding an authority label changes the receipt identity rather than upgrading
  the retained receipt.

## Still blocked

OQ-8 and OQ-10 remain open. M8A does not choose a live SCV0 Space type,
community actor, credential custody model, or writer. A genuinely interactive
`write → submit → admit → publish` SCV0 trial remains a later human decision.
