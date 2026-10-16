import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import test from "node:test";

import { bskyPostUrl, bskyProfileUrl, escapeHtml, externalHttpsUrl, parsePostReference, PostReferenceError } from "./html.js";
import { HttpError } from "./http-error.js";
import { ObserverClient, ProjectionTooLargeError } from "./observer.js";
import { humanDate, renderIdentity, publicPostLink, postedAt, snippet, whyHere } from "./presentation.js";

const visibleText = (markup: string): string => markup.replace(/<[^>]*>/g, "");
import type { HydratedProfile } from "./profiles.js";

test("escapeHtml neutralizes the five markup-significant characters in one pass", () => {
  assert.equal(escapeHtml(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
  assert.equal(escapeHtml("&lt;script&gt;"), "&amp;lt;script&amp;gt;");
  assert.equal(escapeHtml('<a href="x" onclick=\'y\'>'), "&lt;a href=&quot;x&quot; onclick=&#39;y&#39;&gt;");
});

test("bskyProfileUrl builds only from validated DIDs", () => {
  assert.equal(bskyProfileUrl("did:plc:abc123"), "https://bsky.app/profile/did:plc:abc123");
  assert.equal(bskyProfileUrl("did:web:example.com"), "https://bsky.app/profile/did:web:example.com");
  for (const hostile of [
    "",
    "did:plc:",
    "did:PLC:abc",
    "https://deceptive.invalid.test/did:plc:abc",
    "did:plc:abc/path",
    'did:plc:abc" onclick="alert(1)',
    "did:plc:abc%0d%0aSet-Cookie:%20x" + " ",
    "javascript:alert(1)",
    `@handle.invalid.test`,
    `did:plc:${"a".repeat(600)}`,
  ]) {
    assert.throws(() => bskyProfileUrl(hostile), TypeError);
  }
});

test("bskyPostUrl builds only from validated post AT URIs", () => {
  assert.equal(
    bskyPostUrl("at://did:plc:abc123/app.bsky.feed.post/3mabc123"),
    "https://bsky.app/profile/did:plc:abc123/post/3mabc123",
  );
  for (const hostile of [
    "at://did:plc:abc123/other.collection/3mabc123",
    "at://not-a-did/app.bsky.feed.post/3mabc123",
    "at://did:plc:abc123/app.bsky.feed.post/3mabc123/extra",
    "at://did:plc:abc123/app.bsky.feed.post/",
    "https://bsky.app/profile/did:plc:abc123/post/3mabc123",
    'at://did:plc:abc/app.bsky.feed.post/x" onclick="alert(1)',
    "",
  ]) {
    assert.throws(() => bskyPostUrl(hostile), TypeError);
  }
});

test("externalHttpsUrl accepts only credential-free https origins", () => {
  assert.equal(externalHttpsUrl("https://cdn.bsky.app/img/avatar.jpeg"), "https://cdn.bsky.app/img/avatar.jpeg");
  for (const hostile of [
    "http://insecure.invalid.test/x",
    "//protocol-relative.invalid.test/x",
    "https://user:password@collect.invalid.test/x",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "not a url",
    "",
  ]) {
    assert.throws(() => externalHttpsUrl(hostile), TypeError);
  }
});

interface RawServer {
  url: string;
  close(): Promise<void>;
}

async function rawServer(handler: (request: IncomingMessage, response: ServerResponse) => void): Promise<RawServer> {
  const server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
    close: () => new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve()))),
  };
}

test("the observer client never returns a truncated document: complete parse or refusal", async () => {
  const fixture = {
    discussions: Array.from({ length: 20 }, (_, index) => ({ text: `item ${index}`, uri: `at://x/${index}` })),
  };
  const payload = JSON.stringify(fixture);
  const server = await rawServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(payload);
  });
  try {
    for (const cap of [10, 100, payload.length - 1, payload.length, payload.length + 100]) {
      const client = new ObserverClient(server.url, cap);
      try {
        const document = await client.get("/api/v0/communities/did:plc:x/discussions");
        assert.deepEqual(document, fixture);
      } catch (error) {
        assert.ok(error instanceof ProjectionTooLargeError, `cap ${cap} must throw only ProjectionTooLargeError`);
      }
    }
  } finally {
    await server.close();
  }
});

test("the byte ceiling applies to streamed responses without a declared length", async () => {
  const server = await rawServer((request, response) => {
    response.writeHead(200, { "Content-Type": "application/json" });
    response.write('{"discussions":["');
    setImmediate(() => response.end(`${"x".repeat(500)}"]}`));
  });
  try {
    const client = new ObserverClient(server.url, 128);
    await assert.rejects(client.get("/anything"), ProjectionTooLargeError);
    const generous = new ObserverClient(server.url, 4096);
    assert.deepEqual(await generous.get("/anything"), { discussions: ["x".repeat(500)] });
  } finally {
    await server.close();
  }
});

test("the item-count ceiling refuses oversized arrays and admits arrays at the ceiling", async () => {
  const server = await rawServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ discussions: [1, 2, 3] }));
  });
  try {
    const client = new ObserverClient(server.url, 64 * 1024);
    await assert.rejects(client.getCapped("/list", "discussions", 2), ProjectionTooLargeError);
    assert.deepEqual(await client.getCapped("/list", "discussions", 3), { discussions: [1, 2, 3] });
    assert.deepEqual(await client.getCapped("/list", "unrelated", 1), { discussions: [1, 2, 3] });
  } finally {
    await server.close();
  }
});

test("an observer 404 surfaces as a coded HttpError 404", async () => {
  const server = await rawServer((request, response) => {
    response.statusCode = 404;
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ error: "not_found" }));
  });
  try {
    const client = new ObserverClient(server.url, 64 * 1024);
    await assert.rejects(client.get("/missing"), (error: unknown) => {
      assert.ok(error instanceof HttpError);
      assert.equal(error.status, 404);
      return true;
    });
  } finally {
    await server.close();
  }
});

test("identities render the DID alone until hydration provides a name", () => {
  const profiles = new Map<string, HydratedProfile>();
  const bare = renderIdentity("did:plc:nobody", profiles, { avatars: false });
  assert.equal(bare, '<span class="identity"><a class="profile" href="https://bsky.app/profile/did:plc:nobody" rel="noopener noreferrer">did:plc:nobody</a></span>');

  profiles.set("did:plc:handled", { did: "did:plc:handled", handle: "handled.example.test" });
  const handled = renderIdentity("did:plc:handled", profiles, { avatars: false });
  assert.match(handled, /@handled\.example\.test/);
  assert.match(handled, /title="did:plc:handled"/);
  assert.doesNotMatch(visibleText(handled), /did:plc:handled/);
  assert.doesNotMatch(handled, /<span class="did">/);
  assert.match(handled, /href="https:\/\/bsky\.app\/profile\/did:plc:handled"/);

  profiles.set("did:plc:named", { did: "did:plc:named", handle: "named.example.test", displayName: "A Readable Name" });
  const named = renderIdentity("did:plc:named", profiles, { avatars: false });
  assert.match(named, /A Readable Name/);
  assert.doesNotMatch(named, /<img/);

  const invalid = renderIdentity("not a did", profiles, { avatars: false });
  assert.equal(invalid, '<span class="identity">not a did</span>');
});

test("the DID is visible text only when no name is known, unless a moderator surface asks for it", () => {
  const profiles = new Map<string, HydratedProfile>([
    ["did:plc:handled", { did: "did:plc:handled", handle: "handled.example.test" }],
  ]);
  const unknown = visibleText(renderIdentity("did:plc:nobody", profiles, { avatars: false }));
  assert.equal(unknown, "did:plc:nobody");

  const known = visibleText(renderIdentity("did:plc:handled", profiles, { avatars: false }));
  assert.equal(known, "@handled.example.test");

  const moderator = renderIdentity("did:plc:handled", profiles, { avatars: false, showDid: true });
  assert.equal(visibleText(moderator), "@handled.example.test did:plc:handled");
  assert.match(moderator, /<span class="did">did:plc:handled<\/span>/);
});

test("identity rendering escapes hostile hydrated values and only shows avatars when enabled", () => {
  const profiles = new Map<string, HydratedProfile>([
    ["did:plc:hostile", {
      did: "did:plc:hostile",
      displayName: '<img src=x onerror=alert(1)>',
      avatar: "https://cdn.bsky.app/img/avatar/plain/did:plc:hostile/bafy@jpeg",
    }],
  ]);
  const off = renderIdentity("did:plc:hostile", profiles, { avatars: false });
  assert.doesNotMatch(off, /<img/);
  assert.match(off, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(off, /cdn\.bsky\.app/);

  const on = renderIdentity("did:plc:hostile", profiles, { avatars: true });
  assert.match(on, /<img class="avatar" src="https:\/\/cdn\.bsky\.app\/img\/avatar\/plain\/did:plc:hostile\/bafy@jpeg" alt="" width="24" height="24">/);

  const noAvatar = renderIdentity("did:plc:plain", new Map([["did:plc:plain", { did: "did:plc:plain", handle: "plain.example.test" }]]), { avatars: true });
  assert.doesNotMatch(noAvatar, /<img/);
});

test("snippet keeps the first line and bounds its length with an ellipsis", () => {
  assert.equal(snippet("short"), "short");
  assert.equal(snippet("first line\nsecond line"), "first line");
  assert.equal(snippet(""), "");
  assert.equal(snippet("x".repeat(140)), "x".repeat(140));
  assert.equal(snippet("x".repeat(141)), `${"x".repeat(140)}…`);
  assert.equal(snippet("x".repeat(10_000)).length, 141);
});

test("publicPostLink builds only validated Bluesky post links and degrades to empty", () => {
  assert.equal(
    publicPostLink("at://did:plc:abc123/app.bsky.feed.post/3mabc123"),
    '<a class="external" href="https://bsky.app/profile/did:plc:abc123/post/3mabc123" rel="noopener noreferrer">Public post on Bluesky</a>',
  );
  for (const invalid of [
    "",
    "not a uri",
    "at://did:plc:abc123/other.collection/3mabc123",
    'at://did:plc:abc/app.bsky.feed.post/x" onclick="alert(1)',
    "https://collect.invalid.test/post",
  ]) {
    assert.equal(publicPostLink(invalid), "");
  }
});

test("whyHere states the admission basis and degrades without a valid subject", () => {
  const full = whyHere("2026-09-09T10:00:00.000Z", "at://did:plc:abc123/app.bsky.feed.post/3mabc123");
  assert.match(full, /<summary>Why is this here\?<\/summary>/);
  assert.match(full, /Admitted to this community’s view on <time datetime="2026-09-09T10:00:00\.000Z">9 Sep 2026, 10:00 UTC<\/time>\./);
  assert.match(full, /href="https:\/\/bsky\.app\/profile\/did:plc:abc123\/post\/3mabc123" rel="noopener noreferrer">Public post on Bluesky<\/a>/);
  assert.match(full, /Community removal changes only this view\./);

  const undated = whyHere("", "at://did:plc:abc123/app.bsky.feed.post/3mabc123");
  assert.match(undated, /at an unrecorded time/);

  const unlinked = whyHere("2026-09-09T10:00:00.000Z", "not a uri");
  assert.match(unlinked, /The original is the author’s public record\./);
  assert.doesNotMatch(unlinked, /href=/);

  const hostile = whyHere('"><details open ontoggle=alert(1)>', "not a uri");
  assert.doesNotMatch(hostile, /<details open ontoggle/);
  assert.match(hostile, /&quot;&gt;&lt;details open ontoggle=alert\(1\)&gt;/);
});

test("postedAt renders a time element or nothing", () => {
  assert.equal(postedAt(""), "");
  assert.equal(
    postedAt("2026-09-08T09:30:00.000Z"),
    'posted <time datetime="2026-09-08T09:30:00.000Z">8 Sep 2026, 09:30 UTC</time>',
  );
  const hostile = postedAt('"><time onmouseover=alert(1)>');
  assert.doesNotMatch(hostile, /<time onmouseover/);
  assert.match(hostile, /&lt;time onmouseover=alert\(1\)&gt;/);
});

test("parsePostReference accepts only exact Bluesky post URLs and post AT URIs", () => {
  assert.deepEqual(parsePostReference("https://bsky.app/profile/did:plc:alice/post/3kpost"), { kind: "did", did: "did:plc:alice", rkey: "3kpost" });
  assert.deepEqual(parsePostReference("at://did:web:alice.example.test/app.bsky.feed.post/3kpost"), { kind: "did", did: "did:web:alice.example.test", rkey: "3kpost" });
  assert.deepEqual(parsePostReference(" https://bsky.app/profile/Alice.Example.TEST/post/3kpost\n"), { kind: "handle", handle: "alice.example.test", rkey: "3kpost" });
  const refused = [
    "",
    "at://did:plc:alice/app.bsky.feed.like/3kpost",
    "at://did:plc:alice/app.bsky.feed.post",
    "at://alice.example.test/app.bsky.feed.post/3kpost",
    "at://did:plc:alice/app.bsky.feed.post/3kpost/extra",
    "https://bsky.app/profile/did:plc:alice/post/",
    "https://bsky.app/profile/did:plc:alice/post/.",
    "https://bsky.app/profile/did:plc:alice/post/3kpost/",
    "https://bsky.app/profile/did:PLC:alice/post/3kpost",
    "https://bsky.app/profile/not_a_handle/post/3kpost",
    "https://BSKY.app/profile/did:plc:alice/post/3kpost",
    "https://bsky.app/profile/did:plc:alice/post/3k\u0000post",
    "https://bsky.app/profile/did:plc:alice/post/3k\u0085post",
    "https://bsky.app/profile/did:plc:alice/post/3k post",
    `https://bsky.app/profile/did:plc:alice/post/${"a".repeat(1000)}`,
    "https://bsky.app/profile/did:plc:alice/post/3kpost?ref=share",
    "file:///etc/passwd",
  ];
  for (const value of refused) {
    assert.throws(() => parsePostReference(value), PostReferenceError, JSON.stringify(value));
  }
  assert.throws(() => parsePostReference("at://did:plc:alice/app.bsky.graph.follow/3k"), /something other than a Bluesky post/);
});

test("humanDate is a fixed UTC rendering independent of the process time zone", () => {
  assert.equal(humanDate("2026-09-24T14:05:00.000Z"), "24 Sep 2026, 14:05 UTC");
  assert.equal(humanDate("2026-09-24T14:05Z"), "24 Sep 2026, 14:05 UTC");
  assert.equal(humanDate("2026-09-24T16:05:00+02:00"), "24 Sep 2026, 14:05 UTC");
  assert.equal(humanDate("2026-12-31T23:59:59.999-01:00"), "1 Jan 2027, 00:59 UTC");
  assert.equal(humanDate("2026-01-05T03:07:00Z"), "5 Jan 2026, 03:07 UTC");
  for (const raw of ["", "2026-09-24", "2026-09-24T14:05:00", "2026-09-24 14:05", "2026-13-40T99:99:00Z", "yesterday"]) {
    assert.equal(humanDate(raw), raw);
  }
  const earlier = postedAt("2026-09-24T14:05:00.000Z");
  assert.equal(earlier, 'posted <time datetime="2026-09-24T14:05:00.000Z">24 Sep 2026, 14:05 UTC</time>');
  assert.equal(postedAt("2026-09-24T14:05:00.000Z"), earlier);
});
