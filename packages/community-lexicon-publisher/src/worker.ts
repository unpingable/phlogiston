import { Client } from "@atproto/lex-client";
import type { LexMap } from "@atproto/lex-data";
import { asStringFormat } from "@atproto/lex-schema";
import {
  buildAtprotoLoopbackClientMetadata,
  NodeOAuthClient,
  OAuthCallbackError,
  OAuthResponseError,
  requestLocalLock,
  type NodeSavedSession,
  type NodeSavedState,
  type OAuthSession,
} from "@atproto/oauth-client-node";
import { resolveTxt } from "node:dns/promises";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import {
  LEXICON_COLLECTION,
  LEXICON_SCOPE,
  createManifest,
  loadPackagedDocuments,
  manifestDigest,
  parseAcceptance,
  parseManifest,
  requireDid,
  stable,
  type PublicationManifest,
} from "./contract.js";
import { FilePublicationJournal } from "./journal.js";
import { startLoopbackCallbackServer } from "./loopback.js";
import {
  publishAcceptedManifest,
  type DnsTxtResolver,
  type LexiconRepository,
} from "./publication.js";
import { SecretStore } from "./store.js";

type BaseConfig = Readonly<{
  runtimeDirectory: string;
  callbackOrigin: string;
  authorityDid: string;
}>;

type PublishConfig = BaseConfig & Readonly<{
  manifestPath: string;
  acceptancePath: string;
  receiptPath: string;
}>;

export async function main(
  argv = process.argv.slice(2),
  env = process.env,
): Promise<number> {
  try {
    const command = argv[0];
    const config = baseConfiguration(env);
    if (command === "manifest") {
      const outputPath = requiredPath(argv[1], "manifest output path is required");
      const manifest = createManifest(config.authorityDid, await loadPackagedDocuments());
      await writeJson(outputPath, manifest, 0o600);
      process.stdout.write(`${stable({
        manifestSha256: manifestDigest(manifest),
        authorityDid: manifest.authorityDid,
        documents: manifest.documents.length,
      })}\n`);
      return 0;
    }

    if (command === "auth-listen") {
      const oauth = client(config);
      const handle = requiredHandle(argv[1]);
      const expected = callbackUrl(config.callbackOrigin);
      const listener = await startLoopbackCallbackServer(expected, async (callback) => {
        await completeCallback(oauth, callback, expected, config.authorityDid);
      });
      try {
        const url = await oauth.authorize(handle, { scope: LEXICON_SCOPE });
        process.stdout.write(`${stable({
          authorizationUrl: url.toString(),
          callbackListening: listener.callbackUrl.origin,
        })}\n`);
        await listener.completion;
        process.stdout.write(`${stable({ authenticatedDid: config.authorityDid })}\n`);
        return 0;
      } catch (error) {
        await listener.close();
        throw error;
      }
    }

    if (command === "publish") {
      const publishConfig = publicationConfiguration(config, env);
      const documents = await loadPackagedDocuments();
      const manifest = parseManifest(await readJson(publishConfig.manifestPath), documents);
      const acceptance = parseAcceptance(
        await readJson(publishConfig.acceptancePath),
        manifest,
      );
      const session = await client(config).restore(config.authorityDid);
      const receipt = await publishAcceptedManifest(
        repository(session, config.authorityDid),
        systemDnsResolver,
        new FilePublicationJournal(join(config.runtimeDirectory, "intents")),
        manifest,
        acceptance,
      );
      await writeJson(publishConfig.receiptPath, receipt, 0o600);
      process.stdout.write(`${stable(receipt)}\n`);
      return 0;
    }
    throw new Error("unsupported PCV0 Lexicon publisher command");
  } catch (error) {
    const classification = safeErrorClassification(error);
    process.stderr.write(`${stable({
      error: "pcv0_lexicon_publication_refused",
      ...(classification ? { classification } : {}),
    })}\n`);
    return 1;
  }
}

type SafeErrorClassification = Readonly<{
  kind: string;
  phase?: string;
  issuerParameter?: "present" | "absent";
  libraryCheck?: string;
  status?: number;
  oauthError?: string;
}>;

export function safeErrorClassification(
  error: unknown,
): readonly SafeErrorClassification[] | undefined {
  const result: SafeErrorClassification[] = [];
  let current: unknown = error;
  for (let depth = 0; depth < 4 && current instanceof Error; depth += 1) {
    if (current instanceof OAuthCallbackError) {
      const callbackError = current.params.get("error") ?? "";
      const allowed = [
        "access_denied", "invalid_request", "invalid_scope", "server_error",
        "temporarily_unavailable", "unauthorized_client",
      ].includes(callbackError) ? callbackError : undefined;
      const phase = current.params.has("error")
        ? "authorization_error"
        : current.params.has("code")
          ? "code_received"
          : current.params.has("state")
            ? "state_only"
            : "callback_shape_invalid";
      const knownChecks = new Map([
        ["iss missing from the response", "issuer_parameter_required"],
        ["Issuer mismatch", "issuer_parameter_mismatch"],
        ["Issuer not found in metadata", "issuer_metadata_missing"],
        ["Missing \"code\" query param", "authorization_code_missing"],
        ["Missing \"state\" parameter", "state_parameter_missing"],
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
    } else if (current instanceof OAuthResponseError) {
      const allowed = [
        "invalid_dpop_proof", "invalid_grant", "invalid_request", "invalid_scope",
        "invalid_token", "use_dpop_nonce",
      ].includes(current.error ?? "") ? current.error : undefined;
      result.push(Object.freeze({
        kind: "oauth_response_error",
        status: current.status,
        ...(allowed ? { oauthError: allowed } : {}),
      }));
    } else if (current.message === "OAuth subject is not manifest schema authority") {
      result.push(Object.freeze({ kind: "oauth_subject_mismatch" }));
    } else if (current.name === "JwkError") {
      result.push(Object.freeze({ kind: "oauth_key_error" }));
    } else if (current.name === "FetchResponseError") {
      result.push(Object.freeze({ kind: "oauth_fetch_response_error" }));
    } else if (current.name === "OAuthResolverError") {
      result.push(Object.freeze({ kind: "oauth_identity_resolution_error" }));
    } else if (current.name === "IdentityResolverError") {
      result.push(Object.freeze({ kind: "oauth_identity_document_error" }));
    } else if (current.name === "HandleResolverError") {
      result.push(Object.freeze({ kind: "oauth_handle_resolution_error" }));
    } else if (current.name === "DidError") {
      result.push(Object.freeze({ kind: "oauth_did_resolution_error" }));
    } else if (current.name === "ZodError") {
      result.push(Object.freeze({ kind: "oauth_token_shape_error" }));
    } else if (current.name === "TypeError") {
      result.push(Object.freeze({ kind: "oauth_type_error" }));
    }
    current = "cause" in current ? current.cause : undefined;
  }
  return result.length ? Object.freeze(result) : undefined;
}

const systemDnsResolver: DnsTxtResolver = Object.freeze({
  resolveTxt: async (name: string) => (await resolveTxt(name)).map((chunks) => chunks.join("")),
});

function repository(session: OAuthSession, authorityDid: string): LexiconRepository {
  if (session.did !== authorityDid) throw new Error("OAuth subject is not manifest schema authority");
  const lex = new Client(session);
  return Object.freeze({
    create: async ({ rkey, record }: Readonly<{ rkey: string; record: LexMap }>) => {
      const response = await lex.createRecord(
        { ...record, $type: asStringFormat(String(record.$type), "nsid") },
        asStringFormat(rkey, "record-key"),
        { validate: false, maxRetries: 0 },
      );
      return response.body;
    },
    get: async ({ rkey }: Readonly<{ rkey: string }>) => {
      try {
        const response = await lex.getRecord(
          asStringFormat(LEXICON_COLLECTION, "nsid"),
          asStringFormat(rkey, "record-key"),
          { repo: asStringFormat(authorityDid, "at-identifier"), maxRetries: 0 },
        );
        return { ...response.body, cid: response.body.cid ?? "" };
      } catch (error) {
        if (isRecordNotFound(error)) return null;
        throw error;
      }
    },
  });
}

function isRecordNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "error" in error
    && error.error === "RecordNotFound";
}

async function completeCallback(
  oauth: NodeOAuthClient,
  callback: URL,
  expected: URL,
  authorityDid: string,
): Promise<OAuthSession> {
  if (callback.origin !== expected.origin || callback.pathname !== expected.pathname) {
    throw new Error("callback target mismatch");
  }
  const { session } = await oauth.callback(callback.searchParams);
  if (session.did !== authorityDid) {
    await oauth.revoke(session.did).catch(() => undefined);
    throw new Error("OAuth subject is not manifest schema authority");
  }
  return session;
}

function client(config: BaseConfig): NodeOAuthClient {
  return new NodeOAuthClient({
    clientMetadata: buildAtprotoLoopbackClientMetadata({
      redirect_uris: [callbackUrl(config.callbackOrigin).toString()],
      scope: LEXICON_SCOPE,
    }),
    allowHttp: false,
    stateStore: new SecretStore<NodeSavedState>(join(config.runtimeDirectory, "oauth-state")),
    sessionStore: new SecretStore<NodeSavedSession>(join(config.runtimeDirectory, "oauth-session")),
    requestLock: requestLocalLock,
  });
}

function callbackUrl(origin: string): URL {
  return new URL("/lexicon-callback", origin);
}

function baseConfiguration(env: NodeJS.ProcessEnv): BaseConfig {
  const runtimeDirectory = env.PCV0_LEXICON_RUNTIME_DIR?.trim();
  const callbackOrigin = env.PCV0_LEXICON_CALLBACK_ORIGIN?.trim();
  const authorityDid = env.PCV0_LEXICON_AUTHORITY_DID?.trim();
  if (!runtimeDirectory || !callbackOrigin || !authorityDid) {
    throw new Error("PCV0 Lexicon publisher base configuration missing");
  }
  requireDid(authorityDid);
  const parsed = new URL(callbackOrigin);
  if (
    parsed.protocol !== "http:"
    || parsed.hostname !== "127.0.0.1"
    || parsed.pathname !== "/"
    || parsed.search
    || parsed.hash
  ) {
    throw new Error("publisher callback must be explicit IPv4 loopback origin");
  }
  return Object.freeze({
    runtimeDirectory: resolve(runtimeDirectory),
    callbackOrigin: parsed.origin,
    authorityDid,
  });
}

function publicationConfiguration(config: BaseConfig, env: NodeJS.ProcessEnv): PublishConfig {
  const manifestPath = env.PCV0_LEXICON_MANIFEST?.trim();
  const acceptancePath = env.PCV0_LEXICON_ACCEPTANCE?.trim();
  const receiptPath = env.PCV0_LEXICON_RECEIPT?.trim();
  if (!manifestPath || !acceptancePath || !receiptPath) {
    throw new Error("PCV0 Lexicon publication artifact configuration missing");
  }
  return Object.freeze({
    ...config,
    manifestPath: resolve(manifestPath),
    acceptancePath: resolve(acceptancePath),
    receiptPath: resolve(receiptPath),
  });
}

function requiredHandle(value: string | undefined): string {
  const result = value?.replace(/^@/u, "").trim();
  if (!result || result.includes("\0")) throw new Error("schema authority handle required");
  return result;
}

function requiredPath(value: string | undefined, message: string): string {
  if (!value?.trim() || value.includes("\0")) throw new Error(message);
  return resolve(value);
}

async function readJson(path: string): Promise<unknown> {
  return JSON.parse(await readFile(path, "utf8")) as unknown;
}

async function writeJson(path: string, value: unknown, mode: number): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temporary, `${stable(value)}\n`, { mode, flag: "wx" });
  await rename(temporary, path);
}

if (process.argv[1] && import.meta.filename === process.argv[1]) {
  process.exitCode = await main();
}
