import { isIP } from "node:net";
import { resolve } from "node:path";

export interface AppConfig {
  profile?: "legacy" | "p0";
  sitePausePath?: string;
  admissionPausePath?: string;
  p0TestPdsOrigin?: string;
  p0HostedPdsOrigin?: string;
  p0AllowBluesky?: boolean;
  readerEnabled?: boolean;
  publicUrl: string;
  communityDid: string;
  communityName: string;
  communityPurpose: string;
  moderatorDid: string;
  runtimeDirectory: string;
  observerUrl: string;
  observerMaxResponseBytes: number;
  discussionsMaxItems: number;
  appViewOrigin: string;
  avatarsEnabled: boolean;
  observerPublicUrl?: string | undefined;
  /** Isolated-qualification seams: an alternative did:plc directory and an XRPC handle resolver. */
  plcDirectoryUrl?: string | undefined;
  handleResolverUrl?: string | undefined;
  authoritySocket: string;
  integrationFaultDirectory?: string | undefined;
  port: number;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const profile = env.COMMUNITY_PROFILE ?? "legacy";
  if (profile !== "legacy" && profile !== "p0") throw new Error("COMMUNITY_PROFILE is invalid");
  const sitePausePath = profile === "p0" ? required(env.COMMUNITY_SITE_PAUSE_PATH, "COMMUNITY_SITE_PAUSE_PATH") : undefined;
  if (sitePausePath && !sitePausePath.startsWith("/")) throw new Error("site pause path must be absolute");
  const admissionPausePath = profile === "p0" ? required(env.COMMUNITY_ADMISSION_PAUSE_PATH, "COMMUNITY_ADMISSION_PAUSE_PATH") : undefined;
  if (admissionPausePath && !admissionPausePath.startsWith("/")) throw new Error("admission pause path must be absolute");
  const publicUrl = exactOrigin(required(env.COMMUNITY_PUBLIC_URL, "COMMUNITY_PUBLIC_URL"));
  const p0TestPdsOrigin = env.COMMUNITY_P0_TEST_PDS_ORIGIN;
  if (p0TestPdsOrigin !== undefined && (profile !== "p0" || !isLoopbackOrigin(publicUrl) || p0TestPdsOrigin !== "https://juche.social")) throw new Error("P0 test PDS is allowed only as exact Juche fixture on loopback P0");
  const p0HostedPdsOrigin = env.COMMUNITY_P0_HOSTED_PDS_ORIGIN;
  if (p0HostedPdsOrigin !== undefined && (profile !== "p0" || p0HostedPdsOrigin !== "https://phlogiston.social" || p0TestPdsOrigin !== undefined)) throw new Error("P0 hosted PDS origin must be exact Phlogiston PDS without a test-provider override");
  const p0AllowBluesky = env.COMMUNITY_P0_ALLOW_BLUESKY;
  if (p0AllowBluesky !== undefined && (p0AllowBluesky !== "true" || p0HostedPdsOrigin === undefined)) throw new Error("P0 Bluesky combination requires explicit true and the exact hosted PDS origin");
  const readerEnabled = env.COMMUNITY_READER_ENABLED;
  if (readerEnabled !== undefined && (readerEnabled !== "true" || profile !== "p0")) throw new Error("COMMUNITY_READER_ENABLED requires explicit true in P0");
  const communityDid = did(required(env.COMMUNITY_DID, "COMMUNITY_DID"), "COMMUNITY_DID");
  const communityName = required(env.COMMUNITY_NAME, "COMMUNITY_NAME");
  const communityPurpose = required(env.COMMUNITY_PURPOSE, "COMMUNITY_PURPOSE");
  const moderatorDid = did(required(env.COMMUNITY_MODERATOR_DID, "COMMUNITY_MODERATOR_DID"), "COMMUNITY_MODERATOR_DID");
  const runtimeDirectory = resolve(required(env.COMMUNITY_RUNTIME_DIR, "COMMUNITY_RUNTIME_DIR"));
  const observerUrl = exactOrigin(required(env.COMMUNITY_OBSERVER_URL, "COMMUNITY_OBSERVER_URL"));
  const observerMaxResponseBytes = boundedInt(env.COMMUNITY_OBSERVER_MAX_BYTES, "COMMUNITY_OBSERVER_MAX_BYTES", 1024 * 1024, 1024, 64 * 1024 * 1024);
  const discussionsMaxItems = boundedInt(env.COMMUNITY_DISCUSSIONS_MAX_ITEMS, "COMMUNITY_DISCUSSIONS_MAX_ITEMS", 500, 1, 100_000);
  const appViewOrigin = exactOrigin(env.COMMUNITY_APPVIEW_ORIGIN ?? "https://public.api.bsky.app");
  const avatarsEnabled = avatars(env.COMMUNITY_AVATARS);
  const observerPublicUrl = observerPublicBase(env.COMMUNITY_OBSERVER_PUBLIC_URL);
  const plcDirectoryUrl = identityService(env.COMMUNITY_PLC_DIRECTORY_URL, "COMMUNITY_PLC_DIRECTORY_URL", publicUrl);
  const handleResolverUrl = identityService(env.COMMUNITY_HANDLE_RESOLVER_URL, "COMMUNITY_HANDLE_RESOLVER_URL", publicUrl);
  const authoritySocket = resolve(required(env.COMMUNITY_AUTHORITY_SOCKET, "COMMUNITY_AUTHORITY_SOCKET"));
  const integrationFaultDirectory = integrationFaults(env);
  const port = Number(env.PORT ?? "3210");
  if (!Number.isInteger(port) || port < 1 || port > 65_535) throw new Error("PORT is invalid");
  return { profile, ...(admissionPausePath === undefined ? {} : {admissionPausePath}), ...(p0TestPdsOrigin === undefined ? {} : {p0TestPdsOrigin}), ...(p0HostedPdsOrigin === undefined ? {} : {p0HostedPdsOrigin}), ...(p0AllowBluesky === undefined ? {} : {p0AllowBluesky: true}), ...(readerEnabled === undefined ? {} : {readerEnabled: true}), ...(sitePausePath === undefined ? {} : {sitePausePath}), publicUrl, communityDid, communityName, communityPurpose, moderatorDid, runtimeDirectory, observerUrl, observerMaxResponseBytes, discussionsMaxItems, appViewOrigin, avatarsEnabled, observerPublicUrl, plcDirectoryUrl, handleResolverUrl, authoritySocket, integrationFaultDirectory, port };
}

function observerPublicBase(value: string | undefined): string | undefined {
  const normalized = value?.trim();
  if (!normalized) return undefined;
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error("COMMUNITY_OBSERVER_PUBLIC_URL is invalid");
  }
  if ((parsed.protocol !== "https:" && !isLoopbackOrigin(parsed.origin)) || parsed.username || parsed.password) {
    throw new Error("COMMUNITY_OBSERVER_PUBLIC_URL must use HTTPS (loopback HTTP is allowed)");
  }
  if (parsed.search || parsed.hash || !/^\/c\/[^/]+$/.test(parsed.pathname)) {
    throw new Error("COMMUNITY_OBSERVER_PUBLIC_URL must be the observer’s public /c/{slug} base");
  }
  return `${parsed.origin}${parsed.pathname}`;
}

// The OAuth client resolves handles and did:plc documents through the public
// directory and DNS/HTTPS by default. An isolated qualification run has no
// public identity infrastructure, so it may name stand-ins for both. These
// seams exist only for that isolated run: any value at all is refused unless
// the app itself is a loopback origin, the same rule that lets OAuth run
// without TLS there, so a deployed app can never be pointed at a substitute
// identity directory.
function identityService(value: string | undefined, name: string, publicUrl: string): string | undefined {
  const normalized = value?.trim();
  if (!normalized) return undefined;
  if (!isLoopbackOrigin(publicUrl)) {
    throw new Error(`${name} is an isolated-qualification seam and is refused unless COMMUNITY_PUBLIC_URL is a loopback origin`);
  }
  try {
    return exactOrigin(normalized);
  } catch {
    throw new Error(`${name} must be a bare HTTPS or loopback HTTP origin`);
  }
}

// COMMUNITY_AVATARS=enabled makes every signed-in or anonymous viewer's
// browser request avatar images directly from https://cdn.bsky.app, which
// discloses the viewer's IP address and page-view timing to that CDN.
// Avatars are omitted unless this exact value is set; any other non-empty
// value is a configuration error.
function avatars(value: string | undefined): boolean {
  if (value === undefined || value.trim() === "") return false;
  if (value === "enabled") return true;
  throw new Error("COMMUNITY_AVATARS is invalid");
}

function integrationFaults(env: NodeJS.ProcessEnv): string | undefined {
  const enabled = env.COMMUNITY_INTEGRATION_FAULTS;
  const directory = env.COMMUNITY_INTEGRATION_FAULT_DIR?.trim();
  if (enabled === undefined && directory === undefined) return undefined;
  if (enabled !== "enabled" || !directory) {
    throw new Error("integration faults require explicit enablement and a directory");
  }
  const resolved = resolve(directory);
  if (resolved === "/" || !directory.startsWith("/")) {
    throw new Error("integration fault directory must be a bounded absolute path");
  }
  return resolved;
}

export function isLoopbackOrigin(origin: string): boolean {
  const hostname = new URL(origin).hostname.replace(/^\[|\]$/g, "");
  return hostname === "localhost" || hostname === "::1" || (isIP(hostname) === 4 && hostname.startsWith("127."));
}

function exactOrigin(value: string): string {
  const parsed = new URL(value);
  if ((parsed.protocol !== "https:" && !isLoopbackOrigin(parsed.origin)) || parsed.username || parsed.password) {
    throw new Error("origin must use HTTPS (loopback HTTP is allowed)");
  }
  if (parsed.pathname !== "/" || parsed.search || parsed.hash) throw new Error("origin must not contain a path");
  return parsed.origin;
}

function did(value: string, name: string): string {
  if (!/^did:(?:plc|web):[^\s/]+$/.test(value)) throw new Error(`${name} must be a DID`);
  return value;
}

function boundedInt(value: string | undefined, name: string, fallback: number, min: number, max: number): number {
  if (value === undefined) return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) throw new Error(`${name} is invalid`);
  return parsed;
}

function required(value: string | undefined, name: string): string {
  const normalized = value?.trim();
  if (!normalized) throw new Error(`${name} is required`);
  return normalized;
}
