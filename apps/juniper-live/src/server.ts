import type { OAuthSession } from "@atproto/oauth-client-node";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { AuthorActionStore } from "./actions.js";
import { loadConfig, type AppConfig } from "./config.js";
import { OAUTH_SCOPE } from "./constants.js";
import { readProjectionBundle, type ProjectionBundle } from "./feed.js";
import { clientMetadata, createOAuthClient } from "./oauth.js";
import {
  createAndSubmitExact,
  deleteExactSource,
  editExactSource,
  OAuthSpaceRecordWriter,
  type SpaceRecordWriter,
  SubmissionWriteFailed,
  withdrawExactAdmission,
} from "./records.js";
import { WebSessionStore } from "./storage.js";
import { page } from "./views.js";

const COOKIE = "juniper_session";
const MAX_FORM_BYTES = 64 * 1024;

type OAuthFacade = Readonly<{
  authorize(input: string, options: { scope: string }): Promise<URL>;
  callback(params: URLSearchParams): Promise<{ session: OAuthSession }>;
  restore(did: string): Promise<OAuthSession>;
  revoke(did: string): Promise<void>;
}>;

type Dependencies = Readonly<{
  config: AppConfig;
  oauth: OAuthFacade;
  webSessions: WebSessionStore;
  actions: AuthorActionStore;
  readBundle(): Promise<ProjectionBundle>;
  writer(session: OAuthSession): SpaceRecordWriter;
  now(): Date;
}>;

export function createHandler(deps: Dependencies) {
  return async (request: IncomingMessage, response: ServerResponse): Promise<void> => {
    try {
      await route(deps, request, response);
    } catch (error) {
      const code = safeErrorCode(error);
      response.statusCode = code === "request_invalid" ? 400 : code === "not_authenticated" ? 401 : 503;
      securityHeaders(response);
      response.setHeader("Content-Type", "text/html; charset=utf-8");
      response.end(`<!doctype html><title>Juniper unavailable</title><h1>Juniper couldn’t complete that step.</h1><p>${messageFor(code)}</p><p><a href="/">Return to the community</a></p>`);
    }
  };
}

async function route(
  deps: Dependencies,
  request: IncomingMessage,
  response: ServerResponse,
): Promise<void> {
  const method = request.method ?? "GET";
  const url = new URL(request.url ?? "/", deps.config.publicUrl);
  if (method === "GET" && url.pathname === "/healthz") return text(response, 200, "ok\n");
  if (method === "GET" && url.pathname === "/styles.css") {
    const css = await readFile(join(import.meta.dirname, "../public/styles.css"));
    return bytes(response, 200, "text/css; charset=utf-8", css);
  }
  if (method === "GET" && url.pathname === "/oauth-client-metadata.json") {
    return json(response, 200, clientMetadata(deps.config));
  }
  if (method === "POST") requireSameOrigin(request, deps.config.publicUrl);
  if (method === "POST" && url.pathname === "/oauth/login") {
    const form = await readForm(request);
    const handle = required(form, "handle").replace(/^@/, "");
    const target = await deps.oauth.authorize(handle, { scope: OAUTH_SCOPE });
    return redirect(response, target.toString());
  }
  if (method === "GET" && url.pathname === "/oauth/callback") {
    const { session } = await deps.oauth.callback(url.searchParams);
    const token = await deps.webSessions.issue(session.did, deps.now());
    response.setHeader("Set-Cookie", cookie(token, deps.config.publicUrl));
    return redirect(response, "/create");
  }
  if (method === "POST" && url.pathname === "/oauth/logout") {
    const token = cookieValue(request.headers.cookie, COOKIE);
    const did = await deps.webSessions.resolve(token, deps.now());
    await deps.webSessions.revoke(token);
    if (did) await deps.oauth.revoke(did).catch(() => undefined);
    response.setHeader("Set-Cookie", expiredCookie(deps.config.publicUrl));
    return redirect(response, "/");
  }

  const token = cookieValue(request.headers.cookie, COOKIE);
  const did = await deps.webSessions.resolve(token, deps.now());
  if (method === "POST" && url.pathname.startsWith("/author/")) {
    if (!did) throw coded("not_authenticated");
    const session = await deps.oauth.restore(did).catch(() => {
      throw coded("not_authenticated");
    });
    const form = await readForm(request);
    await authorAction(deps, deps.writer(session), did, url.pathname, form);
    return redirect(response, "/mine?notice=action-recorded");
  }

  if (method !== "GET") return text(response, 405, "method not allowed\n");
  const allowed = new Set(["/", "/create", "/mine", "/post", "/receipt"]);
  if (!allowed.has(url.pathname)) return text(response, 404, "not found\n");
  const bundle = await deps.readBundle();
  const actions = did ? await deps.actions.list(did) : [];
  const path = url.pathname as "/" | "/create" | "/mine" | "/post" | "/receipt";
  return html(response, 200, page({
    path,
    bundle,
    signedInDid: did,
    actions,
    projection: url.searchParams.get("projection") ?? undefined,
    notice: noticeText(url.searchParams.get("notice")),
  }));
}

async function authorAction(
  deps: Dependencies,
  writer: SpaceRecordWriter,
  did: string,
  path: string,
  form: URLSearchParams,
): Promise<void> {
  const now = deps.now().toISOString();
  if (path === "/author/create-submit") {
    if (form.get("consent") !== "yes") throw coded("request_invalid");
    const title = required(form, "title");
    const body = required(form, "body");
    const authorDisplayReference = required(form, "authorDisplayReference");
    try {
      const result = await createAndSubmitExact(writer, {
        authorDid: did,
        communityActorDid: deps.config.communityActorDid,
        title,
        body,
        authorDisplayReference,
        now,
      });
      await deps.actions.recordCreation({
        authorDid: did,
        result,
        title,
        body,
        authorDisplayReference,
        createdAt: now,
      });
      return;
    } catch (error) {
      if (error instanceof SubmissionWriteFailed) throw coded("partial_submission");
      throw error;
    }
  }
  const itemId = required(form, "itemId");
  const item = (await deps.actions.list(did)).find((candidate) => candidate.itemId === itemId);
  if (!item) throw coded("request_invalid");
  if (path === "/author/edit") {
    if (!item.currentSource) throw coded("request_invalid");
    const title = required(form, "title");
    const body = required(form, "body");
    const source = await editExactSource(writer, {
      authorDid: did,
      prior: item.currentSource,
      title,
      body,
      now,
    });
    await deps.actions.recordEdit({ authorDid: did, itemId, source, title, body, updatedAt: now });
    return;
  }
  if (path === "/author/delete") {
    if (!item.currentSource) throw coded("request_invalid");
    await deleteExactSource(writer, { authorDid: did, prior: item.currentSource });
    await deps.actions.recordDeletion(did, itemId, now);
    return;
  }
  if (path === "/author/withdraw") {
    const projection = required(form, "projection");
    const audit = (await deps.readBundle()).audit?.entries.find(
      (entry) => entry.projectionIdentity === projection && entry.sourceUri === item.post.uri,
    );
    const receipt = audit?.technicalReceipts;
    const admissionUri = receipt?.admissionRecordUri;
    const admissionCid = receipt?.admissionRecordCid;
    if (typeof admissionUri !== "string" || typeof admissionCid !== "string") {
      throw coded("withdrawal_reference_unavailable");
    }
    const withdrawal = await withdrawExactAdmission(writer, {
      authorDid: did,
      communityActorDid: deps.config.communityActorDid,
      post: item.post,
      submission: item.submission,
      admission: { uri: admissionUri, cid: admissionCid },
      now,
    });
    await deps.actions.recordWithdrawal(did, itemId, withdrawal);
    return;
  }
  throw coded("request_invalid");
}

function required(form: URLSearchParams, key: string): string {
  const value = form.get(key)?.trim();
  if (!value || value.includes("\0")) throw coded("request_invalid");
  return value;
}

async function readForm(request: IncomingMessage): Promise<URLSearchParams> {
  const type = request.headers["content-type"]?.split(";", 1)[0];
  if (type !== "application/x-www-form-urlencoded") throw coded("request_invalid");
  const declared = Number(request.headers["content-length"] ?? "0");
  if (declared > MAX_FORM_BYTES) throw coded("request_invalid");
  const chunks: Buffer[] = [];
  let length = 0;
  for await (const chunk of request) {
    const bytes = Buffer.from(chunk);
    length += bytes.length;
    if (length > MAX_FORM_BYTES) throw coded("request_invalid");
    chunks.push(bytes);
  }
  return new URLSearchParams(Buffer.concat(chunks).toString("utf8"));
}

function requireSameOrigin(request: IncomingMessage, expected: string): void {
  if (request.headers.origin !== expected) throw coded("request_invalid");
}

function cookie(value: string, publicUrl: string): string {
  return `${COOKIE}=${value}; Path=/; HttpOnly; SameSite=Lax; Max-Age=28800${new URL(publicUrl).protocol === "https:" ? "; Secure" : ""}`;
}
function expiredCookie(publicUrl: string): string { return `${COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${new URL(publicUrl).protocol === "https:" ? "; Secure" : ""}`; }
function cookieValue(header: string | undefined, name: string): string | undefined {
  for (const part of header?.split(";") ?? []) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return undefined;
}
function noticeText(value: string | null): string | undefined {
  return value === "action-recorded" ? "Your action was recorded. Juniper’s public feed changes only after the observer qualifies the new state." : undefined;
}

function securityHeaders(response: ServerResponse): void {
  response.setHeader("Content-Security-Policy", "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'");
  response.setHeader("Referrer-Policy", "no-referrer");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("Cache-Control", "no-store");
}
function html(response: ServerResponse, status: number, value: string): void { securityHeaders(response); response.statusCode = status; response.setHeader("Content-Type", "text/html; charset=utf-8"); response.end(value); }
function text(response: ServerResponse, status: number, value: string): void { securityHeaders(response); response.statusCode = status; response.setHeader("Content-Type", "text/plain; charset=utf-8"); response.end(value); }
function json(response: ServerResponse, status: number, value: object): void { securityHeaders(response); response.statusCode = status; response.setHeader("Content-Type", "application/json; charset=utf-8"); response.end(JSON.stringify(value)); }
function bytes(response: ServerResponse, status: number, type: string, value: Uint8Array): void { securityHeaders(response); response.statusCode = status; response.setHeader("Content-Type", type); response.end(value); }
function redirect(response: ServerResponse, location: string): void { securityHeaders(response); response.statusCode = 303; response.setHeader("Location", location); response.end(); }

function coded(code: string): Error { const error = new Error(code); error.name = "JuniperError"; return error; }
function safeErrorCode(error: unknown): string {
  if (error instanceof Error && error.name === "JuniperError") return error.message;
  return "internal_failure";
}
function messageFor(code: string): string {
  return ({ request_invalid: "The request did not match the bounded Juniper action.", not_authenticated: "Your disposable sign-in is missing or expired.", partial_submission: "The source post was created, but submission failed. Juniper will not claim it was submitted.", withdrawal_reference_unavailable: "The exact admission reference is not available in the qualified audit artifact yet.", internal_failure: "No community or source state was changed optimistically. Try again after checking service status." } as Record<string, string>)[code] ?? "The bounded action refused.";
}

if (process.argv[1] && import.meta.filename === process.argv[1]) {
  const config = loadConfig();
  const oauth = createOAuthClient(config);
  const webSessions = new WebSessionStore(join(config.runtimeDirectory, "web-sessions"));
  const actions = new AuthorActionStore(join(config.runtimeDirectory, "author-actions.json"));
  const handler = createHandler({
    config,
    oauth,
    webSessions,
    actions,
    readBundle: () => readProjectionBundle(config.projectionDirectory),
    writer: (session) => new OAuthSpaceRecordWriter(session, config.spaceUri),
    now: () => new Date(),
  });
  createServer((request, response) => void handler(request, response)).listen(config.port, "127.0.0.1", () => {
    process.stdout.write(`juniper_live_ready port=${config.port}\n`);
  });
}
