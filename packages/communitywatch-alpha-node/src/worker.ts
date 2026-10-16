import { Client } from "@atproto/lex-client";
import { asStringFormat, l } from "@atproto/lex-schema";
import {
  buildAtprotoLoopbackClientMetadata,
  NodeOAuthClient,
  type NodeSavedSession,
  type NodeSavedState,
} from "@atproto/oauth-client-node";
import { join } from "node:path";
import { acquireArtifact, type AcquisitionRequest, type SafeTransportAttempt } from "./acquire.js";
import { loadConfig, OAUTH_SCOPE } from "./config.js";
import { SecretStore } from "./store.js";

const MAX_STDIN = 64 * 1024;
const getDelegationToken = l.query(
  "com.atproto.space.getDelegationToken",
  l.params({ space: l.string({ format: "space-ref" }) }),
  l.jsonPayload({ token: l.string() }),
);

export async function main(argv = process.argv.slice(2), env = process.env): Promise<number> {
  try {
    const config = loadConfig(env);
    const attempts: SafeTransportAttempt[] = [];
    const trackedFetch: typeof fetch = async (input, init) => {
      const request = new Request(input, init);
      const ordinal = attempts.length;
      try {
        const response = await fetch(request);
        attempts.push(Object.freeze({ ordinal, method: request.method, url: request.url, status: response.status, purpose: "oauth-library" }));
        return response;
      } catch (error) {
        attempts.push(Object.freeze({ ordinal, method: request.method, url: request.url, status: null, purpose: "oauth-library" }));
        throw error;
      }
    };
    const oauth = new NodeOAuthClient({
      clientMetadata: buildAtprotoLoopbackClientMetadata({ redirect_uris: [`${config.callbackOrigin}/callback`], scope: OAUTH_SCOPE }),
      allowHttp: false,
      fetch: trackedFetch,
      stateStore: new SecretStore<NodeSavedState>(join(config.runtimeDirectory, "oauth-state")),
      sessionStore: new SecretStore<NodeSavedSession>(join(config.runtimeDirectory, "oauth-session")),
    });
    if (argv[0] === "auth-start") {
      const handle = argv[1]?.replace(/^@/, "");
      if (!handle) throw new Error("handle required");
      const url = await oauth.authorize(handle, { scope: OAUTH_SCOPE });
      process.stdout.write(`${JSON.stringify({ authorizationUrl: url.toString() })}\n`);
      return 0;
    }
    if (argv[0] === "auth-callback") {
      const callback = new URL(argv[1] ?? "invalid:");
      if (callback.origin !== config.callbackOrigin || callback.pathname !== "/callback") throw new Error("callback target mismatch");
      const { session } = await oauth.callback(callback.searchParams);
      if (session.did !== config.observerDid) { await oauth.revoke(session.did).catch(() => undefined); throw new Error("OAuth subject is not observer identity"); }
      process.stdout.write(`${JSON.stringify({ authenticatedDid: session.did })}\n`);
      return 0;
    }
    if (argv[0] === "acquire") {
      const session = await oauth.restore(config.observerDid);
      if (session.did !== config.observerDid) throw new Error("stored OAuth subject mismatch");
      const request = JSON.parse(await stdin()) as AcquisitionRequest;
      const start = attempts.length;
      const result = await acquireArtifact(config, {
        getDelegationToken: async (space) => {
          const client = new Client(session);
          const response = await client.call(getDelegationToken, { space: asStringFormat(space, "space-ref") });
          return { token: response.token, attempts: Object.freeze(attempts.slice(start)) };
        },
      }, request);
      process.stdout.write(`${JSON.stringify(result)}\n`);
      return 0;
    }
    throw new Error("unsupported observer alpha command");
  } catch {
    process.stderr.write(`${JSON.stringify({ error: "communitywatch_alpha_refused" })}\n`);
    return 1;
  }
}

async function stdin(): Promise<string> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    const bytes = Buffer.from(chunk);
    size += bytes.length;
    if (size > MAX_STDIN) throw new Error("input too large");
    chunks.push(bytes);
  }
  return Buffer.concat(chunks).toString("utf8");
}

if (process.argv[1] && import.meta.filename === process.argv[1]) process.exitCode = await main();
