import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { OAuthSession } from "@atproto/oauth-client-node";
import { AuthorActionStore } from "./actions.js";
import type { AppConfig } from "./config.js";
import type { ProjectionBundle, PublicEntry } from "./feed.js";
import type { ExactRecord, SpaceRecordWriter } from "./records.js";
import { createHandler } from "./server.js";
import { WebSessionStore } from "./storage.js";

const AUTHOR = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa";
const COMMUNITY = "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb";
const CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti";

test("real local HTTP surface leads with the feed and never publishes a write optimistically", async () => {
  const root = await mkdtemp(join(tmpdir(), "juniper-http-"));
  const config: AppConfig = {
    publicUrl: "http://127.0.0.1:3210",
    spaceUri: "at://did:plc:authority/type/self",
    communityActorDid: COMMUNITY,
    runtimeDirectory: root,
    projectionDirectory: join(root, "projection"),
    port: 3210,
  };
  const sessions = new WebSessionStore(join(root, "sessions"));
  const actions = new AuthorActionStore(join(root, "actions.json"));
  const writer = new FakeWriter();
  let bundle = publishedBundle();
  const handler = createHandler({
    config,
    oauth: {
      authorize: async () => new URL("https://auth.invalid.test/authorize"),
      callback: async () => ({ session: {} as OAuthSession }),
      restore: async () => ({} as OAuthSession),
      revoke: async () => undefined,
    },
    webSessions: sessions,
    actions,
    readBundle: async () => bundle,
    writer: () => writer,
    now: () => new Date("2026-08-24T12:00:00.000Z"),
  });
  const server = createServer((request, response) => void handler(request, response));
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try {
    const home = await fetch(origin);
    const homeBody = await home.text();
    assert.ok(homeBody.indexOf("Recently featured") < homeBody.indexOf("Why is this here?"));
    assert.match(homeBody, /Shared tool shelf/);
    assert.doesNotMatch(homeBody, /LtHash|DPoP|CARv1/);

    const token = await sessions.issue(AUTHOR, new Date("2026-08-24T12:00:00.000Z"));
    const result = await fetch(`${origin}/author/create-submit`, {
      method: "POST",
      headers: {
        Origin: config.publicUrl,
        Cookie: `juniper_session=${token}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        title: "A new repair note",
        body: "This should wait for qualification.",
        authorDisplayReference: "@alex.invalid.test",
        consent: "yes",
      }),
      redirect: "manual",
    });
    assert.equal(result.status, 303);
    assert.equal(writer.calls.length, 2);
    assert.equal((await actions.list(AUTHOR)).length, 1);
    assert.equal(bundle.ordinary?.entries.length, 1);
    const after = await fetch(origin).then((response) => response.text());
    assert.doesNotMatch(after, /A new repair note/);

    const refused = await fetch(`${origin}/author/create-submit`, {
      method: "POST",
      headers: {
        Origin: "https://substitution.invalid.test",
        Cookie: `juniper_session=${token}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({ title: "No", body: "No", authorDisplayReference: "No", consent: "yes" }),
    });
    assert.equal(refused.status, 400);
    assert.equal(writer.calls.length, 2);
  } finally {
    await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

class FakeWriter implements SpaceRecordWriter {
  readonly calls: string[] = [];
  async create(input: { repoDid: string; collection: string; record: import("@atproto/lex-data").LexMap }): Promise<ExactRecord> {
    this.calls.push(input.collection);
    return {
      uri: `at://did:plc:authority/type/self/${input.repoDid}/${input.collection}/${this.calls.length}`,
      cid: CID,
    };
  }
  async put(): Promise<ExactRecord> { throw new Error("not used"); }
  async delete(): Promise<void> { throw new Error("not used"); }
}

function publishedBundle(): ProjectionBundle {
  const entry: PublicEntry = {
    projectionIdentity: `sha256:${"a".repeat(64)}`,
    projectionStateId: `sha256:${"b".repeat(64)}`,
    lifecycleState: "added",
    sourceUri: "at://did:plc:authority/type/self/did:plc:author/post/1",
    admittedSourceCid: CID,
    authorDid: AUTHOR,
    admissionId: `sha256:${"c".repeat(64)}`,
    admittedAt: "2026-08-24T11:00:00Z",
    sourceRelationship: "exact",
    presentation: {
      sourceReferenceId: `sha256:${"d".repeat(64)}`,
      sourceUri: "at://did:plc:authority/type/self/did:plc:author/post/1",
      sourceCid: CID,
      title: "Shared tool shelf",
      body: "A place for the clamps.",
      authorDisplayReference: "@maya.invalid.test",
    },
    technicalReceipts: null,
    removalId: null,
  };
  return {
    ordinary: {
      feedId: `sha256:${"e".repeat(64)}`,
      artifactId: `sha256:${"f".repeat(64)}`,
      channel: "ordinary_reader",
      publishedAt: "2026-08-24T11:00:00Z",
      communityActorDid: COMMUNITY,
      entries: [entry],
    },
    audit: {
      feedId: `sha256:${"1".repeat(64)}`,
      artifactId: `sha256:${"2".repeat(64)}`,
      channel: "technical_audit",
      publishedAt: "2026-08-24T11:00:01Z",
      communityActorDid: COMMUNITY,
      entries: [{ ...entry, technicalReceipts: { admissionId: entry.admissionId } }],
    },
  };
}
