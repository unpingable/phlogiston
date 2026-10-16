import { Client } from "@atproto/lex-client";
import type { LexMap } from "@atproto/lex-data";
import { asStringFormat } from "@atproto/lex-schema";
import { buildAtprotoLoopbackClientMetadata, NodeOAuthClient, OAuthCallbackError, OAuthResponseError, requestLocalLock, type NodeSavedSession, type NodeSavedState, type OAuthSession } from "@atproto/oauth-client-node";
import { readFile, readdir } from "node:fs/promises";
import { join, resolve } from "node:path";
import { AUTHORITY_DID, LEXICON_COLLECTION, SPACE_TYPE, createExactPublicSpace, parseLexicons, publishExactLexicons, type LexiconRepository, type SpaceBootstrapClient } from "./bootstrap.js";
import { createSpace, getSpace } from "./rpc.js";
import { SecretStore } from "./store.js";
import { startLoopbackCallbackServer } from "./loopback.js";

export const LEXICON_SCOPE = "atproto repo:com.atproto.lexicon.schema?action=create";
export const SPACE_SCOPE = `atproto space:${SPACE_TYPE}?authority=${AUTHORITY_DID}&skey=self&manage=create`;
type Profile = "lexicons" | "space";
type Config = Readonly<{ runtimeDirectory: string; callbackOrigin: string; lexiconDirectory: string }>;

export async function main(argv = process.argv.slice(2), env = process.env): Promise<number> {
  try {
    const config = configuration(env);
    if (argv[0] === "auth-start" || argv[0] === "auth-callback" || argv[0] === "auth-listen") {
      const profile = requireProfile(argv[1]);
      const oauth = client(config, profile);
      if (argv[0] === "auth-listen") {
        const handle = argv[2]?.replace(/^@/, "");
        if (!handle) throw new Error("handle required");
        const expected = callbackUrl(config.callbackOrigin, profile);
        const listener = await startLoopbackCallbackServer(expected, async (callback) => {
          await completeCallback(oauth, callback, expected);
        });
        try {
          const url = await oauth.authorize(handle, { scope: scope(profile) });
          process.stdout.write(`${JSON.stringify({ profile, authorizationUrl: url.toString(), callbackListening: listener.callbackUrl.origin })}\n`);
          await listener.completion;
          process.stdout.write(`${JSON.stringify({ profile, authenticatedDid: AUTHORITY_DID })}\n`);
          return 0;
        } catch (error) {
          await listener.close();
          throw error;
        }
      }
      if (argv[0] === "auth-start") {
        const handle = argv[2]?.replace(/^@/, "");
        if (!handle) throw new Error("handle required");
        const url = await oauth.authorize(handle, { scope: scope(profile) });
        process.stdout.write(`${JSON.stringify({ profile, authorizationUrl: url.toString() })}\n`);
        return 0;
      }
      const expected = callbackUrl(config.callbackOrigin, profile);
      const session = await completeCallback(oauth, new URL(argv[2] ?? "invalid:"), expected);
      process.stdout.write(`${JSON.stringify({ profile, authenticatedDid: session.did })}\n`);
      return 0;
    }
    if (argv[0] === "publish-lexicons") {
      const session = await client(config, "lexicons").restore(AUTHORITY_DID);
      const lex = new Client(session);
      const repository: LexiconRepository = {
        create: async ({ rkey, record }) => {
          const response = await lex.createRecord({ ...record, $type: asStringFormat(String(record.$type), "nsid") }, rkey, { validate: false, maxRetries: 0 });
          return response.body;
        },
        get: async ({ rkey }) => {
          const response = await lex.getRecord(asStringFormat(LEXICON_COLLECTION, "nsid"), asStringFormat(rkey, "record-key"), { repo: asStringFormat(AUTHORITY_DID, "at-identifier"), maxRetries: 0 });
          return { ...response.body, cid: response.body.cid ?? "" };
        },
      };
      const published = await publishExactLexicons(repository, await loadDocuments(config.lexiconDirectory));
      process.stdout.write(`${JSON.stringify({ published })}\n`);
      return 0;
    }
    if (argv[0] === "create-space") {
      const session = await client(config, "space").restore(AUTHORITY_DID);
      const lex = new Client(session);
      const adapter: SpaceBootstrapClient = {
        create: (input) => lex.call(createSpace, input, { maxRetries: 0 }),
        get: (space) => lex.call(getSpace, { space: asStringFormat(space, "space-ref") }, { maxRetries: 0 }),
      };
      process.stdout.write(`${JSON.stringify({ receipt: await createExactPublicSpace(adapter) })}\n`);
      return 0;
    }
    throw new Error("unsupported Juniper bootstrap command");
  } catch (error) {
    const classification = safeErrorClassification(error);
    process.stderr.write(`${JSON.stringify(classification ? { error: "juniper_bootstrap_refused", classification } : { error: "juniper_bootstrap_refused" })}\n`);
    return 1;
  }
}

type SafeErrorClassification = Readonly<{ kind: string; phase?: string; issuerParameter?: "present" | "absent"; libraryCheck?: string; status?: number; oauthError?: string }>;
export function safeErrorClassification(error: unknown): readonly SafeErrorClassification[] | undefined {
  const result: SafeErrorClassification[] = [];
  let current: unknown = error;
  for (let depth = 0; depth < 4 && current instanceof Error; depth += 1) {
    if (current instanceof OAuthCallbackError) {
      const callbackError = current.params.get("error") ?? "";
      const allowed = ["access_denied", "invalid_request", "invalid_scope", "server_error", "temporarily_unavailable", "unauthorized_client"].includes(callbackError) ? callbackError : undefined;
      const phase = current.params.has("error") ? "authorization_error" : current.params.has("code") ? "code_received" : current.params.has("state") ? "state_only" : "callback_shape_invalid";
      const knownChecks = new Map([
        ['iss missing from the response', "issuer_parameter_required"],
        ["Issuer mismatch", "issuer_parameter_mismatch"],
        ["Issuer not found in metadata", "issuer_metadata_missing"],
        ['Missing "code" query param', "authorization_code_missing"],
        ['Missing "state" parameter', "state_parameter_missing"],
        ["JARM not supported", "unsupported_jarm"],
      ]);
      const libraryCheck = knownChecks.get(current.message);
      result.push(Object.freeze({
        kind: "oauth_callback_error",
        phase,
        issuerParameter: current.params.has("iss") ? "present" : "absent",
        ...(libraryCheck ? { libraryCheck } : {}),
        ...(allowed ? { oauthError: allowed } : {}),
      }));
    }
    else if (current instanceof OAuthResponseError) {
      const allowed = ["invalid_dpop_proof", "invalid_grant", "invalid_request", "invalid_scope", "invalid_token", "use_dpop_nonce"].includes(current.error ?? "") ? current.error : undefined;
      result.push(Object.freeze({ kind: "oauth_response_error", status: current.status, ...(allowed ? { oauthError: allowed } : {}) }));
    } else if (current.message === "OAuth subject is not frozen Juniper authority") result.push(Object.freeze({ kind: "oauth_subject_mismatch" }));
    else if (current.name === "JwkError") result.push(Object.freeze({ kind: "oauth_key_error" }));
    else if (current.name === "FetchResponseError") result.push(Object.freeze({ kind: "oauth_fetch_response_error" }));
    else if (current.name === "OAuthResolverError") result.push(Object.freeze({ kind: "oauth_identity_resolution_error" }));
    else if (current.name === "IdentityResolverError") result.push(Object.freeze({ kind: "oauth_identity_document_error" }));
    else if (current.name === "HandleResolverError") result.push(Object.freeze({ kind: "oauth_handle_resolution_error" }));
    else if (current.name === "DidError") result.push(Object.freeze({ kind: "oauth_did_resolution_error" }));
    else if (current.name === "ZodError") result.push(Object.freeze({ kind: "oauth_token_shape_error" }));
    else if (current.name === "TypeError") result.push(Object.freeze({ kind: "oauth_type_error" }));
    current = "cause" in current ? current.cause : undefined;
  }
  return result.length ? Object.freeze(result) : undefined;
}

async function completeCallback(oauth: NodeOAuthClient, callback: URL, expected: URL): Promise<OAuthSession> {
  if (callback.origin !== expected.origin || callback.pathname !== expected.pathname) throw new Error("callback target mismatch");
  const { session } = await oauth.callback(callback.searchParams);
  if (session.did !== AUTHORITY_DID) {
    await oauth.revoke(session.did).catch(() => undefined);
    throw new Error("OAuth subject is not frozen Juniper authority");
  }
  return session;
}

function client(config: Config, profile: Profile): NodeOAuthClient {
  return new NodeOAuthClient({
    clientMetadata: buildAtprotoLoopbackClientMetadata({ redirect_uris: [callbackUrl(config.callbackOrigin, profile).toString()], scope: scope(profile) }),
    allowHttp: false,
    stateStore: new SecretStore<NodeSavedState>(join(config.runtimeDirectory, profile, "state")),
    sessionStore: new SecretStore<NodeSavedSession>(join(config.runtimeDirectory, profile, "session")),
    requestLock: requestLocalLock,
  });
}
function scope(profile: Profile): string { return profile === "lexicons" ? LEXICON_SCOPE : SPACE_SCOPE; }
function requireProfile(value: string | undefined): Profile { if (value !== "lexicons" && value !== "space") throw new Error("bootstrap profile required"); return value; }
function callbackUrl(origin: string, profile: Profile): URL { return new URL(`/${profile}-callback`, origin); }
function configuration(env: NodeJS.ProcessEnv): Config {
  const runtimeDirectory = env.JUNIPER_BOOTSTRAP_RUNTIME_DIR?.trim();
  const callbackOrigin = env.JUNIPER_BOOTSTRAP_CALLBACK_ORIGIN?.trim();
  const lexiconDirectory = env.JUNIPER_BOOTSTRAP_LEXICON_DIR?.trim();
  if (!runtimeDirectory || !callbackOrigin || !lexiconDirectory) throw new Error("Juniper bootstrap configuration missing");
  const parsed = new URL(callbackOrigin);
  if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1" || parsed.pathname !== "/" || parsed.search || parsed.hash) throw new Error("bootstrap callback must be explicit IPv4 loopback origin");
  return { runtimeDirectory: resolve(runtimeDirectory), callbackOrigin: parsed.origin, lexiconDirectory: resolve(lexiconDirectory) };
}
async function loadDocuments(directory: string): Promise<readonly LexMap[]> {
  const names = (await readdir(directory)).filter((name) => name.endsWith(".json")).sort();
  const documents: unknown[] = [];
  for (const name of names) documents.push(JSON.parse(await readFile(join(directory, name), "utf8")));
  return parseLexicons(documents);
}
if (process.argv[1] && import.meta.filename === process.argv[1]) process.exitCode = await main();
