import { isIP } from "node:net";
import { resolve } from "node:path";

export type AppConfig = Readonly<{
  publicUrl: string;
  spaceUri: string;
  communityActorDid: string;
  runtimeDirectory: string;
  projectionDirectory: string;
  port: number;
}>;

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const publicUrl = exactOrigin(required(env.JUNIPER_PUBLIC_URL, "JUNIPER_PUBLIC_URL"));
  const spaceUri = required(env.JUNIPER_SPACE_URI, "JUNIPER_SPACE_URI");
  if (!/^at:\/\/did:(?:plc|web):[^/]+\/[^/]+\/[^/]+$/.test(spaceUri)) {
    throw new Error("JUNIPER_SPACE_URI must be one exact Space AT URI");
  }
  const communityActorDid = required(
    env.JUNIPER_COMMUNITY_ACTOR_DID,
    "JUNIPER_COMMUNITY_ACTOR_DID",
  );
  if (!/^did:(?:plc|web):[^\s/]+$/.test(communityActorDid)) {
    throw new Error("JUNIPER_COMMUNITY_ACTOR_DID must be a DID");
  }
  const runtimeDirectory = resolve(
    required(env.JUNIPER_RUNTIME_DIR, "JUNIPER_RUNTIME_DIR"),
  );
  const projectionDirectory = resolve(
    required(env.JUNIPER_PROJECTION_DIR, "JUNIPER_PROJECTION_DIR"),
  );
  const port = Number(env.PORT ?? "3210");
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new Error("PORT must be an integer from 1 through 65535");
  }
  return {
    publicUrl,
    spaceUri,
    communityActorDid,
    runtimeDirectory,
    projectionDirectory,
    port,
  };
}

export function isLoopbackOrigin(origin: string): boolean {
  const hostname = new URL(origin).hostname.replace(/^\[|\]$/g, "");
  return (
    hostname === "localhost" ||
    hostname === "::1" ||
    (isIP(hostname) === 4 && hostname.startsWith("127."))
  );
}

function exactOrigin(value: string): string {
  const parsed = new URL(value);
  const loopback = isLoopbackOrigin(parsed.origin);
  if ((parsed.protocol !== "https:" && !loopback) || parsed.username || parsed.password) {
    throw new Error("JUNIPER_PUBLIC_URL must be an HTTPS origin");
  }
  if (parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error("JUNIPER_PUBLIC_URL must not contain path, query, or fragment");
  }
  return parsed.origin;
}

function required(value: string | undefined, name: string): string {
  const normalized = value?.trim();
  if (!normalized) throw new Error(`${name} is required`);
  return normalized;
}
