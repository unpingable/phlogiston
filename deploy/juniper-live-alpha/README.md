# Juniper disposable Spaces-alpha PDS

This deployment is the fail-closed fallback for the BPS hosted-alpha Lexicon
OAuth denial. It is not production infrastructure and it does not modify or
share configuration, data, accounts, or secrets with `juche.social`.

The official amd64 image is pinned to:

```text
ghcr.io/bluesky-social/atproto:pds-spaces-alpha@sha256:bc8ad28e0082b3098a38ac95eb15f2d2f37392d2a287799ab7b5ab9917975e32
```

Host state lives under `/home/jbeck/juniper-alpha-pds`; both `/pds` and the
image-declared `/app/data` volume are replaced with explicit Juniper-only bind
mounts so Docker cannot create hidden anonymous custody. The container binds
host port 3001 through host networking, while Caddy exposes only the four exact
names in `Caddyfile.fragment`. The existing PDS uses port 3000 and is not read,
stopped, reconfigured, mounted, or joined.

The real `pds.env` must be created on the host with umask 077. All five secret
values are independently generated there. The file, account passwords,
invites, PLC keys, OAuth sessions, and DPoP material never enter Git, command
output, public artifacts, or observer receipts.

Account provisioning is limited to:

```text
authority.juniper-pds.sp00ky.net
author.juniper-pds.sp00ky.net
moderator.juniper-pds.sp00ky.net
```

Their exact DIDs are bound into D2 and deployment configuration only after
the PDS returns them. Account credentials remain separate; no role may reuse
another role's OAuth session.

`provision-accounts.py` creates one three-use admin invite and the three exact
role accounts through loopback XRPC. It writes the generated account passwords
only to `account-credentials.json` with mode 0600 and prints only the public
handle/DID mapping. It deliberately discards the access and refresh tokens
returned by account creation. The operator, not an observer or publisher,
retains the private file.

`install-pds.sh` refuses existing state, generates all secrets on the host,
suppresses image/container output, and creates but does not start the pinned
container. The operator validates and installs the Caddy fragment before the
first start. It never prints the generated environment.
