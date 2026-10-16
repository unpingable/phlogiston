import assert from "node:assert/strict";
import { mkdir, mkdtemp, readdir, writeFile } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { OAuthSession } from "@atproto/oauth-client-node";

import { ActivitySnapshots, type SeenStore } from "./activity.js";
import type { AppConfig } from "./config.js";
import { escapeHtml } from "./html.js";
import { createHandler, type Dependencies } from "./server.js";
import { userMessage, type ContributionPlan } from "./contributions.js";
import { ObserverClient } from "./observer.js";
import { AppViewProfileDirectory, ProfileCache } from "./profiles.js";
import { ContributionPlanStore, WebSessionStore } from "./storage.js";
import { canonical, type ObservedRecord, type PublicRepoWriter, type RecordAddress } from "./operations.js";

const MODERATOR = "did:plc:moderator";
const MEMBER = "did:plc:alice";
const COMMUNITY = "did:plc:community";
const ADMISSION = "app.phlogiston.community.admission";

interface StubReply {
  status?: number;
  body?: unknown;
  raw?: string;
}

interface Harness {
  origin: string;
  config: AppConfig;
  sessions: WebSessionStore;
  plans: ContributionPlanStore;
  signOutCalls: string[];
  writer: FakeRepoWriter;
  close(): Promise<void>;
}

/** Stands in for the participant's own PDS behind the OAuth session. */
class FakeRepoWriter implements PublicRepoWriter {
  public readonly records = new Map<string, ObservedRecord>();
  public readonly creates: string[] = [];
  public readonly reads: string[] = [];
  public failAfterCommitCollection?: string | undefined;

  public async create(address: RecordAddress, record: unknown): Promise<{ cid: string }> {
    const key = `${address.repo}/${address.collection}/${address.rkey}`;
    this.creates.push(key);
    if (this.records.has(key)) throw new Error("record already exists");
    const cid = `cid-${canonical(record).length}`;
    this.records.set(key, { cid, record });
    if (this.failAfterCommitCollection === address.collection) {
      this.failAfterCommitCollection = undefined;
      throw new Error("response lost after commit");
    }
    return { cid };
  }

  public async get(address: RecordAddress): Promise<ObservedRecord | null> {
    const key = `${address.repo}/${address.collection}/${address.rkey}`;
    this.reads.push(key);
    return this.records.get(key) ?? null;
  }
}

async function startApp(
  reply: (path: string) => StubReply,
  overrides: Partial<AppConfig> = {},
  appViewReply: (path: string) => StubReply = () => ({ status: 500, body: {} }),
  oauth: Partial<Dependencies["oauth"]> = {},
): Promise<Harness> {
  const root = await mkdtemp(join(tmpdir(), "community-http-"));
  const observer = createServer((request, response) => {
    const stub = reply(request.url ?? "/");
    response.statusCode = stub.status ?? 200;
    response.setHeader("Content-Type", "application/json");
    response.end(stub.raw ?? JSON.stringify(stub.body ?? {}));
  });
  await new Promise<void>((resolve) => observer.listen(0, "127.0.0.1", resolve));
  const observerUrl = `http://127.0.0.1:${(observer.address() as AddressInfo).port}`;
  const appView = createServer((request, response) => {
    const stub = appViewReply(request.url ?? "/");
    response.statusCode = stub.status ?? 200;
    response.setHeader("Content-Type", "application/json");
    response.end(stub.raw ?? JSON.stringify(stub.body ?? {}));
  });
  await new Promise<void>((resolve) => appView.listen(0, "127.0.0.1", resolve));
  const appViewOrigin = `http://127.0.0.1:${(appView.address() as AddressInfo).port}`;
  const config: AppConfig = {
    publicUrl: "http://127.0.0.1:3210",
    communityDid: COMMUNITY,
    communityName: "Test Community",
    communityPurpose: "A bounded test community",
    moderatorDid: MODERATOR,
    runtimeDirectory: root,
    observerUrl,
    observerMaxResponseBytes: 64 * 1024,
    discussionsMaxItems: 500,
    appViewOrigin,
    avatarsEnabled: false,
    authoritySocket: join(root, "authority.sock"),
    port: 3210,
    ...overrides,
  };
  const sessions = new WebSessionStore(join(root, "web-sessions"));
  const plans = new ContributionPlanStore(join(root, "contribution-plans"));
  const signOutCalls: string[] = [];
  const writer = new FakeRepoWriter();
  const deps: Dependencies = {
    config,
    oauth: {
      authorize: async () => new URL("https://auth.invalid.test/authorize"),
      callback: async () => ({ session: { did: MEMBER } as unknown as OAuthSession }),
      restore: async (did: string) => ({
        did,
        signOut: async () => {
          signOutCalls.push(did);
        },
      } as unknown as OAuthSession),
      revoke: async (did: string) => {
        signOutCalls.push(did);
      },
      ...oauth,
    },
    webSessions: sessions,
    plans,
    activities: new ActivitySnapshots(Buffer.alloc(32, 3), new MemorySeenStore()),
    authority: { request: async () => ({ ok: true }) },
    projection: new ObserverClient(config.observerUrl, config.observerMaxResponseBytes),
    profiles: new AppViewProfileDirectory(
      config.appViewOrigin,
      new ProfileCache(1_000, 10 * 60 * 1_000, 60 * 1_000, () => Date.now()),
    ),
    repoWriter: (_session, did) => {
      assert.equal(did, _session.did);
      return writer;
    },
  };
  const app = createServer((request, response) => void createHandler(deps)(request, response));
  await new Promise<void>((resolve) => app.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(app.address() as AddressInfo).port}`;
  return {
    origin,
    config,
    sessions,
    plans,
    signOutCalls,
    writer,
    close: async () => {
      await closeServer(app);
      await closeServer(observer);
      await closeServer(appView);
    },
  };
}

function closeServer(server: Server): Promise<void> {
  return new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}

class MemorySeenStore implements SeenStore {
  private readonly versions = new Map<string, number>();

  public async get(memberDid: string, discussionUri: string): Promise<number> {
    return this.versions.get(`${memberDid} ${discussionUri}`) ?? 0;
  }

  public async advance(memberDid: string, discussionUri: string, displayedVersion: number): Promise<void> {
    const item = `${memberDid} ${discussionUri}`;
    const current = this.versions.get(item) ?? 0;
    if (displayedVersion > current) this.versions.set(item, displayedVersion);
  }
}

interface Page {
  status: number;
  body: string;
  headers: Headers;
}

async function get(origin: string, path: string, cookie?: string): Promise<Page> {
  const response = await fetch(`${origin}${path}`, {
    headers: cookie === undefined ? {} : { Cookie: cookie },
    redirect: "manual",
  });
  return { status: response.status, body: await response.text(), headers: response.headers };
}

async function post(
  origin: string,
  path: string,
  form: Record<string, string>,
  options: { cookie?: string; origin?: string } = {},
): Promise<Page> {
  const response = await fetch(`${origin}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Origin: options.origin ?? "http://127.0.0.1:3210",
      ...(options.cookie === undefined ? {} : { Cookie: options.cookie }),
    },
    body: new URLSearchParams(form),
    redirect: "manual",
  });
  return { status: response.status, body: await response.text(), headers: response.headers };
}

function cookie(token: string): string {
  return `community_session=${token}`;
}

function discussionItem(rkey: string, text: string): Record<string, unknown> {
  return {
    discussion: { uri: `at://${COMMUNITY}/${ADMISSION}/${rkey}`, cid: `cid-${rkey}` },
    root: { uri: `at://did:plc:bob/app.bsky.feed.post/${rkey}`, cid: `post-cid-${rkey}` },
    post: { text, createdAt: "2026-09-08T09:30:00.000Z" },
    authorDid: "did:plc:bob",
    admittedAt: "2026-09-09T10:00:00.000Z",
    status: "visible",
    closed: false,
  };
}

function discussionList(count: number): Record<string, unknown> {
  return {
    communityDid: COMMUNITY,
    discussions: Array.from({ length: count }, (_, index) => discussionItem(`rkey${index}`, `Topic number ${index}`)),
    cursor: null,
    snapshot: {},
  };
}

const DETAIL = {
  communityDid: COMMUNITY,
  discussion: discussionItem("root1", "Root post text"),
  replies: [
    {
      status: "visible",
      authorDid: "did:plc:carol",
      post: { text: "A visible reply", createdAt: "2026-09-08T10:00:00.000Z" },
      admission: { uri: `at://${COMMUNITY}/app.phlogiston.community.replyAdmission/reply1`, cid: "cid-reply1" },
      subject: { uri: "at://did:plc:carol/app.bsky.feed.post/reply1", cid: "post-cid-reply1" },
      admittedAt: "2026-09-08T11:00:00.000Z",
    },
    {
      status: "removed",
      reason: "Off topic",
      post: {},
      admission: { uri: `at://${COMMUNITY}/app.phlogiston.community.replyAdmission/reply2`, cid: "cid-reply2" },
      subject: { uri: "at://did:plc:carol/app.bsky.feed.post/reply2", cid: "post-cid-reply2" },
      authorDid: "did:plc:carol",
      admittedAt: "2026-09-08T11:05:00.000Z",
    },
  ],
  activity: [],
  snapshot: {},
};

test("anonymous home lists discussions with the sign-in form and no session actions", async () => {
  const harness = await startApp(() => ({ body: discussionList(2) }));
  try {
    const page = await get(harness.origin, "/");
    assert.equal(page.status, 200);
    assert.match(page.headers.get("content-type") ?? "", /text\/html/);
    assert.match(page.headers.get("content-security-policy") ?? "", /default-src 'self'/);
    assert.match(page.body, /Topic number 0/);
    assert.match(page.body, /Topic number 1/);
    assert.match(page.body, /href="\/d\/rkey0"/);
    assert.match(page.body, /action="\/oauth\/login"/);
    assert.match(page.body, /href="\/static\/app\.css"/);
    assert.doesNotMatch(page.body, /Sign out|Disconnect/);
  } finally {
    await harness.close();
  }
});

test("the stylesheet is served same-origin with a CSS content type", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const page = await get(harness.origin, "/static/app.css");
    assert.equal(page.status, 200);
    assert.match(page.headers.get("content-type") ?? "", /text\/css/);
    assert.match(page.body, /font-family/);
    assert.doesNotMatch(page.body, /<html/);
  } finally {
    await harness.close();
  }
});

test("signed-in home shows the contribute form and session actions", async () => {
  const harness = await startApp(() => ({ body: discussionList(1) }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /action="\/contribute"/);
    assert.match(page.body, /action="\/signout"/);
    assert.match(page.body, /action="\/disconnect"/);
    assert.match(page.body, />Sign out</);
    assert.match(page.body, />Disconnect</);
    assert.match(page.body, new RegExp(escapeHtml(MEMBER)));
    assert.doesNotMatch(page.body, /action="\/oauth\/login"/);
  } finally {
    await harness.close();
  }
});

test("the discussion list paginates locally with a truthful total", async () => {
  const harness = await startApp(() => ({ body: discussionList(30) }));
  try {
    const first = await get(harness.origin, "/");
    assert.equal(first.status, 200);
    assert.match(first.body, /1–25 of 30 discussions/);
    assert.match(first.body, /Page 1 of 2/);
    assert.match(first.body, /<nav class="pages" aria-label="Pages">/);
    assert.match(first.body, /href="\/\?page=2"/);
    assert.match(first.body, /Topic number 24/);
    assert.doesNotMatch(first.body, /Topic number 29/);

    const second = await get(harness.origin, "/?page=2");
    assert.equal(second.status, 200);
    assert.match(second.body, /26–30 of 30 discussions/);
    assert.match(second.body, /Page 2 of 2/);
    assert.match(second.body, /Topic number 29/);
    assert.doesNotMatch(second.body, /Topic number 24/);
    const previous = second.body.slice(second.body.indexOf("Previous page") - 60, second.body.indexOf("Previous page"));
    assert.match(previous, /href="\/"/);
  } finally {
    await harness.close();
  }
});

test("malformed page numbers are refused and out-of-range pages clamp to the real range", async () => {
  const harness = await startApp(() => ({ body: discussionList(30) }));
  try {
    const malformed = await get(harness.origin, "/?page=xyz");
    assert.equal(malformed.status, 400);
    assert.match(malformed.headers.get("content-type") ?? "", /text\/html/);
    const negative = await get(harness.origin, "/?page=-1");
    assert.equal(negative.status, 400);
    const clamped = await get(harness.origin, "/?page=99");
    assert.equal(clamped.status, 200);
    assert.match(clamped.body, /Page 2 of 2/);
    const zero = await get(harness.origin, "/?page=0");
    assert.equal(zero.status, 200);
    assert.match(zero.body, /Page 1 of 2/);
  } finally {
    await harness.close();
  }
});

test("the item-count ceiling renders the outgrown state and never a truncated list", async () => {
  const harness = await startApp(() => ({ body: discussionList(4) }), { discussionsMaxItems: 3 });
  try {
    const page = await get(harness.origin, "/");
    assert.equal(page.status, 200);
    assert.match(page.body, /<p class="notice">This community has more discussions than this page can show yet\.<\/p>/);
    assert.doesNotMatch(page.body, /pagination|Topic number/);
    assert.doesNotMatch(page.body, /href="\/discussion/);
    assert.doesNotMatch(page.body, /of 4 discussions/);
  } finally {
    await harness.close();
  }
});

test("the response-byte ceiling renders the same outgrown state", async () => {
  const harness = await startApp(() => ({ body: discussionList(2) }), { observerMaxResponseBytes: 256 });
  try {
    const page = await get(harness.origin, "/");
    assert.equal(page.status, 200);
    assert.match(page.body, /This community has more discussions than this page can show yet\./);
    assert.doesNotMatch(page.body, /Topic number/);
  } finally {
    await harness.close();
  }
});

test("a found discussion renders its root, replies, tombstones, and reply form", async () => {
  const harness = await startApp(() => ({ body: DETAIL }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /Root post text/);
    assert.match(page.body, /A visible reply/);
    assert.match(page.body, /class="tombstone"/);
    assert.match(page.body, /Off topic/);
    assert.match(page.body, /<label for="reply-text">Reply<\/label><p id="reply-note">Your reply is posted publicly on your Bluesky account\.<\/p><textarea id="reply-text" name="text" aria-describedby="reply-note" required>/);
    assert.match(page.body, /<button>Post reply and add to this discussion<\/button>/);
    assert.doesNotMatch(page.body, /opt in|Withdraw/i);
  } finally {
    await harness.close();
  }
});

test("a missing discussion is a truthful 404, whether by status or by shape", async () => {
  const byStatus = await startApp(() => ({ status: 404, body: { error: "not_found" } }));
  try {
    const { token } = await byStatus.sessions.issue(MEMBER);
    const page = await get(byStatus.origin, "/d/missing", cookie(token));
    assert.equal(page.status, 404);
    assert.match(page.headers.get("content-type") ?? "", /text\/html/);
    assert.match(page.body, /Not found/);
    assert.match(page.body, /That discussion isn&#39;t in this community\./);
  } finally {
    await byStatus.close();
  }
  const byShape = await startApp(() => ({ body: { communityDid: COMMUNITY } }));
  try {
    const { token } = await byShape.sessions.issue(MEMBER);
    const page = await get(byShape.origin, "/d/missing", cookie(token));
    assert.equal(page.status, 404);
    assert.match(page.body, /That discussion isn&#39;t in this community\./);
  } finally {
    await byShape.close();
  }
});

test("a discussion request without an rkey is a 400", async () => {
  const harness = await startApp(() => ({ body: DETAIL }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/discussion", cookie(token));
    assert.equal(page.status, 400);
    assert.match(page.body, /rkey is required/);
  } finally {
    await harness.close();
  }
});

test("anonymous visitors past the home page get a 401 with the sign-in form", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const page = await get(harness.origin, "/mine");
    assert.equal(page.status, 401);
    assert.match(page.headers.get("content-type") ?? "", /text\/html/);
    assert.match(page.body, /Sign in is required/);
    assert.match(page.body, /action="\/oauth\/login"/);
    const moderation = await get(harness.origin, "/moderation");
    assert.equal(moderation.status, 401);
  } finally {
    await harness.close();
  }
});

test("my discussions renders unread badges from the signed snapshot", async () => {
  const participants = {
    communityDid: COMMUNITY,
    participantDid: MEMBER,
    discussions: [{
      discussion: { uri: `at://${COMMUNITY}/${ADMISSION}/root1`, cid: "cid-root1" },
      authorDid: "did:plc:bob",
      post: { text: "A readable root title", createdAt: "2026-09-08T09:30:00.000Z" },
      admittedAt: "2026-09-09T10:00:00.000Z",
      lastActivitySequence: 4,
    }],
    activity: [
      { discussion: { uri: `at://${COMMUNITY}/${ADMISSION}/root1`, cid: "cid-root1" }, type: "reply_admitted" },
    ],
    snapshot: {},
  };
  const harness = await startApp(
    () => ({ body: participants }),
    {},
    appViewWith({ "did:plc:bob": { handle: "bob.example.test" } }),
  );
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/mine", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /<span class="badge">Unread<\/span>/);
    assert.match(page.body, /<a href="\/d\/root1">A readable root title<\/a>/);
    assert.match(page.body, /@bob\.example\.test/);
    assert.match(page.body, /1 replies, 0 moderation changes/);
    assert.match(page.body, /action="\/seen"/);
  } finally {
    await harness.close();
  }
});

test("the moderation queue is forbidden for non-moderators", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/moderation", cookie(token));
    assert.equal(page.status, 403);
    assert.match(page.body, /Moderator permission is required/);
    const submitted = await post(harness.origin, "/moderate", {
      csrf,
      kind: "admit-root",
      uri: `at://${MEMBER}/app.phlogiston.community.submit/x`,
      cid: "cid-x",
    }, { cookie: cookie(token) });
    assert.equal(submitted.status, 403);
    assert.match(submitted.body, /Moderator permission is required/);
  } finally {
    await harness.close();
  }
});

test("the moderation queue lists pending submissions for the moderator", async () => {
  const queue = {
    communityDid: COMMUNITY,
    submissions: [
      {
        submission: { uri: `at://${MEMBER}/app.phlogiston.community.submit/sub1`, cid: "cid-sub1" },
        subject: { uri: `at://${MEMBER}/app.bsky.feed.post/cand1`, cid: "post-cid-cand1" },
      },
    ],
    snapshot: {},
  };
  const harness = await startApp(() => ({ body: queue }));
  try {
    const { token } = await harness.sessions.issue(MODERATOR);
    const page = await get(harness.origin, "/moderation", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /app\.phlogiston\.community\.submit\/sub1/);
    assert.match(page.body, /Moderate<\/a>/);
    assert.match(page.body, /href="https:\/\/bsky\.app\/profile\/did:plc:alice\/post\/cand1" rel="noopener noreferrer">Public post on Bluesky<\/a>/);
  } finally {
    await harness.close();
  }
});

test("the moderation queue keeps the author DID visible beside a hydrated handle", async () => {
  const queue = {
    communityDid: COMMUNITY,
    submissions: [
      {
        submission: { uri: `at://${MEMBER}/app.phlogiston.community.submit/sub1`, cid: "cid-sub1" },
        subject: { uri: `at://${MEMBER}/app.bsky.feed.post/cand1`, cid: "post-cid-cand1" },
        authorDid: MEMBER,
      },
    ],
    snapshot: {},
  };
  const harness = await startApp(() => ({ body: queue }), {}, appViewWith({ [MEMBER]: { handle: "alice.example.test" } }));
  try {
    const { token } = await harness.sessions.issue(MODERATOR);
    const page = await get(harness.origin, "/moderation", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /@alice\.example\.test/);
    assert.match(page.body, /<span class="did">did:plc:alice<\/span>/);
    assert.match(page.body, /app\.phlogiston\.community\.submit\/sub1/);
  } finally {
    await harness.close();
  }
});

test("a resumable operation explains the interruption in plain words", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    await harness.plans.save({
      operationId: "op-own-1",
      sourceOperationId: "op-own-1-source",
      contextOperationId: "op-own-1-context",
      authorDid: MEMBER,
      source: { repo: MEMBER, collection: "app.bsky.feed.post", rkey: "3m1" },
      context: { repo: MEMBER, collection: "app.phlogiston.community.submit", rkey: "3m1" },
      communityDid: COMMUNITY,
      createdAt: "2026-09-10T00:00:00.000Z",
    });
    const page = await get(harness.origin, "/operation?id=op-own-1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /<p>Your last action was interrupted\. Nothing was duplicated; you can safely pick up where you left off\.<\/p>/);
    assert.match(page.body, /name="operationId" value="op-own-1"><button>Continue<\/button>/);
    assert.doesNotMatch(page.body, /exact records/);
  } finally {
    await harness.close();
  }
});

test("a form without its token is a 400 that says the form expired", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/signout", { text: "no token" }, { cookie: cookie(token) });
    assert.equal(page.status, 400);
    assert.match(page.body, /This form has expired\. Go back and try again\./);
    assert.doesNotMatch(page.body, /csrf/i);
    assert.deepEqual(harness.signOutCalls, []);
  } finally {
    await harness.close();
  }
});

test("unknown routes render an HTML 404 for signed-in users", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/no-such-page", cookie(token));
    assert.equal(page.status, 404);
    assert.match(page.headers.get("content-type") ?? "", /text\/html/);
    assert.match(page.body, /Not found/);
    assert.doesNotMatch(page.body, /^not found\n$/);
  } finally {
    await harness.close();
  }
});

test("a missing operation is a 404 and another member's operation is a 403", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const missing = await get(harness.origin, "/operation?id=00000000-0000-0000-0000-000000000000", cookie(token));
    assert.equal(missing.status, 404);
    const malformed = await get(harness.origin, "/operation?id=not%20an%20id", cookie(token));
    assert.equal(malformed.status, 400);
    await harness.plans.save({
      operationId: "op-foreign-1",
      sourceOperationId: "op-foreign-1-source",
      contextOperationId: "op-foreign-1-context",
      authorDid: "did:plc:someone-else",
      source: { repo: "did:plc:someone-else", collection: "app.bsky.feed.post", rkey: "3m1" },
      context: { repo: "did:plc:someone-else", collection: "app.phlogiston.community.submit", rkey: "3m1" },
      communityDid: COMMUNITY,
      createdAt: "2026-09-10T00:00:00.000Z",
    });
    const foreign = await get(harness.origin, "/operation?id=op-foreign-1", cookie(token));
    assert.equal(foreign.status, 403);
    assert.match(foreign.body, /That action belongs to a different account\./);
    assert.doesNotMatch(foreign.body, /another member/);
  } finally {
    await harness.close();
  }
});

test("sign out ends the web session, revokes the provider tokens and returns home", async () => {
  const harness = await startApp(() => ({ body: discussionList(1) }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/signout", { csrf }, { cookie: cookie(token) });
    assert.equal(page.status, 303);
    assert.equal(page.headers.get("location"), "/");
    assert.match(page.headers.get("set-cookie") ?? "", /community_session=;.*Max-Age=0/);
    assert.equal(await harness.sessions.resolve(token), null);
    assert.deepEqual(harness.signOutCalls, [MEMBER], "no refresh token outlives sign-out");
  } finally {
    await harness.close();
  }
});

test("sign out with a mismatched form token is refused and keeps the session", async () => {
  const harness = await startApp(() => ({ body: discussionList(1) }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/signout", { csrf: "forged" }, { cookie: cookie(token) });
    assert.equal(page.status, 403);
    assert.notEqual(await harness.sessions.resolve(token), null);
  } finally {
    await harness.close();
  }
});

test("disconnect revokes OAuth access, ends the web session, and explains what remains", async () => {
  const harness = await startApp(() => ({ body: discussionList(1) }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/disconnect", { csrf }, { cookie: cookie(token) });
    assert.equal(page.status, 200);
    assert.deepEqual(harness.signOutCalls, [MEMBER]);
    assert.equal(await harness.sessions.resolve(token), null);
    assert.match(page.headers.get("set-cookie") ?? "", /Max-Age=0/);
    assert.match(page.body, /revoked this app’s access/);
    assert.match(page.body, /public posts remain public on your PDS/);
    assert.match(page.body, /admission history is unchanged/);
    assert.match(page.body, /sign back in at any time/);
    assert.doesNotMatch(page.body, /logout/i);
  } finally {
    await harness.close();
  }
});

test("a failed OAuth restore ends the web session and asks for a fresh sign-in", async () => {
  const harness = await startApp(() => ({ body: {} }), {}, undefined, {
    restore: async () => {
      throw new Error("refresh token revoked at https://pds.internal.test/token");
    },
  });
  try {
    seedOwnPost(harness);
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/submit-existing", { csrf, post: OWN_POST_URI }, { cookie: cookie(token) });
    assert.equal(page.status, 401);
    assert.match(page.body, /<h1>Sign in is required<\/h1>/);
    assert.match(page.body, /Your sign-in has expired\. Sign in again\./);
    assert.match(page.body, /action="\/oauth\/login"/);
    assert.doesNotMatch(page.body, /pds\.internal\.test|Something went wrong/);
    assert.match(page.headers.get("set-cookie") ?? "", /community_session=;.*Max-Age=0/);
    assert.equal(await harness.sessions.resolve(token), null);
    assert.deepEqual(harness.writer.creates, []);
    const plans = await readdir(join(harness.config.runtimeDirectory, "contribution-plans")).catch(() => []);
    assert.deepEqual(plans, []);
    // The ended session gets the ordinary sign-in answer, not a repeat of the failure.
    const again = await post(harness.origin, "/submit-existing", { csrf, post: OWN_POST_URI }, { cookie: cookie(token) });
    assert.equal(again.status, 401);
    assert.match(again.body, /Sign in is required to view this page\./);
  } finally {
    await harness.close();
  }
});

test("disconnect ends every session and revokes even when the OAuth session cannot be restored", async () => {
  const harness = await startApp(() => ({ body: {} }), {}, undefined, {
    restore: async () => {
      throw new Error("session store unreadable");
    },
  });
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const other = await harness.sessions.issue(MEMBER);
    const stranger = await harness.sessions.issue("did:plc:someoneelse");
    const page = await post(harness.origin, "/disconnect", { csrf }, { cookie: cookie(token) });
    assert.equal(page.status, 200);
    assert.match(page.headers.get("set-cookie") ?? "", /community_session=;.*Max-Age=0/);
    assert.equal(await harness.sessions.resolve(token), null);
    assert.equal(await harness.sessions.resolve(other.token), null, "the account's other browsers are signed out too");
    assert.notEqual(await harness.sessions.resolve(stranger.token), null, "another account is untouched");
    assert.deepEqual(harness.signOutCalls, [MEMBER]);
  } finally {
    await harness.close();
  }
});

test("delete my data erases this account's stores, revokes access and leaves other accounts alone", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const plan = (operationId: string, authorDid: string) => ({ operationId, authorDid, createdAt: new Date().toISOString() }) as ContributionPlan;
    await harness.plans.save(plan("op-mine", MEMBER));
    await harness.plans.save(plan("op-theirs", "did:plc:someoneelse"));
    const operations = join(harness.config.runtimeDirectory, "operations");
    await mkdir(operations, { recursive: true });
    await writeFile(join(operations, `${encodeURIComponent(MEMBER)}.json`), "{}");
    await writeFile(join(operations, `${encodeURIComponent("did:plc:someoneelse")}.json`), "{}");
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const other = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/erase", { csrf }, { cookie: cookie(token) });
    assert.equal(page.status, 200);
    assert.match(page.body, /1 submission draft and 1 write journal/);
    assert.match(page.body, /src="\/static\/forget\.js"/);
    assert.match(page.body, /keeps no backup/);
    assert.match(page.headers.get("set-cookie") ?? "", /community_session=;.*Max-Age=0/);
    assert.equal(await harness.sessions.resolve(other.token), null);
    assert.deepEqual(harness.signOutCalls, [MEMBER]);
    assert.deepEqual((await harness.plans.byAuthor(MEMBER)).length, 0);
    assert.deepEqual((await harness.plans.byAuthor("did:plc:someoneelse")).length, 1);
    assert.deepEqual(await readdir(operations), [`${encodeURIComponent("did:plc:someoneelse")}.json`]);
  } finally {
    await harness.close();
  }
});

test("delete my data needs the form token", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    await harness.plans.save({ operationId: "op-mine", authorDid: MEMBER, createdAt: new Date().toISOString() } as ContributionPlan);
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/erase", {}, { cookie: cookie(token) });
    assert.equal(page.status, 400);
    assert.equal((await harness.plans.byAuthor(MEMBER)).length, 1);
    assert.deepEqual(harness.signOutCalls, []);
  } finally {
    await harness.close();
  }
});

test("cross-origin posts are refused before any route runs", async () => {
  const harness = await startApp(() => ({ body: discussionList(1) }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/signout", { csrf }, {
      cookie: cookie(token),
      origin: "https://substitution.invalid.test",
    });
    assert.equal(page.status, 403);
    assert.notEqual(await harness.sessions.resolve(token), null);
  } finally {
    await harness.close();
  }
});

test("an observer outage renders a place-level 500 without internals", async () => {
  const harness = await startApp(() => ({ status: 500, body: { error: "database corrupt at /var/lib/observer/secrets.db" } }));
  try {
    const page = await get(harness.origin, "/");
    assert.equal(page.status, 500);
    assert.match(page.body, /<h1>This community can&#39;t be shown right now<\/h1>/);
    assert.match(page.body, /<p class="error-message">Try again in a moment\.<\/p>/);
    assert.doesNotMatch(page.body, /Something went wrong|secrets\.db|Community projection/);
  } finally {
    await harness.close();
  }
});

const HOSTILE = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '" autofocus onfocus=alert(1) x="',
  "' onclick='alert(1)",
  '<form action="https://collect.invalid.test/c"><button>Sign in again</button></form>',
  '<style>body{background:url("https://collect.invalid.test/x")}</style>',
  '<a href="javascript:alert(1)">moderator announcement</a>',
  'paypal-security.invalid.test verify your account',
  '\u202e4mF\u202d reversed text',
  'body { display: none } </style><script>alert(2)</script>',
  'A'.repeat(10_000),
];

test("hostile discussion payloads render only inert text", async () => {
  const hostileList = {
    communityDid: COMMUNITY,
    discussions: HOSTILE.map((textValue, index) => discussionItem(`hostile${index}`, textValue)),
    cursor: null,
    snapshot: {},
  };
  const hostileTime = '"><time onmouseover=alert(1)>';
  const hostileDetail = {
    ...DETAIL,
    discussion: {
      ...discussionItem("hostile0", HOSTILE[0] as string),
      admittedAt: hostileTime,
      post: { text: HOSTILE[0] as string, createdAt: hostileTime },
      discussion: { uri: `at://${COMMUNITY}/${ADMISSION}/hostile0" autofocus onfocus=alert(1) x="`, cid: 'cid" onmouseover="alert(1)' },
    },
    replies: HOSTILE.map((textValue, index) => ({
      status: "visible",
      authorDid: textValue,
      post: { text: textValue, createdAt: hostileTime },
      admittedAt: hostileTime,
      admission: { uri: `at://${COMMUNITY}/app.phlogiston.community.replyAdmission/h${index}`, cid: `cid-h${index}` },
    })),
  };
  const harness = await startApp((path) => path.includes("/discussions/hostile0")
    ? { body: hostileDetail }
    : { body: hostileList });
  try {
    const { token } = await harness.sessions.issue(MODERATOR);
    for (const path of ["/", "/d/hostile0"]) {
      const page = await get(harness.origin, path, cookie(token));
      assert.equal(page.status, 200);
      assert.doesNotMatch(page.body, /<script/i);
      assert.doesNotMatch(page.body, /<img/i);
      assert.doesNotMatch(page.body, /<style/i);
      assert.doesNotMatch(page.body, /href="javascript:/i);
      assert.doesNotMatch(page.body, /" autofocus onfocus=/);
      assert.doesNotMatch(page.body, /<time onmouseover/);
      for (const href of page.body.match(/href="[^"]*"/g) ?? []) {
        assert.match(href, /^href="(\/|#|https:\/\/bsky\.app\/)/);
      }
      assert.match(page.body, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
      assert.match(page.body, /&quot; autofocus onfocus=/);
      assert.match(page.body, /paypal-security\.invalid\.test/);
      if (path === "/") {
        assert.match(page.body, new RegExp(`${"A".repeat(140)}…`));
        assert.doesNotMatch(page.body, new RegExp("A".repeat(10_000)));
      } else {
        assert.match(page.body, new RegExp(escapeHtml("A".repeat(10_000))));
        assert.match(page.body, /&lt;time onmouseover=alert\(1\)&gt;/);
      }
      for (const form of page.body.match(/<form[^>]*action="[^"]*"/g) ?? []) {
        assert.match(form, /action="\/(contribute|submit-existing|moderate|signout|disconnect|seen)"/);
      }
    }
  } finally {
    await harness.close();
  }
});

function appViewWith(profiles: Record<string, Record<string, unknown>>): (path: string) => StubReply {
  return (path) => {
    if (!path.includes("app.bsky.actor.getProfiles")) return { status: 404, body: {} };
    const actors = new URL(path, "http://stub.invalid").searchParams.getAll("actors");
    return {
      body: { profiles: actors.filter((did) => did in profiles).map((did) => ({ did, ...profiles[did] })) },
    };
  };
}

test("home hydrates author identities for anonymous visitors", async () => {
  const harness = await startApp(
    () => ({ body: discussionList(2) }),
    {},
    appViewWith({ "did:plc:bob": { handle: "bob.example.test", displayName: "Bob Example" } }),
  );
  try {
    const page = await get(harness.origin, "/");
    assert.equal(page.status, 200);
    assert.match(page.body, /Bob Example/);
    assert.match(page.body, /title="did:plc:bob"/);
    assert.doesNotMatch(page.body.replace(/<[^>]*>/g, ""), /did:plc:bob/);
  } finally {
    await harness.close();
  }
});

test("a total AppView outage keeps every page at 200 with DID presentation", async () => {
  const harness = await startApp((path) => path.includes("/discussions/root1")
    ? { body: DETAIL }
    : { body: discussionList(1) });
  try {
    const home = await get(harness.origin, "/");
    assert.equal(home.status, 200);
    assert.match(home.body, /did:plc:bob/);
    assert.doesNotMatch(home.body, /class="name"/);
    const { token } = await harness.sessions.issue(MEMBER);
    const detail = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(detail.status, 200);
    assert.match(detail.body, /did:plc:carol/);
    assert.match(detail.body, /Root post text/);
    const mine = await get(harness.origin, "/mine", cookie(token));
    assert.equal(mine.status, 200);
    const health = await get(harness.origin, "/healthz");
    assert.equal(health.status, 200);
    assert.equal(health.body, "ok\n");
  } finally {
    await harness.close();
  }
});

test("the discussion page hydrates the root and reply authors", async () => {
  const harness = await startApp(
    () => ({ body: DETAIL }),
    {},
    appViewWith({
      "did:plc:bob": { handle: "bob.example.test", displayName: "Bob Example" },
      "did:plc:carol": { handle: "carol.example.test" },
    }),
  );
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /Started by <span class="identity" title="did:plc:bob">/);
    assert.match(page.body, /Bob Example/);
    assert.match(page.body, /@carol\.example\.test/);
  } finally {
    await harness.close();
  }
});

test("the moderator sees author DIDs beside hydrated names on a discussion page", async () => {
  const harness = await startApp(
    () => ({ body: DETAIL }),
    {},
    appViewWith({
      "did:plc:bob": { handle: "bob.example.test", displayName: "Bob Example" },
      "did:plc:carol": { handle: "carol.example.test" },
    }),
  );
  try {
    const { token } = await harness.sessions.issue(MODERATOR);
    const page = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /Started by <span class="identity" title="did:plc:bob">.*?Bob Example<\/a><\/span> <span class="did">did:plc:bob<\/span><\/span>/);
    assert.match(page.body, /@carol\.example\.test<\/a><\/span> <span class="did">did:plc:carol<\/span>/);
    const member = await get(harness.origin, "/d/root1", cookie((await harness.sessions.issue(MEMBER)).token));
    assert.doesNotMatch(member.body, /class="did"/);
    const anonymous = await get(harness.origin, "/d/root1");
    assert.doesNotMatch(anonymous.body, /class="did"/);
  } finally {
    await harness.close();
  }
});

test("the moderation queue hydrates the submitter identity", async () => {
  const queue = {
    communityDid: COMMUNITY,
    submissions: [
      { submission: { uri: `at://${MEMBER}/app.phlogiston.community.submit/sub1`, cid: "cid-sub1" }, authorDid: MEMBER },
    ],
    snapshot: {},
  };
  const harness = await startApp(
    () => ({ body: queue }),
    {},
    appViewWith({ [MEMBER]: { handle: "alice.example.test" } }),
  );
  try {
    const { token } = await harness.sessions.issue(MODERATOR);
    const page = await get(harness.origin, "/moderation", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /@alice\.example\.test/);
    assert.match(page.body, /title="did:plc:alice"/);
  } finally {
    await harness.close();
  }
});

test("avatars are omitted by default and rendered only when enabled and validated", async () => {
  const profiles = {
    "did:plc:bob": { handle: "bob.example.test", avatar: "https://cdn.bsky.app/img/avatar/plain/did:plc:bob/bafy@jpeg" },
  };
  const off = await startApp(() => ({ body: discussionList(1) }), {}, appViewWith(profiles));
  try {
    const page = await get(off.origin, "/");
    assert.equal(page.status, 200);
    assert.doesNotMatch(page.body, /<img/);
    assert.doesNotMatch(page.body, /cdn\.bsky\.app/);
    assert.doesNotMatch(page.headers.get("content-security-policy") ?? "", /img-src/);
  } finally {
    await off.close();
  }

  const list = discussionList(2);
  (list.discussions as unknown[])[1] = { ...discussionItem("rkey1", "Topic number 1"), authorDid: "did:plc:carol" };
  const on = await startApp(
    () => ({ body: list }),
    { avatarsEnabled: true },
    appViewWith({
      "did:plc:bob": { handle: "bob.example.test", avatar: "https://cdn.bsky.app/img/avatar/plain/did:plc:bob/bafy@jpeg" },
      "did:plc:carol": { handle: "carol.example.test", avatar: "https://track.invalid.test/pixel.png" },
    }),
  );
  try {
    const page = await get(on.origin, "/");
    assert.equal(page.status, 200);
    assert.match(page.body, /<img class="avatar" src="https:\/\/cdn\.bsky\.app\/img\/avatar\/plain\/did:plc:bob\/bafy@jpeg" alt="" width="24" height="24">/);
    assert.doesNotMatch(page.body, /track\.invalid\.test/);
    assert.match(page.body, /@carol\.example\.test/);
    assert.match(page.headers.get("content-security-policy") ?? "", /img-src 'self' https:\/\/cdn\.bsky\.app/);
  } finally {
    await on.close();
  }
});

test("home renders the community context block, layer labels, and outbound Bluesky links", async () => {
  const harness = await startApp(() => ({ body: discussionList(1) }));
  try {
    const page = await get(harness.origin, "/");
    assert.equal(page.status, 200);
    assert.match(page.body, /<summary>What is this\?<\/summary>/);
    assert.match(page.body, /<summary>What is this\?<\/summary><p>This is a moderated collection of public Bluesky posts\. Each post stays in its author's own account; the community only records which exact versions are shown here and can stop showing them\./);
    assert.match(page.body, /<p class="legend"><span class="layer">Community view<\/span> marks posts the community has added to this page\./);
    assert.doesNotMatch(page.body, /admitted into this projection/);
    assert.match(page.body, /posted <time datetime="2026-09-08T09:30:00\.000Z">8 Sep 2026, 09:30 UTC<\/time>/);
    assert.match(page.body, /<summary>Why is this here\?<\/summary>/);
    assert.match(page.body, /Admitted to this community’s view on <time datetime="2026-09-09T10:00:00\.000Z">9 Sep 2026, 10:00 UTC<\/time>\. The original is the author’s public record/);
    assert.match(page.body, /<a class="external" href="https:\/\/bsky\.app\/profile\/did:plc:bob\/post\/rkey0" rel="noopener noreferrer">Public post on Bluesky<\/a>/);
    assert.match(page.body, /<a class="profile" href="https:\/\/bsky\.app\/profile\/did:plc:bob" rel="noopener noreferrer">did:plc:bob<\/a>/);
  } finally {
    await harness.close();
  }
});

test("a removed reply tombstone explains the projection and links only the public post", async () => {
  const harness = await startApp(() => ({ body: DETAIL }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /Removed from this community’s view: Off topic\. The author’s public post is not deleted or changed: <a class="external" href="https:\/\/bsky\.app\/profile\/did:plc:carol\/post\/reply2" rel="noopener noreferrer">Public post on Bluesky<\/a>\./);
    assert.doesNotMatch(page.body, /Observer record for this admission/);
  } finally {
    await harness.close();
  }
});

test("a removed root renders a tombstone banner and omits the observer permalink by default", async () => {
  const removed = { ...DETAIL, discussion: { ...discussionItem("root1", "Root post text"), status: "removed" } };
  const harness = await startApp(() => ({ body: removed }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /<p class="tombstone-banner">This discussion was removed from this community’s view; the author’s public post is not deleted or changed\. /);
    assert.match(page.body, /href="https:\/\/bsky\.app\/profile\/did:plc:bob\/post\/root1" rel="noopener noreferrer">Public post on Bluesky<\/a>/);
    assert.doesNotMatch(page.body, /Observer record for this admission/);
    assert.doesNotMatch(page.body, /Root post text|<article>/);
    assert.match(page.body, /A visible reply/);
  } finally {
    await harness.close();
  }
});

test("my discussions names a removed root without its text and keeps its permalink", async () => {
  const participants = {
    communityDid: COMMUNITY,
    participantDid: MEMBER,
    discussions: [
      { ...discussionItem("gone1", "Text the moderator removed"), status: "removed", lastActivitySequence: 3 },
      { ...discussionItem("kept1", "Text still in the community"), lastActivitySequence: 1 },
    ],
    activity: [],
    snapshot: {},
  };
  const harness = await startApp(() => ({ body: participants }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/mine", cookie(token));
    assert.equal(page.status, 200);
    assert.doesNotMatch(page.body, /Text the moderator removed/);
    assert.match(page.body, /<a href="\/d\/gone1">Removed from the community<\/a>/);
    assert.match(page.body, /<a href="\/d\/kept1">Text still in the community<\/a>/);
  } finally {
    await harness.close();
  }
});

test("a configured observer public URL adds a root admission permalink only", async () => {
  const removed = { ...DETAIL, discussion: { ...discussionItem("root1", "Root post text"), status: "removed" } };
  const harness = await startApp(() => ({ body: removed }), { observerPublicUrl: "https://observer.example.test/c/internal-dogfood" });
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /href="https:\/\/observer\.example\.test\/c\/internal-dogfood\/i\/root1" rel="noopener noreferrer">Observer record for this admission<\/a>/);
    assert.equal(page.body.match(/Observer record for this admission/g)?.length, 1);
    assert.doesNotMatch(page.body, /\/i\/reply2/);
  } finally {
    await harness.close();
  }
});

test("signed-in responses are not stored; anonymous themed HTML varies by Cookie", async () => {
  const harness = await startApp((path) => path.includes("/discussions/root1") ? { body: DETAIL } : { body: discussionList(1) });
  try {
    for (const path of ["/", "/d/root1"]) {
      const anonymous = await get(harness.origin, path);
      assert.equal(anonymous.status, 200, path);
      assert.equal(anonymous.headers.get("cache-control"), "private, no-cache", path);
      assert.equal(anonymous.headers.get("vary"), "Cookie", path);
    }
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    for (const path of ["/", "/d/root1", "/mine", "/no-such-page"]) {
      const signedIn = await get(harness.origin, path, cookie(token));
      assert.equal(signedIn.headers.get("cache-control"), "no-store", path);
    }
    const signout = await post(harness.origin, "/signout", { csrf }, { cookie: cookie(token) });
    assert.equal(signout.status, 303);
    assert.equal(signout.headers.get("cache-control"), "no-store");
  } finally {
    await harness.close();
  }
});

test("the sign-in callback redirect is never stored by a cache", async () => {
  const harness = await signInHarness();
  try {
    const login = await post(harness.origin, "/oauth/login", { handle: "alice.example.test" });
    const back = await get(harness.origin, "/oauth/callback?code=x", loginCookieOf(login));
    assert.equal(back.status, 303);
    assert.equal(back.headers.get("cache-control"), "no-store");
  } finally {
    await harness.close();
  }
});

test("pages expose a skip link, landmarks, and a labelled account nav", async () => {
  const harness = await startApp(() => ({ body: discussionList(1) }));
  try {
    const anonymous = await get(harness.origin, "/");
    assert.equal(anonymous.status, 200);
    assert.match(anonymous.body, /<a class="skip" href="#content">Skip to content<\/a>/);
    assert.match(anonymous.body, /<header>/);
    assert.match(anonymous.body, /<main id="content">/);
    assert.doesNotMatch(anonymous.body, /<nav aria-label="Account">/);
    const { token } = await harness.sessions.issue(MEMBER);
    const signedIn = await get(harness.origin, "/", cookie(token));
    assert.equal(signedIn.status, 200);
    assert.match(signedIn.body, /<a class="skip" href="#content">Skip to content<\/a>/);
    assert.match(signedIn.body, /<nav aria-label="Account">/);
    assert.match(signedIn.body, /<main id="content">/);
  } finally {
    await harness.close();
  }
});

test("an anonymous reader gets the discussion permalink with no forms or private state", async () => {
  const harness = await startApp(() => ({ body: DETAIL }));
  try {
    const home = await get(harness.origin, "/");
    const page = await get(harness.origin, "/d/root1");
    assert.equal(page.status, 200);
    assert.match(page.headers.get("content-type") ?? "", /text\/html/);
    assert.equal(page.headers.get("content-security-policy"), home.headers.get("content-security-policy"));
    assert.equal(page.headers.get("referrer-policy"), "same-origin");
    assert.equal(page.headers.get("x-content-type-options"), "nosniff");
    assert.equal(page.headers.get("set-cookie"), null);
    assert.match(page.body, /Root post text/);
    assert.match(page.body, /A visible reply/);
    assert.match(page.body, /Why is this here\?/);
    assert.match(page.body, /class="tombstone"/);
    assert.match(page.body, /<a href="\/\?return=%2Fd%2Froot1">Sign in to reply<\/a>/);
    assert.doesNotMatch(page.body, /<form/i);
    assert.doesNotMatch(page.body, /csrf/i);
    assert.doesNotMatch(page.body, /Remove from community|Restore to community|Withdraw/);
    assert.doesNotMatch(page.body, /Post public reply|Post reply and add|Your reply is posted publicly/);
    assert.doesNotMatch(page.body, /My discussions|Unread|\/mine|\/moderation|\/operation/);
  } finally {
    await harness.close();
  }
});

test("a signed-in participant's permalink keeps the reply form and no moderation", async () => {
  const harness = await startApp(() => ({ body: DETAIL }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /<form method="post" action="\/contribute">/);
    assert.match(page.body, /Post reply and add to this discussion/);
    assert.doesNotMatch(page.body, /opt in/i);
    assert.match(page.body, new RegExp(`name="csrf" value="${csrf}"`));
    assert.doesNotMatch(page.body, /Sign in to reply/);
    assert.doesNotMatch(page.body, /action="\/moderate"/);
  } finally {
    await harness.close();
  }
});

test("the moderator's permalink keeps the moderation forms", async () => {
  const detail = {
    ...DETAIL,
    replies: [
      DETAIL.replies[0],
      { ...DETAIL.replies[1], controllingAction: { uri: `at://${COMMUNITY}/app.phlogiston.community.moderationAction/m1`, cid: "cid-m1" } },
    ],
  };
  const harness = await startApp(() => ({ body: detail }));
  try {
    const { token } = await harness.sessions.issue(MODERATOR);
    const page = await get(harness.origin, "/d/root1", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /name="kind" value="remove-root">.*?<label>Reason <input name="reason" required><\/label><button>Remove from community<\/button>/);
    assert.match(page.body, /name="kind" value="remove-reply">.*?<button>Remove from community<\/button>/);
    assert.doesNotMatch(page.body, /Withdraw|discovery|opt in/i);
    assert.match(page.body, /Restore to community/);
    assert.match(page.body, /action="\/contribute"/);
  } finally {
    await harness.close();
  }
});

test("the legacy discussion query route redirects to the permalink", async () => {
  const harness = await startApp(() => ({ body: DETAIL }));
  try {
    const anonymous = await get(harness.origin, "/discussion?rkey=root1");
    assert.equal(anonymous.status, 303);
    assert.equal(anonymous.headers.get("location"), "/d/root1");
    const { token } = await harness.sessions.issue(MEMBER);
    const signedIn = await get(harness.origin, "/discussion?rkey=3m2abc", cookie(token));
    assert.equal(signedIn.status, 303);
    assert.equal(signedIn.headers.get("location"), "/d/3m2abc");
    const malformed = await get(harness.origin, "/discussion?rkey=%3Cscript%3E");
    assert.equal(malformed.status, 400);
    assert.equal(malformed.headers.get("location"), null);
  } finally {
    await harness.close();
  }
});

test("a malformed permalink key is a 400 page and never reaches the projection", async () => {
  const requested: string[] = [];
  const harness = await startApp((path) => {
    requested.push(path);
    return { body: DETAIL };
  });
  try {
    for (const path of ["/d/", "/d/bad%20key", "/d/a/b", "/d/%3Cscript%3E", "/d/a%2Fb", `/d/${"x".repeat(513)}`]) {
      const page = await get(harness.origin, path);
      assert.equal(page.status, 400, path);
      assert.match(page.headers.get("content-type") ?? "", /text\/html/);
      assert.match(page.body, /^<!doctype html>/);
      assert.match(page.body, /That request was not understood/);
      assert.match(page.body, /That discussion link is malformed\./);
      assert.doesNotMatch(page.body, /<script|HttpError|at route|\/api\/v0|\.ts:/);
    }
    assert.deepEqual(requested, []);
  } finally {
    await harness.close();
  }
});

test("an unknown permalink key is an anonymous 404 page without internals", async () => {
  const harness = await startApp(() => ({ status: 404, body: { error: "not_found" } }));
  try {
    const page = await get(harness.origin, "/d/unknown1");
    assert.equal(page.status, 404);
    assert.match(page.headers.get("content-type") ?? "", /text\/html/);
    assert.match(page.body, /^<!doctype html>/);
    assert.match(page.body, /<h1>Not found<\/h1>/);
    assert.match(page.body, /That discussion isn&#39;t in this community\./);
    assert.doesNotMatch(page.body, /Sign in is required|\/api\/v0|HttpError|not_found|projection/);
  } finally {
    await harness.close();
  }
  const byShape = await startApp(() => ({ body: { communityDid: COMMUNITY } }));
  try {
    const page = await get(byShape.origin, "/d/unknown1");
    assert.equal(page.status, 404);
    assert.match(page.body, /That discussion isn&#39;t in this community\./);
  } finally {
    await byShape.close();
  }
});

test("a replayed reply form for a removed discussion writes nothing", async () => {
  const harness = await startApp(() => ({ body: { ...DETAIL, discussion: { ...DETAIL.discussion, status: "removed" } } }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/contribute", {
      csrf,
      text: "late reply",
      discussionUri: `at://${COMMUNITY}/app.phlogiston.community.admission/root1`,
      discussionCid: "cid-root1",
      rootUri: "at://did:plc:bob/app.bsky.feed.post/root1",
      rootCid: "post-cid-root1",
      parentUri: "at://did:plc:bob/app.bsky.feed.post/root1",
      parentCid: "post-cid-root1",
    }, { cookie: cookie(token) });
    assert.equal(page.status, 409);
    assert.match(page.body, /<h1>That action could not be confirmed<\/h1>/);
    assert.match(page.body, /no longer in the community, so replies can&#39;t be added/);
    assert.deepEqual(harness.writer.creates, []);
    const plans = await readdir(join(harness.config.runtimeDirectory, "contribution-plans")).catch(() => []);
    assert.deepEqual(plans, []);
  } finally {
    await harness.close();
  }
});

test("a removed discussion stays readable anonymously with its tombstone banner", async () => {
  const harness = await startApp(() => ({ body: { ...DETAIL, discussion: { ...DETAIL.discussion, status: "removed" } } }));
  try {
    const page = await get(harness.origin, "/d/root1");
    assert.equal(page.status, 200);
    assert.match(page.body, /class="tombstone-banner"/);
    assert.match(page.body, /href="https:\/\/bsky\.app\/profile\/did:plc:bob\/post\/root1" rel="noopener noreferrer">Public post on Bluesky<\/a>/);
    assert.doesNotMatch(page.body, /Root post text|<article>/);
    assert.doesNotMatch(page.body, /Admitted to this community’s view on 2026-09-09/);
    assert.match(page.body, /A visible reply/);
    assert.match(page.body, /class="tombstone"/);
    assert.doesNotMatch(page.body, /<form/i);
  } finally {
    await harness.close();
  }
});

test("a projection outage on the anonymous permalink is the generic 500, not a 401", async () => {
  const harness = await startApp(() => ({ status: 500, body: { error: "database corrupt at /var/lib/observer/secrets.db" } }));
  try {
    const home = await get(harness.origin, "/");
    const page = await get(harness.origin, "/d/root1");
    assert.equal(page.status, 500);
    assert.equal(page.status, home.status);
    assert.match(page.body, /This community can&#39;t be shown right now/);
    assert.match(page.body, /Try again in a moment\./);
    assert.doesNotMatch(page.body, /Something went wrong|Sign in is required|secrets\.db|Community projection/);
  } finally {
    await harness.close();
  }
});

test("participant-private pages and every mutation still require a session", async () => {
  const requested: string[] = [];
  const harness = await startApp((path) => {
    requested.push(path);
    return { body: DETAIL };
  });
  try {
    for (const path of ["/mine", "/moderation", "/operation?id=00000000-0000-0000-0000-000000000000"]) {
      const page = await get(harness.origin, path);
      assert.equal(page.status, 401, path);
      assert.match(page.body, /Sign in is required/);
    }
    const form = { csrf: "guess", text: "anonymous write attempt" };
    for (const path of ["/contribute", "/submit-existing", "/moderate", "/seen", "/operation/resume", "/signout", "/disconnect"]) {
      const page = await post(harness.origin, path, form);
      assert.equal(page.status, 401, path);
    }
    assert.deepEqual(requested, []);
    assert.deepEqual(harness.signOutCalls, []);
    const plans = await readdir(join(harness.config.runtimeDirectory, "contribution-plans")).catch(() => []);
    assert.deepEqual(plans, []);
  } finally {
    await harness.close();
  }
});

const OWN_POST_KEY = `${MEMBER}/app.bsky.feed.post/3kpost`;
const OWN_POST_URI = `at://${MEMBER}/app.bsky.feed.post/3kpost`;

function seedOwnPost(harness: Harness): void {
  harness.writer.records.set(OWN_POST_KEY, {
    cid: "bafy-current-post-cid",
    record: { $type: "app.bsky.feed.post", text: "Something I said last week", createdAt: "2026-09-17T08:00:00.000Z" },
  });
}

function submitRecords(harness: Harness): Array<[string, ObservedRecord]> {
  return [...harness.writer.records].filter(([key]) => key.includes("/app.phlogiston.community.submit/"));
}

test("signed-in home offers adding an existing post beside starting a discussion", async () => {
  const harness = await startApp(() => ({ body: discussionList(0) }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/", cookie(token));
    assert.match(page.body, /<form method="post" action="\/submit-existing" class="contribute">/);
    assert.match(page.body, /Add a post you already made<input name="post" required maxlength="1024"/);
    assert.match(page.body, /The post is not changed; this asks the moderator to add it here\./);
    const anonymous = await get(harness.origin, "/");
    assert.doesNotMatch(anonymous.body, /submit-existing/);
  } finally {
    await harness.close();
  }
});

test("an own post by DID URL writes exactly one submit record at the read-back CID", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    seedOwnPost(harness);
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/submit-existing", {
      csrf,
      post: `https://bsky.app/profile/${MEMBER}/post/3kpost`,
    }, { cookie: cookie(token) });
    assert.equal(page.status, 200);
    assert.match(page.body, /Submitted\. Your post is now waiting for the moderator to add it here\./);
    assert.match(page.body, /View my discussions/);
    const submits = submitRecords(harness);
    assert.equal(submits.length, 1);
    const [key, written] = submits[0]!;
    assert.match(key, new RegExp(`^${MEMBER}/app\\.phlogiston\\.community\\.submit/[2-7a-z]{13}$`));
    const record = written.record as Record<string, unknown>;
    assert.deepEqual(record.subject, { uri: OWN_POST_URI, cid: "bafy-current-post-cid" });
    assert.equal(record.community, COMMUNITY);
    assert.equal("discussion" in record, false);
    assert.equal(harness.writer.creates.filter((item) => item.includes("app.bsky.feed.post")).length, 0);
    assert.ok(harness.writer.reads.includes(OWN_POST_KEY));
  } finally {
    await harness.close();
  }
});

test("an AT URI names an own post exactly as a DID URL does", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    seedOwnPost(harness);
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/submit-existing", { csrf, post: `  ${OWN_POST_URI}  ` }, { cookie: cookie(token) });
    assert.equal(page.status, 200);
    assert.match(page.body, /waiting for the moderator/);
    assert.equal(submitRecords(harness).length, 1);
  } finally {
    await harness.close();
  }
});

test("submitting the same post version twice resumes one operation and writes once", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    seedOwnPost(harness);
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const form = { csrf, post: OWN_POST_URI };
    const first = await post(harness.origin, "/submit-existing", form, { cookie: cookie(token) });
    const second = await post(harness.origin, "/submit-existing", { csrf, post: `https://bsky.app/profile/${MEMBER}/post/3kpost` }, { cookie: cookie(token) });
    assert.equal(first.status, 200);
    assert.match(first.body, /Submitted\. Your post is now waiting for the moderator/);
    assert.equal(second.status, 200);
    assert.match(second.body, /You already asked to add this exact post; nothing new was created\./);
    assert.doesNotMatch(second.body, /now waiting for the moderator/);
    assert.equal(submitRecords(harness).length, 1);
    assert.equal(harness.writer.creates.length, 1);
    assert.equal((await readdir(join(harness.config.runtimeDirectory, "contribution-plans"))).length, 1);

    // A new version of the post is a different exact subject and a new submission.
    harness.writer.records.set(OWN_POST_KEY, { cid: "bafy-edited-post-cid", record: { text: "edited" } });
    await post(harness.origin, "/submit-existing", form, { cookie: cookie(token) });
    assert.equal(submitRecords(harness).length, 2);
  } finally {
    await harness.close();
  }
});

test("a lost submit response resumes by readback without a duplicate record", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    seedOwnPost(harness);
    harness.writer.failAfterCommitCollection = "app.phlogiston.community.submit";
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/submit-existing", { csrf, post: OWN_POST_URI }, { cookie: cookie(token) });
    assert.equal(page.status, 200);
    assert.match(page.body, /Your Bluesky post is unchanged; the request to add it here is not confirmed yet\./);
    const operationId = /name="operationId" value="([^"]+)"/.exec(page.body)?.[1];
    assert.ok(operationId);
    const resumed = await post(harness.origin, "/operation/resume", { csrf, operationId }, { cookie: cookie(token) });
    assert.equal(resumed.status, 200);
    assert.match(resumed.body, /waiting for the moderator/);
    assert.equal(harness.writer.creates.length, 1);
    assert.equal(submitRecords(harness).length, 1);
    const again = await post(harness.origin, "/submit-existing", { csrf, post: OWN_POST_URI }, { cookie: cookie(token) });
    assert.match(again.body, /You already asked to add this exact post; nothing new was created\./);
    assert.equal(harness.writer.creates.length, 1);
  } finally {
    await harness.close();
  }
});

test("my discussions lists the signed-in author's unfinished actions with a way back to each", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    seedOwnPost(harness);
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const empty = await get(harness.origin, "/mine", cookie(token));
    assert.doesNotMatch(empty.body, /Unfinished actions/);

    // A plan saved before its writes ran (the browser lost the response).
    await harness.plans.save({
      operationId: "op-own-1",
      sourceOperationId: "op-own-1:source",
      contextOperationId: "op-own-1:context",
      authorDid: MEMBER,
      source: { repo: MEMBER, collection: "app.bsky.feed.post", rkey: "3m1" },
      context: { repo: MEMBER, collection: "app.phlogiston.community.submit", rkey: "3m1" },
      communityDid: COMMUNITY,
      createdAt: "2026-09-10T00:00:00.000Z",
    });
    await harness.plans.save({
      operationId: "op-foreign-1",
      sourceOperationId: "op-foreign-1:source",
      contextOperationId: "op-foreign-1:context",
      authorDid: "did:plc:someone-else",
      source: { repo: "did:plc:someone-else", collection: "app.bsky.feed.post", rkey: "3m1" },
      context: { repo: "did:plc:someone-else", collection: "app.phlogiston.community.submit", rkey: "3m1" },
      communityDid: COMMUNITY,
      createdAt: "2026-09-11T00:00:00.000Z",
    });
    // A submission whose response was lost after the commit: journal not yet committed.
    harness.writer.failAfterCommitCollection = "app.phlogiston.community.submit";
    const lost = await post(harness.origin, "/submit-existing", { csrf, post: OWN_POST_URI }, { cookie: cookie(token) });
    const lostId = /name="operationId" value="([^"]+)"/.exec(lost.body)?.[1];
    assert.ok(lostId);

    const page = await get(harness.origin, "/mine", cookie(token));
    assert.equal(page.status, 200);
    assert.match(page.body, /<h2>Unfinished actions<\/h2><p>These actions were interrupted before they finished\. Nothing was duplicated; open one to check the exact records and continue\.<\/p>/);
    assert.match(page.body, /<li><a href="\/operation\?id=op-own-1">A new discussion<\/a> · started <time datetime="2026-09-10T00:00:00\.000Z">10 Sep 2026, 00:00 UTC<\/time><\/li>/);
    assert.match(page.body, new RegExp(`<a href="/operation\\?id=${lostId}">Adding a post you already made</a>`));
    assert.doesNotMatch(page.body, /op-foreign-1|someone-else/);
    assert.ok(page.body.indexOf(lostId) < page.body.indexOf("op-own-1"), "newest first");

    // Resuming completes the lost one; it leaves the list while the other stays.
    const resumed = await post(harness.origin, "/operation/resume", { csrf, operationId: lostId }, { cookie: cookie(token) });
    assert.match(resumed.body, /waiting for the moderator/);
    const after = await get(harness.origin, "/mine", cookie(token));
    assert.doesNotMatch(after.body, new RegExp(lostId));
    assert.match(after.body, /\/operation\?id=op-own-1/);
  } finally {
    await harness.close();
  }
});

test("a handle URL is accepted only when hydration names it as the session's own handle", async () => {
  const harness = await startApp(
    () => ({ body: {} }),
    {},
    appViewWith({ [MEMBER]: { handle: "Alice.Example.Test" } }),
  );
  try {
    seedOwnPost(harness);
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const own = await post(harness.origin, "/submit-existing", {
      csrf,
      post: "https://bsky.app/profile/alice.example.test/post/3kpost",
    }, { cookie: cookie(token) });
    assert.equal(own.status, 200);
    assert.match(own.body, /waiting for the moderator/);
    const other = await post(harness.origin, "/submit-existing", {
      csrf,
      post: "https://bsky.app/profile/bob.example.test/post/3kpost",
    }, { cookie: cookie(token) });
    assert.equal(other.status, 403);
    assert.match(other.body, /You can only add your own posts here\. That link names a different account; to add one of yours, paste the link that shows your account as did:plc:alice\./);
    assert.equal(submitRecords(harness).length, 1);
  } finally {
    await harness.close();
  }
});

test("an AppView answer of handle.invalid leaves the session's handle unknown, not someone else's", async () => {
  const harness = await startApp(() => ({ body: {} }), {}, appViewWith({ [MEMBER]: { handle: "handle.invalid" } }));
  try {
    seedOwnPost(harness);
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/submit-existing", {
      csrf,
      post: "https://bsky.app/profile/alice.example.test/post/3kpost",
    }, { cookie: cookie(token) });
    assert.equal(page.status, 503);
    assert.match(page.body, /We couldn&#39;t confirm that link is yours right now\./);
    assert.doesNotMatch(page.body, /You can only add your own posts here/);
    const home = await get(harness.origin, "/", cookie(token));
    assert.doesNotMatch(home.body, /handle\.invalid/);
    assert.deepEqual(harness.writer.reads, []);
    assert.deepEqual(harness.writer.creates, []);
  } finally {
    await harness.close();
  }
});

test("a handle URL is not called someone else's when the session's handle cannot be established", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    seedOwnPost(harness);
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/submit-existing", {
      csrf,
      post: "https://bsky.app/profile/alice.example.test/post/3kpost",
    }, { cookie: cookie(token) });
    assert.equal(page.status, 503);
    assert.match(page.body, /<h1>That could not be checked right now<\/h1>/);
    assert.doesNotMatch(page.body, /Something went wrong/);
    assert.match(page.body, /We couldn&#39;t confirm that link is yours right now\. Try again in a moment, or paste the link that shows your account as did:plc:alice\./);
    assert.doesNotMatch(page.body, /You can only add your own posts here/);
    assert.deepEqual(harness.writer.reads, []);
    assert.deepEqual(harness.writer.creates, []);
  } finally {
    await harness.close();
  }
});

test("another repository's post is refused before any read or write", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    for (const value of [
      "https://bsky.app/profile/did:plc:bob/post/3kpost",
      "at://did:plc:bob/app.bsky.feed.post/3kpost",
      `at://${MEMBER}x/app.bsky.feed.post/3kpost`,
    ]) {
      const page = await post(harness.origin, "/submit-existing", { csrf, post: value }, { cookie: cookie(token) });
      assert.equal(page.status, 403, value);
      assert.match(page.body, /You can only add your own posts here\./);
    }
    assert.deepEqual(harness.writer.reads, []);
    assert.deepEqual(harness.writer.creates, []);
    const plans = await readdir(join(harness.config.runtimeDirectory, "contribution-plans")).catch(() => []);
    assert.deepEqual(plans, []);
  } finally {
    await harness.close();
  }
});

test("a post absent from the author's repository is refused without a plan", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/submit-existing", { csrf, post: OWN_POST_URI }, { cookie: cookie(token) });
    assert.equal(page.status, 404);
    assert.match(page.body, /That post is not in your Bluesky account; it may have been deleted\./);
    assert.deepEqual(harness.writer.creates, []);
    const plans = await readdir(join(harness.config.runtimeDirectory, "contribution-plans")).catch(() => []);
    assert.deepEqual(plans, []);
  } finally {
    await harness.close();
  }
});

test("hostile and non-post references are refused with fixed text and no writes", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    const { token, csrf } = await harness.sessions.issue(MEMBER);
    const cases: Array<[string, RegExp]> = [
      [`at://${MEMBER}/app.bsky.feed.like/3kpost`, /something other than a Bluesky post/],
      [`at://${MEMBER}/app.phlogiston.community.submit/3kpost`, /something other than a Bluesky post/],
      [`https://bsky.app/profile/${MEMBER}/feed/3kpost`, /something other than a Bluesky post/],
      [`https://bsky.app/profile/${MEMBER}/lists/3kpost`, /something other than a Bluesky post/],
      [`http://bsky.app/profile/${MEMBER}/post/3kpost`, /does not look like a Bluesky post link/],
      [`https://bsky.app.evil.test/profile/${MEMBER}/post/3kpost`, /does not look like a Bluesky post link/],
      [`https://user@bsky.app/profile/${MEMBER}/post/3kpost`, /does not look like a Bluesky post link/],
      [`https://bsky.app/profile/${MEMBER}/post/3kpost?x=1`, /does not look like a Bluesky post link/],
      [`https://bsky.app/profile/${MEMBER}/post/3kpost#frag`, /does not look like a Bluesky post link/],
      [`https://bsky.app/profile/${MEMBER}/post/..`, /does not look like a Bluesky post link/],
      [`https://bsky.app/profile/${MEMBER}/post/3k%2Fpost`, /does not look like a Bluesky post link/],
      [`at://alice.example.test/app.bsky.feed.post/3kpost`, /does not look like a Bluesky post link/],
      [`https://bsky.app/profile/${MEMBER}/post/3k\u0007post`, /does not look like a Bluesky post link/],
      [`https://bsky.app/profile/${MEMBER}/post/3k‮post`, /does not look like a Bluesky post link/],
      [`https://bsky.app/profile/${MEMBER}/post/3k post`, /does not look like a Bluesky post link/],
      [`https://bsky.app/profile/${MEMBER}/post/${"a".repeat(2000)}`, /does not look like a Bluesky post link/],
      ['<script>alert(1)</script>', /does not look like a Bluesky post link/],
      ['javascript:alert(1)', /does not look like a Bluesky post link/],
      ['" onmouseover="alert(1)', /does not look like a Bluesky post link/],
    ];
    for (const [value, message] of cases) {
      const page = await post(harness.origin, "/submit-existing", { csrf, post: value }, { cookie: cookie(token) });
      assert.equal(page.status, 400, value);
      assert.match(page.body, message, value);
      assert.doesNotMatch(page.body, /<script>alert|onmouseover="/, value);
    }
    assert.deepEqual(harness.writer.reads, []);
    assert.deepEqual(harness.writer.creates, []);
  } finally {
    await harness.close();
  }
});

test("existing-post submission requires the form token", async () => {
  const harness = await startApp(() => ({ body: {} }));
  try {
    seedOwnPost(harness);
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await post(harness.origin, "/submit-existing", { csrf: "guess", post: OWN_POST_URI }, { cookie: cookie(token) });
    assert.equal(page.status, 403);
    assert.deepEqual(harness.writer.creates, []);
  } finally {
    await harness.close();
  }
});

test("the composition form states its consequence before submission", async () => {
  const harness = await startApp(() => ({ body: discussionList(0) }));
  try {
    const { token } = await harness.sessions.issue(MEMBER);
    const page = await get(harness.origin, "/", cookie(token));
    assert.match(page.body, /<label for="new-discussion">Start a discussion<\/label><p id="new-discussion-note">This publishes a new post on your own Bluesky account, then asks the moderator to add it here\.<\/p><textarea id="new-discussion" name="text" aria-describedby="new-discussion-note" required><\/textarea><button>Post to Bluesky and submit<\/button>/);
    assert.doesNotMatch(page.body, /Post publicly and submit|opt in|Withdraw/i);
  } finally {
    await harness.close();
  }
});

test("a completed composition says a new discussion is waiting and a reply is not yet recorded", () => {
  const root = { operationId: "op" } as ContributionPlan;
  const reply = { operationId: "op", discussion: { uri: "at://x/y/z", cid: "c" } } as ContributionPlan;
  assert.equal(userMessage("complete", root), "Submitted. Your post is now waiting for the moderator to add it here.");
  assert.equal(userMessage("complete", reply), "Posted. It will appear in the discussion once the community records it.");
  assert.doesNotMatch(userMessage("complete", root) + userMessage("complete", reply), /Posted to the community/);
});

test("an unconfirmed community submission is described in plain words", () => {
  const root = { operationId: "op" } as ContributionPlan;
  for (const status of ["community_submission_pending", "community_submission_outcome_unknown"] as const) {
    assert.equal(userMessage(status, root), "Your post is on Bluesky. The request to add it here is still being saved.");
  }
  assert.equal(userMessage("source_outcome_unknown", root), "Checking whether your public post was saved…");
});

test("sign-in explains itself and failed sign-in steps are plain 400 pages", async () => {
  const harness = await startApp(() => ({ body: discussionList(0) }), {}, undefined, {
    authorize: async () => {
      throw new Error("resolver exploded at /internal/path.ts:12");
    },
    callback: async () => {
      throw new Error("access_denied: internal oauth detail");
    },
  });
  try {
    const home = await get(harness.origin, "/");
    assert.match(home.body, /Sign in with your Bluesky \(ATProto\) account\. Nothing is created here; you will be asked to allow this site to post and submit on your behalf\./);
    const login = await post(harness.origin, "/oauth/login", { handle: "nobody.invalid" });
    assert.equal(login.status, 400);
    assert.match(login.body, /That handle could not be found\./);
    const callback = await get(harness.origin, "/oauth/callback?error=access_denied");
    assert.equal(callback.status, 400);
    assert.match(callback.body, /Sign-in was not completed\. Nothing changed\./);
    for (const body of [login.body, callback.body]) {
      assert.doesNotMatch(body, /exploded|internal|\.ts:|access_denied|Error/);
    }
  } finally {
    await harness.close();
  }
});

/** A sign-in harness whose callback echoes whatever state the last authorize carried. */
async function signInHarness(): Promise<Harness & { states: string[]; setCallbackState(value: string | null): void; signedOut: string[] }> {
  const states: string[] = [];
  const signedOut: string[] = [];
  let callbackState: string | null | "latest" = "latest";
  const harness = await startApp(() => ({ body: discussionList(0) }), {}, undefined, {
    authorize: async (_input, options) => {
      states.push(options.state ?? "");
      return new URL("https://auth.invalid.test/authorize");
    },
    callback: async () => ({
      session: { did: MEMBER, signOut: async () => { signedOut.push(MEMBER); } } as unknown as OAuthSession,
      state: callbackState === "latest" ? states.at(-1) ?? null : callbackState,
    }),
  });
  return { ...harness, states, signedOut, setCallbackState: (value) => { callbackState = value; } };
}

function loginCookieOf(page: Page): string {
  const value = /community_login=([^;]+);/.exec(page.headers.get("set-cookie") ?? "")?.[1];
  assert.ok(value, "login cookie issued");
  return `community_login=${value}`;
}

test("sign in to reply returns to the same discussion and ignores any other return path", async () => {
  const harness = await signInHarness();
  try {
    const home = await get(harness.origin, "/?return=%2Fd%2Froot1");
    assert.match(home.body, /<input type="hidden" name="return" value="\/d\/root1">/);
    for (const bad of ["https://evil.test/d/x", "//evil.test/d/x", "/mine", "/d/a/b", "/d/%3Cx%3E", "/d/.."]) {
      const other = await get(harness.origin, `/?return=${encodeURIComponent(bad)}`);
      assert.doesNotMatch(other.body, /name="return"/, bad);
    }
    const login = await post(harness.origin, "/oauth/login", { handle: "alice.example.test", return: "/d/root1" });
    await post(harness.origin, "/oauth/login", { handle: "alice.example.test", return: "https://evil.test/" });
    assert.deepEqual(harness.states.map((state) => new URLSearchParams(state).get("return")), ["/d/root1", null]);
    const returnState = harness.states[0]!;
    harness.setCallbackState(returnState);
    const back = await get(harness.origin, "/oauth/callback?code=x", loginCookieOf(login));
    assert.equal(back.status, 303);
    assert.equal(back.headers.get("location"), "/d/root1");
    harness.setCallbackState(returnState.replace("%2Fd%2Froot1", encodeURIComponent("//evil.test/d/root1")));
    const refused = await get(harness.origin, "/oauth/callback?code=x", loginCookieOf(login));
    assert.equal(refused.headers.get("location"), "/");
  } finally {
    await harness.close();
  }
});

test("the OAuth callback is bound to the browser that started the sign-in", async () => {
  const harness = await signInHarness();
  try {
    const login = await post(harness.origin, "/oauth/login", { handle: "alice.example.test" });
    assert.equal(login.status, 303);
    const issued = login.headers.get("set-cookie") ?? "";
    assert.match(issued, /^community_login=[A-Za-z0-9_-]{16,}; Path=\/oauth; HttpOnly; SameSite=Lax; Max-Age=600$/);
    assert.doesNotMatch(issued, /community_session/);
    const nonce = new URLSearchParams(harness.states[0]).get("nonce");
    assert.ok(nonce && issued.includes(`community_login=${nonce};`), "the state carries the cookie's nonce");

    // Without the cookie: the callback is not accepted and no session exists.
    const noCookie = await get(harness.origin, "/oauth/callback?code=x");
    assert.equal(noCookie.status, 400);
    assert.match(noCookie.body, /Sign-in was not completed\. Nothing changed\./);
    assert.doesNotMatch(noCookie.headers.get("set-cookie") ?? "", /community_session=/);
    assert.match(noCookie.headers.get("set-cookie") ?? "", /community_login=;.*Max-Age=0/);

    // With a cookie from a different browser: the same refusal and the OAuth session is dropped.
    const wrong = await get(harness.origin, "/oauth/callback?code=x", "community_login=someone-elses-nonce-0000");
    assert.equal(wrong.status, 400);
    assert.match(wrong.body, /Sign-in was not completed\. Nothing changed\./);
    assert.doesNotMatch(wrong.headers.get("set-cookie") ?? "", /community_session=/);
    assert.deepEqual(harness.signedOut, [MEMBER]);
    const sessions = await readdir(join(harness.config.runtimeDirectory, "web-sessions")).catch(() => []);
    assert.deepEqual(sessions, []);

    // The browser that started the sign-in completes it, and the login cookie is cleared.
    const back = await get(harness.origin, "/oauth/callback?code=x", loginCookieOf(login));
    assert.equal(back.status, 303);
    assert.equal(back.headers.get("location"), "/");
    const cookies = back.headers.getSetCookie();
    assert.ok(cookies.some((value) => /^community_session=[A-Za-z0-9_-]+; Path=\/; HttpOnly; SameSite=Lax; Max-Age=28800$/.test(value)), cookies.join(" | "));
    assert.ok(cookies.some((value) => /^community_login=; Path=\/oauth; .*Max-Age=0$/.test(value)), cookies.join(" | "));
    assert.equal(harness.signedOut.length, 1);
  } finally {
    await harness.close();
  }
});
