import { Client } from "@atproto/lex-client";
import type { LexMap } from "@atproto/lex-data";
import { asStringFormat } from "@atproto/lex-schema";
import type { OAuthSession } from "@atproto/oauth-client-node";
import {
  CONSENT_PROFILE,
  POST_COLLECTION,
  SUBMISSION_COLLECTION,
  WITHDRAWAL_COLLECTION,
} from "./constants.js";
import {
  createSpaceRecord,
  deleteSpaceRecord,
  putSpaceRecord,
} from "./space-rpc.js";

export type ExactRecord = Readonly<{ uri: string; cid: string }>;

export interface SpaceRecordWriter {
  create(input: {
    repoDid: string;
    collection: string;
    record: LexMap;
  }): Promise<ExactRecord>;
  put(input: {
    repoDid: string;
    collection: string;
    rkey: string;
    record: LexMap;
  }): Promise<ExactRecord>;
  delete(input: {
    repoDid: string;
    collection: string;
    rkey: string;
  }): Promise<void>;
}

export class OAuthSpaceRecordWriter implements SpaceRecordWriter {
  readonly #client: Client;

  constructor(
    session: OAuthSession,
    readonly spaceUri: string,
  ) {
    this.#client = new Client(session);
  }

  async create(input: {
    repoDid: string;
    collection: string;
    record: LexMap;
  }): Promise<ExactRecord> {
    requireAuthorCollection(input.collection, "create");
    return this.#client.call(createSpaceRecord, {
      space: asStringFormat(this.spaceUri, "space-ref"),
      repo: asStringFormat(input.repoDid, "did"),
      collection: asStringFormat(input.collection, "nsid"),
      validate: false,
      record: input.record,
    });
  }

  async put(input: {
    repoDid: string;
    collection: string;
    rkey: string;
    record: LexMap;
  }): Promise<ExactRecord> {
    if (input.collection !== POST_COLLECTION) {
      throw new Error("author writer may update only its post collection");
    }
    return this.#client.call(putSpaceRecord, {
      space: asStringFormat(this.spaceUri, "space-ref"),
      repo: asStringFormat(input.repoDid, "did"),
      collection: asStringFormat(input.collection, "nsid"),
      rkey: asStringFormat(input.rkey, "record-key"),
      validate: false,
      record: input.record,
    });
  }

  async delete(input: {
    repoDid: string;
    collection: string;
    rkey: string;
  }): Promise<void> {
    if (input.collection !== POST_COLLECTION) {
      throw new Error("author writer may delete only from its post collection");
    }
    await this.#client.call(deleteSpaceRecord, {
      space: asStringFormat(this.spaceUri, "space-ref"),
      repo: asStringFormat(input.repoDid, "did"),
      collection: asStringFormat(input.collection, "nsid"),
      rkey: asStringFormat(input.rkey, "record-key"),
    });
  }
}

export type CreateAndSubmitInput = Readonly<{
  authorDid: string;
  communityActorDid: string;
  title: string;
  body: string;
  authorDisplayReference: string;
  now: string;
}>;

export type CreatedSubmission = Readonly<{
  post: ExactRecord;
  submission: ExactRecord;
  consentProfile: typeof CONSENT_PROFILE;
}>;

/**
 * A post write and a submission write are separate alpha repository effects.
 * If the second fails, the author still owns the successfully-created post.
 * The caller must present this as a partial outcome, never as a submission.
 */
export class SubmissionWriteFailed extends Error {
  readonly name = "SubmissionWriteFailed";

  constructor(
    readonly post: ExactRecord,
    options: ErrorOptions,
  ) {
    super("source post was created but exact submission was not", options);
  }
}

export async function createAndSubmitExact(
  writer: SpaceRecordWriter,
  input: CreateAndSubmitInput,
): Promise<CreatedSubmission> {
  const title = boundedText(input.title, "title", 140, false);
  const body = boundedText(input.body, "body", 20_000, true);
  const authorDisplayReference = boundedText(
    input.authorDisplayReference,
    "author display reference",
    512,
    false,
  );
  assertDid(input.authorDid, "author DID");
  assertDid(input.communityActorDid, "community actor DID");
  const now = exactInstant(input.now);

  const post = await writer.create({
    repoDid: input.authorDid,
    collection: POST_COLLECTION,
    record: { $type: POST_COLLECTION, title, body, createdAt: now },
  });
  let submission: ExactRecord;
  try {
    submission = await writer.create({
      repoDid: input.authorDid,
      collection: SUBMISSION_COLLECTION,
      record: {
        $type: SUBMISSION_COLLECTION,
        subject: post,
        communityActor: input.communityActorDid,
        consentProfile: CONSENT_PROFILE,
        presentation: { title, body, authorDisplayReference },
        createdAt: now,
      },
    });
  } catch (cause) {
    throw new SubmissionWriteFailed(post, { cause });
  }
  return { post, submission, consentProfile: CONSENT_PROFILE };
}

export async function editExactSource(
  writer: SpaceRecordWriter,
  input: Readonly<{
    authorDid: string;
    prior: ExactRecord;
    title: string;
    body: string;
    now: string;
  }>,
): Promise<ExactRecord> {
  assertDid(input.authorDid, "author DID");
  const rkey = exactRkey(input.prior.uri, input.authorDid, POST_COLLECTION);
  return writer.put({
    repoDid: input.authorDid,
    collection: POST_COLLECTION,
    rkey,
    record: {
      $type: POST_COLLECTION,
      title: boundedText(input.title, "title", 140, false),
      body: boundedText(input.body, "body", 20_000, true),
      createdAt: exactInstant(input.now),
    },
  });
}

export async function deleteExactSource(
  writer: SpaceRecordWriter,
  input: Readonly<{ authorDid: string; prior: ExactRecord }>,
): Promise<void> {
  assertDid(input.authorDid, "author DID");
  await writer.delete({
    repoDid: input.authorDid,
    collection: POST_COLLECTION,
    rkey: exactRkey(input.prior.uri, input.authorDid, POST_COLLECTION),
  });
}

export async function withdrawExactAdmission(
  writer: SpaceRecordWriter,
  input: Readonly<{
    authorDid: string;
    communityActorDid: string;
    post: ExactRecord;
    submission: ExactRecord;
    admission: ExactRecord;
    now: string;
  }>,
): Promise<ExactRecord> {
  assertDid(input.authorDid, "author DID");
  assertDid(input.communityActorDid, "community actor DID");
  for (const [name, value] of Object.entries({
    post: input.post,
    submission: input.submission,
    admission: input.admission,
  })) {
    exactRecord(value, name);
  }
  return writer.create({
    repoDid: input.authorDid,
    collection: WITHDRAWAL_COLLECTION,
    record: {
      $type: WITHDRAWAL_COLLECTION,
      submission: input.submission,
      admission: input.admission,
      subject: input.post,
      communityActor: input.communityActorDid,
      createdAt: exactInstant(input.now),
    },
  });
}

function exactRecord(value: ExactRecord, name: string): void {
  if (!value.uri.startsWith("at://") || !value.cid.startsWith("b")) {
    throw new Error(`${name} must be an exact URI+CID`);
  }
}

function exactRkey(uri: string, did: string, collection: string): string {
  const marker = `/${did}/${collection}/`;
  const offset = uri.indexOf(marker);
  if (!uri.startsWith("at://") || offset < 0) {
    throw new Error("source URI does not match author/collection");
  }
  const rkey = uri.slice(offset + marker.length);
  if (!rkey || rkey.includes("/")) throw new Error("source URI has invalid rkey");
  return rkey;
}

function boundedText(
  value: string,
  name: string,
  maxBytes: number,
  allowEmpty: boolean,
): string {
  const normalized = value.trim();
  if ((!allowEmpty && !normalized) || normalized.includes("\0")) {
    throw new Error(`${name} is required`);
  }
  if (Buffer.byteLength(normalized, "utf8") > maxBytes) {
    throw new Error(`${name} is too long`);
  }
  return normalized;
}

function exactInstant(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.valueOf()) || date.toISOString() !== value) {
    throw new Error("timestamp must be canonical ISO-8601 UTC");
  }
  return value;
}

function assertDid(value: string, name: string): void {
  if (!/^did:(?:plc|web):[^\s/]+$/.test(value)) {
    throw new Error(`${name} is invalid`);
  }
}

function requireAuthorCollection(collection: string, action: string): void {
  if (![POST_COLLECTION, SUBMISSION_COLLECTION, WITHDRAWAL_COLLECTION].includes(collection)) {
    throw new Error(`author writer may not ${action} authority records`);
  }
}
