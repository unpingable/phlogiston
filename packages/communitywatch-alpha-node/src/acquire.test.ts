import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { mkdtemp, readFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { acquireArtifact, type DelegationSource } from "./acquire.js";
import type { ObserverConfig } from "./config.js";

const DELEGATION = "synthetic-delegation.secret.value";
const CREDENTIAL = "eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiJzcGFjZSJ9.c2lnbmF0dXJl";
const CAR = Buffer.from("synthetic-car-boundary-bytes\0\x01");
const OPS = Buffer.from('{"ops":[],"commit":{"rev":"3mtn3fop2xe25"}}');

test("full repo and operation artifacts are acquired as exact, private spool bytes", async (t) => {
  const requests: Array<Readonly<{ method: string; url: string; authorization: string | undefined; dpop: string | undefined }>> = [];
  const server = createServer(async (request, response) => route(request, response, requests));
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const address = server.address();
  assert(address && typeof address === "object");
  const origin = `http://127.0.0.1:${address.port}`;
  const runtimeDirectory = await mkdtemp(join(tmpdir(), "juniper-observer-"));
  const config = fixtureConfig(origin, runtimeDirectory);
  const source: DelegationSource = {
    getDelegationToken: async () => ({ token: DELEGATION, attempts: Object.freeze([]) }),
  };

  const full = await acquireArtifact(config, source, {
    kind: "get_repo",
    requestId: "full-1",
    repoDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb",
  });
  assert.deepEqual(await readFile(full.bodyFile), CAR);
  assert.equal(full.receipt.bodySha256, "204ff96d35c4406a8255a4a5c96b2bfeaecd6022d46fdd3008f2f23d9a8643c2");
  assert.equal((await stat(full.bodyFile)).mode & 0o777, 0o600);
  assert.equal((await stat(full.receiptFile)).mode & 0o777, 0o600);
  assert.equal(full.receipt.attempts.length, 2);
  assert.equal(full.receipt.automaticArtifactRetries, 0);
  assert.equal(full.receipt.redirectsFollowed, 0);

  const ops = await acquireArtifact(config, source, {
    kind: "list_repo_ops",
    requestId: "ops-1",
    repoDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb",
    since: "3mtn3fop2xe25",
    cursor: "page-one",
    limit: 25,
  });
  assert.deepEqual(await readFile(ops.bodyFile), OPS);
  assert.match(ops.receipt.requestedUrl, /cursor=page-one/);
  assert.match(ops.receipt.requestedUrl, /limit=25/);
  assert.equal(requests.length, 4);
  assert.equal(requests[0]?.authorization, `Bearer ${DELEGATION}`);
  assert.equal(requests[1]?.authorization, `DPoP ${CREDENTIAL}`);
  assert.ok(requests.every((item) => item.dpop?.split(".").length === 3));

  const publicReceipt = await readFile(full.receiptFile, "utf8");
  for (const secret of [DELEGATION, CREDENTIAL, "synthetic-delegation", "signature"]) {
    assert.equal(publicReceipt.includes(secret), false);
    assert.equal(JSON.stringify(full).includes(secret), false);
  }
  assert.deepEqual(full.receipt.explicitNonClaims, [
    "artifact_validity",
    "source_authority",
    "did_resolution",
    "space_admission",
    "community_standing",
    "governance_authority",
    "currentness",
    "complete_history",
  ]);
  await assert.rejects(acquireArtifact(config, source, {
    kind: "get_repo",
    requestId: "full-1",
    repoDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb",
  }), /EEXIST/);
});

test("redirects, oversized bodies, and substituted request fields fail closed", async (t) => {
  let mode: "redirect" | "oversized" | "bad-credential" = "redirect";
  const server = createServer((request, response) => {
    if (mode === "redirect") { response.writeHead(302, { Location: "https://other.invalid.test/" }); response.end(); return; }
    if (mode === "bad-credential") { response.writeHead(200, { "Content-Type": "application/json" }); response.end('{"credential":"nope","authority":true}'); return; }
    if (request.url?.includes("getSpaceCredential")) { response.writeHead(200, { "Content-Type": "application/json" }); response.end(JSON.stringify({ credential: CREDENTIAL })); return; }
    response.writeHead(200, { "Content-Length": "17" }); response.end("x".repeat(17));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const address = server.address();
  assert(address && typeof address === "object");
  const origin = `http://127.0.0.1:${address.port}`;
  const source: DelegationSource = { getDelegationToken: async () => ({ token: DELEGATION, attempts: [] }) };
  const base = fixtureConfig(origin, await mkdtemp(join(tmpdir(), "juniper-observer-hostile-")));
  const request = { kind: "get_repo" as const, requestId: "hostile", repoDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb" };

  await assert.rejects(acquireArtifact(base, source, request), /redirect refused/);
  mode = "bad-credential";
  await assert.rejects(acquireArtifact(base, source, request), /fields differ/);
  mode = "oversized";
  await assert.rejects(acquireArtifact({ ...base, maximumCarBytes: 16 }, source, request), /size refused/);
  await assert.rejects(acquireArtifact(base, source, { ...request, requestId: "../escape" }), /request ID/);
  await assert.rejects(acquireArtifact(base, source, { ...request, authority: true } as never), /unexpected fields/);
});

test("HTTP endpoints are accepted only in explicit loopback fixture configuration", async () => {
  const { loadConfig } = await import("./config.js");
  const environment = {
    JUNIPER_OBSERVER_RUNTIME_DIR: "/tmp/juniper-observer-fixture",
    JUNIPER_OBSERVER_DID: "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
    JUNIPER_OBSERVER_CALLBACK_ORIGIN: "http://127.0.0.1:3012",
    JUNIPER_SPACE_URI: "at://did:plc:authority/network.example.community/self",
    JUNIPER_SPACE_AUTHORITY_ORIGIN: "http://127.0.0.1:3013",
    JUNIPER_SPACE_REPO_HOST_ORIGIN: "http://127.0.0.1:3014",
  };
  assert.throws(() => loadConfig(environment), /HTTPS/);
  assert.equal(loadConfig({ ...environment, JUNIPER_OBSERVER_ALLOW_LOOPBACK_FIXTURES: "1" }).allowLoopbackFixtures, true);
  assert.throws(() => loadConfig({ ...environment, JUNIPER_OBSERVER_ALLOW_LOOPBACK_FIXTURES: "1", JUNIPER_SPACE_REPO_HOST_ORIGIN: "http://example.com" }), /HTTPS/);
  assert.throws(() => loadConfig({ ...environment, JUNIPER_OBSERVER_ALLOW_LOOPBACK_FIXTURES: "1", JUNIPER_OBSERVER_CALLBACK_ORIGIN: "https://oauth.invalid.test" }), /loopback/);
});

function fixtureConfig(origin: string, runtimeDirectory: string): ObserverConfig {
  return {
    runtimeDirectory,
    observerDid: "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
    callbackOrigin: "http://127.0.0.1:3012",
    space: "at://did:plc:authority/network.example.community/self",
    authorityOrigin: origin,
    repoHostOrigin: origin,
    maximumCarBytes: 1 << 20,
    maximumJsonBytes: 1 << 20,
    timeoutMilliseconds: 2_000,
    allowLoopbackFixtures: true,
  };
}

async function route(request: IncomingMessage, response: ServerResponse, seen: Array<Readonly<{ method: string; url: string; authorization: string | undefined; dpop: string | undefined }>>): Promise<void> {
  seen.push(Object.freeze({ method: request.method ?? "", url: request.url ?? "", authorization: request.headers.authorization, dpop: request.headers.dpop as string | undefined }));
  if (request.url === "/xrpc/com.atproto.space.getSpaceCredential") {
    for await (const _chunk of request) { /* consume exact request body */ }
    response.writeHead(200, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ credential: CREDENTIAL }));
    return;
  }
  if (request.url?.startsWith("/xrpc/com.atproto.space.getRepo?")) {
    response.writeHead(200, { "Content-Type": "application/vnd.ipld.car", "Content-Length": String(CAR.length) });
    response.end(CAR);
    return;
  }
  if (request.url?.startsWith("/xrpc/com.atproto.space.listRepoOps?")) {
    response.writeHead(200, { "Content-Type": "application/json", "Content-Length": String(OPS.length) });
    response.end(OPS);
    return;
  }
  response.writeHead(404);
  response.end();
}
