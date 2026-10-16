import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { OAuthSession } from "@atproto/oauth-client-node";
import type { AppConfig } from "./config.js";
import { createHandler, type Dependencies } from "./server.js";
import { WebSessionStore, ContributionPlanStore } from "./storage.js";
import { READER_SCOPE } from "./p0.js";

const DID = "did:plc:frontdoorfixture";
const POST = "at://did:plc:source/app.bsky.feed.post/example";
async function fixture(readerEnabled = true) {
  const root = await mkdtemp(join(tmpdir(), "frontdoor-test-"));
  let state = "";
  let callbackState: string | undefined;
  const config = { publicUrl: "http://127.0.0.1:3210", communityDid: DID, communityName: "The Cabinet", communityPurpose: "Internet curiosities worth preserving", moderatorDid: DID, runtimeDirectory: root, observerUrl: "http://127.0.0.1:1", observerMaxResponseBytes: 65536, discussionsMaxItems: 500, appViewOrigin: "https://api.bsky.app", avatarsEnabled: false, authoritySocket: join(root, "authority.sock"), port: 3210, profile: "p0", readerEnabled } as AppConfig;
  const session = { did: DID, getTokenInfo: async () => ({ sub: DID, iss: "https://bsky.social", aud: "https://phellinus.us-west.host.bsky.network", scope: readerEnabled ? READER_SCOPE : "atproto repo:app.phlogiston.community.submit?action=create" }), signOut: async () => {} } as unknown as OAuthSession;
  const document = { communityDid: DID, discussions: [{ discussion: { uri: `at://${DID}/app.phlogiston.community.admission/card`, cid: "admission-cid" }, root: { uri: POST, cid: "post-cid" }, post: { text: "A real Cabinet projection fixture", createdAt: "2026-10-12T00:00:00Z" }, authorDid: DID, admittedAt: "2026-10-12T00:00:00Z", status: "visible", closed: false }], cursor: null, snapshot: {} };
  const sessions = new WebSessionStore(join(root, "sessions"));
  const deps = { config, webSessions: sessions, plans: new ContributionPlanStore(join(root, "plans")), oauth: { authorize: async (_actor: string, options: { state?: string }) => { state = options.state ?? ""; return new URL("https://auth.fixture.test/authorize"); }, callback: async () => ({ session, state: callbackState ?? state }), restore: async () => session }, projection: { get: async () => document, getCapped: async () => document }, profiles: { lookup: async () => new Map() }, authority: { request: async () => { throw new Error("anonymous dispatch must not occur"); } } } as unknown as Dependencies;
  const server = createServer((req, res) => void createHandler(deps)(req, res));
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { sessions, state: () => state, callbackState: (value: string) => { callbackState = value; }, request: async (path: string, form?: Record<string,string>, cookie?: string) => fetch(origin + path, { redirect: "manual", ...(form ? { method: "POST", body: new URLSearchParams(form), headers: { Origin: config.publicUrl, "Content-Type": "application/x-www-form-urlencoded", ...(cookie ? { Cookie: cookie } : {}) } } : { headers: cookie ? { Cookie: cookie } : {} }) }), close: async () => { await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve())); await rm(root, { recursive: true }); } };
}

test("reader front door centralizes sign-in and retains anonymous Cabinet cards", async () => {
 const f = await fixture(); try {
  const home = await f.request("/"); assert.equal(home.status, 200); const body = await home.text();
  assert.match(body, /Phlogiston/); assert.ok(body.indexOf("A different way to experience Bluesky.") < body.indexOf("A real Cabinet projection fixture")); assert.match(body, /href="\/signin"/); assert.match(body, /A real Cabinet projection fixture/); assert.doesNotMatch(body, /name="handle"/);
  const community = await f.request("/community"); assert.equal(community.status, 200); assert.doesNotMatch(await community.text(), /name="handle"/);
  const signin = await f.request("/signin"); assert.equal(signin.status, 200); const signinBody = await signin.text(); assert.equal(signinBody.match(/name="handle"/g)?.length, 1);
 } finally { await f.close(); }
});

test("anonymous reader documents redirect while JSON and mutations remain unauthorized", async () => {
 const f = await fixture(); try {
  for (const path of ["/home","/feed","/feeds",`/thread?uri=${encodeURIComponent(POST)}`,`/context?uri=${encodeURIComponent(POST)}`,"/attention","/labels","/settings","/mine","/moderation","/operation?id=70033408-4e42-4d25-80cf-bbd19cd5a66b"]) {
   const response = await f.request(path); assert.equal(response.status, 303, path); const target = new URL(response.headers.get("location")!, "http://fixture.test"); assert.equal(target.pathname, "/signin"); assert.equal(target.searchParams.get("return"), path);
  }
  assert.equal((await f.request("/sources")).status, 401);
  for (const path of ["/local-quiet","/quiet","/moderate"]) assert.equal((await f.request(path, { action: "quiet" })).status, 401, path);
 } finally { await f.close(); }
});

 test("normal nonce-bound OAuth returns only to a validated local document", async () => {
 const f = await fixture(); try {
  const destination = `/thread?uri=${encodeURIComponent(POST)}`;
  const login = await f.request("/oauth/login", { handle: "alice.bsky.social", return: destination }); assert.equal(login.status,303);
  assert.equal(new URLSearchParams(f.state()).get("return"), destination);
  const cookie = /community_login=([^;]+)/.exec(login.headers.get("set-cookie") ?? "")![0];
  assert.equal((await f.request("/oauth/callback?code=x")).status,400);
  const callback = await f.request("/oauth/callback?code=x", undefined, cookie); assert.equal(callback.status,303); assert.equal(callback.headers.get("location"),destination); assert.match(callback.headers.get("set-cookie") ?? "", /community_session=/);
  for (const safe of ["/home?personal=70033408-4e42-4d25-80cf-bbd19cd5a66b", "/feeds?edit=70033408-4e42-4d25-80cf-bbd19cd5a66b", "/feed?feed=at%3A%2F%2Fdid%3Aplc%3Agenerator%2Fapp.bsky.feed.generator%2Ftest", "/community#submit"]) {
   const response = await f.request("/oauth/login", { handle: "alice.bsky.social", return: safe });
   assert.equal(new URLSearchParams(f.state()).get("return"), safe);
   const ownCookie = /community_login=([^;]+)/.exec(response.headers.get("set-cookie") ?? "")![0];
   assert.equal((await f.request("/oauth/callback?code=x", undefined, ownCookie)).headers.get("location"), safe);
  }
  for (const bad of ["https://other.test/home", "//other.test/home", "/unknown", "/home#fragment", "/home?return=https://other.test", "/thread?uri=javascript:bad", "/home/../settings", "/home?personal=70033408-4e42-4d25-80cf-bbd19cd5a66b&personal=70033408-4e42-4d25-80cf-bbd19cd5a66b", "/home?cursor=private", "/home?personal=70033408-4e42-4d25-80cf-bbd19cd5a66b&feed=at%3A%2F%2Fdid%3Aplc%3Ax%2Fapp.bsky.feed.generator%2Fy", "/home\\other", "/settings%0A"]) {
   await f.request("/oauth/login", { handle: "alice.bsky.social", return: bad }); assert.equal(new URLSearchParams(f.state()).get("return"), null, bad);
  }
  const finalLogin = await f.request("/oauth/login", {handle: "alice.bsky.social", return: "/labels"});
  const finalCookie = /community_login=([^;]+)/.exec(finalLogin.headers.get("set-cookie") ?? "")![0];
  f.callbackState(new URLSearchParams({nonce: new URLSearchParams(f.state()).get("nonce")!, return: "https://other.test/home"}).toString());
  assert.equal((await f.request("/oauth/callback?code=x", undefined, finalCookie)).headers.get("location"), "/home");
 } finally { await f.close(); }
});

 test("nonreader front door retains its existing form and unauthorized document behavior", async () => {
 const f = await fixture(false); try {
  assert.match(await (await f.request("/")).text(), /name="handle"/);
  assert.equal((await f.request("/mine")).status, 401);
 } finally { await f.close(); }
});
 test("expired reader document session redirects without turning JSON into HTML", async () => {
 const f = await fixture(); try {
  const issued = await f.sessions.issue(DID, new Date("2000-01-01T00:00:00Z"), READER_SCOPE);
  const cookie = `community_session=${issued.token}`;
  const expired = await f.request("/labels", undefined, cookie); assert.equal(expired.status, 303);
  const signin = await f.request(expired.headers.get("location")!, undefined, cookie); assert.equal(signin.status, 200); assert.match(await signin.text(), /name="handle"/);
  assert.equal((await f.request("/sources", undefined, cookie)).status, 401);
  const malformed = await f.request("/thread?uri=invalid");
  assert.equal(new URL(malformed.headers.get("location")!, "http://fixture.test").searchParams.get("return"), "/home");
 } finally { await f.close(); }
});
