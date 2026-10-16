import { createHash } from "node:crypto";

import {
  DurableWriteJournal,
  type PublicRepoWriter,
  type RecordAddress,
  type WritePhase,
} from "./operations.js";

export const POST_COLLECTION = "app.bsky.feed.post";
export const SUBMIT_COLLECTION = "app.phlogiston.community.submit";

export interface StrongRef {
  uri: string;
  cid: string;
}

export interface ContributionPlan {
  operationId: string;
  sourceOperationId: string;
  contextOperationId: string;
  authorDid: string;
  source: RecordAddress;
  context: RecordAddress;
  communityDid: string;
  createdAt: string;
  discussion?: StrongRef;
  /**
   * Set when the source post existed before this operation: the source phase is
   * already committed at this exact CID (read back from the author's own repo),
   * so only the community submission record is written.
   */
  existingPostCid?: string;
}

export type ContributionStatus =
  | "source_pending"
  | "source_outcome_unknown"
  | "source_conflict"
  | "community_submission_pending"
  | "community_submission_outcome_unknown"
  | "community_submission_conflict"
  | "complete";

export interface ContributionResult {
  status: ContributionStatus;
  plan: ContributionPlan;
}

export interface PrepareContribution {
  operationId: string;
  authorDid: string;
  sourceRkey: string;
  text: string;
  communityDid: string;
  createdAt: string;
  reply?: {
    root: StrongRef;
    parent: StrongRef;
    discussion: StrongRef;
  };
}

export class ContributionService {
  public constructor(
    private readonly journal: DurableWriteJournal,
    private readonly writer: PublicRepoWriter,
  ) {}

  public async readContext(plan: ContributionPlan) {
    return this.writer.get(plan.context);
  }

  public async prepare(input: PrepareContribution): Promise<ContributionPlan> {
    if (!input.authorDid.startsWith("did:")) throw new Error("invalid author DID");
    if (!input.communityDid.startsWith("did:")) throw new Error("invalid community DID");
    if (input.text.trim().length === 0) throw new Error("post text is required");
    if (input.reply !== undefined && input.reply.discussion.uri.length === 0) {
      throw new Error("reply opt-in requires an admitted discussion");
    }

    const source: RecordAddress = {
      repo: input.authorDid,
      collection: POST_COLLECTION,
      rkey: input.sourceRkey,
    };
    const sourceRecord: Record<string, unknown> = {
      $type: POST_COLLECTION,
      text: input.text,
      createdAt: input.createdAt,
    };
    if (input.reply !== undefined) {
      sourceRecord.reply = {
        root: input.reply.root,
        parent: input.reply.parent,
      };
    }
    const sourceOperationId = `${input.operationId}:source`;
    await this.journal.prepare(source, sourceRecord, sourceOperationId);

    const contextRkey = deterministicTid(`${input.operationId}:context`);
    const context: RecordAddress = {
      repo: input.authorDid,
      collection: SUBMIT_COLLECTION,
      rkey: contextRkey,
    };
    const contextOperationId = `${input.operationId}:context`;

    return {
      operationId: input.operationId,
      sourceOperationId,
      contextOperationId,
      authorDid: input.authorDid,
      source,
      context,
      communityDid: input.communityDid,
      createdAt: input.createdAt,
      ...(input.reply === undefined ? {} : { discussion: input.reply.discussion }),
    };
  }


  /** Read the author's own post to learn its exact current CID; null when absent. */
  public async readOwnPost(authorDid: string, rkey: string): Promise<StrongRef | null> {
    const observed = await this.writer.get({ repo: authorDid, collection: POST_COLLECTION, rkey });
    if (observed === null) return null;
    return { uri: `at://${authorDid}/${POST_COLLECTION}/${rkey}`, cid: observed.cid };
  }

  /**
   * Plan the submission of an existing post. The operation and submission keys
   * derive from the community and the exact subject, so submitting the same
   * post version again resumes the same operation instead of writing a second
   * submission record.
   */
  public planExisting(input: {
    authorDid: string;
    subject: StrongRef;
    communityDid: string;
    createdAt: string;
  }): ContributionPlan {
    if (!input.authorDid.startsWith("did:")) throw new Error("invalid author DID");
    if (!input.communityDid.startsWith("did:")) throw new Error("invalid community DID");
    const prefix = `at://${input.authorDid}/${POST_COLLECTION}/`;
    if (!input.subject.uri.startsWith(prefix) || input.subject.cid.length === 0) {
      throw new Error("an existing-post submission must name the author's own post exactly");
    }
    const operationId = existingPostOperationId(input.communityDid, input.subject);
    return {
      operationId,
      sourceOperationId: `${operationId}:source`,
      contextOperationId: `${operationId}:context`,
      authorDid: input.authorDid,
      source: {
        repo: input.authorDid,
        collection: POST_COLLECTION,
        rkey: input.subject.uri.slice(prefix.length),
      },
      context: {
        repo: input.authorDid,
        collection: SUBMIT_COLLECTION,
        rkey: submissionRkey(input.communityDid, input.subject),
      },
      communityDid: input.communityDid,
      createdAt: input.createdAt,
      existingPostCid: input.subject.cid,
    };
  }

  public async advance(plan: ContributionPlan, readbackOnly = false): Promise<ContributionResult> {
    let sourceCid = plan.existingPostCid;
    if (sourceCid === undefined) {
      const source = await this.runRecoverable(plan.sourceOperationId, readbackOnly);
      if (source.phase === "attempted_unknown") {
        return { status: "source_outcome_unknown", plan };
      }
      if (source.phase === "conflict") return { status: "source_conflict", plan };
      if (source.phase !== "committed") return { status: "source_pending", plan };
      if (source.cid === undefined) throw new Error("committed source is missing its CID");
      sourceCid = source.cid;
    }

    const contextRecord: Record<string, unknown> = {
      $type: SUBMIT_COLLECTION,
      community: plan.communityDid,
      subject: {
        uri: `at://${plan.authorDid}/${POST_COLLECTION}/${plan.source.rkey}`,
        cid: sourceCid,
      },
      createdAt: plan.createdAt,
    };
    if (plan.discussion !== undefined) contextRecord.discussion = plan.discussion;
    await this.journal.prepare(plan.context, contextRecord, plan.contextOperationId);
    const context = await this.runRecoverable(plan.contextOperationId, readbackOnly);
    if (context.phase === "attempted_unknown") {
      return { status: "community_submission_outcome_unknown", plan };
    }
    if (context.phase === "conflict") {
      return { status: "community_submission_conflict", plan };
    }
    if (context.phase !== "committed") {
      return { status: "community_submission_pending", plan };
    }
    return { status: "complete", plan };
  }

  private async runRecoverable(operationId: string, readbackOnly = false) {
    if (readbackOnly) {
      const operation = await this.journal.get(operationId);
      if (operation.phase === "attempted_unknown") return this.journal.reconcile(operationId, this.writer);
      return { phase: operation.phase, operation, reason: operation.reason, cid: operation.committedCid };
    }
    const result = await this.journal.run(operationId, this.writer);
    if (result.phase !== "refused" || result.reason !== "confirmed_absent") {
      return result;
    }
    await this.journal.retryConfirmedAbsent(operationId);
    return this.journal.run(operationId, this.writer);
  }
}

export function userMessage(status: ContributionStatus, plan?: ContributionPlan): string {
  if (plan?.existingPostCid !== undefined) {
    if (status === "complete") return "Submitted. Your post is now waiting for the moderator to add it here.";
    if (status.endsWith("conflict")) return "The saved record differs from this operation; nothing was overwritten.";
    return "Your Bluesky post is unchanged; the request to add it here is not confirmed yet.";
  }
  if (status === "source_outcome_unknown") return "Checking whether your public post was saved…";
  if (status === "community_submission_outcome_unknown" || status === "community_submission_pending") {
    return "Your post is on Bluesky. The request to add it here is still being saved.";
  }
  if (status.endsWith("conflict")) return "The saved record differs from this operation; nothing was overwritten.";
  if (status === "complete") {
    return plan?.discussion === undefined
      ? "Submitted. Your post is now waiting for the moderator to add it here."
      : "Posted. It will appear in the discussion once the community records it.";
  }
  return "Posting…";
}

/** Journal and plan key for one existing-post submission of an exact subject. */
export function existingPostOperationId(communityDid: string, subject: StrongRef): string {
  const material = `existing-post\n${communityDid}\n${subject.uri}\n${subject.cid}`;
  return `existing-${createHash("sha256").update(material).digest("hex").slice(0, 40)}`;
}

/**
 * The same content-derived TID `community-submit` uses, so one exact subject
 * maps to one submission record key in the author's repository whichever
 * participant tool wrote it.
 */
export function submissionRkey(communityDid: string, subject: StrongRef): string {
  const alphabet = "234567abcdefghijklmnopqrstuvwxyz";
  const digest = createHash("sha256")
    .update(`community-submit\n${communityDid}\n${subject.uri}\n${subject.cid}`)
    .digest();
  const value = digest.readBigUInt64BE(0) & 0x7fffffffffffffffn;
  let result = "";
  for (let shift = 60n; shift >= 0n; shift -= 5n) result += alphabet[Number((value >> shift) & 31n)];
  return result;
}

export function deterministicTid(seed: string): string {
  const alphabet = "234567abcdefghijklmnopqrstuvwxyz";
  const bytes = createHash("sha256").update(seed).digest();
  let result = "";
  for (let index = 0; index < 13; index += 1) {
    // A TID's first character carries the top timestamp bits: only the first
    // sixteen alphabet letters are valid there; the observer rejects the rest.
    result += alphabet[bytes[index]! & (index === 0 ? 15 : 31)];
  }
  return result;
}
