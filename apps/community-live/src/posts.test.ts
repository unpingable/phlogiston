import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import test from "node:test";

import { AppViewPostDirectory, displayPostText, MAX_POST_TEXT_LENGTH, PostCache, type PostDirectory } from "./posts.js";

type StubResponse = { status?: number; body?: unknown; raw?: string } | "hang";

interface AppViewStub {
  url: string;
  requests: string[][];
  paths: string[];
  close(): Promise<void>;
}

async function appViewStub(respond: (uris: string[]) => StubResponse): Promise<AppViewStub> {
  const requests: string[][] = [];
  const paths: string[] = [];
  const server: Server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://stub.invalid");
    paths.push(url.pathname);
    const uris = url.searchParams.getAll("uris");
    requests.push(uris);
    const reply = respond(uris);
    if (reply === "hang") return;
    response.statusCode = reply.status ?? 200;
    response.setHeader("Content-Type", "application/json");
    response.end(reply.raw ?? JSON.stringify(reply.body ?? {}));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    requests,
    paths,
    close: () => new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

function directory(
  url: string,
  now: () => number = () => Date.now(),
  options: { timeoutMs?: number; maxResponseBytes?: number; maxBatchSize?: number } = {},
): PostDirectory {
  return new AppViewPostDirectory(url, new PostCache(1_000, 10 * 60 * 1_000, 60 * 1_000, now), options);
}

const URIS = Array.from({ length: 26 }, (_, index) => `at://did:plc:user${index}/app.bsky.feed.post/p${index}`);
const view = (uri: string, text: unknown = `text of ${uri}`, cid: unknown = `cid-${uri.split("/").at(-1)}`) => ({
  uri,
  cid,
  author: { did: uri.split("/")[2] },
  record: { $type: "app.bsky.feed.post", text, createdAt: "2026-09-24T00:00:00.000Z" },
});

test("post lookup calls getPosts in batches of at most 25 URIs", async () => {
  const stub = await appViewStub((uris) => ({ body: { posts: uris.map((uri) => view(uri)) } }));
  try {
    const posts = await directory(stub.url, () => Date.now(), { maxBatchSize: 500 }).lookup(URIS);
    assert.deepEqual(stub.paths, ["/xrpc/app.bsky.feed.getPosts", "/xrpc/app.bsky.feed.getPosts"]);
    assert.equal(stub.requests[0]?.length, 25);
    assert.equal(stub.requests[1]?.length, 1);
    assert.equal(posts.size, 26);
    assert.equal(posts.get(URIS[3] as string)?.cid, "cid-p3");
    assert.equal(posts.get(URIS[3] as string)?.text, `text of ${URIS[3]}`);
  } finally {
    await stub.close();
  }
});

test("unrequested, malformed, and CID-less post views are dropped", async () => {
  const stub = await appViewStub(() => ({
    body: {
      posts: [
        view(URIS[0] as string),
        view("at://did:plc:intruder/app.bsky.feed.post/x"),
        view(URIS[1] as string, 42),
        view(URIS[2] as string, "fine", ""),
        { uri: URIS[3], cid: "c", record: "not a record" },
        "garbage",
        null,
      ],
    },
  }));
  try {
    const posts = await directory(stub.url).lookup(URIS.slice(0, 4));
    assert.deepEqual([...posts.keys()], [URIS[0]]);
  } finally {
    await stub.close();
  }
});

test("hostile post text is stripped of control characters and bounded", () => {
  assert.equal(displayPostText("a\u0000b\u0007c\u001bd\u007fe\u0085f‮g⁦h"), "abcdefgh");
  assert.equal(displayPostText("line one\nline\ttwo"), "line one\nline\ttwo");
  assert.equal(displayPostText("<script>alert(1)</script>"), "<script>alert(1)</script>");
  const long = displayPostText("A".repeat(10_000));
  assert.equal(long.length, MAX_POST_TEXT_LENGTH + 1);
  assert.ok(long.endsWith("…"));
});

test("post failures, timeouts, and oversized bodies resolve to absence and are negatively cached", async () => {
  let now = 1_000_000;
  const failing = await appViewStub(() => ({ status: 500, body: {} }));
  const hanging = await appViewStub(() => "hang");
  const oversized = await appViewStub((uris) => ({ body: { posts: uris.map((uri) => view(uri)), padding: "x".repeat(4096) } }));
  try {
    const posts = directory(failing.url, () => now);
    assert.equal((await posts.lookup([URIS[0] as string])).size, 0);
    assert.equal((await posts.lookup([URIS[0] as string])).size, 0);
    assert.equal(failing.requests.length, 1);
    now += 61_000;
    await posts.lookup([URIS[0] as string]);
    assert.equal(failing.requests.length, 2);
    assert.equal((await directory(hanging.url, () => Date.now(), { timeoutMs: 50 }).lookup([URIS[0] as string])).size, 0);
    assert.equal((await directory(oversized.url, () => Date.now(), { maxResponseBytes: 1024 }).lookup([URIS[0] as string])).size, 0);
  } finally {
    await failing.close();
    await hanging.close();
    await oversized.close();
  }
});

test("hydrated posts are cached for the hit TTL and the cache is bounded", async () => {
  let now = 5_000_000;
  const stub = await appViewStub((uris) => ({ body: { posts: uris.map((uri) => view(uri)) } }));
  try {
    const posts = directory(stub.url, () => now);
    await posts.lookup([URIS[0] as string]);
    await posts.lookup([URIS[0] as string]);
    assert.equal(stub.requests.length, 1);
    now += 600_001;
    await posts.lookup([URIS[0] as string]);
    assert.equal(stub.requests.length, 2);
  } finally {
    await stub.close();
  }
  const cache = new PostCache(2, 1_000, 1_000, () => 0);
  cache.putMiss("a");
  cache.putMiss("b");
  cache.putMiss("c");
  assert.equal(cache.size, 2);
  assert.equal(cache.fresh("a"), undefined);
});

test("invalid requested post URIs never reach the network", async () => {
  const stub = await appViewStub(() => ({ body: { posts: [] } }));
  try {
    const posts = await directory(stub.url).lookup(["", "at://did:plc:a/app.phlogiston.community.submit/x", "https://evil.test/x"]);
    assert.equal(posts.size, 0);
    assert.equal(stub.requests.length, 0);
  } finally {
    await stub.close();
  }
});
