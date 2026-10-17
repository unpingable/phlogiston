import { Client, XrpcResponseError } from "@atproto/lex-client";
import type { LexMap } from "@atproto/lex-data";
import { asStringFormat } from "@atproto/lex-schema";
import type { OAuthSession } from "@atproto/oauth-client-node";

import {
  RecordConflictError,
  ProviderRefusalError,
  type ObservedRecord,
  type PublicRepoWriter,
  type RecordAddress,
} from "./operations.js";

const ALLOWED = new Set(["app.bsky.feed.post", "app.bsky.feed.like", "app.bsky.feed.repost", "app.phlogiston.community.submit"]);

export class OAuthPublicRepoWriter implements PublicRepoWriter {
  private readonly client: Client;
  public constructor(
    session: OAuthSession,
    private readonly expectedDid: string,
  ) {
    if (session.did !== expectedDid) throw new Error("OAuth subject mismatch");
    this.client = new Client(session);
  }

  public async create(address: RecordAddress, record: unknown): Promise<{ cid: string }> {
    this.validate(address);
    const value = record as LexMap;
    if (value.$type !== address.collection) throw new Error("record type does not match its collection");
    let response;
    try { response = await this.client.createRecord(
      {
        ...value,
        $type: asStringFormat(String(value.$type), "nsid"),
      },
      asStringFormat(address.rkey, "record-key"),
      { validate: false, maxRetries: 0 },
    ); } catch (error) { throw providerError(error); }
    if (response.body.uri !== atUri(address) || typeof response.body.cid !== "string" || !response.body.cid) {
      throw new Error("PDS returned an unexpected record identity");
    }
    return { cid: response.body.cid };
  }

  public async get(address: RecordAddress): Promise<ObservedRecord | null> {
    this.validate(address);
    try {
      const response = await this.client.getRecord(
        asStringFormat(address.collection, "nsid"),
        asStringFormat(address.rkey, "record-key"),
        { repo: asStringFormat(address.repo, "at-identifier"), maxRetries: 0 },
      );
      if (response.body.uri !== atUri(address) || typeof response.body.cid !== "string" || !response.body.cid) throw new Error("PDS returned an unexpected record identity");
      return { cid: response.body.cid, record: response.body.value };
    } catch (error) {
      if (isNotFound(error)) return null;
      throw error;
    }
  }

  public async delete(address: RecordAddress, swapRecord?: string): Promise<void> {
    this.validate(address);
    try {
      await this.client.deleteRecord(
        asStringFormat(address.collection, "nsid"), asStringFormat(address.rkey, "record-key"),
        { repo: asStringFormat(address.repo, "at-identifier"), ...(swapRecord ? {swapRecord} : {}), maxRetries: 0 },
      );
    } catch (error) {
      if (typeof error === "object" && error !== null && "error" in error && error.error === "InvalidSwap") throw new RecordConflictError("record changed before delete");
      throw providerError(error);
    }
  }

  private validate(address: RecordAddress): void {
    if (address.repo !== this.expectedDid) throw new Error("writer may affect only OAuth subject repo");
    if (!ALLOWED.has(address.collection)) throw new Error("collection is outside participant grant");
  }
}

function providerError(error: unknown): unknown {
  // Only a complete, typed provider refusal establishes no dispatch effect.
  // Timeouts, proxy errors, 5xx and unexpected response bodies stay unknown.
  if (error instanceof XrpcResponseError && error.body !== undefined && [400,401,403,429].includes(error.status) &&
      ["InvalidRequest","AuthRequired","AuthenticationRequired","Forbidden","InsufficientScope","InvalidToken","ExpiredToken","RateLimitExceeded"].includes(error.error)) {
    return new ProviderRefusalError(error.error);
  }
  return error;
}

function atUri(address: RecordAddress): string {
  return `at://${address.repo}/${address.collection}/${address.rkey}`;
}

function isNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "error" in error && error.error === "RecordNotFound";
}
