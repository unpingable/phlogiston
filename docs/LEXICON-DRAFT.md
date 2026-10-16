# Provisional V0 Lexicons

## Status and naming

These are review fixtures, not published schemas. The family
`app.phlogiston.community.*` is the permanent namespace ratified by OQ-1
(operator-decision receipt `OQDR-OQ-1-2026-08-14-A-01`, reverse-DNS authority
`community.phlogiston.app`). It replaced the reserved `invalid.community.*`
draft family in commit `c3c8a9a`; those draft IDs must never be published or
aliased.

Naming is settled; publication is not. No `lexicons/<ns>/*.json` documents
exist in this repository, and nothing here serves the namespace at its
reverse-DNS authority. Authoring and publishing those documents is S1 work in
`ROADMAP.md` and is not authorized by `BUILD.md`.

The draft follows local ATProto patterns:

- `literal:self` for an actor declaration;
- `tid` for a user-created submission;
- `any` for authority records whose rkeys are deterministic operation IDs; and
- `com.atproto.repo.strongRef` for every exact URI+CID reference.

Lexicon validation alone cannot establish repository ownership, signatures,
authorization, or agreement between two references. Those are envelope and
projection invariants in `V0-STATE-MACHINE.md`.

## `app.phlogiston.community.profile`

Stored at `at://<community-did>/app.phlogiston.community.profile/self`.

```json
{
  "lexicon": 1,
  "id": "app.phlogiston.community.profile",
  "defs": {
    "main": {
      "type": "record",
      "key": "literal:self",
      "description": "A public declaration of a community actor.",
      "record": {
        "type": "object",
        "required": ["displayName", "createdAt"],
        "properties": {
          "displayName": {
            "type": "string",
            "minLength": 1,
            "maxGraphemes": 64,
            "maxLength": 640
          },
          "description": {
            "type": "string",
            "maxGraphemes": 256,
            "maxLength": 2560
          },
          "createdAt": {"type": "string", "format": "datetime"}
        }
      }
    }
  }
}
```

Example:

```json
{
  "$type": "app.phlogiston.community.profile",
  "displayName": "Homelab",
  "description": "Tiny computers, loud fans, unnecessary VLANs.",
  "createdAt": "2026-07-10T14:00:00Z"
}
```

The administrator DID is intentionally absent. V0 authorization is fixed
deployment configuration, not a public role protocol.

## `app.phlogiston.community.submit`

```json
{
  "lexicon": 1,
  "id": "app.phlogiston.community.submit",
  "defs": {
    "main": {
      "type": "record",
      "key": "tid",
      "description": "An author's request to admit an exact version of their own post.",
      "record": {
        "type": "object",
        "required": ["community", "subject", "createdAt"],
        "properties": {
          "community": {"type": "string", "format": "did"},
          "subject": {
            "type": "ref",
            "ref": "com.atproto.repo.strongRef"
          },
          "createdAt": {"type": "string", "format": "datetime"}
        }
      }
    }
  }
}
```

Example from `did:web:alice.invalid`:

```json
{
  "$type": "app.phlogiston.community.submit",
  "community": "did:web:community.invalid",
  "subject": {
    "uri": "at://did:web:alice.invalid/app.bsky.feed.post/3jzfcijpj2z2a",
    "cid": "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"
  },
  "createdAt": "2026-07-10T14:01:00Z"
}
```

The indexer must additionally require that the envelope repo DID equals the
DID authority in `subject.uri`, the subject collection is exactly
`app.bsky.feed.post`, and `community` is the configured community actor. There
is no redundant `submitter`; authorship comes from the signed repository.

## `app.phlogiston.community.admission`

```json
{
  "lexicon": 1,
  "id": "app.phlogiston.community.admission",
  "defs": {
    "main": {
      "type": "record",
      "key": "any",
      "description": "A community actor's acceptance of an exact self-submission and post version.",
      "record": {
        "type": "object",
        "required": ["submission", "subject", "actor", "createdAt"],
        "properties": {
          "submission": {
            "type": "ref",
            "ref": "com.atproto.repo.strongRef"
          },
          "subject": {
            "type": "ref",
            "ref": "com.atproto.repo.strongRef"
          },
          "actor": {
            "type": "string",
            "format": "did",
            "description": "Administrator DID whose request the community actor attests."
          },
          "createdAt": {"type": "string", "format": "datetime"}
        }
      }
    }
  }
}
```

Example from `did:web:community.invalid`:

```json
{
  "$type": "app.phlogiston.community.admission",
  "submission": {
    "uri": "at://did:web:alice.invalid/app.phlogiston.community.submit/3jzfcijpj2z2b",
    "cid": "bafyreigoxt64qghytzkr6ik7qvtzc7lyytiq5xbbrokbxjows2wp7vmo6q"
  },
  "subject": {
    "uri": "at://did:web:alice.invalid/app.bsky.feed.post/3jzfcijpj2z2a",
    "cid": "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"
  },
  "actor": "did:web:admin.invalid",
  "createdAt": "2026-07-10T14:02:00Z"
}
```

The record must live in the configured community repo. The referenced
submission must target that repo DID, must be self-authored, and must contain
the identical subject strong reference. The community-repo signature is the
portable authority; `actor` is attribution attested by that authority, not a
second signature.

The V0 rkey is:

```text
admit-<lowercase SHA-256 hex of "v0\n" + submission URI + "\n" + submission CID>
```

The deterministic `any` key makes writer retry discoverable. A compatible
existing record (same submission, subject, and actor, with valid stored
`createdAt`) is the prior result. A different submission may create a distinct
admission lifecycle for the same exact subject. Incompatible authority-defining
fields are a hard conflict, never an update.

## `app.phlogiston.community.modAction`

```json
{
  "lexicon": 1,
  "id": "app.phlogiston.community.modAction",
  "defs": {
    "main": {
      "type": "record",
      "key": "any",
      "description": "An append-only moderation action in a community view. V0 understands removal only.",
      "record": {
        "type": "object",
        "required": ["action", "admission", "subject", "actor", "createdAt"],
        "properties": {
          "action": {"type": "string", "knownValues": ["remove"]},
          "admission": {
            "type": "ref",
            "ref": "com.atproto.repo.strongRef"
          },
          "subject": {
            "type": "ref",
            "ref": "com.atproto.repo.strongRef"
          },
          "actor": {"type": "string", "format": "did"},
          "reason": {
            "type": "string",
            "maxGraphemes": 300,
            "maxLength": 3000,
            "description": "Optional explanatory text; it does not determine authority or state."
          },
          "createdAt": {"type": "string", "format": "datetime"}
        }
      }
    }
  }
}
```

Example from `did:web:community.invalid`:

```json
{
  "$type": "app.phlogiston.community.modAction",
  "action": "remove",
  "admission": {
    "uri": "at://did:web:community.invalid/app.phlogiston.community.admission/admit-a2d124bb56d1024475998d71b53d0fb36fc3caf4433efbcc7cc095dd226ff752",
    "cid": "bafyreiaizynclnqiolq7byfpjjtgqzn4sfrsgn7z2hhf6bo4utdwkin7ke"
  },
  "subject": {
    "uri": "at://did:web:alice.invalid/app.bsky.feed.post/3jzfcijpj2z2a",
    "cid": "bafyreidfayvfuwqa7qlnopdjiqrxzs6blmoeu4rujcjtnci5beludirz2a"
  },
  "actor": "did:web:admin.invalid",
  "reason": "Off-topic for this community.",
  "createdAt": "2026-07-10T14:03:00Z"
}
```

The action and admission must live in the community repo, the actor must be
configured, the admission must resolve exactly, and both subject fields must
match. A valid removal masks all duplicate admissions for that exact subject.

The V0 rkey is:

```text
remove-<lowercase SHA-256 hex of "v0\n" + admission URI + "\n" + admission CID>
```

At that key, `action`, admission, subject, actor, and requested reason define
compatibility. Only generated `createdAt` is excluded from a retry comparison.
Stored fields are never overwritten. To refuse removal bypass through a second
submission/admission, `communityd` separately reads the community actor's
current admission/action collections by exact subject; it never consults
`communitywatch`.

## Deliberately absent records

There is no V0 role assignment. One administrator DID is configuration, and
the community actor attests its actions. Rules, memberships, bans, locks,
flair, votes, native comments, restore/readmit, and fork records are also
outside the authorized slice. Labels may decorate presentation later but may
never encode these authority relationships.
