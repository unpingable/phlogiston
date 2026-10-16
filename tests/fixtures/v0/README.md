# V0 offline fixture set

This directory freezes the product-facing vectors used by V0-M1.  All records
and identifiers are synthetic and use reserved `.invalid` names.  They contain
no credentials and are not suitable for publication.

`records/` is one internally consistent lifecycle: an ordinary author-owned
post, a self-submission, a community admission, and a removal, plus the
standalone community profile.  `record-vectors.json` pins the canonical
observer JSON hash and exact DAG-CBOR bytes/CID for each record.  The CBOR
bytes are evidence fixtures; V0-M1 does not add a CBOR encoder or treat an
observer JSON hash as a record CID.

`golden-vectors.json` pins the V0 domain-separated identifiers.  The first
admission/removal rkey pair uses the literal references printed in
`docs/LEXICON-DRAFT.md`; the lifecycle pair uses the content-consistent records
in this directory.  The delete-envelope vector also freezes the normalized
fixture envelope chosen for the offline seam that V0-D1 had left unspecified.
