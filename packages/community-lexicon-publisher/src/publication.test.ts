import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { LexMap } from "@atproto/lex-data";
import {
  ACCEPTANCE_CONTRACT,
  createManifest,
  loadPackagedDocuments,
  manifestDigest,
  stable,
  type HumanAcceptance,
} from "./contract.js";
import {
  publishAcceptedManifest,
  verifyNamespaceDns,
  type DnsTxtResolver,
  type ExactRecord,
  type LexiconRepository,
  type PublicationIntent,
  type PublicationJournal,
} from "./publication.js";
import { FilePublicationJournal } from "./journal.js";

const AUTHORITY_DID = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa";
const CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti";

class MemoryJournal implements PublicationJournal {
  public readonly values = new Map<string, PublicationIntent>();

  public async reserve(intent: PublicationIntent): Promise<PublicationIntent> {
    const existing = this.values.get(intent.nsid);
    if (existing) return existing;
    this.values.set(intent.nsid, intent);
    return intent;
  }

  public async save(intent: PublicationIntent): Promise<void> {
    assert.ok(this.values.has(intent.nsid));
    this.values.set(intent.nsid, intent);
  }
}

class MemoryRepository implements LexiconRepository {
  public readonly records = new Map<string, ExactRecord>();
  public readonly creates: string[] = [];

  public constructor(private readonly authorityDid = AUTHORITY_DID) {}

  public async create(input: Readonly<{ rkey: string; record: LexMap }>) {
    this.creates.push(input.rkey);
    const result = {
      uri: `at://${this.authorityDid}/com.atproto.lexicon.schema/${input.rkey}`,
      cid: CID,
      value: input.record,
    };
    this.records.set(input.rkey, result);
    return { uri: result.uri, cid: result.cid };
  }

  public async get(input: Readonly<{ rkey: string }>) {
    return this.records.get(input.rkey) ?? null;
  }
}

async function inputs() {
  const manifest = createManifest(AUTHORITY_DID, await loadPackagedDocuments());
  const acceptance: HumanAcceptance = Object.freeze({
    contract: ACCEPTANCE_CONTRACT,
    manifestSha256: manifestDigest(manifest),
    authorityDid: AUTHORITY_DID,
    acceptedBy: "maintainer@example.invalid",
    acceptedAt: "2026-09-08T12:00:00Z",
  });
  const resolver: DnsTxtResolver = {
    resolveTxt: async () => ["unrelated=permitted", `did=${AUTHORITY_DID}`],
  };
  return { manifest, acceptance, resolver };
}

test("publishes all accepted records once and verifies exact readback", async () => {
  const { manifest, acceptance, resolver } = await inputs();
  const repository = new MemoryRepository();
  const journal = new MemoryJournal();
  const receipt = await publishAcceptedManifest(
    repository,
    resolver,
    journal,
    manifest,
    acceptance,
    () => new Date("2026-09-08T13:00:00Z"),
  );
  assert.equal(repository.creates.length, 8);
  assert.ok(receipt.records.every((record) => record.disposition === "created"));
  assert.ok([...journal.values.values()].every((intent) => intent.phase === "settled"));
  assert.equal(receipt.dns.verified, true);
  assert.equal(receipt.completedAt, "2026-09-08T13:00:00.000Z");
  const serialized = stable(receipt);
  assert.ok(!serialized.includes("maintainer@example.invalid"));
  assert.ok(!serialized.includes("token"));

  const resumed = await publishAcceptedManifest(
    repository,
    resolver,
    journal,
    manifest,
    acceptance,
  );
  assert.equal(repository.creates.length, 8);
  assert.ok(resumed.records.every((record) => record.disposition === "read_back"));
});

test("ambiguous creates settle only by exact readback without hidden retry", async () => {
  const { manifest, acceptance, resolver } = await inputs();
  const backing = new MemoryRepository();
  let creates = 0;
  const repository: LexiconRepository = {
    create: async (input) => {
      creates += 1;
      await backing.create(input);
      throw new Error("synthetic lost response with secret detail");
    },
    get: (input) => backing.get(input),
  };
  const receipt = await publishAcceptedManifest(
    repository,
    resolver,
    new MemoryJournal(),
    manifest,
    acceptance,
  );
  assert.equal(creates, 8);
  assert.ok(receipt.records.every((record) => record.disposition === "read_back"));
  assert.ok(!stable(receipt).includes("secret detail"));
});

test("DNS mismatch, schema conflict, and substituted identity refuse", async () => {
  const { manifest, acceptance } = await inputs();
  await assert.rejects(
    publishAcceptedManifest(
      new MemoryRepository(),
      { resolveTxt: async () => ["did=did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"] },
      new MemoryJournal(),
      manifest,
      acceptance,
    ),
    /DNS/u,
  );
  await assert.rejects(
    verifyNamespaceDns(
      { resolveTxt: async () => [`did=${AUTHORITY_DID}`, "did=did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"] },
      manifest,
    ),
    /DNS/u,
  );

  const conflict = new MemoryRepository();
  const first = manifest.documents[0];
  assert.ok(first);
  conflict.records.set(first.rkey, {
    uri: first.uri,
    cid: CID,
    value: { $type: "com.atproto.lexicon.schema", lexicon: 1, id: first.nsid, defs: {} },
  });
  const journal = new MemoryJournal();
  journal.values.set(first.nsid, Object.freeze({
    contract: "pcv0-lexicon-publication-intent/1",
    manifestSha256: manifestDigest(manifest),
    authorityDid: manifest.authorityDid,
    nsid: first.nsid,
    rkey: first.rkey,
    expectedUri: first.uri,
    documentSha256: first.documentSha256,
    recordSha256: first.recordSha256,
    phase: "attempted_unknown",
    attempts: 1,
  }));
  await assert.rejects(
    publishAcceptedManifest(
      conflict,
      { resolveTxt: async () => [`did=${AUTHORITY_DID}`] },
      journal,
      manifest,
      acceptance,
    ),
    /differs/u,
  );

  await assert.rejects(
    publishAcceptedManifest(
      new MemoryRepository("did:plc:bbbbbbbbbbbbbbbbbbbbbbbb"),
      { resolveTxt: async () => [`did=${AUTHORITY_DID}`] },
      new MemoryJournal(),
      manifest,
      acceptance,
    ),
    /substituted/u,
  );
});

test("an unknown operation with absent readback refuses another create", async () => {
  const { manifest, acceptance, resolver } = await inputs();
  const repository = new MemoryRepository();
  const journal = new MemoryJournal();
  const first = manifest.documents[0];
  assert.ok(first);
  journal.values.set(first.nsid, Object.freeze({
    contract: "pcv0-lexicon-publication-intent/1",
    manifestSha256: manifestDigest(manifest),
    authorityDid: manifest.authorityDid,
    nsid: first.nsid,
    rkey: first.rkey,
    expectedUri: first.uri,
    documentSha256: first.documentSha256,
    recordSha256: first.recordSha256,
    phase: "attempted_unknown",
    attempts: 1,
  }));
  await assert.rejects(
    publishAcceptedManifest(repository, resolver, journal, manifest, acceptance),
    /remains unknown/u,
  );
  assert.equal(repository.creates.length, 0);
  assert.equal(journal.values.get(first.nsid)?.attempts, 1);
  assert.equal(journal.values.get(first.nsid)?.phase, "attempted_unknown");

  repository.records.set(first.rkey, {
    uri: first.uri,
    cid: CID,
    value: { $type: "com.atproto.lexicon.schema", ...first.document },
  });
  await publishAcceptedManifest(repository, resolver, journal, manifest, acceptance);
  assert.equal(repository.creates.filter((rkey) => rkey === first.rkey).length, 0);
  assert.equal(journal.values.get(first.nsid)?.attempts, 1);
  assert.equal(journal.values.get(first.nsid)?.phase, "settled");
});

test("an interrupted attempting operation becomes unknown without redispatch", async () => {
  const { manifest, acceptance, resolver } = await inputs();
  const repository = new MemoryRepository();
  const journal = new MemoryJournal();
  const first = manifest.documents[0];
  assert.ok(first);
  journal.values.set(first.nsid, Object.freeze({
    contract: "pcv0-lexicon-publication-intent/1",
    manifestSha256: manifestDigest(manifest),
    authorityDid: manifest.authorityDid,
    nsid: first.nsid,
    rkey: first.rkey,
    expectedUri: first.uri,
    documentSha256: first.documentSha256,
    recordSha256: first.recordSha256,
    phase: "attempting",
    attempts: 1,
  }));
  await assert.rejects(
    publishAcceptedManifest(repository, resolver, journal, manifest, acceptance),
    /remains unknown/u,
  );
  assert.equal(repository.creates.length, 0);
  assert.equal(journal.values.get(first.nsid)?.phase, "attempted_unknown");
  assert.equal(journal.values.get(first.nsid)?.attempts, 1);
});

test("an uncertain create stays single-attempt across journal reopen", async () => {
  const { manifest, acceptance, resolver } = await inputs();
  const directory = await mkdtemp(join(tmpdir(), "pcv0-lexicon-unknown-"));
  const first = manifest.documents[0];
  assert.ok(first);
  const creates: string[] = [];
  const records = new Map<string, ExactRecord>();
  const repository: LexiconRepository = {
    create: async ({ rkey }) => {
      creates.push(rkey);
      throw new Error("uncertain create result");
    },
    get: async ({ rkey }) => records.get(rkey) ?? null,
  };
  try {
    await assert.rejects(
      publishAcceptedManifest(repository, resolver, new FilePublicationJournal(directory), manifest, acceptance),
      /did not settle/u,
    );
    assert.deepEqual(creates, [first.rkey]);
    await assert.rejects(
      publishAcceptedManifest(repository, resolver, new FilePublicationJournal(directory), manifest, acceptance),
      /remains unknown/u,
    );
    assert.deepEqual(creates, [first.rkey]);

    records.set(first.rkey, {
      uri: first.uri,
      cid: CID,
      value: { $type: "com.atproto.lexicon.schema", ...first.document },
    });
    // Only the next schema may now dispatch; the first must settle by readback.
    await assert.rejects(
      publishAcceptedManifest(repository, resolver, new FilePublicationJournal(directory), manifest, acceptance),
      /did not settle/u,
    );
    assert.deepEqual(creates, [first.rkey, manifest.documents[1]?.rkey]);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("partial publication resumes without recreating settled records", async () => {
  const { manifest, acceptance, resolver } = await inputs();
  const backing = new MemoryRepository();
  const journal = new MemoryJournal();
  const attempted: string[] = [];
  const blocked = manifest.documents[2];
  assert.ok(blocked);
  let refuse = true;
  const repository: LexiconRepository = {
    create: async (input) => {
      attempted.push(input.rkey);
      if (refuse && input.rkey === blocked.rkey) throw new Error("synthetic interruption");
      return backing.create(input);
    },
    get: (input) => backing.get(input),
  };
  await assert.rejects(
    publishAcceptedManifest(repository, resolver, journal, manifest, acceptance),
    /did not settle/u,
  );
  assert.ok(manifest.documents.slice(0, 2).every(
    (item) => journal.values.get(item.nsid)?.phase === "settled",
  ));

  refuse = false;
  await assert.rejects(
    publishAcceptedManifest(repository, resolver, journal, manifest, acceptance),
    /remains unknown/u,
  );
  assert.equal(attempted.filter((rkey) => rkey === blocked.rkey).length, 1);
  backing.records.set(blocked.rkey, {
    uri: blocked.uri,
    cid: CID,
    value: { $type: "com.atproto.lexicon.schema", ...blocked.document },
  });
  const receipt = await publishAcceptedManifest(
    repository,
    resolver,
    journal,
    manifest,
    acceptance,
  );
  assert.equal(receipt.records.length, 8);
  assert.ok(manifest.documents.slice(0, 2).every(
    (item) => attempted.filter((rkey) => rkey === item.rkey).length === 1,
  ));
  assert.equal(attempted.filter((rkey) => rkey === blocked.rkey).length, 1);
});
