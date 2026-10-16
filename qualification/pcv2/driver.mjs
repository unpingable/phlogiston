// Synthetic-user driver for the isolated PCV2 qualification run.
//
// Everything this file talks to is on loopback: three real PDS containers,
// the loopback identity directory, and the real community-live, communityd,
// communitywatch(+web) and community-notify processes it starts itself. The
// only deliberately synthetic services are the AppView stand-in (there is no
// isolated AppView) and the room webhook receiver, both hosted in this
// process and labelled as such in the receipt. See README.md.
//
// Run through run-synthetic-user.sh, which supplies the environment.

import { spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { chmod, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { createServer as createHttpServer } from "node:http";
import { createServer as createHttpsServer } from "node:https";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";

const env = (name) => {
  const value = process.env[name];
  if (value === undefined || value === "") throw new Error(`${name} is required`);
  return value;
};

const ROOT = env("PCV2_ROOT");
const SCRATCH = env("PCV2_SCRATCH");
const PLC = env("PCV2_PLC");
const PDS = {
  community: env("PCV2_PDS_COMMUNITY"),
  participant: env("PCV2_PDS_PARTICIPANT"),
  moderator: env("PCV2_PDS_MODERATOR"),
};
const PDS_IMAGE = env("PCV2_PDS_IMAGE");
const RECEIPT = env("PCV2_RECEIPT");
const PYTHON = env("PCV2_PYTHON");
const TLS_CERT = env("PCV2_TLS_CERT");
const TLS_KEY = env("PCV2_TLS_KEY");
const SOURCE_COMMIT = env("PCV2_SOURCE_COMMIT");
// The policy worker must reach communityd from a different OS UID than the
// web peer (communityd refuses equal peer UIDs), so it runs in a container:
// the host's own interpreter and /usr, read-only, as UID+1.
const POLICY_IMAGE = env("PCV2_POLICY_IMAGE");
const POLICY_PYTHON = env("PCV2_POLICY_PYTHON");
const LIVE_DIR = join(ROOT, "apps", "community-live");
const PYTHONPATH = ["community-model", "communityd", "communitywatch", "communitywatch-web", "community-notify"]
  .map((name) => join(ROOT, "packages", name, "src")).join(":");

const require = createRequire(join(LIVE_DIR, "package.json"));
const { chromium } = require("playwright-core");
const BROWSER_CANDIDATES = [
  process.env.COMMUNITY_BROWSER_EXECUTABLE,
  `${homedir()}/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell`,
  "/usr/bin/google-chrome",
].filter((value) => typeof value === "string" && value !== "");
const browserExecutable = BROWSER_CANDIDATES.find((candidate) => existsSync(candidate));
if (browserExecutable === undefined) throw new Error("no browser executable found; set COMMUNITY_BROWSER_EXECUTABLE");

const POST = "app.bsky.feed.post";
const SUBMIT = "app.phlogiston.community.submit";
const ADMISSION = "app.phlogiston.community.admission";
const MOD_ACTION = "app.phlogiston.community.modAction";
const REPLY_POLICY = "app.phlogiston.community.replyPolicy";
const REPLY_ADMISSION = "app.phlogiston.community.replyAdmission";
const REPLY_ACTION = "app.phlogiston.community.replyAction";
const COMMUNITY_NAME = "Isolated PCV2 Trial";
const COMMUNITY_PURPOSE = "Exhaust the plumbing before a human sees it.";

// ---------------------------------------------------------------- receipt --

const startedAt = Date.now();
const receipt = {
  schema: "atproto-community.pcv2-synthetic-user.v1",
  result: "failed",
  generatedAt: new Date().toISOString(),
  sourceCommit: SOURCE_COMMIT,
  pdsImage: PDS_IMAGE,
  components: {
    real: [
      "PDS x3 (pinned image, dev mode, isolated bridge, loopback-published)",
      "PDS OAuth authorization server and consent UI (driven by headless Chromium)",
      "community-live (node --import tsx src/server.ts, loopback OAuth client)",
      "communityd (serve_cli, Unix socket, PDS writer with app-password credential file)",
      "communitywatch ObserverStore + VerifyingEventSource (repo proofs against the PDS)",
      "communitywatch-web projection API (loopback)",
      "community-notify --once per step (real HTTPS webhook sender, self-signed loopback CA)",
      "community-policy run-once per step (real worker, own SQLite state, communityd socket peer as UID+1 in a container that mounts the host's /usr read-only)",
      "Playwright Chromium as three browsers: participant, moderator, signed-out",
    ],
    standIn: [
      "identity directory: did:plc registry + com.atproto.identity.resolveHandle over the PDS-submitted PLC operations (no signature checks, no history)",
      "AppView: app.bsky.actor.getProfiles and app.bsky.feed.getPosts answered from the real PDS records via com.atproto.repo.getRecord (real current CIDs); can simulate unavailable, mismatched CID, and handle.invalid",
      "room webhook receiver: loopback HTTPS endpoint that records payloads and can reject one event",
      "observer transport: com.atproto.repo.listRecords polling in place of a firehose; every claim is still repo-proof verified",
    ],
  },
  communityLiveConfigSeams: ["COMMUNITY_PLC_DIRECTORY_URL", "COMMUNITY_HANDLE_RESOLVER_URL"],
  identities: {},
  steps: [],
  negatives: [],
  payloads: {},
  recordCounts: {},
  defects: [],
  timings: {},
};

class Failure extends Error {}
function check(condition, message, evidence) {
  if (!condition) throw new Failure(evidence === undefined ? message : `${message}: ${JSON.stringify(evidence).slice(0, 600)}`);
}

let fatal = false;
async function run(list, id, title, body) {
  const entry = { id, title, ok: false, ms: 0, evidence: {} };
  list.push(entry);
  const began = Date.now();
  if (fatal) {
    entry.error = "skipped after a fatal failure";
    entry.ms = 0;
    return entry;
  }
  try {
    await body(entry.evidence);
    entry.ok = true;
  } catch (error) {
    entry.error = error instanceof Failure ? error.message : `${error?.name ?? "Error"}: ${error?.message ?? error}`;
    if (!(error instanceof Failure)) entry.stack = String(error?.stack ?? "").split("\n").slice(0, 6);
    process.stderr.write(`  FAIL ${id}: ${entry.error}\n`);
  }
  entry.ms = Date.now() - began;
  process.stderr.write(`${entry.ok ? "ok  " : "FAIL"} ${id} (${entry.ms} ms)\n`);
  return entry;
}
const step = (id, title, body) => run(receipt.steps, id, title, body);
const negative = (id, title, body) => run(receipt.negatives, id, title, body);
async function must(id, title, body) {
  const entry = await step(id, title, body);
  if (!entry.ok) fatal = true;
  return entry;
}

// ------------------------------------------------------------------- xrpc --

async function xrpc(origin, nsid, { body, query, token } = {}) {
  const url = new URL(`/xrpc/${nsid}`, origin);
  for (const [key, value] of Object.entries(query ?? {})) url.searchParams.set(key, value);
  const headers = { accept: "application/json" };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (token !== undefined) headers.authorization = `Bearer ${token}`;
  const response = await fetch(url, { method: body === undefined ? "GET" : "POST", headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await response.text();
  if (!response.ok) throw new Error(`${nsid} -> HTTP ${response.status}: ${text.slice(0, 300)}`);
  return text === "" ? {} : JSON.parse(text);
}

const accounts = {};
async function createAccount(role, origin, handle, password) {
  const created = await xrpc(origin, "com.atproto.server.createAccount", { body: { handle, email: `${handle.replace(/\./g, "-")}@example.test`, password } });
  accounts[role] = { did: created.did, handle, origin, password, token: created.accessJwt };
  return accounts[role];
}
const createRecord = (account, collection, record, rkey) =>
  xrpc(account.origin, "com.atproto.repo.createRecord", { body: { repo: account.did, collection, record, ...(rkey === undefined ? {} : { rkey }) }, token: account.token });
const putRecord = (account, collection, rkey, record) =>
  xrpc(account.origin, "com.atproto.repo.putRecord", { body: { repo: account.did, collection, rkey, record }, token: account.token });
const deleteRecord = (account, collection, rkey) =>
  xrpc(account.origin, "com.atproto.repo.deleteRecord", { body: { repo: account.did, collection, rkey }, token: account.token });
async function listRecords(origin, repo, collection) {
  const page = await xrpc(origin, "com.atproto.repo.listRecords", { query: { repo, collection, limit: "100" } });
  return page.records ?? [];
}
async function counts() {
  const p = accounts.participant, m = accounts.moderator, c = accounts.community;
  return {
    participant: { posts: (await listRecords(p.origin, p.did, POST)).length, submits: (await listRecords(p.origin, p.did, SUBMIT)).length },
    moderator: { posts: (await listRecords(m.origin, m.did, POST)).length, submits: (await listRecords(m.origin, m.did, SUBMIT)).length },
    community: {
      admissions: (await listRecords(c.origin, c.did, ADMISSION)).length,
      modActions: (await listRecords(c.origin, c.did, MOD_ACTION)).length,
      replyPolicies: (await listRecords(c.origin, c.did, REPLY_POLICY)).length,
      replyAdmissions: (await listRecords(c.origin, c.did, REPLY_ADMISSION)).length,
      replyActions: (await listRecords(c.origin, c.did, REPLY_ACTION)).length,
    },
  };
}
const rkeyOf = (uri) => uri.split("/").at(-1);
// An ATProto TID: 13 base32-sortable characters whose first character encodes
// only four bits (community_model.validate_tid refuses anything else).
const CANONICAL_TID = /^[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}$/;
function recordTidDefect(where, rkeys) {
  if (receipt.defects.some((defect) => defect.id === "D-deterministic-tid-range")) return;
  receipt.defects.push({
    id: "D-deterministic-tid-range",
    severity: "product defect",
    where: "apps/community-live/src/contributions.ts:254-262 deterministicTid (new-post source rkey at server.ts:217, submit rkey at contributions.ts:97)",
    observed: `${where}: ${JSON.stringify(rkeys)}; the first character is outside 234567abcdefghij, so community_model.validate_tid (packages/community-model/src/community_model/identifiers.py:277) rejects the record and the observer never lists the submission (moderation queue or reply candidates). About half of all new-post operations are affected (bytes[0] & 31 >= 16).`,
    note: "Smallest fix: take the first character from four bits, alphabet[bytes[0] & 15], and the remaining twelve from five bits as now.",
  });
}

// -------------------------------------------------------------- processes --

const processes = new Map();
async function startProcess(name, command, args, { cwd, env: extra } = {}) {
  await mkdir(join(SCRATCH, "logs"), { recursive: true });
  const child = spawn(command, args, { cwd, env: { ...process.env, ...extra }, stdio: ["ignore", "pipe", "pipe"] });
  const log = [];
  const lines = { stdout: [], stderr: [] };
  for (const stream of ["stdout", "stderr"]) {
    let buffer = "";
    child[stream].on("data", (chunk) => {
      buffer += chunk;
      let index;
      while ((index = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + 1);
        lines[stream].push(line);
        log.push(`${stream}: ${line}`);
      }
    });
  }
  const exit = new Promise((resolve) => child.on("exit", (code, signal) => resolve({ code, signal })));
  const handle = { name, child, lines, log, exit, flush: () => writeFile(join(SCRATCH, "logs", `${name}.log`), `${log.join("\n")}\n`) };
  processes.set(name, handle);
  return handle;
}
async function stopProcess(handle, signal = "SIGTERM") {
  if (handle.child.exitCode === null && handle.child.signalCode === null) {
    handle.child.kill(signal);
    await Promise.race([handle.exit, sleep(8000).then(() => handle.child.kill("SIGKILL"))]);
  }
  await handle.flush();
}
async function waitFor(predicate, { timeoutMs = 30_000, what = "condition" } = {}) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    if (await predicate()) return;
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${what}`);
}
async function waitForLine(handle, pattern, timeoutMs = 30_000) {
  let found;
  await waitFor(() => {
    found = [...handle.lines.stdout, ...handle.lines.stderr].find((line) => pattern.test(line));
    if (found === undefined && handle.child.exitCode !== null) throw new Error(`${handle.name} exited: ${handle.log.slice(-5).join(" | ")}`);
    return found !== undefined;
  }, { timeoutMs, what: `${handle.name} ${pattern}` });
  return found;
}

// -------------------------------------------------------- stand-in servers --

async function resolveDidDocument(did) {
  const response = await fetch(`${PLC}/${encodeURIComponent(did)}`);
  if (!response.ok) return null;
  return response.json();
}
function pdsEndpoint(document) {
  return document?.service?.find((entry) => entry.type === "AtprotoPersonalDataServer")?.serviceEndpoint ?? null;
}

const appView = { mode: "normal", requests: [] };
function json(response, status, body) {
  const encoded = Buffer.from(JSON.stringify(body));
  response.writeHead(status, { "content-type": "application/json", "content-length": encoded.length });
  response.end(encoded);
}
async function appViewHandler(request, response) {
  const url = new URL(request.url, "http://appview.invalid");
  appView.requests.push({ mode: appView.mode, path: url.pathname });
  if (appView.mode === "unavailable") return json(response, 503, { error: "synthetic AppView outage" });
  if (url.pathname === "/xrpc/app.bsky.actor.getProfiles") {
    const profiles = [];
    for (const did of url.searchParams.getAll("actors")) {
      const document = await resolveDidDocument(did);
      if (document === null) continue;
      const alias = (document.alsoKnownAs ?? []).find((value) => value.startsWith("at://"));
      // "handle-invalid" mode: the AppView's placeholder for an account whose
      // handle does not currently resolve (a real AppView state).
      const handle = alias === undefined || appView.mode === "handle-invalid" ? "handle.invalid" : alias.slice("at://".length);
      profiles.push({ did, handle });
    }
    return json(response, 200, { profiles });
  }
  if (url.pathname === "/xrpc/app.bsky.feed.getPosts") {
    const posts = [];
    for (const uri of url.searchParams.getAll("uris")) {
      const match = /^at:\/\/(did:[^/]+)\/app\.bsky\.feed\.post\/([^/]+)$/.exec(uri);
      if (match === null) continue;
      const origin = pdsEndpoint(await resolveDidDocument(match[1]));
      if (origin === null) continue;
      try {
        const record = await xrpc(origin, "com.atproto.repo.getRecord", { query: { repo: match[1], collection: POST, rkey: match[2] } });
        const cid = appView.mode === "mismatch" ? `${record.cid.slice(0, -1)}${record.cid.endsWith("a") ? "b" : "a"}` : record.cid;
        posts.push({ uri, cid, author: { did: match[1] }, record: record.value, indexedAt: new Date().toISOString() });
      } catch {
        // absent post: omitted from the view, as a real AppView would omit it
      }
    }
    return json(response, 200, { posts });
  }
  return json(response, 404, { error: "unknown lexicon" });
}

const webhook = { mode: "accept", received: [], rejected: [] };
function webhookHandler(request, response) {
  let body = "";
  request.on("data", (chunk) => { body += chunk; });
  request.on("end", () => {
    let payload;
    try { payload = JSON.parse(body); } catch { payload = { raw: body }; }
    if (webhook.mode === "reject-next") {
      webhook.mode = "accept";
      webhook.rejected.push({ at: new Date().toISOString(), payload });
      response.writeHead(500, { "content-type": "text/plain" });
      response.end("synthetic room rejection");
      return;
    }
    webhook.received.push({ at: new Date().toISOString(), payload });
    response.writeHead(200, { "content-type": "text/plain" });
    response.end("ok");
  });
}
function listen(server, host = "127.0.0.1") {
  return new Promise((resolve) => server.listen(0, host, () => resolve(server.address().port)));
}

// ------------------------------------------------------------- the stack --

let LIVE;
let livePort;
let observer;
let projectionOrigin;
let controlOrigin;
let liveProcess;
let liveEnv;
const runtimeDir = join(SCRATCH, "community-web");
const faultDir = join(SCRATCH, "community-web-faults");
const notifyDir = join(SCRATCH, "community-notify");
const policyDir = join(SCRATCH, "community-policy");
let notifyConfigPath;
let policyArgs;

async function startLive() {
  liveProcess = await startProcess("community-live", process.execPath, ["--import", "tsx", "src/server.ts"], { cwd: LIVE_DIR, env: liveEnv });
  await waitFor(async () => {
    if (liveProcess.child.exitCode !== null) throw new Error(`community-live exited: ${liveProcess.log.slice(-8).join(" | ")}`);
    try { return (await fetch(`${LIVE}/healthz`)).ok; } catch { return false; }
  }, { what: "community-live health" });
}

async function ingest() {
  const response = await fetch(`${controlOrigin}/ingest`, { method: "POST" });
  const body = await response.json();
  if (!response.ok) throw new Error(`observer ingest failed: ${body.error}`);
  return body;
}
async function projection(path) {
  const response = await fetch(`${projectionOrigin}/api/v0/communities/${encodeURIComponent(accounts.community.did)}${path}`);
  const body = await response.json();
  if (!response.ok) throw new Error(`projection ${path} -> ${response.status} ${JSON.stringify(body).slice(0, 200)}`);
  return body;
}

async function notifyOnce() {
  const handle = await startProcess(`community-notify-${Date.now()}`, PYTHON, ["-m", "community_notify", "--config", notifyConfigPath, "--once"], {
    cwd: ROOT,
    env: { PYTHONPATH, SSL_CERT_FILE: TLS_CERT },
  });
  const { code } = await handle.exit;
  await handle.flush();
  const stdout = handle.lines.stdout.at(-1);
  const logs = handle.lines.stderr.map((line) => { try { return JSON.parse(line).community_notify; } catch { return line; } });
  return { code, counts: stdout === undefined ? null : JSON.parse(stdout), logs };
}

async function policyOnce() {
  const handle = await startProcess(`community-policy-${Date.now()}`, "docker", policyArgs, { cwd: ROOT });
  const { code } = await handle.exit;
  await handle.flush();
  const stdout = handle.lines.stdout.at(-1);
  let counts = null;
  try { counts = stdout === undefined ? null : JSON.parse(stdout); } catch { counts = null; }
  return { code, counts, stderr: handle.lines.stderr.slice(-5) };
}

// ----------------------------------------------------------------- browser --

let browser;
async function newContext() {
  return browser.newContext({ viewport: { width: 1280, height: 900 } });
}
async function mainText(page) {
  return (await page.locator("main").innerText()).replace(/\s+/g, " ").trim();
}
async function bodyText(page) {
  return (await page.locator("body").innerText()).replace(/\s+/g, " ").trim();
}
async function oauthSignIn(page, account, { deny = false, capture } = {}) {
  await page.goto(`${LIVE}/`);
  await page.fill('form.signin input[name="handle"]', account.handle);
  await Promise.all([page.waitForURL(/\/oauth\/authorize/), page.click("form.signin button")]);
  await page.waitForSelector('input[name="password"]');
  const prefilled = await page.inputValue('input[name="username"]');
  const signInText = await page.locator("body").innerText();
  await page.fill('input[name="password"]', account.password);
  await page.click("button[type=submit]:has-text('Sign in')");
  const consentButton = page.getByRole("button", { name: deny ? "Deny access" : "Authorize" });
  await consentButton.waitFor();
  const consentText = (await page.locator("body").innerText()).replace(/\s+/g, " ").trim();
  const callbacks = [];
  const listener = (request) => { if (request.url().startsWith(`${LIVE}/oauth/callback`)) callbacks.push(request.url()); };
  page.on("request", listener);
  await Promise.all([page.waitForURL((url) => url.origin === LIVE && (deny || !url.pathname.startsWith("/oauth/"))), consentButton.click()]);
  page.off("request", listener);
  if (capture !== undefined) capture.callbackUrl = callbacks[0];
  return { prefilled, signInPageMentionsPds: /localhost PDS/.test(signInText), consentText, finalUrl: page.url(), title: await page.title(), text: await bodyText(page) };
}
async function csrfFor(page) {
  return page.locator('input[name="csrf"]').first().inputValue();
}
async function cookieHeader(context) {
  return (await context.cookies(LIVE)).map((cookie) => `${cookie.name}=${cookie.value}`).join("; ");
}
const decodeEntities = (value) => value.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const stripHtml = (html) => decodeEntities(html.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
async function rawPost(path, fields, { cookie, origin = LIVE } = {}) {
  const headers = { "content-type": "application/x-www-form-urlencoded" };
  if (origin !== null) headers.origin = origin;
  if (cookie !== undefined) headers.cookie = cookie;
  const response = await fetch(`${LIVE}${path}`, { method: "POST", headers, body: new URLSearchParams(fields).toString(), redirect: "manual" });
  const text = await response.text();
  return { status: response.status, location: response.headers.get("location"), text: stripHtml(text).slice(0, 400), setCookie: response.headers.getSetCookie() };
}
async function rawGet(path, { cookie } = {}) {
  const response = await fetch(`${LIVE}${path}`, { headers: cookie === undefined ? {} : { cookie }, redirect: "manual" });
  const html = await response.text();
  return { status: response.status, location: response.headers.get("location"), html, text: stripHtml(html), setCookie: response.headers.getSetCookie() };
}
const clearsSessionCookie = (setCookie) => setCookie.some((value) => /^community_session=;?/.test(value) && /Max-Age=0|Expires=Thu, 01 Jan 1970/i.test(value));
const oauthSessionFile = (did) => join(runtimeDir, "oauth", "session", createHash("sha256").update(did).digest("hex"));
const existingPostOperationId = (communityDid, subject) =>
  `existing-${createHash("sha256").update(`existing-post\n${communityDid}\n${subject.uri}\n${subject.cid}`).digest("hex").slice(0, 40)}`;

// ------------------------------------------------------------------- main --

async function main() {
  await mkdir(runtimeDir, { recursive: true, mode: 0o700 });
  await mkdir(faultDir, { recursive: true, mode: 0o700 });
  await mkdir(notifyDir, { recursive: true, mode: 0o700 });

  // Synthetic identities: the community actor alone on PDS A, the participant
  // on PDS B, the moderator on PDS C. Passwords are never written anywhere.
  const community = await createAccount("community", PDS.community, "pcv2-community.test", `synthetic-${randomBytes(9).toString("hex")}`);
  const participant = await createAccount("participant", PDS.participant, "pcv2-participant.test", `synthetic-${randomBytes(9).toString("hex")}`);
  const moderator = await createAccount("moderator", PDS.moderator, "pcv2-moderator.test", `synthetic-${randomBytes(9).toString("hex")}`);
  receipt.identities = {
    community: { did: community.did, handle: community.handle, pds: community.origin },
    participant: { did: participant.did, handle: participant.handle, pds: participant.origin },
    moderator: { did: moderator.did, handle: moderator.handle, pds: moderator.origin },
    distinct: new Set([community.did, participant.did, moderator.did]).size === 3,
  };

  // The participant's ordinary Bluesky posts exist before any of this.
  const post1 = await createRecord(participant, POST, { $type: POST, text: "First isolated post: a question about repository proofs.", createdAt: "2026-09-25T09:00:00.000Z" });
  const post2 = await createRecord(participant, POST, { $type: POST, text: "Second isolated post, submitted by its bsky.app handle link.", createdAt: "2026-09-25T09:01:00.000Z" });
  const post3 = await createRecord(participant, POST, { $type: POST, text: "Third isolated post, deleted before submission.", createdAt: "2026-09-25T09:02:00.000Z" });
  const post4 = await createRecord(participant, POST, { $type: POST, text: "Fourth isolated post, used for the forged-CID form attempt.", createdAt: "2026-09-25T09:03:00.000Z" });
  const moderatorPost = await createRecord(moderator, POST, { $type: POST, text: "The moderator's own post; the participant may not submit it.", createdAt: "2026-09-25T09:04:00.000Z" });
  receipt.payloads.participantPosts = { post1: post1.uri, post2: post2.uri, post3: post3.uri, post4: post4.uri, moderatorPost: moderatorPost.uri };

  // Stand-ins.
  const appViewServer = createHttpServer((request, response) => { appViewHandler(request, response).catch((error) => json(response, 500, { error: String(error) })); });
  const appViewPort = await listen(appViewServer);
  const webhookServer = createHttpsServer({ cert: await readFile(TLS_CERT), key: await readFile(TLS_KEY) }, webhookHandler);
  const webhookPort = await listen(webhookServer);

  // communityd: the sole community-authority writer, real PDS adapter.
  const communitydDir = join(SCRATCH, "communityd");
  await mkdir(communitydDir, { recursive: true, mode: 0o700 });
  const credentialPath = join(communitydDir, "community-credential.json");
  await writeFile(credentialPath, JSON.stringify({ identifier: community.handle, app_password: community.password }), { mode: 0o600 });
  // The socket sits in its own directory so the policy container can be
  // given that directory alone (communityd makes it 0750, the socket 0660).
  const socketDir = join(communitydDir, "socket");
  const socketPath = join(socketDir, "communityd.sock");
  const uid = process.getuid();
  const policyUid = uid + 1;
  await writeFile(join(communitydDir, "communityd.toml"), [
    `community_did = "${community.did}"`,
    `administrator_did = "${moderator.did}"`,
    `community_pds_url = "${community.origin}"`,
    `allowed_uid = ${uid}`,
    'reader_adapter = "pds"',
    'ledger_adapter = "pds"',
    'writer_adapter = "pds"',
    'credential_provider = "env_file"',
    'credential_ref = "env:PCV2_COMMUNITY_CREDENTIAL"',
    "request_timeout_ms = 5000",
    "max_retries = 0",
    `operation_journal_path = "${join(communitydDir, "authority.sqlite3")}"`,
    `authority_socket_path = "${socketPath}"`,
    `web_peer_uid = ${uid}`,
    `policy_peer_uid = ${policyUid}`,
    `plc_directory_url = "${PLC}"`,
    "allow_loopback_public_endpoints = true",
    "",
  ].join("\n"));
  const communityd = await startProcess("communityd", PYTHON, ["-c", "from communityd.serve_cli import main; raise SystemExit(main())", "--config", join(communitydDir, "communityd.toml")], {
    cwd: ROOT,
    env: { PYTHONPATH, PCV2_COMMUNITY_CREDENTIAL: credentialPath },
  });
  await waitFor(() => {
    if (communityd.child.exitCode !== null) throw new Error(`communityd exited: ${communityd.log.slice(-5).join(" | ")}`);
    return existsSync(socketPath);
  }, { what: "communityd socket" });

  // Observer: real store, verifier and projection API; polling transport.
  observer = await startProcess("observer", PYTHON, [
    join(ROOT, "qualification", "pcv2", "observer_service.py"),
    "--root", join(SCRATCH, "observer"),
    "--plc", PLC,
    "--community-did", community.did,
    "--administrator-did", moderator.did,
    "--repos", [participant.did, moderator.did, community.did].join(","),
  ], { cwd: ROOT, env: { PYTHONPATH } });
  const announced = JSON.parse(await waitForLine(observer, /^\{"projection"/));
  projectionOrigin = announced.projection;
  controlOrigin = announced.control;

  // community-policy: real worker with its own state, run once per step as
  // the configured policy peer UID. Its configuration names container paths.
  await mkdir(join(policyDir, "state"), { recursive: true });
  await chmod(policyDir, 0o750);
  await chmod(join(policyDir, "state"), 0o770); // the policy UID writes its SQLite state here through the group
  await writeFile(join(policyDir, "community-policy.toml"), [
    `community_did = "${community.did}"`,
    `observer_origin = "${projectionOrigin}"`,
    'authority_socket = "/authority/communityd.sock"',
    'state_path = "/policy/state/policy.sqlite3"',
    "poll_interval_seconds = 5.0",
    "request_timeout_seconds = 10.0",
    "",
  ].join("\n"), { mode: 0o640 });
  policyArgs = [
    "run", "--rm", "--network", "host", "--user", `${policyUid}:${process.getgid()}`,
    "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONPATH=/src/community-model:/src/community-policy",
    "--mount", "type=bind,source=/usr,target=/usr,readonly",
    "--mount", `type=bind,source=${join(ROOT, "packages", "community-model", "src")},target=/src/community-model,readonly`,
    "--mount", `type=bind,source=${join(ROOT, "packages", "community-policy", "src")},target=/src/community-policy,readonly`,
    "--mount", `type=bind,source=${policyDir},target=/policy`,
    "--mount", `type=bind,source=${socketDir},target=/authority`,
    POLICY_IMAGE, POLICY_PYTHON, "-m", "community_policy", "--config", "/policy/community-policy.toml", "run-once",
  ];

  // community-live on a loopback origin; OAuth loopback client.
  const probe = createHttpServer();
  livePort = await listen(probe);
  await new Promise((resolve) => probe.close(resolve));
  LIVE = `http://127.0.0.1:${livePort}`;
  liveEnv = {
    COMMUNITY_PUBLIC_URL: LIVE,
    COMMUNITY_DID: community.did,
    COMMUNITY_NAME: COMMUNITY_NAME,
    COMMUNITY_PURPOSE: COMMUNITY_PURPOSE,
    COMMUNITY_MODERATOR_DID: moderator.did,
    COMMUNITY_RUNTIME_DIR: runtimeDir,
    COMMUNITY_OBSERVER_URL: projectionOrigin,
    COMMUNITY_APPVIEW_ORIGIN: `http://127.0.0.1:${appViewPort}`,
    COMMUNITY_AUTHORITY_SOCKET: socketPath,
    COMMUNITY_PLC_DIRECTORY_URL: PLC,
    COMMUNITY_HANDLE_RESOLVER_URL: PLC,
    COMMUNITY_INTEGRATION_FAULTS: "enabled",
    COMMUNITY_INTEGRATION_FAULT_DIR: faultDir,
    COMMUNITY_SNAPSHOT_SECRET: randomBytes(32).toString("base64url"),
    PORT: String(livePort),
  };
  await startLive();

  // community-notify: real worker and HTTPS sender against the loopback room.
  notifyConfigPath = join(notifyDir, "community-notify.toml");
  await writeFile(notifyConfigPath, [
    `projection_origin = "${projectionOrigin}"`,
    `community_did = "${community.did}"`,
    `community_name = "${COMMUNITY_NAME}"`,
    `public_base_url = "https://127.0.0.1:${livePort}"`,
    `webhook_url = "https://127.0.0.1:${webhookPort}/room/incoming"`,
    'webhook_payload_key = "content"',
    "poll_interval_seconds = 30.0",
    `cursor_path = "${join(notifyDir, "cursor.json")}"`,
    "",
  ].join("\n"), { mode: 0o600 });
  receipt.payloads.notifyPublicBaseNote = `community-notify refuses a non-https public_base_url, so its links use https://127.0.0.1:${livePort} while community-live actually serves ${LIVE}; only the path is asserted.`;

  browser = await chromium.launch({ executablePath: browserExecutable });
  const participantContext = await newContext();
  const moderatorContext = await newContext();
  const anonContext = await newContext();
  const pPage = await participantContext.newPage();
  const mPage = await moderatorContext.newPage();
  const aPage = await anonContext.newPage();
  receipt.timings.bringUpMs = Date.now() - startedAt;
  receipt.recordCounts.afterBringUp = await counts();

  // ------------------------------------------------------------ happy path --

  await must("H0", "notify first start baselines an empty projection and creates its cursor", async (ev) => {
    await ingest();
    ev.notify = await notifyOnce();
    check(ev.notify.code === 0 && ev.notify.counts.baselined === 0 && ev.notify.counts.sent === 0, "expected an empty baseline", ev.notify);
    check(existsSync(join(notifyDir, "cursor.json")), "cursor file must exist after first start");
  });

  await must("H1", "signed-out home renders name, purpose, What is this?, and only the sign-in form", async (ev) => {
    const response = await aPage.goto(`${LIVE}/`);
    ev.status = response.status();
    ev.text = await mainText(aPage);
    check(ev.status === 200, "home status");
    check(ev.text.includes(COMMUNITY_NAME) || (await aPage.title()) === COMMUNITY_NAME, "community name missing");
    check(ev.text.includes(COMMUNITY_PURPOSE), "purpose missing");
    check(ev.text.includes("What is this?"), "What is this? missing");
    ev.forms = await aPage.locator("form").evaluateAll((forms) => forms.map((form) => form.getAttribute("action")));
    check(ev.forms.length === 1 && ev.forms[0] === "/oauth/login", "exactly one form, the sign-in form", ev.forms);
    check(ev.text.includes("Sign in with your Bluesky (ATProto) account"), "sign-in explanation missing");
  });

  const participantOAuth = {};
  await must("H2", "participant signs in through the real PDS OAuth flow and lands on /", async (ev) => {
    Object.assign(ev, await oauthSignIn(pPage, participant, { capture: participantOAuth }));
    check(ev.prefilled === participant.handle, "PDS sign-in page carries the handle as login hint", ev.prefilled);
    check(ev.finalUrl === `${LIVE}/`, "landed on /", ev.finalUrl);
    check(ev.text.includes(participant.did), "session DID shown", ev.text);
    check(/Repository/.test(ev.consentText), "consent page named the repository scope", ev.consentText);
    ev.cookies = (await participantContext.cookies(LIVE)).map((cookie) => ({ name: cookie.name, httpOnly: cookie.httpOnly, sameSite: cookie.sameSite }));
    check(ev.cookies.some((cookie) => cookie.name === "community_session" && cookie.httpOnly), "HttpOnly session cookie", ev.cookies);
    check(typeof participantOAuth.callbackUrl === "string", "callback observed");
    delete ev.consentText;
  });

  await must("H2b", "return path not reflected: an off-site return target is not echoed on the home page", async (ev) => {
    // The return parameter is only honoured for local /d/ paths; the
    // honoured case is exercised once a discussion exists (H9b).
    const response = await rawGet("/?return=https://evil.invalid/");
    ev.status = response.status;
    check(!response.html.includes("evil.invalid"), "off-site return target must not be reflected");
    check(response.status === 200, "home renders");
  });

  await must("H3", "the participant's ordinary post exists in their own repository", async (ev) => {
    const records = await listRecords(participant.origin, participant.did, POST);
    ev.posts = records.map((record) => ({ uri: record.uri, cid: record.cid }));
    check(records.some((record) => record.uri === post1.uri && record.cid === post1.cid), "post1 present with its CID");
  });

  let submit1;
  await must("H4", "submit post1 by at:// URI: ownership by session DID, exact CID, only a submit record created, through the journal", async (ev) => {
    ev.before = await counts();
    await pPage.goto(`${LIVE}/`);
    ev.formFields = await pPage.locator('form[action="/submit-existing"] input, form[action="/submit-existing"] textarea').evaluateAll((els) => els.map((el) => el.getAttribute("name")));
    check(ev.formFields.every((name) => name === "csrf" || name === "post"), "the form carries no CID or DID field (CID is read back server-side)", ev.formFields);
    ev.formCopy = await pPage.locator('form[action="/submit-existing"]').innerText();
    check(/The post is not changed; this asks the moderator to add it here/.test(ev.formCopy), "consequence stated before submission", ev.formCopy);
    await pPage.fill('form[action="/submit-existing"] input[name="post"]', post1.uri);
    await pPage.click('form[action="/submit-existing"] button');
    await pPage.waitForLoadState();
    ev.status = "rendered";
    ev.text = await mainText(pPage);
    check(ev.text.includes("Submitted. Your post is now waiting for the moderator to add it here."), "truthful pending message", ev.text);
    check(!/posted to the community|now in the community/i.test(ev.text), "no premature success claim", ev.text);
    ev.after = await counts();
    check(ev.after.participant.posts === ev.before.participant.posts, "no new post created");
    check(ev.after.participant.submits === ev.before.participant.submits + 1, "exactly one submit record created");
    const submits = await listRecords(participant.origin, participant.did, SUBMIT);
    submit1 = submits.find((record) => record.value.subject?.uri === post1.uri);
    check(submit1 !== undefined, "submit names post1");
    ev.submitRecord = { uri: submit1.uri, cid: submit1.cid, value: submit1.value };
    check(submit1.value.subject.cid === post1.cid, "submit carries the exact current CID read back from the PDS", submit1.value.subject);
    check(submit1.value.community === community.did, "submit names the community");
    // Journal: the operation page exists and resumes cleanly with no new record.
    const operationId = existingPostOperationId(community.did, { uri: post1.uri, cid: post1.cid });
    const page = await pPage.goto(`${LIVE}/operation?id=${operationId}`);
    check(page.status() === 200, "operation page exists", page.status());
    ev.operationPageText = await mainText(pPage);
    await pPage.click('form[action="/operation/resume"] button');
    await pPage.waitForLoadState();
    ev.resumedText = await mainText(pPage);
    check(ev.resumedText.includes("Submitted. Your post is now waiting for the moderator"), "resume reports the committed state", ev.resumedText);
    ev.afterResume = await counts();
    check(ev.afterResume.participant.submits === ev.after.participant.submits, "resume created nothing");
    const journal = JSON.parse(await readFile(join(runtimeDir, "operations", `${encodeURIComponent(participant.did)}.json`), "utf8"));
    ev.journalPhases = Object.fromEntries(Object.entries(journal.operations).map(([key, op]) => [key, op.phase]));
    check(ev.journalPhases[`${operationId}:context`] === "committed", "journal records the committed context write", ev.journalPhases);
  });

  await must("H5", "/mine shows the submission as waiting for the moderator", async (ev) => {
    ev.ingest = await ingest();
    check(ev.ingest.verdicts.some((verdict) => verdict.collection === SUBMIT && verdict.outcome === "verified" && verdict.method === "repo-proof-v1"), "submission verified by repository proof", ev.ingest);
    await pPage.goto(`${LIVE}/mine`);
    ev.text = await mainText(pPage);
    check(ev.text.includes("Waiting for the moderator"), "waiting heading", ev.text);
    check(ev.text.includes("The moderator has not admitted them yet, so they are not in the community view"), "truthful explanation", ev.text);
    check(ev.text.includes(post1.value?.text ?? "First isolated post"), "post text shown via the AppView stand-in", ev.text);
    check(ev.text.includes("(text from Bluesky, unverified)"), "hydration labelled unverified", ev.text);
  });

  await must("H6", "observer ingests the submission; notify emits exactly one pending event", async (ev) => {
    ev.ingest = await ingest();
    const queue = await projection("/moderation-queue");
    ev.queue = queue.submissions;
    check(queue.submissions.length === 1 && queue.submissions[0].submission.uri === submit1.uri && queue.submissions[0].submission.cid === submit1.cid, "queue holds exactly the verified submission", queue.submissions);
    const before = webhook.received.length;
    ev.notify = await notifyOnce();
    check(ev.notify.counts.sent === 1 && ev.notify.counts.failed === 0, "exactly one event sent", ev.notify);
    check(webhook.received.length === before + 1, "webhook received exactly one payload");
    ev.payload = webhook.received.at(-1).payload;
    receipt.payloads.pendingEvent = ev.payload;
    const expected = `[${COMMUNITY_NAME}] pending: A new post is waiting for the moderator.\nhttps://127.0.0.1:${livePort}/\nPublic post: https://bsky.app/profile/${participant.did}/post/${rkeyOf(post1.uri)}`;
    check(ev.payload.content === expected, "pending payload has the fixed shape", { got: ev.payload, expected });
    check(!ev.payload.content.includes("First isolated post"), "payload never includes post text");
  });

  await must("H12", "restart community-live and notify after submit, before admit: no duplicate record, no duplicate notification, session survives", async (ev) => {
    await stopProcess(liveProcess);
    await startLive();
    ev.notify = await notifyOnce();
    check(ev.notify.counts.sent === 0 && ev.notify.counts.observed === 1, "re-run sends nothing new", ev.notify);
    ev.counts = await counts();
    check(ev.counts.participant.submits === 1, "still exactly one submit record", ev.counts);
    await pPage.goto(`${LIVE}/mine`);
    ev.mine = await bodyText(pPage);
    check(ev.mine.includes(participant.did) && ev.mine.includes("Waiting for the moderator"), "participant session and waiting state survive the restart", ev.mine);
    const operationId = existingPostOperationId(community.did, { uri: post1.uri, cid: post1.cid });
    await pPage.goto(`${LIVE}/operation?id=${operationId}`);
    await pPage.click('form[action="/operation/resume"] button');
    await pPage.waitForLoadState();
    ev.resumeAfterRestart = await mainText(pPage);
    check((await counts()).participant.submits === 1, "resume after restart wrote nothing");
  });

  // ------------------------------------------- negatives: sign-in and auth --

  await negative("N-malformed-handle", "malformed handle is a 400 page", async (ev) => {
    const r = await rawPost("/oauth/login", { handle: "not a handle!!" });
    ev.status = r.status; ev.text = r.text;
    check(r.status === 400 && r.text.includes("That handle could not be found. Check it and try again."), "400 with plain refusal", r);
  });
  await negative("N-unknown-account", "unknown account is a 400 page", async (ev) => {
    const r = await rawPost("/oauth/login", { handle: "nobody.test" });
    ev.status = r.status; ev.text = r.text;
    check(r.status === 400 && r.text.includes("That handle could not be found"), "400 with plain refusal", r);
  });
  await negative("N-declined-consent", "declining consent on the PDS page yields a 400 page and no session", async (ev) => {
    const context = await newContext();
    try {
      const page = await context.newPage();
      const result = await oauthSignIn(page, moderator, { deny: true });
      ev.finalPath = new URL(result.finalUrl).pathname;
      ev.title = result.title; ev.text = result.text;
      ev.status = (await page.evaluate(() => performance.getEntriesByType("navigation").at(-1)?.responseStatus)) ?? null;
      check(ev.finalPath === "/oauth/callback" && result.text.includes("Sign-in was not completed. Nothing changed."), "400 page text", result.text);
      check(result.title === "That request was not understood", "400 title", result.title);
      ev.cookies = (await context.cookies(LIVE)).map((cookie) => cookie.name);
      check(!ev.cookies.includes("community_session"), "no session cookie after denial", ev.cookies);
      const home = await rawGet("/", { cookie: await cookieHeader(context) });
      check(home.text.includes("Sign in with your Bluesky"), "still signed out");
    } finally {
      await context.close();
    }
  });
  await negative("N-callback-forged-state", "callback with unknown state is a 400 page", async (ev) => {
    const r = await rawGet(`/oauth/callback?state=forged-state&code=forged-code&iss=${encodeURIComponent(participant.origin)}`);
    ev.status = r.status; ev.text = r.text.slice(0, 200);
    check(r.status === 400 && r.text.includes("Sign-in was not completed. Nothing changed."), "400", r.status);
  });
  await negative("N-callback-replayed", "replaying the participant's consumed callback is a 400 page", async (ev) => {
    const url = new URL(participantOAuth.callbackUrl);
    ev.params = [...url.searchParams.keys()];
    const r = await rawGet(`${url.pathname}${url.search}`);
    ev.status = r.status; ev.text = r.text.slice(0, 200);
    check(r.status === 400 && r.text.includes("Sign-in was not completed"), "400", r.status);
  });
  await negative("N-callback-other-browser", "a callback completed by a browser that did not start the sign-in is a 400 page with no session; the starting browser can still complete it", async (ev) => {
    // Login CSRF: the callback is held before it reaches community-live,
    // replayed from a cookie-less client, then released to its own browser.
    const context = await newContext();
    try {
      const page = await context.newPage();
      await page.goto(`${LIVE}/`);
      await page.fill('form.signin input[name="handle"]', participant.handle);
      await Promise.all([page.waitForURL(/\/oauth\/authorize/), page.click("form.signin button")]);
      await page.waitForSelector('input[name="password"]');
      await page.fill('input[name="password"]', participant.password);
      await page.click("button[type=submit]:has-text('Sign in')");
      const consent = page.getByRole("button", { name: "Authorize" });
      await consent.waitFor();
      // Hold the callback before community-live sees it: the app is stopped
      // while consent is given, so the browser's redirect to /oauth/callback
      // cannot complete; the URL it tried is taken from the request. The
      // OAuth state store and the login cookie both survive the restart.
      const callbacks = [];
      const listener = (request) => { if (request.url().startsWith(`${LIVE}/oauth/callback`)) callbacks.push(request.url()); };
      page.on("request", listener);
      await stopProcess(liveProcess);
      await consent.click();
      await waitFor(() => callbacks.length > 0, { what: "the browser's callback request" });
      await page.waitForLoadState().catch(() => undefined);
      page.off("request", listener);
      await startLive();
      const held = callbacks[0];
      ev.heldByStoppingApp = true;
      check(typeof held === "string", "callback URL captured before community-live saw it");
      ev.params = [...new URL(held).searchParams.keys()];
      ev.loginCookieInStartingBrowser = (await context.cookies(`${LIVE}/oauth/callback`)).some((cookie) => cookie.name === "community_login");
      check(ev.loginCookieInStartingBrowser, "the starting browser holds the login cookie");
      const stranger = await rawGet(held.slice(LIVE.length));
      ev.stranger = { status: stranger.status, text: stranger.text.slice(0, 160), setCookie: stranger.setCookie.map((value) => value.split("=")[0]) };
      check(stranger.status === 400 && stranger.text.includes("Sign-in was not completed. Nothing changed."), "cookie-less completion is a 400 page", ev.stranger);
      check(!stranger.setCookie.some((value) => /^community_session=[^;]/.test(value)), "no session cookie issued to the stranger", stranger.setCookie);
      const release = await page.goto(held);
      ev.owner = { status: release.status(), finalUrl: page.url(), text: (await mainText(page)).slice(0, 160) };
      ev.ownerCookies = (await context.cookies(LIVE)).map((cookie) => cookie.name);
      if (ev.owner.finalUrl === `${LIVE}/` && ev.ownerCookies.includes("community_session")) {
        ev.ownerOutcome = "completed normally: the cookie-less attempt was refused before the state was consumed";
      } else {
        ev.ownerOutcome = "refused: the state had been consumed by the cookie-less attempt";
        check(ev.owner.status === 400 && !ev.ownerCookies.includes("community_session"), "starting browser is refused cleanly", ev.owner);
      }
    } finally {
      await context.close();
    }
  });
  await negative("N-signed-out-gets", "signed-out GET /mine, /moderation, /operation are refused with a sign-in explanation", async (ev) => {
    ev.results = {};
    for (const path of ["/mine", "/moderation", "/operation?id=existing-x"]) {
      const r = await rawGet(path);
      ev.results[path] = { status: r.status, text: r.text.slice(0, 160) };
      check(r.status === 401 && r.text.includes("Sign in is required to view this page.") && r.text.includes("Sign in with your Bluesky"), `${path} refused with sign-in form`, ev.results[path]);
    }
  });
  await negative("N-signed-out-posts", "signed-out POST to every mutation route is refused and changes no record", async (ev) => {
    const before = await counts();
    ev.results = {};
    const attempts = {
      "/contribute": { csrf: "x", text: "signed-out attempt" },
      "/submit-existing": { csrf: "x", post: post2.uri },
      "/operation/resume": { csrf: "x", operationId: "existing-x" },
      "/seen": { csrf: "x", snapshot: "x" },
      "/moderate": { csrf: "x", kind: "admit-root", uri: submit1.uri, cid: submit1.cid },
      "/signout": { csrf: "x" },
      "/disconnect": { csrf: "x" },
    };
    for (const [path, fields] of Object.entries(attempts)) {
      const r = await rawPost(path, fields);
      ev.results[path] = { status: r.status, text: r.text.slice(0, 120) };
      check(r.status === 401, `${path} refused`, ev.results[path]);
      const wrongOrigin = await rawPost(path, fields, { origin: "https://evil.invalid" });
      check(wrongOrigin.status === 403, `${path} cross-origin refused`, wrongOrigin.status);
    }
    ev.after = await counts();
    check(JSON.stringify(ev.after) === JSON.stringify(before), "record counts unchanged", ev.after);
  });
  await negative("N-participant-moderation", "the participant cannot open /moderation or admit", async (ev) => {
    const cookie = await cookieHeader(participantContext);
    const r = await rawGet("/moderation", { cookie });
    ev.get = { status: r.status, text: r.text.slice(0, 160) };
    check(r.status === 403 && r.text.includes("Moderator permission is required."), "403", ev.get);
    await pPage.goto(`${LIVE}/`);
    const csrf = await csrfFor(pPage);
    const before = await counts();
    const post = await rawPost("/moderate", { csrf, kind: "admit-root", uri: submit1.uri, cid: submit1.cid }, { cookie });
    ev.post = { status: post.status, text: post.text.slice(0, 160) };
    check(post.status === 403, "admit refused", ev.post);
    check((await counts()).community.admissions === before.community.admissions, "no admission created");
  });

  // ---------------------------------------- negatives: existing-post submit --

  async function submitExisting(page, reference, extra = {}) {
    await page.goto(`${LIVE}/`);
    const csrf = await csrfFor(page);
    const cookie = await cookieHeader(page.context());
    return rawPost("/submit-existing", { csrf, post: reference, ...extra }, { cookie });
  }
  await negative("N-others-post-by-did", "submitting the moderator's post by AT URI is a plain 403 refusal", async (ev) => {
    const before = await counts();
    const r = await submitExisting(pPage, moderatorPost.uri);
    ev.status = r.status; ev.text = r.text.slice(0, 200);
    check(r.status === 403 && r.text.includes("You can only add your own posts here."), "403 plain refusal", r);
    check((await counts()).participant.submits === before.participant.submits, "no record created");
  });
  await negative("N-others-post-by-handle", "submitting the moderator's post by bsky.app handle link is a plain 403 refusal", async (ev) => {
    const r = await submitExisting(pPage, `https://bsky.app/profile/${moderator.handle}/post/${rkeyOf(moderatorPost.uri)}`);
    ev.status = r.status; ev.text = r.text.slice(0, 200);
    check(r.status === 403 && r.text.includes("You can only add your own posts here."), "403 plain refusal", r);
  });
  await negative("N-others-post-wrong-did-in-url", "a bsky.app link naming another DID is a plain 403 refusal", async (ev) => {
    const r = await submitExisting(pPage, `https://bsky.app/profile/${moderator.did}/post/${rkeyOf(moderatorPost.uri)}`);
    ev.status = r.status; ev.text = r.text.slice(0, 200);
    check(r.status === 403 && r.text.includes("You can only add your own posts here."), "403", r);
  });
  await negative("N-malformed-reference", "a non-post link is refused with a specific message", async (ev) => {
    ev.results = [];
    for (const reference of ["https://bsky.app/profile/participant.test/lists/abc", "https://example.invalid/x", "at://did:plc:x/app.bsky.feed.like/abc"]) {
      const r = await submitExisting(pPage, reference);
      ev.results.push({ reference, status: r.status, text: r.text.slice(0, 120) });
      check(r.status === 400, `${reference} is a 400`, r.status);
    }
  });
  await negative("N-deleted-source", "a deleted source post is refused with a message naming the situation", async (ev) => {
    await deleteRecord(participant, POST, rkeyOf(post3.uri));
    const before = await counts();
    const r = await submitExisting(pPage, post3.uri);
    ev.status = r.status; ev.text = r.text.slice(0, 200);
    check(r.status === 404 && r.text.includes("That post is not in your Bluesky account; it may have been deleted."), "404 naming deletion", r);
    check((await counts()).participant.submits === before.participant.submits, "no record created");
  });
  await negative("N-cid-substitution", "a forged cid form field is ignored; the record carries the CID read back from the PDS", async (ev) => {
    const before = await counts();
    const r = await submitExisting(pPage, post4.uri, { cid: "bafyreiforgedforgedforgedforgedforgedforgedforgedforgedfo" });
    ev.status = r.status; ev.text = r.text.slice(0, 160);
    check(r.status === 200, "submission accepted", r);
    const submits = await listRecords(participant.origin, participant.did, SUBMIT);
    const record = submits.find((item) => item.value.subject?.uri === post4.uri);
    ev.subject = record?.value.subject;
    check(record !== undefined && record.value.subject.cid === post4.cid, "subject CID is the real current CID", ev.subject);
    check(submits.length === before.participant.submits + 1, "exactly one new record");
  });
  await negative("N-appview-down-own-handle", "with the AppView unavailable, the participant's own-post-by-handle link is 'couldn't confirm', not 'not yours'", async (ev) => {
    await stopProcess(liveProcess); await startLive(); // drop the profile cache
    appView.mode = "unavailable";
    try {
      const before = await counts();
      const r = await submitExisting(pPage, `https://bsky.app/profile/${participant.handle}/post/${rkeyOf(post2.uri)}`);
      ev.status = r.status; ev.text = r.text.slice(0, 300);
      check(r.status === 503, "503", r.status);
      check(r.text.includes("That could not be checked right now"), "503 page title is specific, not 'Something went wrong'", r.text);
      check(r.text.includes("We couldn't confirm that link is yours right now."), "couldn't-confirm message", r.text);
      check(r.text.includes(participant.did), "message names the DID form to paste", r.text);
      check(!r.text.includes("You can only add your own posts here"), "not a refusal");
      check((await counts()).participant.submits === before.participant.submits, "no record created");
    } finally {
      appView.mode = "normal";
    }
  });

  let submit2;
  await must("H4b", "submit post2 by its bsky.app handle link once the AppView answers", async (ev) => {
    await stopProcess(liveProcess); await startLive(); // drop the negative profile-cache entry
    const before = await counts();
    await pPage.goto(`${LIVE}/`);
    await pPage.fill('form[action="/submit-existing"] input[name="post"]', `https://bsky.app/profile/${participant.handle}/post/${rkeyOf(post2.uri)}`);
    await pPage.click('form[action="/submit-existing"] button');
    await pPage.waitForLoadState();
    ev.text = await mainText(pPage);
    check(ev.text.includes("Submitted. Your post is now waiting for the moderator"), "pending message", ev.text);
    const submits = await listRecords(participant.origin, participant.did, SUBMIT);
    submit2 = submits.find((item) => item.value.subject?.uri === post2.uri);
    check(submit2 !== undefined && submit2.value.subject.cid === post2.cid, "submit for post2 with exact CID", submit2?.value);
    check(submits.length === before.participant.submits + 1, "one new record");
  });
  await negative("N-duplicate-submit-pending", "submitting post1 again while pending creates no second record and the page is truthful", async (ev) => {
    const before = await counts();
    const r = await submitExisting(pPage, post1.uri);
    ev.status = r.status; ev.text = r.text.slice(0, 200);
    check(r.status === 200, "200", r.status);
    check(r.text.includes("You already asked to add this exact post; nothing new was created."), "the page says it was a repeat", r.text);
    check(!r.text.includes("now waiting for the moderator"), "no restated 'now waiting'", r.text);
    check((await counts()).participant.submits === before.participant.submits, "no second submit record");
  });

  // -------------------------------------------------------------- moderator --

  await must("H7a", "moderator signs in through the real PDS OAuth flow in a separate browser", async (ev) => {
    Object.assign(ev, await oauthSignIn(mPage, moderator));
    check(ev.finalUrl === `${LIVE}/` && ev.text.includes(moderator.did) && ev.text.includes("Moderate"), "moderator home with Moderate link", ev.text);
    delete ev.consentText;
  });
  await must("H7b", "moderator queue shows the submitted posts' text via the AppView stand-in, labelled unverified", async (ev) => {
    await ingest();
    await mPage.goto(`${LIVE}/moderation`);
    ev.text = await mainText(mPage);
    check(ev.text.includes("First isolated post") && ev.text.includes("Second isolated post"), "both texts", ev.text);
    check(ev.text.includes("(text from Bluesky, unverified)"), "unverified label", ev.text);
    check(ev.text.includes(participant.handle), "author handle hydrated", ev.text);
    ev.admitForms = await mPage.locator('form[action="/moderate"] input[name="uri"]').evaluateAll((els) => els.map((el) => el.value));
    check(ev.admitForms.includes(submit1.uri), "admit form targets the submission URI", ev.admitForms);
  });
  await negative("N-appview-down-moderator", "with the AppView unavailable the moderator sees link-only entries", async (ev) => {
    await stopProcess(liveProcess); await startLive();
    appView.mode = "unavailable";
    try {
      await mPage.goto(`${LIVE}/moderation`);
      ev.text = await mainText(mPage);
      check(!ev.text.includes("First isolated post"), "no text", ev.text);
      check(ev.text.includes("Public post on Bluesky") && ev.text.includes(submit1.uri), "link and submission URI still shown", ev.text);
      check(ev.text.includes(participant.did), "author falls back to DID", ev.text);
      check(await mPage.locator("form[action='/moderate']").count() >= 2, "admit forms remain");
    } finally {
      appView.mode = "normal";
    }
  });
  await negative("N-appview-mismatch", "when the AppView reports a different CID no text is shown", async (ev) => {
    await stopProcess(liveProcess); await startLive();
    appView.mode = "mismatch";
    try {
      await mPage.goto(`${LIVE}/moderation`);
      ev.text = await mainText(mPage);
      check(!ev.text.includes("First isolated post") && !ev.text.includes("Second isolated post"), "no text on CID mismatch", ev.text);
      check(ev.text.includes("Public post on Bluesky"), "link remains");
    } finally {
      appView.mode = "normal";
    }
  });
  await negative("N-source-replaced", "post2 replaced under the same rkey: queue shows link-only, admission of the stale exact subject is refused", async (ev) => {
    await putRecord(participant, POST, rkeyOf(post2.uri), { $type: POST, text: "Second isolated post, REPLACED after submission.", createdAt: "2026-09-25T09:01:00.000Z" });
    await stopProcess(liveProcess); await startLive();
    await mPage.goto(`${LIVE}/moderation`);
    ev.text = await mainText(mPage);
    check(ev.text.includes("First isolated post"), "post1 text still shown", ev.text);
    check(!ev.text.includes("Second isolated post") && !ev.text.includes("REPLACED"), "no text for the replaced post (CID mismatch)", ev.text);
    const before = await counts();
    const csrf = await csrfFor(mPage);
    const r = await rawPost("/moderate", { csrf, kind: "admit-root", uri: submit2.uri, cid: submit2.cid }, { cookie: await cookieHeader(moderatorContext) });
    ev.admit = { status: r.status, text: r.text.slice(0, 200) };
    check(r.status === 409 && r.text.includes("Not recorded"), "admission of a stale subject is refused", ev.admit);
    check((await counts()).community.admissions === before.community.admissions, "no admission record");
  });

  let admission;
  await must("H7c", "moderator admits post1 from the queue", async (ev) => {
    const before = await counts();
    await mPage.goto(`${LIVE}/moderation`);
    const item = mPage.locator("li", { hasText: submit1.uri });
    await item.getByRole("button", { name: "Admit" }).click();
    await mPage.waitForLoadState();
    ev.text = await mainText(mPage);
    check(ev.text.includes("Recorded. The observer may take a moment to catch up."), "recorded", ev.text);
    const after = await counts();
    check(after.community.admissions === before.community.admissions + 1 && after.community.replyPolicies === before.community.replyPolicies + 1, "one admission and one reply policy", after);
    admission = (await listRecords(community.origin, community.did, ADMISSION)).find((record) => record.value.submission?.uri === submit1.uri);
    check(admission !== undefined && admission.value.subject.cid === post1.cid && admission.value.submission.cid === submit1.cid, "admission names exact submission and subject", admission?.value);
    ev.admission = { uri: admission.uri, cid: admission.cid, value: admission.value };
  });
  await negative("N-admit-retry", "moderator refresh/retry of the same admit yields a single admission record", async (ev) => {
    const before = await counts();
    const csrf = await csrfFor(mPage.url().endsWith("/moderation") ? mPage : (await mPage.goto(`${LIVE}/moderation`), mPage));
    const r = await rawPost("/moderate", { csrf, kind: "admit-root", uri: submit1.uri, cid: submit1.cid }, { cookie: await cookieHeader(moderatorContext) });
    ev.retry = { status: r.status, text: r.text.slice(0, 160) };
    // The journal answers the replayed command with the committed result;
    // the page does not distinguish a replay from the first recording.
    check(r.status === 200 && r.text.includes("Recorded. The observer may take a moment to catch up."), "the replay renders 'Recorded.'", ev.retry);
    ev.note = "no 'Already recorded' variant exists; the replay page reads exactly as the first recording";
    const after = await counts();
    check(after.community.admissions === before.community.admissions, "admission count unchanged", after);
    ev.admissions = (await listRecords(community.origin, community.did, ADMISSION)).map((record) => record.uri);
  });
  await negative("N-duplicate-admission-after-ingest", "once the queue no longer lists post1, a duplicate admit is refused or idempotent with no new record", async (ev) => {
    await ingest();
    await mPage.goto(`${LIVE}/moderation`);
    ev.queueText = await mainText(mPage);
    check(!ev.queueText.includes(submit1.uri), "admitted submission left the queue", ev.queueText);
    const before = await counts();
    const csrf = await csrfFor(mPage);
    const r = await rawPost("/moderate", { csrf, kind: "admit-root", uri: submit1.uri, cid: submit1.cid }, { cookie: await cookieHeader(moderatorContext) });
    ev.result = { status: r.status, text: r.text.slice(0, 160) };
    check((await counts()).community.admissions === before.community.admissions, "no new admission record");
  });

  // -------------------------------------------------- notify: admitted event --

  await must("H8", "observer ingests the admission; notify delivers the admitted event with /d/<rkey> and the pending event for post2, surviving one rejection", async (ev) => {
    ev.ingest = await ingest();
    const discussions = await projection("/discussions");
    ev.discussions = discussions.discussions.map((item) => ({ uri: item.discussion.uri, status: item.status, text: item.post?.text }));
    check(discussions.discussions.length === 1 && discussions.discussions[0].discussion.uri === admission.uri, "one visible discussion", ev.discussions);
    const receivedBefore = webhook.received.length;
    webhook.mode = "reject-next";
    ev.first = await notifyOnce();
    // New since the last poll: pending(post2), pending(post4, from the forged-CID attempt), admitted(post1).
    check(ev.first.counts.observed === 3 && ev.first.counts.failed === 1 && ev.first.counts.sent === 2, "one rejected, the other two still delivered", ev.first);
    check(webhook.rejected.length === 1 && webhook.received.length === receivedBefore + 2, "receiver saw one rejection and two deliveries");
    ev.rejectedPayload = webhook.rejected[0].payload;
    ev.second = await notifyOnce();
    check(ev.second.counts.sent === 1 && ev.second.counts.failed === 0, "the rejected event is retried on the next poll", ev.second);
    ev.third = await notifyOnce();
    check(ev.third.counts.sent === 0 && ev.third.counts.failed === 0, "nothing is re-sent afterwards", ev.third);
    const contents = webhook.received.slice(receivedBefore).map((item) => item.payload.content);
    ev.delivered = contents;
    const admitted = contents.find((content) => content.includes("admitted"));
    check(admitted === `[${COMMUNITY_NAME}] admitted: A new discussion was admitted.\nhttps://127.0.0.1:${livePort}/d/${rkeyOf(admission.uri)}`, "admitted payload shape", admitted);
    check(contents.filter((content) => content.includes("pending")).length === 2, "the pending events for post2 and post4 were delivered exactly once each", contents);
    check(contents.some((content) => content.endsWith(`/post/${rkeyOf(post2.uri)}`)) && contents.some((content) => content.endsWith(`/post/${rkeyOf(post4.uri)}`)), "pending events name post2 and post4", contents);
    check(new Set(contents).size === contents.length && webhook.received.map((item) => item.payload.content).filter((content) => content === receipt.payloads.pendingEvent.content).length === 1, "no duplicate deliveries across the run");
    receipt.payloads.admittedEvent = { content: admitted };
    receipt.payloads.rejectedThenRetried = ev.rejectedPayload;
  });

  // ------------------------------------------------------ anonymous reading --

  const rkey = () => rkeyOf(admission.uri);
  await must("H9", "signed-out /d/<rkey> is readable, has no forms and no CSRF token", async (ev) => {
    const response = await aPage.goto(`${LIVE}/d/${rkey()}`);
    ev.status = response.status();
    ev.text = await mainText(aPage);
    check(ev.status === 200 && ev.text.includes("First isolated post"), "readable", ev.text);
    ev.forms = await aPage.locator("form").count();
    ev.csrfInputs = await aPage.locator('input[name="csrf"]').count();
    check(ev.forms === 0 && ev.csrfInputs === 0, "no forms, no CSRF", { forms: ev.forms, csrf: ev.csrfInputs });
    check(ev.text.includes("Sign in to reply"), "sign-in prompt for replies", ev.text);
    check(ev.text.includes("Why is this here?"), "explanation present");
    ev.cookies = (await anonContext.cookies(LIVE)).map((cookie) => cookie.name);
    check(ev.cookies.length === 0, "anonymous reading creates no session", ev.cookies);
    const legacy = await rawGet(`/discussion?rkey=${rkey()}`);
    check(legacy.status === 303 && legacy.location === `/d/${rkey()}`, "legacy route redirects", legacy);
  });
  await must("H9b", "callback state: signing in from the permalink returns to it", async (ev) => {
    const context = await newContext();
    try {
      const page = await context.newPage();
      await page.goto(`${LIVE}/d/${rkey()}`);
      await page.click("a:has-text('Sign in to reply')");
      await page.fill('form.signin input[name="handle"]', participant.handle);
      await Promise.all([page.waitForURL(/\/oauth\/authorize/), page.click("form.signin button")]);
      await page.waitForSelector('input[name="password"]');
      await page.fill('input[name="password"]', participant.password);
      await page.click("button[type=submit]:has-text('Sign in')");
      const consent = page.getByRole("button", { name: "Authorize" });
      await consent.waitFor();
      await Promise.all([page.waitForURL((url) => url.origin === LIVE && !url.pathname.startsWith("/oauth/")), consent.click()]);
      ev.finalPath = new URL(page.url()).pathname;
      check(ev.finalPath === `/d/${rkey()}`, "returned to the permalink", ev.finalPath);
      ev.text = await mainText(page);
      check((await page.locator('form[action="/contribute"]').count()) === 1, "signed-in reply form now present");
    } finally {
      await context.close();
    }
  });
  await must("H9c", "not-found and malformed permalinks are truthful and distinct", async (ev) => {
    const missing = await rawGet("/d/doesnotexist");
    const malformed = await rawGet("/d/bad%20key");
    ev.missing = { status: missing.status, text: missing.text.slice(0, 160) };
    ev.malformed = { status: malformed.status, text: malformed.text.slice(0, 160) };
    check(missing.status === 404 && missing.text.includes("That discussion isn't in this community."), "404", ev.missing);
    check(malformed.status === 400 && malformed.text.includes("That discussion link is malformed."), "400", ev.malformed);
  });

  await negative("N-handle-invalid-own-handle", "when the AppView reports handle.invalid for the participant, their own-post-by-handle link is 'couldn't confirm' (503), and the DID link is accepted", async (ev) => {
    await stopProcess(liveProcess); await startLive(); // drop the profile cache
    appView.mode = "handle-invalid";
    try {
      const post6 = await createRecord(participant, POST, { $type: POST, text: "Sixth isolated post, submitted while the AppView reports handle.invalid.", createdAt: "2026-09-25T09:05:00.000Z" });
      receipt.payloads.participantPosts.post6 = post6.uri;
      const before = await counts();
      const byHandle = await submitExisting(pPage, `https://bsky.app/profile/${participant.handle}/post/${rkeyOf(post6.uri)}`);
      ev.byHandle = { status: byHandle.status, text: byHandle.text.slice(0, 300) };
      check(byHandle.status === 503, "503, not 403", ev.byHandle);
      check(byHandle.text.includes("We couldn't confirm that link is yours right now."), "couldn't-confirm message", ev.byHandle);
      check(!byHandle.text.includes("You can only add your own posts here"), "not a 'not yours' refusal", ev.byHandle);
      check((await counts()).participant.submits === before.participant.submits, "no record created by the handle link");
      const byDid = await submitExisting(pPage, `https://bsky.app/profile/${participant.did}/post/${rkeyOf(post6.uri)}`);
      ev.byDid = { status: byDid.status, text: byDid.text.slice(0, 200) };
      check(byDid.status === 200 && byDid.text.includes("Submitted. Your post is now waiting for the moderator"), "DID link accepted", ev.byDid);
      const submits = await listRecords(participant.origin, participant.did, SUBMIT);
      const record = submits.find((item) => item.value.subject?.uri === post6.uri);
      check(record !== undefined && record.value.subject.cid === post6.cid && submits.length === before.participant.submits + 1, "exactly one submit with the exact CID", record?.value);
      ev.counts = await counts();
    } finally {
      appView.mode = "normal";
      await stopProcess(liveProcess); await startLive(); // drop the unresolved-handle cache entry
    }
  });

  // ------------------------------------------------- replies and policy --

  const replyText = "First isolated reply, posted from the discussion page.";
  let replyPost;
  let replySubmit;
  let replyAdmission;
  const replyPublicLink = () => `https://bsky.app/profile/${participant.did}/post/${rkeyOf(replyPost.uri)}`;
  await must("H15", "participant posts a reply from /d/<rkey>: one post with reply.root/parent, one submit with discussion, truthful completion copy", async (ev) => {
    const before = await counts();
    await pPage.goto(`${LIVE}/d/${rkey()}`);
    ev.button = await pPage.locator('form[action="/contribute"] button').innerText();
    check(ev.button === "Post reply and add to this discussion", "reply button copy", ev.button);
    ev.note = await pPage.locator("#reply-note").innerText();
    check(ev.note.includes("Your reply is posted publicly on your Bluesky account."), "consequence stated before posting", ev.note);
    ev.formFields = await pPage.locator('form[action="/contribute"] input, form[action="/contribute"] textarea').evaluateAll((els) => els.map((el) => el.getAttribute("name")));
    await pPage.fill('form[action="/contribute"] textarea[name="text"]', replyText);
    await pPage.click('form[action="/contribute"] button');
    await pPage.waitForLoadState();
    ev.text = await mainText(pPage);
    check(ev.text.includes("Posted. It will appear in the discussion once the community records it."), "truthful completion copy", ev.text);
    check(!/waiting for the moderator|now in the discussion|has been added/i.test(ev.text), "no premature claim", ev.text);
    const after = await counts();
    check(after.participant.posts === before.participant.posts + 1 && after.participant.submits === before.participant.submits + 1, "exactly one post and one submit", { before, after });
    check(after.community.replyAdmissions === before.community.replyAdmissions, "nothing written by the community yet", after);
    replyPost = (await listRecords(participant.origin, participant.did, POST)).find((record) => record.value.text === replyText);
    check(replyPost !== undefined, "reply post present in the participant's repository");
    ev.replyPost = { uri: replyPost.uri, cid: replyPost.cid, reply: replyPost.value.reply };
    const reply = replyPost.value.reply ?? {};
    check(reply.root?.uri === post1.uri && reply.root?.cid === post1.cid && reply.parent?.uri === post1.uri && reply.parent?.cid === post1.cid, "reply.root and reply.parent name the exact admitted root post", reply);
    replySubmit = (await listRecords(participant.origin, participant.did, SUBMIT)).find((record) => record.value.subject?.uri === replyPost.uri);
    check(replySubmit !== undefined, "submit names the reply post");
    ev.rkeys = { post: rkeyOf(replyPost.uri), submit: rkeyOf(replySubmit.uri) };
    ev.rkeysCanonical = { post: CANONICAL_TID.test(ev.rkeys.post), submit: CANONICAL_TID.test(ev.rkeys.submit) };
    if (!ev.rkeysCanonical.post || !ev.rkeysCanonical.submit) recordTidDefect("H15 reply", ev.rkeys);
    check(ev.rkeysCanonical.submit, "the reply submit rkey is a canonical TID (the observer refuses any other)", ev.rkeys);
    ev.replySubmit = { uri: replySubmit.uri, cid: replySubmit.cid, value: replySubmit.value };
    check(replySubmit.value.subject.cid === replyPost.cid && replySubmit.value.community === community.did, "submit carries the exact reply CID and the community", replySubmit.value);
    check(replySubmit.value.discussion?.uri === admission.uri && replySubmit.value.discussion?.cid === admission.cid, "submit opts into the exact root admission", replySubmit.value.discussion);
    ev.counts = after;
  });

  await must("H16", "observer offers the reply as a candidate; community-policy (own UID) requests admission through communityd; exactly one replyAdmission, retry idempotent", async (ev) => {
    ev.ingest = await ingest();
    check(ev.ingest.verdicts.some((verdict) => verdict.collection === SUBMIT && verdict.rkey === rkeyOf(replySubmit.uri) && verdict.outcome === "verified"), "reply submission verified by repository proof", ev.ingest.verdicts);
    const offered = await projection("/reply-candidates");
    ev.candidates = offered.candidates;
    check(offered.candidates.length === 1 && offered.candidates[0].submission.uri === replySubmit.uri && offered.candidates[0].submission.cid === replySubmit.cid && offered.candidates[0].rootAdmission.uri === admission.uri, "exactly the reply submission is offered", ev.candidates);
    const before = await counts();
    ev.policy = await policyOnce();
    check(ev.policy.code === 0 && ev.policy.counts !== null, "policy worker ran", ev.policy);
    check(ev.policy.counts.candidates === 1 && ev.policy.counts.committed === 1 && ev.policy.counts.refused === 0 && ev.policy.counts.pending === 0, "one candidate, one committed admission", ev.policy.counts);
    const after = await counts();
    check(after.community.replyAdmissions === before.community.replyAdmissions + 1 && after.community.admissions === before.community.admissions && after.community.modActions === before.community.modActions, "one replyAdmission and nothing else written by the community", { before, after });
    replyAdmission = (await listRecords(community.origin, community.did, REPLY_ADMISSION)).find((record) => record.value.submission?.uri === replySubmit.uri);
    check(replyAdmission !== undefined, "replyAdmission names the submission");
    ev.replyAdmission = { uri: replyAdmission.uri, cid: replyAdmission.cid, value: replyAdmission.value };
    const value = replyAdmission.value;
    check(value.submission.cid === replySubmit.cid && value.subject?.uri === replyPost.uri && value.subject?.cid === replyPost.cid && value.discussion?.uri === admission.uri && value.discussion?.cid === admission.cid, "replyAdmission names the exact submission, reply and root admission", value);
    // The observer still offers the candidate until it ingests the admission;
    // the worker's own state keeps the second run from asking again.
    ev.policyAgain = await policyOnce();
    check(ev.policyAgain.code === 0 && ev.policyAgain.counts?.committed === 0 && ev.policyAgain.counts?.refused === 0, "a second run asks for nothing new", ev.policyAgain);
    ev.counts = await counts();
    check(ev.counts.community.replyAdmissions === after.community.replyAdmissions, "second run wrote nothing", ev.counts);
  });

  await must("H17", "observer ingests the replyAdmission; the reply is shown on /d/<rkey> signed-out and signed-in; the candidate is gone", async (ev) => {
    ev.ingest = await ingest();
    check(ev.ingest.verdicts.some((verdict) => verdict.collection === REPLY_ADMISSION && verdict.outcome === "verified" && verdict.method === "repo-proof-v1"), "replyAdmission verified by repository proof", ev.ingest.verdicts);
    check(ev.ingest.subjects.some((subject) => subject.uri === replyPost.uri && subject.cid === replyPost.cid), "the reply post was resolved as the admission's subject", ev.ingest.subjects);
    const doc = await projection(`/discussions/${encodeURIComponent(rkey())}`);
    ev.replies = doc.replies.map((item) => ({ subject: item.subject, status: item.status, text: item.post?.text }));
    check(doc.replies.length === 1 && doc.replies[0].subject.uri === replyPost.uri && doc.replies[0].status !== "removed" && doc.replies[0].post?.text === replyText, "projection carries the one visible reply with its text", ev.replies);
    check((await projection("/reply-candidates")).candidates.length === 0, "no candidate remains");
    const response = await aPage.goto(`${LIVE}/d/${rkey()}`);
    ev.anonymous = await mainText(aPage);
    check(response.status() === 200 && ev.anonymous.includes(replyText), "signed-out reader sees the reply", ev.anonymous);
    check((await aPage.locator("ol > li").count()) === 1 && (await aPage.locator("form").count()) === 0, "one reply item, no forms");
    ev.anonymousReplyItem = await aPage.locator("ol > li").innerText();
    check(ev.anonymousReplyItem.includes("Why is this here?"), "the reply carries its own explanation", ev.anonymousReplyItem);
    await pPage.goto(`${LIVE}/d/${rkey()}`);
    ev.participant = await mainText(pPage);
    check(ev.participant.includes(replyText), "signed-in participant sees the reply", ev.participant);
    check((await pPage.locator("ol > li form").count()) === 0, "the participant gets no moderation form on the reply");
    ev.counts = await counts();
  });

  let replyRemoval;
  await must("H18", "moderator removes the reply with a reason: tombstone with reason and public-post link, no text, signed-out and signed-in", async (ev) => {
    const before = await counts();
    await mPage.goto(`${LIVE}/d/${rkey()}`);
    const item = mPage.locator("ol > li", { hasText: replyText });
    check((await item.count()) === 1, "moderator sees the reply item");
    ev.moderatorItem = await item.innerText();
    check(ev.moderatorItem.includes(participant.did), "moderator sees the reply author's DID", ev.moderatorItem);
    await item.locator('form[action="/moderate"] input[name="reason"]').fill("isolated reply removal");
    await item.getByRole("button", { name: "Remove from community" }).click();
    await mPage.waitForLoadState();
    ev.moderatorText = await mainText(mPage);
    check(ev.moderatorText.includes("Recorded."), "recorded", ev.moderatorText);
    const after = await counts();
    check(after.community.replyActions === before.community.replyActions + 1 && after.community.modActions === before.community.modActions && after.community.replyAdmissions === before.community.replyAdmissions, "exactly one replyAction record", { before, after });
    replyRemoval = (await listRecords(community.origin, community.did, REPLY_ACTION)).find((record) => record.value.admission?.uri === replyAdmission.uri);
    check(replyRemoval !== undefined && replyRemoval.value.admission.cid === replyAdmission.cid && replyRemoval.value.reason === "isolated reply removal", "replyAction cites the exact reply admission and carries the reason", replyRemoval?.value);
    ev.replyRemoval = { uri: replyRemoval.uri, cid: replyRemoval.cid, value: replyRemoval.value };
    ev.ingest = await ingest();
    for (const [who, page] of [["anonymous", aPage], ["participant", pPage]]) {
      await page.goto(`${LIVE}/d/${rkey()}`);
      const text = await mainText(page);
      ev[who] = text;
      check(text.includes("Removed from this community’s view: isolated reply removal."), `${who}: tombstone names the reason`, text);
      check(!text.includes(replyText), `${who}: no reply text`, text);
      check(text.includes("First isolated post"), `${who}: the root is unaffected`, text);
      const links = await page.locator("ol > li.tombstone a.external").evaluateAll((els) => els.map((el) => [el.textContent, el.getAttribute("href")]));
      check(links.some(([label, href]) => label === "Public post on Bluesky" && href === replyPublicLink()), `${who}: tombstone links the author's public post`, links);
      check((await page.locator("ol > li form").count()) === 0, `${who}: no form on the tombstone`);
    }
    const replyRecord = await xrpc(participant.origin, "com.atproto.repo.getRecord", { query: { repo: participant.did, collection: POST, rkey: rkeyOf(replyPost.uri) } });
    check(replyRecord.cid === replyPost.cid, "the author's reply is unchanged on their PDS");
    await mPage.goto(`${LIVE}/d/${rkey()}`);
    ev.moderatorRestoreForms = await mPage.locator("ol > li.tombstone form button", { hasText: "Restore to community" }).count();
    check(ev.moderatorRestoreForms === 1, "moderator is offered exactly one restore form", ev.moderatorRestoreForms);
    ev.counts = after;
  });

  await must("H19", "moderator restores the reply: text visible again signed-out and signed-in", async (ev) => {
    const before = await counts();
    await mPage.goto(`${LIVE}/d/${rkey()}`);
    const tombstone = mPage.locator("ol > li.tombstone");
    await tombstone.locator('form[action="/moderate"] input[name="reason"]').fill("isolated reply restore");
    await tombstone.getByRole("button", { name: "Restore to community" }).click();
    await mPage.waitForLoadState();
    ev.moderatorText = await mainText(mPage);
    check(ev.moderatorText.includes("Recorded."), "recorded", ev.moderatorText);
    const after = await counts();
    check(after.community.replyActions === before.community.replyActions + 1, "exactly one more replyAction record", { before, after });
    const restore = (await listRecords(community.origin, community.did, REPLY_ACTION)).find((record) => record.value.previousAction?.uri === replyRemoval.uri);
    check(restore !== undefined && restore.value.admission?.uri === replyAdmission.uri, "restore chains to the removal it reverses", restore?.value);
    ev.replyRestore = { uri: restore.uri, cid: restore.cid, value: restore.value };
    ev.ingest = await ingest();
    for (const [who, page] of [["anonymous", aPage], ["participant", pPage]]) {
      await page.goto(`${LIVE}/d/${rkey()}`);
      const text = await mainText(page);
      ev[who] = text;
      check(text.includes(replyText), `${who}: reply text visible again`, text);
      check(!text.includes("Removed from this community’s view"), `${who}: no tombstone`, text);
    }
    ev.counts = after;
  });

  await must("H11", "participant /mine lists the admitted discussion with its reply and Mark as read clears the unread badge", async (ev) => {
    await pPage.goto(`${LIVE}/mine`);
    ev.before = await mainText(pPage);
    check(ev.before.includes("First isolated post"), "discussion listed", ev.before);
    check(!/First isolated post.*Waiting for the moderator|Waiting for the moderator.*First isolated post/.test(ev.before) || !ev.before.includes("First isolated post: a question about repository proofs. Public post on Bluesky"), "admitted post no longer listed as waiting");
    const row = () => pPage.locator("li", { hasText: "First isolated post" }).first();
    ev.unreadBefore = await pPage.locator(".badge", { hasText: "Unread" }).count();
    ev.rowBefore = await row().innerText();
    check(ev.unreadBefore === 1, "exactly one unread badge", ev.unreadBefore);
    check(/unread/i.test(ev.rowBefore), "the discussion's own row is marked unread", ev.rowBefore);
    check(/1 replies/.test(ev.rowBefore), "the row counts the one admitted reply", ev.rowBefore);
    await pPage.click('form[action="/seen"] button');
    await pPage.waitForURL(`${LIVE}/mine`);
    ev.after = await mainText(pPage);
    ev.unreadAfter = await pPage.locator(".badge", { hasText: "Unread" }).count();
    ev.rowAfter = await row().innerText();
    check(ev.unreadAfter === 0, "no unread badge after Mark as read", ev.unreadAfter);
    check(ev.rowAfter.includes("First isolated post") && !/unread/i.test(ev.rowAfter), "the discussion's row is still listed and no longer marked unread", ev.rowAfter);
  });

  await must("H10", "moderator removes the root; the signed-out permalink shows only the tombstone banner and public-post link", async (ev) => {
    await mPage.goto(`${LIVE}/d/${rkey()}`);
    await mPage.fill('form[action="/moderate"] input[name="reason"]', "isolated removal");
    await mPage.click("form[action='/moderate'] button:has-text('Remove from community')");
    await mPage.waitForLoadState();
    ev.moderatorText = await mainText(mPage);
    check(ev.moderatorText.includes("Recorded."), "recorded", ev.moderatorText);
    ev.counts = await counts();
    check(ev.counts.community.modActions === 1, "one modAction record", ev.counts);
    ev.ingest = await ingest();
    const response = await aPage.goto(`${LIVE}/d/${rkey()}`);
    ev.status = response.status();
    ev.text = await mainText(aPage);
    check(ev.status === 200, "still 200");
    check(ev.text.includes("This discussion was removed from this community’s view; the author’s public post is not deleted or changed."), "tombstone banner", ev.text);
    check(!ev.text.includes("First isolated post"), "no post text", ev.text);
    // The root keeps no explanation; the restored reply under it stays
    // visible with its own (replies are moderated independently).
    ev.whyHere = { total: await aPage.locator("details.why").count(), onReplies: await aPage.locator("ol > li details.why").count() };
    check(ev.whyHere.total === ev.whyHere.onReplies, "no Why is this here? for the removed root", ev.whyHere);
    ev.replyStillVisible = ev.text.includes(replyText);
    check(ev.replyStillVisible, "the independently admitted reply remains visible under the tombstone", ev.text);
    ev.links = await aPage.locator("a.external").evaluateAll((els) => els.map((el) => [el.textContent, el.getAttribute("href")]));
    check(ev.links.some(([label, href]) => label === "Public post on Bluesky" && href === `https://bsky.app/profile/${participant.did}/post/${rkeyOf(post1.uri)}`), "public post link", ev.links);
    check((await aPage.locator("article").count()) === 0 && (await aPage.locator("form").count()) === 0, "no article, no forms");
    const home = await rawGet("/");
    ev.homeAfterRemoval = home.text.slice(0, 300);
    check(!home.text.includes("First isolated post"), "removed discussion is not listed on the home page");
    const participantPost = await xrpc(participant.origin, "com.atproto.repo.getRecord", { query: { repo: participant.did, collection: POST, rkey: rkeyOf(post1.uri) } });
    check(participantPost.cid === post1.cid, "the author's post is unchanged on their PDS");
  });
  await must("H10b", "after removal the participant's /mine hides the root's text, shows the fixed removed title and links to the tombstone", async (ev) => {
    await pPage.goto(`${LIVE}/mine`);
    ev.text = await mainText(pPage);
    check(!ev.text.includes("First isolated post"), "removed root's text absent from /mine", ev.text);
    check(ev.text.includes("Removed from the community"), "fixed removed title shown", ev.text);
    ev.links = await pPage.locator("li a").evaluateAll((els) => els.map((el) => [el.textContent, el.getAttribute("href")]));
    check(ev.links.some(([label, href]) => label === "Removed from the community" && href === `/d/${rkey()}`), "the removed title links to the tombstone permalink", ev.links);
    const permalink = await rawGet(`/d/${rkey()}`, { cookie: await cookieHeader(participantContext) });
    check(permalink.status === 200 && permalink.text.includes("This discussion was removed from this community’s view"), "the link resolves to the tombstone", permalink.status);
  });
  await negative("N-reply-after-root-removal", "a reply attempted from the removed discussion is refused: no form, closed message; a stale form replay is recorded", async (ev) => {
    await pPage.goto(`${LIVE}/d/${rkey()}`);
    ev.text = await mainText(pPage);
    ev.replyForms = await pPage.locator('form[action="/contribute"]').count();
    check(ev.replyForms === 0, "reply form absent for the signed-in participant", ev.replyForms);
    check(ev.text.includes("This discussion is closed to new community replies."), "the page says the discussion is closed", ev.text);
    check(!ev.text.includes("Sign in to reply"), "no sign-in-to-reply prompt either", ev.text);
    // A reply form captured before the removal and replayed by hand.
    const before = await counts();
    await pPage.goto(`${LIVE}/`);
    const csrf = await csrfFor(pPage);
    const stale = await rawPost("/contribute", {
      csrf, text: "Stale reply replayed after the root was removed.",
      discussionUri: admission.uri, discussionCid: admission.cid,
      rootUri: post1.uri, rootCid: post1.cid, parentUri: post1.uri, parentCid: post1.cid,
    }, { cookie: await cookieHeader(participantContext) });
    ev.stale = { status: stale.status, text: stale.text.slice(0, 200) };
    const after = await counts();
    ev.staleWrote = { posts: after.participant.posts - before.participant.posts, submits: after.participant.submits - before.participant.submits };
    if (ev.staleWrote.posts === 0 && ev.staleWrote.submits === 0) {
      check(stale.status >= 400 && stale.status < 500, "stale replay refused with a 4xx", ev.stale);
    } else {
      // Not part of the pass criterion (the product's own form is gone); the
      // hand-made replay reaching the participant's repository is recorded
      // as a product gap and shown to be inert for the community.
      receipt.defects.push({
        id: "D-stale-reply-form-writes",
        severity: "product gap",
        where: "apps/community-live/src/server.ts (POST /contribute with reply fields does not check the discussion's current status before writing)",
        observed: `A hand-replayed reply form for the removed discussion returned ${stale.status} and wrote ${ev.staleWrote.posts} post and ${ev.staleWrote.submits} submit to the participant's repository; the observer offers no candidate and community-policy admits nothing.`,
        note: "Smallest fix: when replyInput(form) is present, read the discussion from the projection and refuse with 409 unless it is visible and not closed.",
      });
      await ingest();
      ev.candidatesAfterStale = (await projection("/reply-candidates")).candidates.length;
      ev.policyAfterStale = await policyOnce();
      check(ev.candidatesAfterStale === 0 && ev.policyAfterStale.counts?.committed === 0 && (await counts()).community.replyAdmissions === after.community.replyAdmissions, "the stale reply is never admitted", { candidates: ev.candidatesAfterStale, policy: ev.policyAfterStale });
    }
    ev.counts = await counts();
  });
  await negative("N-duplicate-submit-after-admission", "submitting post1 again after admission and removal: no new record; page text quoted", async (ev) => {
    const before = await counts();
    const r = await submitExisting(pPage, post1.uri);
    ev.status = r.status; ev.text = r.text.slice(0, 240);
    check((await counts()).participant.submits === before.participant.submits, "no new submit record");
    // Before the fix in this tranche the page restated "now waiting for the
    // moderator" for a post that had already been admitted and removed.
    check(r.text.includes("You already asked to add this exact post; nothing new was created."), "repeat is named as a repeat", r.text);
    check(!r.text.includes("now waiting for the moderator"), "no false pending claim after admission and removal", r.text);
  });

  // ------------------------------------------------- interrupted operation --

  await must("H13", "interrupted new-post operation (post.once): resume via 'Check exact records and continue' yields exactly one post and one submit", async (ev) => {
    const before = await counts();
    await writeFile(join(faultDir, "post.once"), "");
    await pPage.goto(`${LIVE}/`);
    const text = "Fifth isolated post, written through the interrupted operation.";
    await pPage.fill('form[action="/contribute"] textarea[name="text"]', text);
    const exited = liveProcess.exit;
    let navigationError = null;
    try {
      await Promise.all([pPage.click('form[action="/contribute"] button'), pPage.waitForLoadState("load", { timeout: 15_000 })]);
    } catch (error) {
      navigationError = String(error?.message ?? error).split("\n")[0];
    }
    ev.exit = await Promise.race([exited, sleep(15_000).then(() => "no exit")]);
    check(ev.exit !== "no exit" && ev.exit.signal === "SIGKILL", "community-live was killed after the post commit", ev.exit);
    check(existsSync(join(faultDir, "post.consumed")) && !existsSync(join(faultDir, "post.once")), "trigger consumed");
    ev.browserSaw = navigationError ?? ((await pPage.locator("body").innerText({ timeout: 3000 }).catch(() => "")).replace(/\s+/g, " ").slice(0, 200) || "connection dropped: empty browser error document, no link back to the operation");
    ev.midway = await counts();
    check(ev.midway.participant.posts === before.participant.posts + 1 && ev.midway.participant.submits === before.participant.submits, "post committed, submit not yet written", ev.midway);
    await liveProcess.flush();
    await startLive();
    // The participant finds the interrupted action under "Unfinished actions"
    // on /mine; the plan store on disk is read only as a cross-check.
    await pPage.goto(`${LIVE}/mine`);
    ev.mine = await mainText(pPage);
    check(ev.mine.includes("Unfinished actions") && ev.mine.includes("These actions were interrupted before they finished. Nothing was duplicated"), "/mine lists unfinished actions", ev.mine);
    ev.unfinishedLinks = await pPage.locator("ul.unfinished li a").evaluateAll((els) => els.map((el) => [el.textContent, el.getAttribute("href")]));
    check(ev.unfinishedLinks.length === 1 && ev.unfinishedLinks[0][0] === "A new discussion" && ev.unfinishedLinks[0][1].startsWith("/operation?id="), "exactly one unfinished action, a new discussion, linking to its operation", ev.unfinishedLinks);
    ev.operationId = decodeURIComponent(ev.unfinishedLinks[0][1].slice("/operation?id=".length));
    const planDir = join(runtimeDir, "contribution-plans");
    const plans = [];
    for (const name of await readdir(planDir)) {
      if (name.startsWith(".")) continue;
      plans.push(JSON.parse(await readFile(join(planDir, name), "utf8")));
    }
    const plan = plans.find((item) => item.operationId === ev.operationId);
    check(plan !== undefined && plan.existingPostCid === undefined && plan.authorDid === participant.did && plan.discussion === undefined, "cross-check: the linked operation is the interrupted new-discussion plan on disk", plans.map((item) => item.operationId));
    ev.rkeys = { post: plan.source.rkey, submit: plan.context.rkey };
    ev.rkeysCanonical = { post: CANONICAL_TID.test(ev.rkeys.post), submit: CANONICAL_TID.test(ev.rkeys.submit) };
    if (!ev.rkeysCanonical.post || !ev.rkeysCanonical.submit) recordTidDefect("H13 new discussion", ev.rkeys);
    await pPage.click("ul.unfinished li a");
    await pPage.waitForLoadState();
    check(new URL(pPage.url()).pathname === "/operation", "operation page reached from /mine", pPage.url());
    ev.operationPage = await mainText(pPage);
    check(ev.operationPage.includes("Your last action was interrupted. Nothing was duplicated; you can safely pick up where you left off."), "operation page", ev.operationPage);
    await pPage.click('form[action="/operation/resume"] button');
    await pPage.waitForLoadState();
    ev.resumed = await mainText(pPage);
    check(ev.resumed.includes("Submitted. Your post is now waiting for the moderator"), "resume completes", ev.resumed);
    ev.after = await counts();
    check(ev.after.participant.posts === before.participant.posts + 1 && ev.after.participant.submits === before.participant.submits + 1, "exactly one post and one submit", ev.after);
    const posts = await listRecords(participant.origin, participant.did, POST);
    check(posts.filter((record) => record.value.text === text).length === 1, "exactly one post with that text");
    const journal = JSON.parse(await readFile(join(runtimeDir, "operations", `${encodeURIComponent(participant.did)}.json`), "utf8"));
    ev.journal = { source: journal.operations[plan.sourceOperationId]?.phase, context: journal.operations[plan.contextOperationId]?.phase };
    check(ev.journal.source === "committed" && ev.journal.context === "committed", "journal reconciled", ev.journal);
    // The new discussion must reach the moderator: the observer lists it only
    // when its submit rkey is a canonical TID.
    ev.ingest = await ingest();
    const queue = await projection("/moderation-queue");
    ev.queued = queue.submissions.map((item) => item.submission.uri);
    check(ev.queued.includes(`at://${participant.did}/${SUBMIT}/${plan.context.rkey}`), "the new discussion's submission is in the moderation queue", { queued: ev.queued, rkeys: ev.rkeys });
    await pPage.goto(`${LIVE}/mine`);
    ev.mineAfter = await mainText(pPage);
    check(!ev.mineAfter.includes("Unfinished actions"), "the finished action leaves the unfinished list", ev.mineAfter);
  });

  await step("H14", "sign out clears the session; signed-out home is back to sign-in only", async (ev) => {
    await pPage.goto(`${LIVE}/`);
    await Promise.all([pPage.waitForURL(`${LIVE}/`), pPage.click("nav form[action='/signout'] button")]);
    ev.text = await mainText(pPage);
    check(ev.text.includes("Sign in with your Bluesky"), "signed out", ev.text);
    ev.cookies = (await participantContext.cookies(LIVE)).map((cookie) => cookie.name);
    check(!ev.cookies.includes("community_session"), "cookie cleared", ev.cookies);
  });

  // ------------------------------------------ negatives: lost OAuth session --

  await negative("N-oauth-session-lost-write", "with the stored OAuth session gone, a write is a 401 'expired' page with the sign-in form, the cookie is cleared and the web session ended", async (ev) => {
    Object.assign(ev, { signIn: (await oauthSignIn(pPage, participant)).finalUrl });
    check(ev.signIn === `${LIVE}/`, "participant signed in again", ev.signIn);
    const file = oauthSessionFile(participant.did);
    check(existsSync(file), "stored OAuth session present after sign-in");
    await rm(file);
    const cookie = await cookieHeader(participantContext);
    const readBefore = await rawGet("/mine", { cookie });
    // Reading needs only the web session; the loss surfaces at the first write.
    ev.mineBeforeWrite = { status: readBefore.status, note: "GET /mine does not restore the OAuth session; it still renders" };
    check(readBefore.status === 200, "/mine still renders before any write", readBefore.status);
    const csrf = await csrfFor(pPage);
    const before = await counts();
    const write = await rawPost("/submit-existing", { csrf, post: post1.uri }, { cookie });
    ev.write = { status: write.status, text: write.text.slice(0, 240), setCookie: write.setCookie };
    check(write.status === 401 && write.text.includes("Your sign-in has expired. Sign in again."), "401 expired page", ev.write);
    check(write.text.includes("Sign in with your Bluesky"), "sign-in form on the 401 page", ev.write);
    check(clearsSessionCookie(write.setCookie), "session cookie cleared", write.setCookie);
    check(JSON.stringify(await counts()) === JSON.stringify(before), "nothing written");
    const readAfter = await rawGet("/mine", { cookie });
    ev.mineAfterWrite = { status: readAfter.status, text: readAfter.text.slice(0, 120) };
    check(readAfter.status === 401 && readAfter.text.includes("Sign in is required to view this page."), "the web session is ended", ev.mineAfterWrite);
    await participantContext.clearCookies();
  });
  await negative("N-oauth-session-lost-disconnect", "with the stored OAuth session gone, Disconnect ends the web session with the 401 'expired' page", async (ev) => {
    Object.assign(ev, { signIn: (await oauthSignIn(pPage, participant)).finalUrl });
    check(ev.signIn === `${LIVE}/`, "participant signed in again", ev.signIn);
    const file = oauthSessionFile(participant.did);
    check(existsSync(file), "stored OAuth session present after sign-in");
    await rm(file);
    await pPage.click("nav form[action='/disconnect'] button");
    await pPage.waitForLoadState();
    ev.status = (await pPage.evaluate(() => performance.getEntriesByType("navigation").at(-1)?.responseStatus)) ?? null;
    ev.text = await mainText(pPage);
    check(ev.text.includes("Your sign-in has expired. Sign in again.") && ev.text.includes("Sign in with your Bluesky"), "401 expired page with sign-in form", ev.text);
    check(ev.status === 401, "status 401", ev.status);
    ev.cookies = (await participantContext.cookies(LIVE)).map((cookie) => cookie.name);
    check(!ev.cookies.includes("community_session"), "session cookie cleared in the browser", ev.cookies);
    await pPage.goto(`${LIVE}/`);
    ev.home = await mainText(pPage);
    check(ev.home.includes("Sign in with your Bluesky") && !ev.home.includes(participant.did), "signed out", ev.home);
  });

  receipt.recordCounts.final = await counts();
  receipt.payloads.webhookDeliveries = webhook.received.map((item) => item.payload.content);
  receipt.payloads.webhookRejections = webhook.rejected.map((item) => item.payload.content);
  receipt.payloads.appViewRequestCount = appView.requests.length;
  await browser.close();
  await new Promise((resolve) => appViewServer.close(resolve));
  await new Promise((resolve) => webhookServer.close(resolve));
}

let failure = null;
try {
  await main();
} catch (error) {
  failure = `${error?.name ?? "Error"}: ${error?.message ?? error}`;
  receipt.fatal = { message: failure, stack: String(error?.stack ?? "").split("\n").slice(0, 8) };
  process.stderr.write(`fatal: ${failure}\n${error?.stack ?? ""}\n`);
} finally {
  for (const handle of processes.values()) await stopProcess(handle);
  try { await browser?.close(); } catch { /* already closed */ }
}
const allOk = failure === null && receipt.steps.every((entry) => entry.ok) && receipt.negatives.every((entry) => entry.ok);
receipt.result = allOk ? "passed" : "failed";
receipt.summary = {
  steps: { total: receipt.steps.length, passed: receipt.steps.filter((entry) => entry.ok).length },
  negatives: { total: receipt.negatives.length, passed: receipt.negatives.filter((entry) => entry.ok).length },
  defects: receipt.defects.length,
};
receipt.timings.totalMs = Date.now() - startedAt;
await mkdir(join(RECEIPT, ".."), { recursive: true });
await writeFile(RECEIPT, `${JSON.stringify(receipt, null, 2)}\n`);
process.stderr.write(`receipt: ${RECEIPT} (${receipt.result})\n`);
process.exit(allOk ? 0 : 1);
