import assert from "node:assert/strict";
import test from "node:test";
import type { AppBskyFeedDefs } from "@atproto/api";
import { PublicThreadReader, SignedOutViewer } from "./public-thread.js";

const ROOT = "at://did:plc:alice/app.bsky.feed.post/root";
const ORIGIN = "https://public.example.test";
const thread = {thread: {$type: "app.bsky.feed.defs#threadViewPost", post: {uri: ROOT, cid: "bafyroot", author: {did: "did:plc:alice", handle: "alice.test"},
  record: {$type: "app.bsky.feed.post", text: "Root", createdAt: "2026-10-12T00:00:00Z"}, indexedAt: "2026-10-12T00:00:00Z"}}};
function fake(body: unknown = thread, init: ResponseInit = {status: 200}) {
  const calls: {url: string; headers: Headers}[] = [];
  const fetchFn = (async (url: string | URL, options?: RequestInit) => {
    calls.push({url: String(url), headers: new Headers(options?.headers)});
    return new Response(typeof body === "string" ? body : JSON.stringify(body), init);
  }) as typeof fetch;
  return {calls, fetchFn};
}

test("reads exactly one bounded public thread for the requested post, without credentials", async () => {
  const f = fake();
  const result = await new PublicThreadReader(ORIGIN, {fetchFn: f.fetchFn}).read(ROOT);
  assert.equal((result as AppBskyFeedDefs.ThreadViewPost).post.uri, ROOT);
  assert.equal(f.calls.length, 1);
  const url = new URL(f.calls[0]!.url);
  assert.equal(url.origin + url.pathname, `${ORIGIN}/xrpc/app.bsky.feed.getPostThread`);
  assert.deepEqual([...url.searchParams], [["uri", ROOT], ["depth", "2"], ["parentHeight", "0"]]);
  assert.equal(f.calls[0]!.headers.get("authorization"), null);
  assert.equal(f.calls[0]!.headers.get("atproto-accept-labelers"), "did:plc:ar7c4by46qjdydhdevvrndac");
});

test("refuses anything but a post URI and never proxies it", async () => {
  const f = fake();
  const reader = new PublicThreadReader(ORIGIN, {fetchFn: f.fetchFn});
  for (const bad of ["https://evil.test/x", "at://did:plc:alice/app.bsky.graph.block/x", `${ROOT}&depth=1000`]) await assert.rejects(reader.read(bad));
  assert.equal(f.calls.length, 0);
});

test("an error status, oversized body or malformed thread is an error, not an empty conversation", async () => {
  await assert.rejects(new PublicThreadReader(ORIGIN, {fetchFn: fake({}, {status: 502}).fetchFn}).read(ROOT));
  await assert.rejects(new PublicThreadReader(ORIGIN, {fetchFn: fake("x".repeat(64), {status: 200}).fetchFn, maxBytes: 32}).read(ROOT));
  await assert.rejects(new PublicThreadReader(ORIGIN, {fetchFn: fake({nothread: true}).fetchFn}).read(ROOT));
});

test("repeat views share one bounded, short-lived cache entry per post", async () => {
  const f = fake();
  let now = 0;
  const reader = new PublicThreadReader(ORIGIN, {fetchFn: f.fetchFn, ttlMs: 30_000, maxEntries: 2, now: () => now});
  await reader.read(ROOT);await reader.read(ROOT);
  assert.equal(f.calls.length, 1);
  now = 30_001;await reader.read(ROOT);
  assert.equal(f.calls.length, 2);
  await reader.read(`${ROOT}2`);await reader.read(`${ROOT}3`);await reader.read(ROOT);
  assert.equal(f.calls.length, 5);
  assert.ok(reader.size() <= 2);
});

test("signed-out moderation honours an author's request not to be shown to signed-out readers", () => {
  const viewer = new SignedOutViewer();
  const post = (labels: NonNullable<AppBskyFeedDefs.PostView["author"]["labels"]>) => ({uri: ROOT, cid: "bafyroot", indexedAt: "2026-10-12T00:00:00Z",
    author: {did: "did:plc:alice", handle: "alice.test", labels}, record: {$type: "app.bsky.feed.post", text: "Hi", createdAt: "2026-10-12T00:00:00Z"}});
  assert.equal(viewer.decision(post([]), "contentList").filter, false);
  const optedOut = viewer.decision(post([{src: "did:plc:alice", uri: "at://did:plc:alice/app.bsky.actor.profile/self", val: "!no-unauthenticated", cts: "2026-10-12T00:00:00Z"}]), "contentView");
  assert.ok(optedOut.filter || optedOut.blur || optedOut.noOverride);
});
