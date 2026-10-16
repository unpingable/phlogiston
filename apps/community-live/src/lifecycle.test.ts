import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { OAuthSession } from "@atproto/oauth-client-node";

import { ActivitySnapshots, type SeenStore } from "./activity.js";
import type { AppConfig } from "./config.js";
import { escapeHtml } from "./html.js";
import type { CommunityProjection } from "./observer.js";
import { AppViewPostDirectory, PostCache, type PostDirectory } from "./posts.js";
import { createHandler, type Dependencies } from "./server.js";
import { ContributionPlanStore, WebSessionStore } from "./storage.js";

const MODERATOR = "did:plc:moderator";
const ALICE = "did:plc:alice";
const BOB = "did:plc:bob";
const COMMUNITY = "did:plc:community";
const QUEUE_PATH = `/api/v0/communities/${encodeURIComponent(COMMUNITY)}/moderation-queue`;

class MemorySeenStore implements SeenStore {
  public async get(): Promise<number> {
    return 0;
  }
  public async advance(): Promise<void> {}
}

type ProjectionReply = Record<string, unknown> | Error;

interface Harness {
  origin: string;
  sessions: WebSessionStore;
  projectionPaths: string[];
  appViewRequests: string[][];
  close(): Promise<void>;
}

async function startApp(
  projection: (path: string) => ProjectionReply,
  appView: ((uris: string[]) => unknown) | "none" = () => ({ posts: [] }),
): Promise<Harness> {
  const root = await mkdtemp(join(tmpdir(), "community-lifecycle-"));
  const config: AppConfig = {
    publicUrl: "http://127.0.0.1:3210",
    communityDid: COMMUNITY,
    communityName: "Test Community",
    communityPurpose: "A bounded test community",
    moderatorDid: MODERATOR,
    runtimeDirectory: root,
    observerUrl: "http://127.0.0.1:1",
    observerMaxResponseBytes: 64 * 1024,
    discussionsMaxItems: 500,
    appViewOrigin: "https://appview.invalid.test",
    avatarsEnabled: false,
    authoritySocket: join(root, "authority.sock"),
    port: 3210,
  };
  const projectionPaths: string[] = [];
  const fakeProjection: CommunityProjection = {
    get: async (path) => {
      projectionPaths.push(path);
      const reply = projection(path);
      if (reply instanceof Error) throw reply;
      return reply;
    },
    getCapped: async (path) => {
      projectionPaths.push(path);
      const reply = projection(path);
      if (reply instanceof Error) throw reply;
      return reply;
    },
  };
  const appViewRequests: string[][] = [];
  let posts: PostDirectory | undefined;
  if (appView !== "none") {
    const respond = appView;
    posts = new AppViewPostDirectory(config.appViewOrigin, new PostCache(100, 60_000, 60_000, () => Date.now()), {
      fetchFn: (async (input: string | URL | Request) => {
        const url = new URL(String(input));
        assert.equal(url.origin, "https://appview.invalid.test");
        assert.equal(url.pathname, "/xrpc/app.bsky.feed.getPosts");
        const uris = url.searchParams.getAll("uris");
        appViewRequests.push(uris);
        return new Response(JSON.stringify(respond(uris)), { status: 200 });
      }) as typeof fetch,
    });
  }
  const sessions = new WebSessionStore(join(root, "web-sessions"));
  const deps: Dependencies = {
    config,
    oauth: {
      authorize: async () => new URL("https://auth.invalid.test/authorize"),
      callback: async () => ({ session: { did: ALICE } as unknown as OAuthSession }),
      restore: async (did: string) => ({ did } as unknown as OAuthSession),
    },
    webSessions: sessions,
    plans: new ContributionPlanStore(join(root, "contribution-plans")),
    activities: new ActivitySnapshots(Buffer.alloc(32, 3), new MemorySeenStore()),
    authority: { request: async () => ({ ok: true }) },
    projection: fakeProjection,
    profiles: { lookup: async () => new Map() },
    ...(posts === undefined ? {} : { posts }),
  };
  const app = createServer((request, response) => void createHandler(deps)(request, response));
  await new Promise<void>((resolve) => app.listen(0, "127.0.0.1", resolve));
  return {
    origin: `http://127.0.0.1:${(app.address() as AddressInfo).port}`,
    sessions,
    projectionPaths,
    appViewRequests,
    close: () => new Promise((resolve, reject) => app.close((error) => (error ? reject(error) : resolve()))),
  };
}

async function get(origin: string, path: string, token: string): Promise<{ status: number; body: string }> {
  const response = await fetch(`${origin}${path}`, { headers: { Cookie: `community_session=${token}` }, redirect: "manual" });
  return { status: response.status, body: await response.text() };
}

function queued(author: string, rkey: string): Record<string, unknown> {
  return {
    submission: { uri: `at://${author}/app.phlogiston.community.submit/${rkey}`, cid: `sub-cid-${rkey}` },
    subject: { uri: `at://${author}/app.bsky.feed.post/${rkey}`, cid: `post-cid-${rkey}` },
    authorDid: author,
    observerSequence: 1,
  };
}

function postView(uri: string, text: string, cid = `post-cid-${uri.split("/").at(-1)}`): Record<string, unknown> {
  return { uri, cid, record: { text } };
}

const EMPTY_PARTICIPANT = { communityDid: COMMUNITY, participantDid: ALICE, discussions: [], activity: [], snapshot: {} };

function queueDocument(...entries: Record<string, unknown>[]): Record<string, unknown> {
  return { communityDid: COMMUNITY, submissions: entries, snapshot: {} };
}

test("the moderation queue shows the exact submitted post text, labelled unverified", async () => {
  const harness = await startApp(
    () => queueDocument(queued(ALICE, "p1")),
    (uris) => ({ posts: uris.map((uri) => postView(uri, "Is anyone going to the meetup?\nSecond line")) }),
  );
  try {
    const { token } = await harness.sessions.issue(MODERATOR);
    const page = await get(harness.origin, "/moderation", token);
    assert.equal(page.status, 200);
    assert.match(page.body, /<article class="submitted-text">Is anyone going to the meetup\?\nSecond line<\/article>/);
    assert.match(page.body, /\(text from Bluesky, unverified\)/);
    assert.match(page.body, /app\.phlogiston\.community\.submit\/p1/);
    assert.match(page.body, /name="kind" value="admit-root"><input type="hidden" name="uri" value="at:\/\/did:plc:alice\/app\.phlogiston\.community\.submit\/p1"><input type="hidden" name="cid" value="sub-cid-p1"><button>Admit<\/button>/);
    assert.match(page.body, /Public post on Bluesky/);
    assert.deepEqual(harness.appViewRequests, [["at://did:plc:alice/app.bsky.feed.post/p1"]]);
  } finally {
    await harness.close();
  }
});

test("moderation text is withheld when the AppView CID differs from the submitted CID", async () => {
  const harness = await startApp(
    () => queueDocument(queued(ALICE, "p1")),
    (uris) => ({ posts: uris.map((uri) => postView(uri, "An edited later version", "some-other-cid")) }),
  );
  try {
    const { token } = await harness.sessions.issue(MODERATOR);
    const page = await get(harness.origin, "/moderation", token);
    assert.equal(page.status, 200);
    assert.doesNotMatch(page.body, /An edited later version/);
    assert.doesNotMatch(page.body, /submitted-text/);
    assert.match(page.body, /Public post on Bluesky/);
    assert.match(page.body, /<button>Admit<\/button>/);
  } finally {
    await harness.close();
  }
});

test("moderation degrades to the plain queue when post hydration is absent or failing", async () => {
  for (const appView of ["none", () => { throw new Error("down"); }] as const) {
    const harness = await startApp(() => queueDocument(queued(ALICE, "p1")), appView);
    try {
      const { token } = await harness.sessions.issue(MODERATOR);
      const page = await get(harness.origin, "/moderation", token);
      assert.equal(page.status, 200);
      assert.doesNotMatch(page.body, /submitted-text|unverified/);
      assert.match(page.body, /app\.phlogiston\.community\.submit\/p1/);
      assert.match(page.body, /<button>Admit<\/button>/);
    } finally {
      await harness.close();
    }
  }
});

const HOSTILE_TEXT = [
  "<script>alert(1)</script>",
  '<img src=x onerror=alert(1)>',
  '" autofocus onfocus=alert(1) x="',
  '<a href="javascript:alert(1)">verify</a>',
  "</article><form action=\"https://collect.invalid.test\"><button>Admit</button></form>",
  "bell\u0007 esc\u001b[31m nul\u0000 rtl‮evil‬",
  "A".repeat(10_000),
];

test("hostile hydrated post text renders inert on the moderation and pending pages", async () => {
  const entries = HOSTILE_TEXT.map((_, index) => queued(ALICE, `h${index}`));
  const byUri = new Map(entries.map((entry, index) => [(entry.subject as { uri: string }).uri, HOSTILE_TEXT[index] as string]));
  const harness = await startApp(
    (path) => path === QUEUE_PATH ? queueDocument(...entries) : EMPTY_PARTICIPANT,
    (uris) => ({ posts: uris.map((uri) => postView(uri, byUri.get(uri) ?? "")) }),
  );
  try {
    const moderator = await harness.sessions.issue(MODERATOR);
    const alice = await harness.sessions.issue(ALICE);
    for (const [path, token] of [["/moderation", moderator.token], ["/mine", alice.token]] as const) {
      const page = await get(harness.origin, path, token);
      assert.equal(page.status, 200);
      assert.doesNotMatch(page.body, /<script/i);
      assert.doesNotMatch(page.body, /<img/i);
      assert.doesNotMatch(page.body, /href="javascript:/i);
      assert.doesNotMatch(page.body, /" autofocus onfocus=/);
      assert.doesNotMatch(page.body, /[\u0000-\u0008\u000b-\u001f\u007f‪-‮]/);
      assert.match(page.body, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
      assert.match(page.body, /&lt;\/article&gt;&lt;form action=&quot;https:\/\/collect\.invalid\.test&quot;&gt;/);
      assert.match(page.body, new RegExp(`${"A".repeat(3_000)}…</article>`));
      assert.doesNotMatch(page.body, new RegExp("A".repeat(3_001)));
      for (const form of page.body.match(/<form[^>]*action="[^"]*"/g) ?? []) {
        assert.match(form, /action="\/(moderate|signout|disconnect|seen)"/);
      }
      for (const href of page.body.match(/href="[^"]*"/g) ?? []) {
        assert.match(href, /^href="(\/|#|https:\/\/bsky\.app\/)/);
      }
    }
  } finally {
    await harness.close();
  }
});

test("my discussions shows only the signed-in author's own pending submissions", async () => {
  const harness = await startApp(
    (path) => path === QUEUE_PATH
      ? queueDocument(queued(ALICE, "mine1"), queued(BOB, "bobs1"), queued(ALICE, "mine2"))
      : EMPTY_PARTICIPANT,
    (uris) => ({ posts: uris.filter((uri) => uri.endsWith("mine1") || uri.endsWith("bobs1")).map((uri) => postView(uri, `Text of ${uri.split("/").at(-1)}`)) }),
  );
  try {
    const { token } = await harness.sessions.issue(ALICE);
    const page = await get(harness.origin, "/mine", token);
    assert.equal(page.status, 200);
    assert.match(page.body, /<h2>Waiting for the moderator<\/h2>/);
    assert.match(page.body, /Text of mine1/);
    assert.match(page.body, /\(text from Bluesky, unverified\)/);
    assert.match(page.body, /href="https:\/\/bsky\.app\/profile\/did:plc:alice\/post\/mine2"/);
    assert.doesNotMatch(page.body, /bobs1|did:plc:bob/);
    assert.doesNotMatch(page.body, /action="\/moderate"|admit-root/);
    assert.deepEqual(harness.appViewRequests.flat().sort(), [
      "at://did:plc:alice/app.bsky.feed.post/mine1",
      "at://did:plc:alice/app.bsky.feed.post/mine2",
    ]);
    assert.match(page.body, /None yet\./);
  } finally {
    await harness.close();
  }
});

test("my discussions omits the waiting section when nothing of mine is pending", async () => {
  const harness = await startApp((path) => path === QUEUE_PATH ? queueDocument(queued(BOB, "bobs1")) : EMPTY_PARTICIPANT);
  try {
    const { token } = await harness.sessions.issue(ALICE);
    const page = await get(harness.origin, "/mine", token);
    assert.equal(page.status, 200);
    assert.doesNotMatch(page.body, /Waiting for the moderator/);
    assert.doesNotMatch(page.body, /bobs1/);
    assert.equal(harness.appViewRequests.length, 0);
  } finally {
    await harness.close();
  }
});

test("my discussions says truthfully when pending status cannot be read", async () => {
  const harness = await startApp((path) => path === QUEUE_PATH
    ? new Error("Community projection is temporarily unavailable.")
    : EMPTY_PARTICIPANT);
  try {
    const { token } = await harness.sessions.issue(ALICE);
    const page = await get(harness.origin, "/mine", token);
    assert.equal(page.status, 200);
    assert.match(page.body, /Waiting for the moderator/);
    assert.match(page.body, /cannot be checked right now/);
    assert.doesNotMatch(page.body, /temporarily unavailable\./);
    assert.match(page.body, /None yet\./);
  } finally {
    await harness.close();
  }
});

test("the moderation queue is still refused to non-moderators before any projection read", async () => {
  const harness = await startApp(() => queueDocument(queued(ALICE, "p1")));
  try {
    const { token } = await harness.sessions.issue(ALICE);
    const page = await get(harness.origin, "/moderation", token);
    assert.equal(page.status, 403);
    assert.deepEqual(harness.projectionPaths, []);
    assert.equal(escapeHtml(page.body).includes("p1"), false);
  } finally {
    await harness.close();
  }
});
