import { isIP } from "node:net";
import { resolve } from "node:path";

export const PERMISSION_SET = "net.sp00ky.juniper-pds.authority.juniperPermissions";
export const OAUTH_SCOPE = `atproto include:${PERMISSION_SET}`;

export type ObserverConfig = Readonly<{
  runtimeDirectory: string;
  observerDid: string;
  callbackOrigin: string;
  space: string;
  authorityOrigin: string;
  repoHostOrigin: string;
  maximumCarBytes: number;
  maximumJsonBytes: number;
  timeoutMilliseconds: number;
  allowLoopbackFixtures: boolean;
}>;

export function loadConfig(env: NodeJS.ProcessEnv): ObserverConfig {
  const allowLoopbackFixtures = env.JUNIPER_OBSERVER_ALLOW_LOOPBACK_FIXTURES === "1";
  const runtimeDirectory = resolve(required(env.JUNIPER_OBSERVER_RUNTIME_DIR, "runtime directory"));
  const observerDid = did(required(env.JUNIPER_OBSERVER_DID, "observer DID"));
  const callbackOrigin = origin(required(env.JUNIPER_OBSERVER_CALLBACK_ORIGIN, "callback origin"), true);
  if (!isLoopback(new URL(callbackOrigin).hostname)) throw new Error("observer OAuth callback must be loopback");
  const space = required(env.JUNIPER_SPACE_URI, "Space URI");
  if (!/^at:\/\/did:(?:plc|web):[^/]+\/[^/]+\/[^/]+$/.test(space)) throw new Error("Space URI is invalid");
  const authorityOrigin = origin(required(env.JUNIPER_SPACE_AUTHORITY_ORIGIN, "authority origin"), allowLoopbackFixtures);
  const repoHostOrigin = origin(required(env.JUNIPER_SPACE_REPO_HOST_ORIGIN, "repo host origin"), allowLoopbackFixtures);
  return {
    runtimeDirectory,
    observerDid,
    callbackOrigin,
    space,
    authorityOrigin,
    repoHostOrigin,
    maximumCarBytes: integer(env.JUNIPER_OBSERVER_MAX_CAR_BYTES, 16 << 20, 1, 64 << 20),
    maximumJsonBytes: integer(env.JUNIPER_OBSERVER_MAX_JSON_BYTES, 1 << 20, 1, 8 << 20),
    timeoutMilliseconds: integer(env.JUNIPER_OBSERVER_TIMEOUT_MS, 10_000, 100, 60_000),
    allowLoopbackFixtures,
  };
}

function required(value: string | undefined, label: string): string {
  const normalized = value?.trim();
  if (!normalized) throw new Error(`${label} is required`);
  return normalized;
}

function did(value: string): string {
  if (!/^did:(?:plc|web):[^\s/]+$/.test(value)) throw new Error("observer DID is invalid");
  return value;
}

function integer(value: string | undefined, fallback: number, minimum: number, maximum: number): number {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) throw new Error("observer numeric bound is invalid");
  return parsed;
}

function origin(value: string, allowLoopbackHttp: boolean): string {
  const parsed = new URL(value);
  const loopback = isLoopback(parsed.hostname);
  if (parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) throw new Error("endpoint must be an origin only");
  if (parsed.protocol !== "https:" && !(allowLoopbackHttp && loopback && parsed.protocol === "http:")) throw new Error("endpoint must use HTTPS");
  return parsed.origin;
}

function isLoopback(value: string): boolean {
  const hostname = value.replace(/^\[|\]$/g, "");
  return hostname === "localhost" || hostname === "::1" || (isIP(hostname) === 4 && hostname.startsWith("127."));
}
