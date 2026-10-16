# SCV0-M6C — Synthetic projection comprehension instrument

Status: **instrument qualified; synthetic information sufficient**
(2026-08-22)

## Question

> Do the exact canonical M6B pages expose enough unambiguous information for
> the SCV0 product distinctions to be recovered mechanically?

This is the synthetic precursor to human product validation. It does not use
people, a language model, browser automation, telemetry, or learned scoring.
It parses visible text from the deterministic in-memory M6B pages and compares
it with a fixed question/cue profile.

## Doctrine

> Machine-detectable explanatory cues are a necessary interface property, not
> evidence that a human understood the interface.

The instrument can report `synthetic_information_sufficient` or
`synthetic_information_insufficient`. Neither verdict means “usable,”
“understood by humans,” “authorized,” or “true.”

## Instrument boundary

Input is one exact typed `PrototypeSite`. Before evaluating any question, the
instrument:

1. revalidates the nested M6A feed/artifact identities;
2. replays both feeds through the canonical M6B implementation;
3. requires byte-identical ordinary and audit pages and equal canonical
   semantics;
4. extracts visible text while ignoring style/script content;
5. evaluates the fixed questions without accepting a caller answer key.

Each immutable question outcome retains its prompt, expected interpretation,
the exact cues observed, and whether all required cues were present. The
report binds the prototype site ID, both page digests, every structured
outcome, the instrument version, fixed claims, and fixed non-claims into a
deterministic report identity.

## Fixed questions

For every lifecycle entry, the instrument asks:

1. What lifecycle state is this item in?
2. Why is it on this community surface?
3. Did publication transfer source ownership?
4. Can disclosed technical references be inspected separately?
5. Did audit disclosure leak into the ordinary view?
6. What changed at the source/community boundary?

The state-specific interpretation is frozen:

| State | Recoverable distinction |
| --- | --- |
| `Added` | the admitted bounded presentation is displayed |
| `ChangedAtSource` | the source changed; no new admission or silent replacement |
| `SourceUnavailable` | the source is unavailable; the community did not remove it |
| `Removed` | the projection was removed; the author source was not deleted |

## Synthetic result

The bounded profile accepts exactly one lifecycle entry per site so that cues
from one card cannot satisfy questions about another. The fixture evaluated
four independently compiled one-entry lifecycle sites. All six questions were
answerable for every site:

| Lifecycle case | Questions answerable | Verdict |
| --- | ---: | --- |
| Added | 6 / 6 | `synthetic_information_sufficient` |
| ChangedAtSource | 6 / 6 | `synthetic_information_sufficient` |
| SourceUnavailable | 6 / 6 | `synthetic_information_sufficient` |
| Removed | 6 / 6 | `synthetic_information_sufficient` |

This establishes that the current canonical pages contain the intended cues
and preserve the expected distinctions. It does not establish whether those
cues are noticed, correctly interpreted, memorable, or persuasive to a human.

Fixture: `tests/fixtures/space-community/scv0-m6c.json`, SHA-256
`d386cee2165aa255b980d4397ad3cad263d5d1a0ccb091720274ed713aa9770f`.

## Hostile witnesses

The suite demonstrates that:

* synthetic success cannot be relabelled as human comprehension, usability,
  reader authorization, or governance authority;
* an altered lifecycle label refuses even when the attacker recomputes the
  page digest, because the page no longer matches canonical M6B replay;
* leaking a technical receipt into the ordinary page similarly refuses;
* a raw page or caller-supplied answer key cannot enter the typed instrument;
* a modified report cannot validate against the original site;
* an unanswerable outcome cannot retain a sufficient verdict;
* later timestamps, repeated observations, or artifact possession cannot
  become currentness or permission.

## Claims and non-claims

M6C proves only that:

* the exact canonical prototype was replayed;
* the fixed explanatory cues were evaluated;
* ordinary/audit disclosure separation was evaluated;
* the retained structured outcomes reproduce deterministically.

It explicitly does not prove human comprehension, usability, accessibility
conformance, reader authentication or permission, membership, moderator or
governance authority, source truth or ownership, repository currentness,
ranking, or production readiness.

## Replacement and next boundary

The pure instrument depends only on `community-space-prototype`; the package
boundary excludes transport, serving, browser automation, AI/model inference,
analytics, telemetry, storage, credentials, reader sessions, moderation, and
ranking.

The next product-validation boundary is therefore genuinely human: a small
synthetic-data comprehension session that asks participants the same fixed
questions. That requires separate authorization and protocol design for
consent, collection, and interpretation. M6C does not fabricate that evidence.
