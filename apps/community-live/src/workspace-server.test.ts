import assert from "node:assert/strict";
import {mkdtemp, rm, writeFile} from "node:fs/promises";
import {createServer} from "node:http";
import type {AddressInfo} from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import type {OAuthSession} from "@atproto/oauth-client-node";
import type {AppBskyFeedDefs, BskyPreferences, ModerationCause, ModerationUI} from "@atproto/api";
import {loadConfig} from "./config.js";
import {createHandler, type Dependencies} from "./server.js";
import {Reader, type ReaderTransport, type ThreadResult} from "./reader.js";
import {LocalQuietStore} from "./local-quiet.js";
import {WebSessionStore} from "./storage.js";
import {FEED_SCOPE, READER_SCOPE} from "./p0.js";

const DID = "did:plc:alice", OTHER = "did:plc:bob";
const FEED = "at://did:plc:abcdefghijklmnopqrstuvwx/app.bsky.feed.generator/interesting";
const UNSAVED = "at://did:plc:abcdefghijklmnopqrstuvwx/app.bsky.feed.generator/unsaved";
const ROOT = `at://${DID}/app.bsky.feed.post/root`;
const CID = "bafyreifkpymf7jb3jg5giimeyzab6lbokwi3ko5hdutcj7ift54i64zqxu";

function post(uri = ROOT): AppBskyFeedDefs.PostView {
  return {uri, cid: CID, author: {did: DID, handle: "alice.test"},
    record: {$type: "app.bsky.feed.post", text: "A fixture post", createdAt: "2026-10-12T00:00:00Z"},
    indexedAt: "2026-10-12T00:00:00Z", labels: [{src: DID, uri, val: "fixture-label", cts: "2026-10-12T00:00:00Z"}]};
}

async function harness(scope = FEED_SCOPE) {
  const directory = await mkdtemp(join(tmpdir(), "phlo-workspace-route-"));
  const config = loadConfig({COMMUNITY_PROFILE: "p0", COMMUNITY_READER_ENABLED: "true",
    COMMUNITY_PUBLIC_URL: "http://127.0.0.1:3210", COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "The Cabinet", COMMUNITY_PURPOSE: "Fixture collection",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator", COMMUNITY_RUNTIME_DIR: directory,
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080", COMMUNITY_AUTHORITY_SOCKET: join(directory, "socket"),
    COMMUNITY_SITE_PAUSE_PATH: join(directory, "site"), COMMUNITY_ADMISSION_PAUSE_PATH: join(directory, "admission")});
  await writeFile(config.sitePausePath!, "open\n", {mode: 0o600});
  const webSessions = new WebSessionStore(join(directory, "sessions"));
  const signed = await webSessions.issue(DID, new Date(), scope);
  const second = await webSessions.issue(OTHER, new Date(), scope);
  const localQuiet = new LocalQuietStore(join(directory, "local-quiet.sqlite"));
  const calls = {feeds: [] as string[], effects: 0, roots: 0, labels: 0, auth: [] as string[], unavailableRoot: false,
    threadResult: null as ThreadResult | null, decision: null as Partial<ModerationUI> | null,
    feed: [{post: post()}] as AppBskyFeedDefs.FeedViewPost[],
    holdRoot: null as null | (() => Promise<void>)};
  const session = (did: string) => ({did, getTokenInfo: async () => ({sub: did,
    aud: "https://phellinus.us-west.host.bsky.network", iss: "https://bsky.social", scope}),
    signOut: async () => {}}) as unknown as OAuthSession;
  const prefs = {feedViewPrefs: {home: {hideReplies: false, hideRepliesByUnfollowed: false,
    hideRepliesByLikeCount: 0, hideReposts: false, hideQuotePosts: false}},
    moderationPrefs: {adultContentEnabled: false, labels: {}, labelers: [], mutedWords: [], hiddenPosts: []}} as unknown as BskyPreferences;
  const transport: ReaderTransport = {
    preferences: async () => prefs,
    savedFeedPreferences: async () => [{$type: "app.bsky.actor.defs#savedFeedsPrefV2", items: [
      {id: "one", type: "feed", value: FEED, pinned: true}]}],
    labelDefinitions: async () => ({}),
    timeline: async () => ({feed: calls.feed}),
    customFeed: async uri => {calls.feeds.push(uri); return {feed: [{post: post()}]};},
    feedGenerators: async uri => [{uri, cid: CID, did: DID, creator: {did: DID, handle: "alice.test"},
      displayName: "Interesting", indexedAt: "2026-10-12T00:00:00Z"}],
    postThread: async uri => {calls.roots++;await calls.holdRoot?.();return calls.threadResult ?? (calls.unavailableRoot ?
      {$type: "app.bsky.feed.defs#notFoundPost", uri, notFound: true} :
      {$type: "app.bsky.feed.defs#threadViewPost", post: post(uri)});},
    muteThread: async () => {calls.effects++;}, unmuteThread: async () => {calls.effects++;},
  };
  const deps = {config, webSessions, localQuiet, reader: (s: OAuthSession) => {
    const reader = new Reader(s, transport);
    const decision = reader.decision.bind(reader);
    reader.decision = (value, context) => {
      const base = decision(value, context);
      return calls.decision ? {...base, filter: base.filter, blur: base.blur, alert: base.alert, inform: base.inform, ...calls.decision} : base;
    };
    return reader;
  },
    oauth: {authorize: async (_handle: string, options: {scope: string}) => {calls.auth.push(options.scope);return new URL("https://bsky.social/auth");},
      restore: async (did: string) => session(did), callback: async () => ({session: session(DID)})},
    labels: {lookup: async () => {calls.labels++;return null;}},
  } as unknown as Dependencies;
  const server = createServer(createHandler(deps));
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const cookie = (who = signed) => `community_session=${who.token}`;
  const get = (path: string, who = signed) => fetch(origin + path, {redirect: "manual", headers: {Cookie: cookie(who)}});
  const postForm = (path: string, fields: Record<string, string>, who = signed,
    headers: Record<string, string> = {}) => fetch(origin + path, {method: "POST", redirect: "manual",
    headers: {Origin: config.publicUrl, Cookie: cookie(who), "Content-Type": "application/x-www-form-urlencoded", ...headers},
    body: new URLSearchParams(fields)});
  return {directory, config, signed, second, localQuiet, calls, origin, get, postForm,
    close: async () => {await new Promise<void>(resolve => server.close(() => resolve()));localQuiet.close();
      await rm(directory, {recursive: true, force: true});}};
}

test("legacy reader grant retains Following while saved feeds require explicit new grant", async () => {
  const h = await harness(READER_SCOPE);
  try {
    const home = await h.get("/home");assert.equal(home.status, 200);assert.match(await home.text(), /A fixture post/);
    const saved = await h.get(`/home?feed=${encodeURIComponent(FEED)}`);
    assert.equal(saved.status, 200);assert.match(await saved.text(), /Connect saved feeds/);
    assert.deepEqual(h.calls.feeds, []);
    const sources = await h.get("/sources");assert.equal(sources.status, 200);
    assert.equal(sources.headers.get("cache-control"), "no-store");
    assert.equal((await sources.json()).feedsConnected, false);
    const login = await h.postForm("/oauth/login", {handle: "alice.test", access: "feeds", return: "/home"});
    assert.equal(login.status, 303);assert.equal(h.calls.auth.at(-1), FEED_SCOPE);
  } finally {await h.close();}
});

test("saved feed route uses only account catalog and context is descriptive, not authority", async () => {
  const h = await harness();
  try {
    const sources = await h.get("/sources");assert.equal(sources.status, 200);
    const catalog = await sources.json();assert.equal(catalog.feedsConnected, true);
    assert.ok(catalog.sources.some((source: {uri: string; name: string}) => source.uri === FEED && source.name === "Interesting"));
    const selected = await h.get(`/home?feed=${encodeURIComponent(FEED)}`);
    assert.equal(selected.status, 200);assert.match(await selected.text(), /A fixture post/);
    assert.deepEqual(h.calls.feeds, [FEED]);
    const unsaved = await h.get(`/home?feed=${encodeURIComponent(UNSAVED)}`);
    assert.equal(unsaved.status, 400);assert.deepEqual(h.calls.feeds, [FEED]);
    const context = await h.get(`/context?uri=${encodeURIComponent(ROOT)}`);
    assert.equal(context.status, 200);
    const body = await context.text();assert.match(body, /fixture-label/);
    assert.match(body, /do not establish current label state or community admission/);
    assert.equal(context.headers.get("cache-control"), "no-store");
    const destination = "/context?uri=" + encodeURIComponent(ROOT);
    const anonymous = await fetch(h.origin + destination, {redirect: "manual"});
    assert.equal(anonymous.status, 303);
    assert.equal(new URL(anonymous.headers.get("location")!, h.origin).searchParams.get("return"), destination);
    assert.doesNotMatch(await anonymous.text(), /fixture-label|Independent observations/);
  } finally {await h.close();}
});

test("local quiet respects Origin, CSRF, site pause, account scope and unknown roots without provider mutation", async () => {
  const h = await harness();
  const fields = {csrf: h.signed.csrf, feed: "following", uri: ROOT, action: "quiet"};
  try {
    const noOrigin = await h.postForm("/local-quiet", fields, h.signed, {Origin: ""});
    assert.equal(noOrigin.status, 403);
    const wrongCsrf = await h.postForm("/local-quiet", {...fields, csrf: "wrong"});
    assert.equal(wrongCsrf.status, 403);
    await writeFile(h.config.sitePausePath!, "paused\n");
    assert.equal((await h.postForm("/local-quiet", fields)).status, 503);
    await writeFile(h.config.sitePausePath!, "open\n");
    h.calls.unavailableRoot = true;
    assert.equal((await h.postForm("/local-quiet", fields)).status, 503);
    assert.deepEqual(h.localQuiet.list(DID, "following"), []);
    h.calls.unavailableRoot = false;
    const set = await h.postForm("/local-quiet", fields);assert.equal(set.status, 200);
    assert.deepEqual(await set.json(), {root: ROOT, feed: "following", quiet: true, providerChanged: false});
    assert.deepEqual(h.localQuiet.list(DID, "following"), [ROOT]);
    assert.doesNotMatch(await (await h.get("/home")).text(), /A fixture post/);
    assert.match(await (await h.get("/home", h.second)).text(), /A fixture post/);
    const other = await h.get("/local-quiet?feed=following", h.second);
    assert.equal(other.status, 200);assert.deepEqual(await other.json(), {roots: []});
    assert.equal(h.calls.effects, 0);
    const restored = await h.postForm("/local-quiet", {...fields, action: "restore", root: ROOT});
    assert.equal(restored.status, 200);assert.deepEqual(h.localQuiet.list(DID, "following"), []);
    assert.match(await (await h.get("/home")).text(), /A fixture post/);
  } finally {await h.close();}
});

test("pause after root resolution but before local write refuses the state transition", async () => {
  const h = await harness();
  try {
    h.calls.holdRoot = async () => {await writeFile(h.config.sitePausePath!, "paused\n");};
    const response = await h.postForm("/local-quiet", {csrf: h.signed.csrf, feed: "following", uri: ROOT, action: "quiet"});
    assert.equal(response.status, 503);
    assert.deepEqual(h.localQuiet.list(DID, "following"), []);
    assert.equal(h.calls.effects, 0);
  } finally {await h.close();}
});

test("withheld post context explains moderation without rendering content or looking up observations", async () => {
  const h = await harness();
  const cause = {type: "label", label: {val: "<fixture-warning>", src: "did:plc:labeler"},
    target: "content", setting: "hide"} as unknown as ModerationCause;
  try {
    for (const state of [{filter: true}, {noOverride: true}, {blur: true}]) {
      h.calls.decision = {...state, filters: [cause]};
      const response = await h.get(`/context?uri=${encodeURIComponent(ROOT)}`);
      assert.equal(response.status, 403);
      assert.equal(response.headers.get("cache-control"), "no-store");
      const body = await response.text();
      assert.match(body, /attention-marker" data-decided-by="viewer"/);
      assert.match(body, /moderation settings, based on a label from did:plc:labeler/);
      assert.match(body, /&lt;fixture-warning&gt;/);
      assert.doesNotMatch(body, /A fixture post|alice\.test|<fixture-warning>|Labels supplied with this post|<h2>Independent observations/);
    }
    assert.equal(h.calls.labels, 0);
    assert.equal(h.calls.effects, 0);
  } finally {await h.close();}
});

test("unavailable post context reports only the supplied outcome", async () => {
  const h = await harness();
  try {
    for (const [thread, expected, absent] of [
      [{$type: "app.bsky.feed.defs#blockedPost", uri: ROOT, blocked: true, author: {did: OTHER, viewer: {blockedBy: true}}}, /data-decided-by="account"/, /data-decided-by="viewer"/],
      [{$type: "app.bsky.feed.defs#blockedPost", uri: ROOT, blocked: true, author: {did: OTHER}}, /data-decided-by="source"/, /You block|This account blocks you/],
      [{$type: "app.bsky.feed.defs#notFoundPost", uri: ROOT, notFound: true}, /may have been deleted or may never have been indexed/, /was deleted/],
    ] as const) {
      h.calls.threadResult = thread as ThreadResult;
      const response = await h.get(`/context?uri=${encodeURIComponent(ROOT)}`);
      assert.equal(response.status, 404);
      const body = await response.text();
      assert.match(body, expected);
      assert.doesNotMatch(body, absent);
      assert.doesNotMatch(body, /A fixture post|Labels supplied with this post/);
    }
    h.calls.threadResult = {$type: "app.bsky.feed.defs#threadViewPost", post: post(ROOT + "-different")};
    const mismatch = await h.get(`/context?uri=${encodeURIComponent(ROOT)}`);
    assert.equal(mismatch.status, 404);
    assert.match(await mismatch.text(), /data-observation="not-established"/);
    for (const malformed of [
      {$type: "app.bsky.feed.defs#notFoundPost", uri: ROOT + "-different", notFound: true},
      {$type: "app.bsky.feed.defs#blockedPost", uri: ROOT + "-different", blocked: true, author: {did: OTHER, viewer: {blockedBy: true}}},
      {$type: "app.bsky.feed.defs#threadViewPost"},
    ]) {
      h.calls.threadResult = malformed as ThreadResult;
      const response = await h.get(`/context?uri=${encodeURIComponent(ROOT)}`);
      assert.equal(response.status, 404);
      const body = await response.text();
      assert.match(body, /data-observation="not-established"/);
      assert.doesNotMatch(body, /data-decided-by=|This account blocks you|Bluesky reports this post was not found/);
    }
    assert.equal(h.calls.labels, 0);
  } finally {await h.close();}
});

test("local quiet keeps conflicting received lineage visible and counts only established roots", async () => {
  const h = await harness();
  const reply = post(ROOT + "-reply");
  reply.record = {...reply.record, reply: {root: {uri: ROOT, cid: CID}, parent: {uri: ROOT, cid: CID}}};
  const other = post(ROOT + "-other");
  const conflict = {post: reply, reply: {root: other, parent: other}} as AppBskyFeedDefs.FeedViewPost;
  h.calls.feed = [{post: post()}, conflict, {post: other}];
  try {
    h.localQuiet.set(DID, "following", ROOT);
    const body = await (await h.get("/home")).text();
    assert.match(body, /Showing 2 of the 3 posts received for this page\. 1 hidden by your settings/);
    const article = body.match(/<article[^>]*data-post-uri="[^"]*-reply"[^>]*>/)?.[0];
    assert.ok(article);
    assert.doesNotMatch(article, /data-local-quiet-root/);
    assert.match(body, new RegExp(`data-local-quiet-root="${other.uri}"`));
    assert.equal(h.calls.effects, 0);
  } finally {await h.close();}
});
