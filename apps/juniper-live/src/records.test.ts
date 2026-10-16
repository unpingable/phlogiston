import assert from "node:assert/strict";
import test from "node:test";
import type { LexMap } from "@atproto/lex-data";
import {
  ADMISSION_COLLECTION,
  CONSENT_PROFILE,
  POST_COLLECTION,
  SUBMISSION_COLLECTION,
  WITHDRAWAL_COLLECTION,
} from "./constants.js";
import {
  createAndSubmitExact,
  deleteExactSource,
  editExactSource,
  SubmissionWriteFailed,
  type ExactRecord,
  type SpaceRecordWriter,
  withdrawExactAdmission,
} from "./records.js";

const AUTHOR = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa";
const COMMUNITY = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb";
const CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti";

class FakeWriter implements SpaceRecordWriter {
  readonly calls: Array<{ action: string; input: Record<string, unknown> }> = [];
  #next = 0;

  async create(input: {
    repoDid: string;
    collection: string;
    record: LexMap;
  }): Promise<ExactRecord> {
    this.calls.push({ action: "create", input });
    this.#next += 1;
    return {
      uri: `at://did:plc:authority/space/type/self/${input.repoDid}/${input.collection}/${this.#next}`,
      cid: CID,
    };
  }

  async put(input: {
    repoDid: string;
    collection: string;
    rkey: string;
    record: LexMap;
  }): Promise<ExactRecord> {
    this.calls.push({ action: "put", input });
    return {
      uri: `at://did:plc:authority/space/type/self/${input.repoDid}/${input.collection}/${input.rkey}`,
      cid: CID.replace(/i$/, "j"),
    };
  }

  async delete(input: {
    repoDid: string;
    collection: string;
    rkey: string;
  }): Promise<void> {
    this.calls.push({ action: "delete", input });
  }
}

class SubmissionFailureWriter extends FakeWriter {
  override async create(input: {
    repoDid: string;
    collection: string;
    record: LexMap;
  }): Promise<ExactRecord> {
    if (input.collection === SUBMISSION_COLLECTION) {
      throw new Error("synthetic downstream refusal");
    }
    return super.create(input);
  }
}

test("create then self-submit binds the returned exact source", async () => {
  const writer = new FakeWriter();
  const result = await createAndSubmitExact(writer, {
    authorDid: AUTHOR,
    communityActorDid: COMMUNITY,
    title: "Shared tool shelf",
    body: "A place for the clamps.",
    authorDisplayReference: "@alex.invalid.test",
    now: "2026-08-24T12:00:00.000Z",
  });
  assert.equal(writer.calls.length, 2);
  assert.equal(writer.calls[0]?.input.collection, POST_COLLECTION);
  assert.equal(writer.calls[1]?.input.collection, SUBMISSION_COLLECTION);
  const submission = writer.calls[1]?.input.record as Record<string, unknown>;
  assert.deepEqual(submission.subject, result.post);
  assert.equal(submission.consentProfile, CONSENT_PROFILE);
  assert.equal(result.consentProfile, CONSENT_PROFILE);
});

test("edit changes the source record only and pins its rkey", async () => {
  const writer = new FakeWriter();
  const prior = {
    uri: `at://did:plc:authority/space/type/self/${AUTHOR}/${POST_COLLECTION}/post-1`,
    cid: CID,
  };
  await editExactSource(writer, {
    authorDid: AUTHOR,
    prior,
    title: "Updated shelf",
    body: "Now with labels.",
    now: "2026-08-24T12:05:00.000Z",
  });
  assert.equal(writer.calls[0]?.action, "put");
  assert.equal(writer.calls[0]?.input.rkey, "post-1");
  assert.equal(writer.calls[0]?.input.collection, POST_COLLECTION);
});

test("delete touches only the author source collection", async () => {
  const writer = new FakeWriter();
  const prior = {
    uri: `at://did:plc:authority/space/type/self/${AUTHOR}/${POST_COLLECTION}/post-1`,
    cid: CID,
  };
  await deleteExactSource(writer, { authorDid: AUTHOR, prior });
  assert.deepEqual(writer.calls[0], {
    action: "delete",
    input: { repoDid: AUTHOR, collection: POST_COLLECTION, rkey: "post-1" },
  });
});

test("withdrawal binds exact post submission admission and community", async () => {
  const writer = new FakeWriter();
  const exact = (name: string): ExactRecord => ({
    uri: `at://did:plc:authority/space/type/self/${AUTHOR}/collection/${name}`,
    cid: CID,
  });
  await withdrawExactAdmission(writer, {
    authorDid: AUTHOR,
    communityActorDid: COMMUNITY,
    post: exact("post"),
    submission: exact("submission"),
    admission: exact("admission"),
    now: "2026-08-24T12:06:00.000Z",
  });
  assert.equal(writer.calls[0]?.input.collection, WITHDRAWAL_COLLECTION);
  const record = writer.calls[0]?.input.record as Record<string, unknown>;
  assert.equal(record.communityActor, COMMUNITY);
  assert.deepEqual(record.subject, exact("post"));
});

test("foreign source URI and invalid consent inputs fail before writes", async () => {
  const writer = new FakeWriter();
  await assert.rejects(
    deleteExactSource(writer, {
      authorDid: AUTHOR,
      prior: { uri: "at://did:plc:other/collection/rkey", cid: CID },
    }),
    /does not match/,
  );
  await assert.rejects(
    createAndSubmitExact(writer, {
      authorDid: AUTHOR,
      communityActorDid: COMMUNITY,
      title: "",
      body: "body",
      authorDisplayReference: "@alex",
      now: "2026-08-24T12:00:00.000Z",
    }),
    /title is required/,
  );
  assert.equal(writer.calls.length, 0);
});

test("partial write preserves the exact created source without claiming submission", async () => {
  const writer = new SubmissionFailureWriter();
  await assert.rejects(
    createAndSubmitExact(writer, {
      authorDid: AUTHOR,
      communityActorDid: COMMUNITY,
      title: "Created, not submitted",
      body: "The second write refuses.",
      authorDisplayReference: "@alex.invalid.test",
      now: "2026-08-24T12:00:00.000Z",
    }),
    (error: unknown) => {
      assert.ok(error instanceof SubmissionWriteFailed);
      assert.equal(error.post.cid, CID);
      assert.equal(error.cause instanceof Error, true);
      assert.equal(error.message.includes("synthetic downstream refusal"), false);
      return true;
    },
  );
  assert.equal(writer.calls.length, 1);
  assert.equal(writer.calls[0]?.input.collection, POST_COLLECTION);
});

test("author write API has no admission capability", async () => {
  const session = {
    fetch: async () => {
      throw new Error("network must not be reached");
    },
  } as unknown as import("@atproto/oauth-client-node").OAuthSession;
  const writer = new (await import("./records.js")).OAuthSpaceRecordWriter(
    session,
    "at://did:plc:authority/type/self",
  );
  await assert.rejects(
    writer.create({
      repoDid: COMMUNITY,
      collection: ADMISSION_COLLECTION,
      record: { $type: ADMISSION_COLLECTION },
    }),
    /may not create authority records/,
  );
});
