import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import test from "node:test";

import {
  AppViewProfileDirectory,
  ProfileCache,
  validAvatarUrl,
  type ProfileDirectory,
} from "./profiles.js";

type StubResponse = { status?: number; body?: unknown; raw?: string } | "hang";

interface AppViewStub {
  url: string;
  requests: string[][];
  close(): Promise<void>;
}

async function appViewStub(respond: (actors: string[]) => StubResponse): Promise<AppViewStub> {
  const requests: string[][] = [];
  const server: Server = createServer((request, response) => {
    const actors = new URL(request.url ?? "/", "http://stub.invalid").searchParams.getAll("actors");
    requests.push(actors);
    const reply = respond(actors);
    if (reply === "hang") return;
    response.statusCode = reply.status ?? 200;
    response.setHeader("Content-Type", "application/json");
    response.end(reply.raw ?? JSON.stringify(reply.body ?? {}));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    requests,
    close: () => new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

function directory(
  url: string,
  now: () => number = () => Date.now(),
  options: { timeoutMs?: number; maxResponseBytes?: number } = {},
): ProfileDirectory {
  return new AppViewProfileDirectory(
    url,
    new ProfileCache(1_000, 10 * 60 * 1_000, 60 * 1_000, now),
    options,
  );
}

const DIDS = Array.from({ length: 26 }, (_, index) => `did:plc:user${index}`);

test("lookup batches at 25 actors per request and hydrates every requested DID", async () => {
  const stub = await appViewStub((actors) => ({
    body: { profiles: actors.map((did) => ({ did, handle: `${did.replace("did:plc:", "")}.example.test` })) },
  }));
  try {
    const profiles = await directory(stub.url).lookup(DIDS);
    assert.equal(stub.requests.length, 2);
    assert.equal(stub.requests[0]?.length, 25);
    assert.equal(stub.requests[1]?.length, 1);
    assert.equal(profiles.size, 26);
    assert.equal(profiles.get("did:plc:user3")?.handle, "user3.example.test");
  } finally {
    await stub.close();
  }
});

test("unrequested, non-DID, and malformed response entries are dropped", async () => {
  const stub = await appViewStub(() => ({
    body: {
      profiles: [
        { did: "did:plc:user0", handle: "first.example.test" },
        { did: "did:plc:intruder", handle: "intruder.example.test" },
        { did: "not a did" },
        { did: 42 },
        "garbage",
        null,
      ],
    },
  }));
  try {
    const profiles = await directory(stub.url).lookup(["did:plc:user0", "did:plc:user1"]);
    assert.deepEqual([...profiles.keys()], ["did:plc:user0"]);
  } finally {
    await stub.close();
  }
});

test("malformed profile fields degrade field-by-field, never to markup", async () => {
  const longName = "x".repeat(300);
  const stub = await appViewStub(() => ({
    body: {
      profiles: [
        { did: "did:plc:user0", handle: "no spaces or tld", displayName: "Readable Name" },
        { did: "did:plc:user1", handle: "valid.example.test", displayName: longName },
        { did: "did:plc:user2", handle: "localhost" },
        { did: "did:plc:user3", displayName: "<script>alert(1)</script>" },
      ],
    },
  }));
  try {
    const profiles = await directory(stub.url).lookup(DIDS.slice(0, 4));
    assert.equal(profiles.get("did:plc:user0")?.handle, undefined);
    assert.equal(profiles.get("did:plc:user0")?.displayName, "Readable Name");
    assert.equal(profiles.get("did:plc:user1")?.handle, "valid.example.test");
    assert.equal(profiles.get("did:plc:user1")?.displayName, undefined);
    assert.equal(profiles.get("did:plc:user2")?.handle, undefined);
    assert.equal(profiles.get("did:plc:user3")?.displayName, "<script>alert(1)</script>");
  } finally {
    await stub.close();
  }
});

test("request failures resolve to absence and are negatively cached for the miss TTL", async () => {
  let now = 1_000_000;
  const stub = await appViewStub(() => ({ status: 500, body: { error: "down" } }));
  try {
    const profiles = directory(stub.url, () => now);
    assert.equal((await profiles.lookup(["did:plc:user0"])).size, 0);
    assert.equal(stub.requests.length, 1);
    assert.equal((await profiles.lookup(["did:plc:user0"])).size, 0);
    assert.equal(stub.requests.length, 1);
    now += 61_000;
    await profiles.lookup(["did:plc:user0"]);
    assert.equal(stub.requests.length, 2);
  } finally {
    await stub.close();
  }
});

test("profiles missing from a successful response are cached as misses", async () => {
  const stub = await appViewStub(() => ({ body: { profiles: [] } }));
  try {
    const profiles = directory(stub.url);
    assert.equal((await profiles.lookup(["did:plc:user0"])).size, 0);
    assert.equal((await profiles.lookup(["did:plc:user0"])).size, 0);
    assert.equal(stub.requests.length, 1);
  } finally {
    await stub.close();
  }
});

test("timeouts resolve to absence instead of throwing into render paths", async () => {
  const stub = await appViewStub(() => "hang");
  try {
    const profiles = directory(stub.url, () => Date.now(), { timeoutMs: 50 });
    assert.equal((await profiles.lookup(["did:plc:user0"])).size, 0);
    // Under load the stub may not have logged the request before the client
    // gave up; what matters is that the timeout is negatively cached, so the
    // second lookup adds no request.
    const requestsAfterTimeout = stub.requests.length;
    assert.ok(requestsAfterTimeout <= 1, `requests: ${requestsAfterTimeout}`);
    assert.equal((await profiles.lookup(["did:plc:user0"])).size, 0);
    assert.equal(stub.requests.length, requestsAfterTimeout);
  } finally {
    await stub.close();
  }
});

test("oversized hydration responses are refused whole", async () => {
  const stub = await appViewStub((actors) => ({
    body: { profiles: actors.map((did) => ({ did, handle: "ok.example.test" })), padding: "x".repeat(4096) },
  }));
  try {
    const profiles = directory(stub.url, () => Date.now(), { maxResponseBytes: 1024 });
    assert.equal((await profiles.lookup(["did:plc:user0"])).size, 0);
    assert.equal(stub.requests.length, 1);
  } finally {
    await stub.close();
  }
});

test("successful profiles are cached positively for the hit TTL", async () => {
  let now = 5_000_000;
  const stub = await appViewStub((actors) => ({
    body: { profiles: actors.map((did) => ({ did, handle: "cached.example.test" })) },
  }));
  try {
    const profiles = directory(stub.url, () => now);
    assert.equal((await profiles.lookup(["did:plc:user0"])).get("did:plc:user0")?.handle, "cached.example.test");
    await profiles.lookup(["did:plc:user0"]);
    assert.equal(stub.requests.length, 1);
    now += 600_001;
    await profiles.lookup(["did:plc:user0"]);
    assert.equal(stub.requests.length, 2);
  } finally {
    await stub.close();
  }
});

test("the cache is bounded and evicts the least-recently-used entry", () => {
  let now = 0;
  const cache = new ProfileCache(3, 1_000, 1_000, () => now);
  const profile = (did: string) => ({ did });
  cache.putHit("did:plc:a", profile("did:plc:a"));
  cache.putHit("did:plc:b", profile("did:plc:b"));
  cache.putHit("did:plc:c", profile("did:plc:c"));
  assert.equal(cache.fresh("did:plc:a")?.kind, "hit");
  cache.putHit("did:plc:d", profile("did:plc:d"));
  assert.equal(cache.size, 3);
  assert.equal(cache.fresh("did:plc:b"), undefined);
  assert.equal(cache.fresh("did:plc:a")?.kind, "hit");
  assert.equal(cache.fresh("did:plc:d")?.kind, "hit");
});

test("avatar URLs are accepted only as credential-free https on the pinned CDN host", () => {
  assert.equal(validAvatarUrl("https://cdn.bsky.app/img/avatar/plain/did:plc:a/bafy@jpeg"), true);
  assert.equal(validAvatarUrl("http://cdn.bsky.app/img/x"), false);
  assert.equal(validAvatarUrl("https://cdn.bsky.app.evil.test/img/x"), false);
  assert.equal(validAvatarUrl("https://user:pass@cdn.bsky.app/img/x"), false);
  assert.equal(validAvatarUrl("//cdn.bsky.app/img/x"), false);
  assert.equal(validAvatarUrl("https://bsky.app/img/x"), false);
  assert.equal(validAvatarUrl(42), false);
});

test("invalid avatar values are stripped during hydration while the profile survives", async () => {
  const stub = await appViewStub(() => ({
    body: {
      profiles: [
        { did: "did:plc:user0", handle: "ok.example.test", avatar: "https://tracking.invalid.test/pixel.png" },
        { did: "did:plc:user1", handle: "cdn.example.test", avatar: "https://cdn.bsky.app/img/avatar/plain/did:plc:user1/bafy@jpeg" },
      ],
    },
  }));
  try {
    const profiles = await directory(stub.url).lookup(["did:plc:user0", "did:plc:user1"]);
    assert.equal(profiles.get("did:plc:user0")?.avatar, undefined);
    assert.equal(profiles.get("did:plc:user0")?.handle, "ok.example.test");
    assert.match(profiles.get("did:plc:user1")?.avatar ?? "", /^https:\/\/cdn\.bsky\.app\//);
  } finally {
    await stub.close();
  }
});

test("the AppView's handle.invalid placeholder is no handle at all", async () => {
  const stub = await appViewStub(() => ({
    body: {
      profiles: [
        { did: "did:plc:user0", handle: "handle.invalid", displayName: "Still Named" },
        { did: "did:plc:user1", handle: "Handle.Invalid" },
        { did: "did:plc:user2", handle: "handle.invalid.example.test" },
      ],
    },
  }));
  try {
    const profiles = await directory(stub.url).lookup(["did:plc:user0", "did:plc:user1", "did:plc:user2"]);
    assert.equal(profiles.get("did:plc:user0")?.handle, undefined);
    assert.equal(profiles.get("did:plc:user0")?.displayName, "Still Named");
    assert.equal(profiles.get("did:plc:user1")?.handle, undefined);
    assert.equal(profiles.get("did:plc:user2")?.handle, "handle.invalid.example.test");
  } finally {
    await stub.close();
  }
});

test("invalid requested DIDs never reach the network", async () => {
  const stub = await appViewStub(() => ({ body: { profiles: [] } }));
  try {
    const profiles = await directory(stub.url).lookup(["not a did", "", "https://evil.test/x"]);
    assert.equal(profiles.size, 0);
    assert.equal(stub.requests.length, 0);
  } finally {
    await stub.close();
  }
});
