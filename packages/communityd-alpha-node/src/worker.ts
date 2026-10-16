import { Client } from "@atproto/lex-client";
import { asStringFormat } from "@atproto/lex-schema";
import { buildAtprotoLoopbackClientMetadata, NodeOAuthClient, type NodeSavedSession, type NodeSavedState } from "@atproto/oauth-client-node";
import { join } from "node:path";
import { createSpaceRecord, getSpaceRecord } from "./rpc.js";
import { SecretStore } from "./store.js";
import { performWrite, type AuthorityClient } from "./write.js";

const SCOPE = "atproto include:net.sp00ky.juniper-pds.authority.juniperPermissions";
const MAX_STDIN = 128 * 1024;

export async function main(argv = process.argv.slice(2), env = process.env): Promise<number> {
  try {
    const config = configuration(env);
    const oauth = new NodeOAuthClient({
      clientMetadata: buildAtprotoLoopbackClientMetadata({ redirect_uris: [`${config.callbackOrigin}/callback`], scope: SCOPE }),
      allowHttp: false,
      stateStore: new SecretStore<NodeSavedState>(join(config.runtimeDirectory, "oauth-state")),
      sessionStore: new SecretStore<NodeSavedSession>(join(config.runtimeDirectory, "oauth-session")),
    });
    if (argv[0] === "auth-start") {
      const handle = argv[1]?.replace(/^@/, "");
      if (!handle) throw new Error("handle required");
      const url = await oauth.authorize(handle, { scope: SCOPE });
      process.stdout.write(JSON.stringify({ authorizationUrl: url.toString() }) + "\n");
      return 0;
    }
    if (argv[0] === "auth-callback") {
      const callback = new URL(argv[1] ?? "invalid:");
      if (callback.origin !== config.callbackOrigin || callback.pathname !== "/callback") throw new Error("callback target mismatch");
      const { session } = await oauth.callback(callback.searchParams);
      if (session.did !== config.actorDid) { await oauth.revoke(session.did).catch(() => undefined); throw new Error("OAuth subject is not community actor"); }
      process.stdout.write(JSON.stringify({ authenticatedDid: session.did }) + "\n");
      return 0;
    }
    if (argv[0] === "write") {
      const session = await oauth.restore(config.actorDid);
      if (session.did !== config.actorDid) throw new Error("stored OAuth subject mismatch");
      const client = new Client(session);
      const adapter: AuthorityClient = {
        create: (input) => client.call(createSpaceRecord, {
          space: asStringFormat(input.space, "space-ref"), repo: asStringFormat(input.actorDid, "did"), collection: asStringFormat(input.collection, "nsid"), rkey: asStringFormat(input.rkey, "record-key"), validate: false, record: input.record,
        }),
        get: (input) => client.call(getSpaceRecord, {
          space: asStringFormat(input.space, "space-ref"), repo: asStringFormat(input.actorDid, "did"), collection: asStringFormat(input.collection, "nsid"), rkey: asStringFormat(input.rkey, "record-key"),
        }),
      };
      const result = await performWrite(adapter, JSON.parse(await stdin()));
      process.stdout.write(JSON.stringify(result) + "\n");
      return 0;
    }
    throw new Error("unsupported communityd alpha command");
  } catch {
    process.stderr.write(JSON.stringify({ error: "communityd_alpha_refused" }) + "\n");
    return 1;
  }
}

function configuration(env: NodeJS.ProcessEnv) {
  const runtimeDirectory = env.JUNIPER_COMMUNITYD_RUNTIME_DIR?.trim();
  const actorDid = env.JUNIPER_COMMUNITY_ACTOR_DID?.trim();
  const callbackOrigin = env.JUNIPER_COMMUNITYD_CALLBACK_ORIGIN?.trim();
  if (!runtimeDirectory || !actorDid || !callbackOrigin) throw new Error("communityd alpha configuration missing");
  const parsed = new URL(callbackOrigin);
  if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1" || parsed.pathname !== "/" || parsed.search || parsed.hash) throw new Error("communityd OAuth callback must be explicit IPv4 loopback origin");
  return { runtimeDirectory, actorDid, callbackOrigin: parsed.origin };
}

async function stdin(): Promise<string> {
  const chunks: Buffer[] = []; let size = 0;
  for await (const chunk of process.stdin) { const bytes = Buffer.from(chunk); size += bytes.length; if (size > MAX_STDIN) throw new Error("input too large"); chunks.push(bytes); }
  return Buffer.concat(chunks).toString("utf8");
}

if (process.argv[1] && import.meta.filename === process.argv[1]) process.exitCode = await main();
