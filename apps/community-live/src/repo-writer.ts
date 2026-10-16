import { Client } from "@atproto/lex-client";
import type { LexMap } from "@atproto/lex-data";
import { asStringFormat } from "@atproto/lex-schema";
import type { OAuthSession } from "@atproto/oauth-client-node";

import type {
  ObservedRecord,
  PublicRepoWriter,
  RecordAddress,
} from "./operations.js";

const ALLOWED = new Set(["app.bsky.feed.post", "app.phlogiston.community.submit"]);

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
    const response = await this.client.createRecord(
      {
        ...value,
        $type: asStringFormat(String(value.$type), "nsid"),
      },
      asStringFormat(address.rkey, "record-key"),
      { validate: false, maxRetries: 0 },
    );
    if (response.body.uri !== atUri(address) || typeof response.body.cid !== "string") {
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
      if (typeof response.body.cid !== "string") throw new Error("PDS omitted record CID");
      return { cid: response.body.cid, record: response.body.value };
    } catch (error) {
      if (isNotFound(error)) return null;
      throw error;
    }
  }

  private validate(address: RecordAddress): void {
    if (address.repo !== this.expectedDid) throw new Error("writer may affect only OAuth subject repo");
    if (!ALLOWED.has(address.collection)) throw new Error("collection is outside participant grant");
  }
}

function atUri(address: RecordAddress): string {
  return `at://${address.repo}/${address.collection}/${address.rkey}`;
}

function isNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "error" in error && error.error === "RecordNotFound";
}
