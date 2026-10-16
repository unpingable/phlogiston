import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { OAuthSession } from "@atproto/oauth-client-node";
import type { AppBskyFeedDefs, BskyPreferences } from "@atproto/api";
import { loadConfig } from "./config.js";
import { createHandler, type Dependencies } from "./server.js";
import { Reader, type ReaderTransport, type ThreadResult } from "./reader.js";
import { WebSessionStore } from "./storage.js";
import { P0_SCOPE, READER_SCOPE } from "./p0.js";

const ALICE = "did:plc:alice", COMMUNITY = "did:plc:community";
const ROOT = `at://${ALICE}/app.bsky.feed.post/root`, ROOT_CID = "bafyreiadmittedrootcid";
const RKEY = "admit-one";
const CREATED = "2026-10-12T00:00:00Z";

function post(uri: string, text: string, cid = ROOT_CID, reply?: string): AppBskyFeedDefs.PostView {
  return {uri, cid, author: {did: ALICE, handle: "alice.test"}, indexedAt: CREATED,
    record: {$type: "app.bsky.feed.post", text, createdAt: CREATED, ...(reply ? {reply: {root: {uri: ROOT, cid: ROOT_CID}, parent: {uri: reply, cid: ROOT_CID}}} : {})}};
}
function discussion(status = "visible") {
  return {discussion: {uri: `at://${COMMUNITY}/app.phlogiston.community.admission/${RKEY}`, cid: "bafyadmission"},
    root: {uri: ROOT, cid: ROOT_CID}, post: {text: "Admitted text https://example.test/page", createdAt: CREATED},
    authorDid: ALICE, admittedAt: CREATED, status, closed: false};
}

async function harness(scope = READER_SCOPE, did = ALICE) {
  const directory = await mkdtemp(join(tmpdir(), "phlo-community-conversation-"));
  const config = loadConfig({COMMUNITY_PROFILE: "p0", COMMUNITY_READER_ENABLED: "true",
    COMMUNITY_PUBLIC_URL: "http://127.0.0.1:3210", COMMUNITY_DID: COMMUNITY,
    COMMUNITY_NAME: "The Cabinet", COMMUNITY_PURPOSE: "Fixture collection",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator", COMMUNITY_RUNTIME_DIR: directory,
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080", COMMUNITY_AUTHORITY_SOCKET: join(directory, "socket"),
    COMMUNITY_SITE_PAUSE_PATH: join(directory, "site"), COMMUNITY_ADMISSION_PAUSE_PATH: join(directory, "admission")});
  await writeFile(config.sitePausePath!, "open\n", {mode: 0o600});
  const sessions = new WebSessionStore(join(directory, "sessions"));
  const signed = await sessions.issue(did, new Date(), scope);
  const state = {status: "visible", threads: 0, publicReads: 0, observerDown: false,
    thread: (): ThreadResult | Promise<ThreadResult> => ({$type: "app.bsky.feed.defs#threadViewPost", post: post(ROOT, "Live root text https://example.test/page"),
      replies: [{$type: "app.bsky.feed.defs#threadViewPost", post: post(`at://${ALICE}/app.bsky.feed.post/reply`, "A PUBLIC REPLY", "bafyreply", ROOT)}]})};
  const transport: ReaderTransport = {
    preferences: async () => ({feedViewPrefs: {home: {hideReplies: false, hideRepliesByUnfollowed: false, hideRepliesByLikeCount: 0, hideReposts: false, hideQuotePosts: false}},
      moderationPrefs: {adultContentEnabled: false, labels: {}, labelers: [], mutedWords: [], hiddenPosts: []}}) as unknown as BskyPreferences,
    labelDefinitions: async () => ({}), timeline: async () => ({feed: []}),
    postThread: async uri => {state.threads++;return uri === ROOT ? state.thread() : {$type: "app.bsky.feed.defs#threadViewPost", post: post(uri, "A PUBLIC REPLY", "bafyreply", ROOT)};},
    muteThread: async () => {}, unmuteThread: async () => {},
  };
  const oauthSession = (did: string) => ({did, getTokenInfo: async () => ({sub: did,
    aud: "https://phellinus.us-west.host.bsky.network", iss: "https://bsky.social", scope}), signOut: async () => {}}) as unknown as OAuthSession;
  const projection = {
    get: async (path: string) => {
      if (state.observerDown) throw new Error("observer down");
      if (path.endsWith(`/discussions/${RKEY}`)) return {discussion: discussion(state.status), replies: []};
      throw Object.assign(new Error("not found"), {status: 404});
    },
    getCapped: async () => {if (state.observerDown) throw new Error("observer down");return {discussions: [discussion(state.status)]};},
  };
  const publicThreads = {read: async (uri: string) => {state.publicReads++;if (uri !== ROOT) throw new Error("only the admitted root");return state.thread();}};
  const deps = {config, webSessions: sessions, projection, publicThreads, profiles: {lookup: async () => new Map()},
    reader: (s: OAuthSession) => new Reader(s, transport), labels: {lookup: async () => null},
    oauth: {authorize: async () => new URL("https://bsky.social/auth"), restore: async (did: string) => oauthSession(did),
      callback: async () => ({session: oauthSession(ALICE)})}} as unknown as Dependencies;
  const server = createServer(createHandler(deps));
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const get = (path: string, signedIn = true) => fetch(origin + path, {redirect: "manual", headers: signedIn ? {Cookie: `community_session=${signed.token}`} : {}});
  return {state, get, close: async () => {await new Promise<void>(r => server.close(() => r()));await rm(directory, {recursive: true, force: true});}};
}

const section = (body: string) => body.slice(body.indexOf('<section class="community-conversation"'));

test("an admitted post's page shows its public conversation as public replies, not community material", async () => {
  const h = await harness();
  try {
    const body = await (await h.get(`/d/${RKEY}`)).text();
    assert.match(body, /<h2 id="public-conversation">Public conversation<\/h2>/);
    assert.match(body, /Replies posted publicly on Bluesky\. The Cabinet has not reviewed or admitted them; your viewing settings apply\./);
    assert.match(section(body), /A PUBLIC REPLY/);
    assert.doesNotMatch(section(body), /class="layer"/);
    assert.match(body, /Live root text/);
    assert.match(body, /Why is this here\?/);
  } finally {await h.close();}
});

test("a removed admission keeps its tombstone and pulls no public conversation into the room", async () => {
  const h = await harness();
  try {
    h.state.status = "removed";
    const body = await (await h.get(`/d/${RKEY}`)).text();
    assert.match(body, /removed from this community’s view/);
    assert.doesNotMatch(body, /Public conversation|A PUBLIC REPLY/);
    assert.equal(h.state.threads, 0);
  } finally {await h.close();}
});

test("a public post that changed since admission shows the admitted text and withholds the newer conversation", async () => {
  const h = await harness();
  try {
    h.state.thread = () => ({$type: "app.bsky.feed.defs#threadViewPost", post: post(ROOT, "REPLACED TEXT", "bafyreinewer"),
      replies: [{$type: "app.bsky.feed.defs#threadViewPost", post: post(`at://${ALICE}/app.bsky.feed.post/reply`, "A PUBLIC REPLY", "bafyreply", ROOT)}]});
    const body = await (await h.get(`/d/${RKEY}`)).text();
    assert.match(body, /Admitted text <a href="https:\/\/example\.test\/page" rel="noreferrer noopener">/);
    assert.doesNotMatch(body, /REPLACED TEXT|A PUBLIC REPLY/);
    assert.match(body, /has changed since The Cabinet admitted it/);
    assert.match(body, /href="\/thread\?uri=/);
  } finally {await h.close();}
});

test("an unreadable conversation is an observation limit and the admitted post still shows", async () => {
  const h = await harness();
  try {
    h.state.thread = () => {throw new Error("appview down");};
    const body = await (await h.get(`/d/${RKEY}`)).text();
    assert.match(body, /Admitted text/);
    assert.match(section(body), /data-observation="not-established"/);
    assert.match(section(body), /could not read the public conversation/);
  } finally {await h.close();}
});

test("no public replies is said plainly", async () => {
  const h = await harness();
  try {
    h.state.thread = () => ({$type: "app.bsky.feed.defs#threadViewPost", post: post(ROOT, "Live root text")});
    assert.match(section(await (await h.get(`/d/${RKEY}`)).text()), /Bluesky returned no public replies\./);
  } finally {await h.close();}
});

test("signed-out readers see the exact admitted post's public replies under default moderation", async () => {
  const h = await harness();
  try {
    const body = section(await (await h.get(`/d/${RKEY}`, false)).text());
    assert.match(body, /A PUBLIC REPLY/);
    assert.match(body, /The Cabinet has not reviewed or admitted them\. Bluesky’s default moderation applies; <a href="\/signin\?return=%2Fd%2Fadmit-one">sign in<\/a> to use your own settings\./);
    assert.doesNotMatch(body, /class="layer"|href="\/thread|href="\/context/);
    assert.equal(h.state.threads, 0);
    assert.equal(h.state.publicReads, 1);
  } finally {await h.close();}
});

test("signed-out readers get the same changed, unreadable and removed outcomes", async () => {
  const h = await harness();
  try {
    h.state.thread = () => ({$type: "app.bsky.feed.defs#threadViewPost", post: post(ROOT, "REPLACED TEXT", "bafyreinewer")});
    let body = await (await h.get(`/d/${RKEY}`, false)).text();
    assert.match(body, /Admitted text/);assert.match(body, /has changed since The Cabinet admitted it/);assert.doesNotMatch(body, /REPLACED TEXT|href="\/thread/);
    h.state.thread = () => {throw new Error("public appview down");};
    body = section(await (await h.get(`/d/${RKEY}`, false)).text());
    assert.match(body, /data-observation="not-established"/);assert.match(body, /could not read the public conversation/);
    h.state.status = "removed";const before = h.state.publicReads;
    body = await (await h.get(`/d/${RKEY}`, false)).text();
    assert.doesNotMatch(body, /Public conversation/);assert.equal(h.state.publicReads, before);
  } finally {await h.close();}
});

test("a submission-only grant is offered the reader connection instead of a conversation", async () => {
  const h = await harness(P0_SCOPE);
  try {
    const body = section(await (await h.get(`/d/${RKEY}`)).text());
    assert.match(body, /Connect my feed/);
    assert.equal(h.state.threads, 0);
  } finally {await h.close();}
});

test("a conversation that starts from an admitted post links back into the community", async () => {
  const h = await harness();
  try {
    const root = await (await h.get(`/thread?uri=${encodeURIComponent(ROOT)}`)).text();
    assert.match(root, /This post is in The Cabinet\. <a href="\/d\/admit-one">Open it there<\/a>/);
    const reply = await (await h.get(`/thread?uri=${encodeURIComponent(`at://${ALICE}/app.bsky.feed.post/reply`)}`)).text();
    assert.match(reply, /This conversation starts from a post in The Cabinet\. <a href="\/d\/admit-one">Open it there<\/a>/);
    h.state.observerDown = true;
    const down = await h.get(`/thread?uri=${encodeURIComponent(ROOT)}`);
    assert.equal(down.status, 200);
    assert.doesNotMatch(await down.text(), /in The Cabinet/);
  } finally {await h.close();}
});

test("community cards open the post's community page by name", async () => {
  const h = await harness();
  try {
    const body = await (await h.get("/community")).text();
    assert.match(body, /<a href="\/d\/admit-one">Open in The Cabinet<\/a>/);
    assert.doesNotMatch(body, />Community admission</);
  } finally {await h.close();}
});

test("the moderator's removal form is folded away from the reading path", async () => {
  const reader = await harness();
  try { assert.doesNotMatch(await (await reader.get(`/d/${RKEY}`)).text(), /value="remove-root"|Moderator actions/); } finally {await reader.close();}
  const h = await harness(READER_SCOPE, "did:plc:moderator");
  try {
    const body = await (await h.get(`/d/${RKEY}`)).text();
    assert.match(body, /<details class="moderator-actions"><summary>Moderator actions<\/summary><form method="post" action="\/moderate">[^]*?value="remove-root"[^]*?<\/form><\/details>/);
    assert.ok(body.indexOf("Moderator actions") > body.indexOf('<section class="community-conversation"'));
  } finally {await h.close();}
});
