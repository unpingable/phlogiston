import assert from "node:assert/strict";
import {mkdtemp, rm, writeFile} from "node:fs/promises";
import {createServer} from "node:http";
import type {AddressInfo} from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import type {OAuthSession} from "@atproto/oauth-client-node";
import type {AppBskyActorDefs, AppBskyFeedDefs, BskyPreferences} from "@atproto/api";
import {loadConfig} from "./config.js";
import {createHandler, type Dependencies} from "./server.js";
import {Reader, type ReaderTransport} from "./reader.js";
import {LocalQuietStore} from "./local-quiet.js";
import {PersonalFeedStore} from "./personal-feeds.js";
import {WebSessionStore} from "./storage.js";
import {CURATION_SCOPE, FEED_SCOPE} from "./p0.js";

const ALICE = "did:plc:alice", BOB = "did:plc:bob", CURATOR = "did:plc:curator";
const BLOCKED = "did:plc:blocked", ROOT = `at://${ALICE}/app.bsky.feed.post/root`;
const CID = "bafyreifkpymf7jb3jg5giimeyzab6lbokwi3ko5hdutcj7ift54i64zqxu";
const checkedAt = "2026-10-12T00:00:00Z";

function post(did: string, text: string): AppBskyFeedDefs.PostView {
  const uri = `at://${did}/app.bsky.feed.post/root`;
  return {uri, cid: CID, author: {did, handle: `${did.slice(8)}.test`},
    record: {$type: "app.bsky.feed.post", text, createdAt: checkedAt}, indexedAt: checkedAt};
}

async function harness(scope = CURATION_SCOPE) {
  const directory = await mkdtemp(join(tmpdir(), "phlo-personal-routes-"));
  const config = loadConfig({COMMUNITY_PROFILE: "p0", COMMUNITY_READER_ENABLED: "true",
    COMMUNITY_PUBLIC_URL: "http://127.0.0.1:3210", COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "The Cabinet", COMMUNITY_PURPOSE: "Fixture collection",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator", COMMUNITY_RUNTIME_DIR: directory,
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080", COMMUNITY_AUTHORITY_SOCKET: join(directory, "socket"),
    COMMUNITY_SITE_PAUSE_PATH: join(directory, "site"), COMMUNITY_ADMISSION_PAUSE_PATH: join(directory, "admission")});
  await writeFile(config.sitePausePath!, "open\n", {mode: 0o600});
  const webSessions = new WebSessionStore(join(directory, "sessions"));
  const alice = await webSessions.issue(ALICE, new Date(), scope);
  const bob = await webSessions.issue(BOB, new Date(), scope);
  const personalFeeds = new PersonalFeedStore(join(directory, "personal-feeds.sqlite"));
  const localQuiet = new LocalQuietStore(join(directory, "local-quiet.sqlite"));
  const calls = {profiles: [] as string[], blocks: [] as string[], timelines: 0, failBlocks: false,
    beforeBlocks: null as null | (() => Promise<void>), curatorDid: CURATOR, excludedDids: [BLOCKED]};
  const session = (did: string) => ({did, getTokenInfo: async () => ({sub: did,
    aud: "https://phellinus.us-west.host.bsky.network", iss: "https://bsky.social", scope}),
    signOut: async () => {}}) as unknown as OAuthSession;
  const prefs = {feedViewPrefs: {home: {hideReplies: false, hideRepliesByUnfollowed: false,
    hideRepliesByLikeCount: 0, hideReposts: false, hideQuotePosts: false}},
    moderationPrefs: {adultContentEnabled: false, labels: {}, labelers: [], mutedWords: [], hiddenPosts: []}} as unknown as BskyPreferences;
  const transport: ReaderTransport = {
    preferences: async () => prefs, savedFeedPreferences: async () => [] as AppBskyActorDefs.Preferences,
    labelDefinitions: async () => ({}),
    timeline: async () => {calls.timelines++; return {feed: [{post: post(BLOCKED, "Excluded fixture post")},
      {post: post(ALICE, "Allowed fixture post")}, {post: post(BOB, "Other fixture post")}], cursor: "next-page"};},
    curatorProfile: async actor => {calls.profiles.push(actor); return {
      did: calls.curatorDid, handle: "curator.test"} as AppBskyActorDefs.ProfileViewDetailed;},
    postThread: async uri => ({$type: "app.bsky.feed.defs#threadViewPost", post: post(ALICE, "Allowed fixture post"),
      ...(uri === ROOT ? {} : {})}),
    muteThread: async () => {}, unmuteThread: async () => {},
  };
  const deps = {config, webSessions, personalFeeds, localQuiet,
    publicBlocks: {read: async (did: string) => {calls.blocks.push(did); await calls.beforeBlocks?.();
      if (calls.failBlocks) throw new Error("public blocks unavailable");
      return {excludedDids: calls.excludedDids, checkedAt, recordCount: calls.excludedDids.length};}},
    reader: (s: OAuthSession) => new Reader(s, transport),
    oauth: {authorize: async () => new URL("https://bsky.social/auth"), restore: async (did: string) => session(did),
      callback: async () => ({session: session(ALICE)})}, labels: {lookup: async () => null},
  } as unknown as Dependencies;
  const server = createServer(createHandler(deps));
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const cookie = (who = alice) => `community_session=${who.token}`;
  const get = (path: string, who = alice) => fetch(origin + path, {redirect: "manual", headers: {Cookie: cookie(who)}});
  const postForm = (path: string, fields: Record<string, string>, who = alice,
    headers: Record<string, string> = {}) => fetch(origin + path, {method: "POST", redirect: "manual",
    headers: {Origin: config.publicUrl, Cookie: cookie(who), "Content-Type": "application/x-www-form-urlencoded", ...headers},
    body: new URLSearchParams(fields)});
  const save = (who = alice, extra: Record<string, string> = {}) => postForm("/feeds", {
    csrf: who.csrf, action: "save", name: "My filtered Following", curator: "curator.test",
    replies: "yes", reposts: "yes", ...extra}, who);
  const idFrom = (response: Response) => new URL(response.headers.get("location")!, config.publicUrl).searchParams.get("edit")!;
  return {directory, config, alice, bob, personalFeeds, localQuiet, calls, origin, get, postForm, save, idFrom,
    close: async () => {await new Promise<void>(resolve => server.close(() => resolve()));
      personalFeeds.close();localQuiet.close();await rm(directory, {recursive: true, force: true});}};
}

test("personal feeds require sign-in and explicit curation grant; responses are private", async () => {
  const h = await harness(FEED_SCOPE);
  try {
    const anonymous = await fetch(h.origin + "/feeds", {redirect: "manual"});
    assert.equal(anonymous.status, 303);assert.equal(anonymous.headers.get("location"), "/signin?return=%2Ffeeds");
    assert.doesNotMatch(await anonymous.text(), /My filtered Following|name="curator"/);
    const connect = await h.get("/feeds");assert.equal(connect.status, 200);
    assert.equal(connect.headers.get("cache-control"), "no-store");
    assert.match(await connect.text(), /Connect personal feeds/);
    const denied = await h.save();assert.equal(denied.status, 200);
    assert.equal(h.personalFeeds.list(ALICE).length, 0);
    assert.deepEqual(h.calls.profiles, []);assert.deepEqual(h.calls.blocks, []);
    const home = await h.get("/home?personal=00000000-0000-4000-8000-000000000000");
    assert.equal(home.status, 200);assert.match(await home.text(), /Connect personal feeds/);
  } finally {await h.close();}
});

test("creation and preview enforce Origin, CSRF and fresh curator policy before saving", async () => {
  const h = await harness();
  try {
    assert.equal((await h.postForm("/feeds", {csrf: h.alice.csrf, action: "save", name: "x", curator: "curator.test"}, h.alice, {Origin: ""})).status, 403);
    assert.equal((await h.save(h.alice, {csrf: "wrong"})).status, 403);
    assert.equal(h.personalFeeds.list(ALICE).length, 0);
    h.calls.failBlocks = true;
    const refused = await h.save();assert.equal(refused.status, 503);
    assert.equal(h.personalFeeds.list(ALICE).length, 0);
    assert.equal(h.calls.timelines, 0);
    h.calls.failBlocks = false;
    const preview = await h.postForm("/feeds", {csrf: h.alice.csrf, action: "preview", name: "Preview", curator: "curator.test"});
    assert.equal(preview.status, 200);const body = await preview.text();
    assert.match(body, /Allowed fixture post/);assert.doesNotMatch(body, /Excluded fixture post/);
    assert.equal(h.personalFeeds.list(ALICE).length, 0);
    const saved = await h.save();assert.equal(saved.status, 303);
    const definition = h.personalFeeds.get(ALICE, h.idFrom(saved))!;
    assert.deepEqual(definition.sources, [{kind: "following"}]);
    assert.deepEqual(definition.policies.publicBlocks, {curatorDid: CURATOR, curatorHandle: "curator.test"});
    assert.equal(definition.publishing, null);
  } finally {await h.close();}
});

test("stored curator DID remains pinned; failed refresh never renders unfiltered Following", async () => {
  const h = await harness();
  try {
    const id = h.idFrom(await h.save());
    h.calls.curatorDid = "did:plc:replacement";
    const view = await h.get(`/home?personal=${id}`);
    assert.equal(view.status, 200);assert.equal(view.headers.get("cache-control"), "no-store");
    const html = await view.text();assert.match(html, /Allowed fixture post/);
    assert.doesNotMatch(html, /Excluded fixture post/);
    assert.equal(h.calls.blocks.at(-1), CURATOR);assert.deepEqual(h.calls.profiles, ["curator.test"]);
    h.calls.failBlocks = true;const before = h.calls.timelines;
    const unavailable = await h.get(`/home?personal=${id}`);
    assert.equal(unavailable.status, 503);assert.doesNotMatch(await unavailable.text(), /Allowed fixture post/);
    assert.equal(h.calls.timelines, before);
  } finally {await h.close();}
});

test("account ownership covers edit, home, deletion and feed-scoped local quiet", async () => {
  const h = await harness();
  try {
    const id = h.idFrom(await h.save());const key = `personal:${id}`;
    h.localQuiet.set(ALICE, key, ROOT);
    assert.equal((await h.get(`/feeds?edit=${id}`, h.bob)).status, 404);
    assert.equal((await h.get(`/home?personal=${id}`, h.bob)).status, 404);
    assert.equal((await h.get(`/local-quiet?feed=${key}`, h.bob)).status, 404);
    assert.equal((await h.postForm("/local-quiet", {csrf:h.bob.csrf,feed:key,uri:ROOT,action:"restore",root:ROOT}, h.bob)).status, 404);
    assert.equal((await h.postForm("/feeds", {csrf:h.bob.csrf,id,action:"delete"}, h.bob)).status, 404);
    assert.deepEqual(h.localQuiet.list(ALICE,key), [ROOT]);
    assert.ok(h.personalFeeds.get(ALICE,id));
    const deleted = await h.postForm("/feeds", {csrf:h.alice.csrf,id,action:"delete"});
    assert.equal(deleted.status, 303);assert.equal(h.personalFeeds.get(ALICE,id), undefined);
    assert.deepEqual(h.localQuiet.list(ALICE,key), []);
    assert.equal((await h.get(`/home?personal=${id}`)).status, 404);
  } finally {await h.close();}
});

test("pause after awaited policy read refuses save; paused deletion retains definition and quiet", async () => {
  const h = await harness();
  try {
    h.calls.beforeBlocks = async () => {await writeFile(h.config.sitePausePath!, "paused\n");};
    assert.equal((await h.save()).status, 503);assert.equal(h.personalFeeds.list(ALICE).length, 0);
    h.calls.beforeBlocks = null;await writeFile(h.config.sitePausePath!, "open\n");
    const id = h.idFrom(await h.save());const key = `personal:${id}`;h.localQuiet.set(ALICE,key,ROOT);
    await writeFile(h.config.sitePausePath!, "paused\n");
    assert.equal((await h.postForm("/feeds", {csrf:h.alice.csrf,id,action:"delete"})).status, 503);
    assert.ok(h.personalFeeds.get(ALICE,id));assert.deepEqual(h.localQuiet.list(ALICE,key), [ROOT]);
  } finally {await h.close();}
});

test("an edited definition invalidates an earlier continuation before policy or timeline reads", async () => {
  const h = await harness();
  try {
    const id = h.idFrom(await h.save());
    const first = await h.get(`/home?personal=${id}`);assert.equal(first.status, 200);
    const firstHtml = await first.text();
    const continuation = firstHtml.match(/href="(\/home\?personal=[^"]+)"[^>]*>Continue reading/);
    assert.ok(continuation, "the first page must expose a revision-bound continuation");
    const changed = await h.save(h.alice, {id,name:"Changed definition"});assert.equal(changed.status,303);
    const blocksBefore = h.calls.blocks.length, timelineBefore = h.calls.timelines;
    const stale = await h.get(continuation[1]!.replaceAll("&amp;","&"));
    assert.equal(stale.status,409);assert.equal(h.calls.blocks.length,blocksBefore);
    assert.equal(h.calls.timelines,timelineBefore);
  } finally {await h.close();}
});

test("home states what Phlogiston received and did not show, by who decided", async () => {
  const h = await harness();
  try {
    const id = h.idFrom(await h.save());
    h.localQuiet.set(ALICE, `personal:${id}`, `at://${BOB}/app.bsky.feed.post/root`);
    const personal = await (await h.get(`/home?personal=${id}`)).text();
    assert.match(personal, /Showing 1 of the 3 posts received for this page\./);
    assert.match(personal, /1 hidden by your settings\./);
    assert.match(personal, /1 excluded by blocks from @curator\.test, which you chose to apply\./);
    assert.match(personal, /<li data-cause="local-quiet" data-decided-by="viewer">1 /);
    assert.doesNotMatch(personal, /Excluded fixture post|Other fixture post/);
    assert.match(personal, /1 received item excluded by these blocks on this page/);
    const following = await (await h.get("/home")).text();
    assert.doesNotMatch(following, /class="attention-summary"/);
    assert.match(following, /Phlogiston does not rank these posts and cannot say why Bluesky ordered them/);
    h.calls.excludedDids = [];
    h.localQuiet.set(ALICE, `personal:${id}`, `at://${ALICE}/app.bsky.feed.post/root`);
    h.localQuiet.set(ALICE, `personal:${id}`, `at://${BLOCKED}/app.bsky.feed.post/root`);
    const empty = await (await h.get(`/home?personal=${id}`)).text();
    assert.match(empty, /<p class="feed-empty">No posts to show on this page\.<\/p>/);
  } finally {await h.close();}
});
