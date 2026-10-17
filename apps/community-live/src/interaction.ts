import { deterministicTid, POST_COLLECTION, type StrongRef } from "./contributions.js";
import { createHash } from "node:crypto";
import { digest, DurableWriteJournal, type PublicRepoWriter, type RecordAddress, type WriteResult } from "./operations.js";

export const LIKE_COLLECTION = "app.bsky.feed.like";
export const REPOST_COLLECTION = "app.bsky.feed.repost";
const URI = /^at:\/\/(did:(?:plc|web):[^/\s]+)\/(app\.bsky\.feed\.(?:post|like|repost))\/([A-Za-z0-9._~:-]{1,512})$/;

export type InteractionKind = "like" | "repost" | "post" | "reply";
export interface InteractionOutcome { operationId: string; result: WriteResult; uri: string }

export class InteractionService {
  public constructor(private readonly journal: DurableWriteJournal, private readonly writer: PublicRepoWriter, private readonly did: string) {}

  public async create(kind: InteractionKind, operationId: string, input: {text?: string; subject?: StrongRef; root?: StrongRef; parent?: StrongRef}): Promise<InteractionOutcome> {
    operation(operationId);
    const text = kind === "post" || kind === "reply" ? postText(input.text) : undefined;
    const subject = kind === "like" || kind === "repost" ? strongRef(input.subject) : undefined;
    const root = kind === "reply" ? strongRef(input.root) : undefined;
    const parent = kind === "reply" ? strongRef(input.parent) : undefined;
    const intentDigest = digest({kind,...(subject ? {subject} : {}),...(root ? {root,parent} : {}),
      ...(text === undefined ? {} : {textSha256:createHash("sha256").update(text).digest("hex")})});
    const existing = await this.journal.find(operationId);
    if (existing) {
      if (existing.repo !== this.did || ![LIKE_COLLECTION,REPOST_COLLECTION,POST_COLLECTION].includes(existing.collection)) throw new Error("operation belongs to another account or feature");
      if (existing.intentDigest !== intentDigest) throw new Error("operation was reused with different intent");
      return {operationId,result:await this.run(operationId),uri:atUri(existing)};
    }
    if (await this.journal.recentCount(this.did,Date.now()-86400000) >= 100) throw new Error("daily content interaction limit reached");
    const unfinished = (await this.journal.entries(this.did)).filter(item => ["prepared","attempted_unknown"].includes(item.phase) || (item.phase === "refused" && ["confirmed_absent","confirmed_present"].includes(item.reason ?? "")));
    if (unfinished.length >= 25) throw new Error("unfinished content interaction limit reached; check outcomes in Settings");
    if ((kind === "post" || kind === "reply") && unfinished.some(item => item.collection === POST_COLLECTION && item.action !== "delete")) {
      throw new Error("an earlier publication is unresolved; check its outcome in Settings before publishing again");
    }
    let collection: string, record: Record<string, unknown>;
    if (kind === "like" || kind === "repost") {
      collection = kind === "like" ? LIKE_COLLECTION : REPOST_COLLECTION;
      if (await this.journal.findCreate(collection,subject!,this.writer)) throw new Error(`a ${kind} for this exact post is already committed or awaiting confirmation`);
      record = {$type: collection, subject:subject!, createdAt: new Date().toISOString()};
    } else {
      collection = POST_COLLECTION;
      record = {$type: POST_COLLECTION, text:text!, createdAt: new Date().toISOString()};
      if (kind === "reply") record.reply = {root:root!, parent:parent!};
    }
    const address = {repo:this.did, collection, rkey:deterministicTid(`interaction\n${this.did}\n${operationId}`)};
    await this.journal.prepare(address, record, operationId, intentDigest);
    const result = await this.run(operationId);
    return {operationId, result, uri:atUri(address)};
  }

  public async remove(kind: "unlike"|"unrepost"|"delete-post", operationId: string, uri: string, cid: string | undefined, expectedSubject?: StrongRef): Promise<InteractionOutcome> {
    operation(operationId);
    const address = parseOwnedUri(uri, this.did);
    const expectedCollection = kind === "unlike" ? LIKE_COLLECTION : kind === "unrepost" ? REPOST_COLLECTION : POST_COLLECTION;
    if (address.collection !== expectedCollection) throw new Error(`${kind} does not match the target record collection`);
    const subject=kind === "delete-post" ? undefined : strongRef(expectedSubject);
    const intentDigest=digest({kind,record:{uri,cid:cid??null},...(subject?{subject}:{})});
    const existing = await this.journal.find(operationId);
    if (existing) {
      if (existing.action !== "delete" || atUri(existing) !== uri || existing.intentDigest !== intentDigest) throw new Error("operation was reused with different intent");
      return {operationId,result:await this.run(operationId),uri};
    }
    if (await this.journal.recentCount(this.did,Date.now()-86400000) >= 100) throw new Error("daily content interaction limit reached");
    if (![LIKE_COLLECTION, REPOST_COLLECTION, POST_COLLECTION].includes(address.collection)) throw new Error("record is not an interaction");
    if ((await this.journal.entries(this.did)).filter(item => ["prepared","attempted_unknown"].includes(item.phase) || (item.phase === "refused" && ["confirmed_absent","confirmed_present"].includes(item.reason ?? ""))).length >= 25) {
      throw new Error("unfinished content interaction limit reached; check outcomes in Settings");
    }
    const observed = await this.writer.get(address);
    if (!observed || (cid !== undefined && observed.cid !== cid)) throw new Error("the exact record to undo is unavailable");
    if (address.collection === POST_COLLECTION) {
      if (!await this.journal.findCommittedCreate(address, observed.cid)) throw new Error("only a post created by this app may be deleted here");
    } else {
      const record = observed.record as {$type?:unknown;subject?:unknown};
      if (record.$type !== address.collection || !sameRef(record.subject, subject!)) throw new Error("the interaction record does not match this post");
    }
    await this.journal.prepareDelete(address, observed, operationId, intentDigest);
    const result = await this.run(operationId);
    return {operationId, result, uri};
  }

  public async resume(operationId: string): Promise<InteractionOutcome> {
    operation(operationId);
    const planned = await this.journal.get(operationId);
    if (planned.repo !== this.did || ![LIKE_COLLECTION, REPOST_COLLECTION, POST_COLLECTION].includes(planned.collection)) throw new Error("operation belongs to another account or feature");
    return {operationId, result:await this.journal.reconcile(operationId,this.writer), uri:atUri(planned)};
  }

  public async planned(operationId: string) {
    operation(operationId);
    const planned = await this.journal.get(operationId);
    if (planned.repo !== this.did || ![LIKE_COLLECTION, REPOST_COLLECTION, POST_COLLECTION].includes(planned.collection)) throw new Error("operation belongs to another account or feature");
    return planned;
  }

  public async retry(operationId: string): Promise<InteractionOutcome> {
    const planned = await this.planned(operationId);
    if (planned.phase !== "prepared") {
      if (planned.phase !== "refused" || (planned.action === "delete" ? planned.reason !== "confirmed_present" : planned.reason !== "confirmed_absent")) throw new Error("only a prepared or confirmed incomplete operation may be retried");
      await this.journal.retryConfirmedAbsent(operationId);
    }
    return {operationId,result:await this.journal.run(operationId,this.writer),uri:atUri(planned)};
  }

  private async run(operationId: string): Promise<WriteResult> {
    const startingPhase=(await this.journal.get(operationId)).phase;
    let result = await this.journal.run(operationId, this.writer);
    if (startingPhase !== "attempted_unknown" && result.phase === "refused" && (result.reason === "confirmed_absent" || result.reason === "confirmed_present")) {
      // A confirmed observation permits a retry. Delete retries need to return
      // to prepared just as creates do, but retain their immutable intent.
      const operation = result.operation;
      if (operation.action === "delete") {
        // Re-preparing the same delete is safe only while the exact record is present.
        const observed = await this.writer.get(operation);
        if (!observed || observed.cid !== operation.committedCid) return result;
      }
      await this.journal.retryConfirmedAbsent(operationId);
      result = await this.journal.run(operationId, this.writer);
    }
    return result;
  }
}

export function postText(value: string | undefined): string {
  const text = value?.trim() ?? "";
  if (!text || /[\u0000]/.test(text)) throw new Error("post text is required");
  if (Buffer.byteLength(text, "utf8") > 3000 || [...new Intl.Segmenter(undefined,{granularity:"grapheme"}).segment(text)].length > 300) {
    throw new Error("post text must be at most 300 characters and 3,000 bytes");
  }
  return text;
}

function operation(value: string): void { if (!/^[A-Za-z0-9_-]{16,200}$/.test(value)) throw new Error("invalid operation identity"); }
function strongRef(value: StrongRef | undefined): StrongRef {
  if (!value || !URI.test(value.uri) || !value.uri.includes("/app.bsky.feed.post/") || !value.cid || value.cid.length > 256 || /\s/.test(value.cid)) throw new Error("invalid exact post reference");
  return {uri:value.uri,cid:value.cid};
}
function sameRef(value: unknown, expected: StrongRef): boolean {
  const item = value as {uri?:unknown;cid?:unknown} | null;
  return item?.uri === expected.uri && item.cid === expected.cid;
}
function parseOwnedUri(uri: string, did: string): RecordAddress {
  const match = URI.exec(uri);
  if (!match || match[1] !== did) throw new Error("undo may affect only the signed-in account's record");
  return {repo:match[1],collection:match[2]!,rkey:match[3]!};
}
function atUri(address: RecordAddress): string { return `at://${address.repo}/${address.collection}/${address.rkey}`; }
