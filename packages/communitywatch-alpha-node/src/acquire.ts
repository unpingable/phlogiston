import { createHash, randomUUID } from "node:crypto";
import { chmod, link, mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { JoseKey } from "@atproto/jwk-jose";
import { createDpopProof, dpopJktForKey, verifyDpopProof } from "@atproto/space";
import type { ObserverConfig } from "./config.js";

export const ACQUISITION_METHOD = "juniper-communitywatch-alpha/1";

export type SafeTransportAttempt = Readonly<{
  ordinal: number;
  method: string;
  url: string;
  status: number | null;
  purpose: "oauth-library" | "credential-exchange" | "artifact";
}>;

export interface DelegationSource {
  getDelegationToken(space: string): Promise<Readonly<{ token: string; attempts: readonly SafeTransportAttempt[] }>>;
}

export type AcquisitionRequest = Readonly<{
  kind: "get_repo" | "list_repo_ops";
  requestId: string;
  repoDid: string;
  since?: string;
  cursor?: string;
  limit?: number;
}>;

export type AcquisitionReceipt = Readonly<{
  receiptId: string;
  method: typeof ACQUISITION_METHOD;
  requestId: string;
  artifactKind: AcquisitionRequest["kind"];
  space: string;
  repoDid: string;
  requestedUrl: string;
  observedAt: string;
  status: number;
  contentType: string | null;
  bodySha256: string;
  bodyLength: number;
  bodyFile: string;
  delegationSha256: string;
  credentialSha256: string;
  dpopKeyThumbprint: string;
  credentialExchangeProofSha256: string;
  artifactProofSha256: string;
  proofClaimsSelfVerified: true;
  attempts: readonly SafeTransportAttempt[];
  automaticArtifactRetries: 0;
  redirectsFollowed: 0;
  verifiedClaims: readonly ["exact_http_response_bytes", "credential_bound_dpop_request"];
  explicitNonClaims: readonly string[];
}>;

const NON_CLAIMS = Object.freeze([
  "artifact_validity",
  "source_authority",
  "did_resolution",
  "space_admission",
  "community_standing",
  "governance_authority",
  "currentness",
  "complete_history",
]);

export async function acquireArtifact(
  config: ObserverConfig,
  delegationSource: DelegationSource,
  request: AcquisitionRequest,
  fetchImplementation: typeof fetch = globalThis.fetch,
  now: () => Date = () => new Date(),
): Promise<Readonly<{ receipt: AcquisitionReceipt; receiptFile: string; bodyFile: string }>> {
  validateRequest(request);
  const delegation = await delegationSource.getDelegationToken(config.space);
  if (!delegation.token) throw new Error("delegation token missing");
  validateAttempts(delegation.attempts);

  const key = await JoseKey.generate(["ES256"]);
  const thumbprint = await dpopJktForKey(key);
  const credentialUrl = `${config.authorityOrigin}/xrpc/com.atproto.space.getSpaceCredential`;
  const exchangeProof = await createDpopProof(key, { htm: "POST", htu: credentialUrl });
  const verifiedExchange = await verifyDpopProof(exchangeProof, { htm: "POST", htu: credentialUrl });
  if (verifiedExchange.jkt !== thumbprint) throw new Error("credential exchange proof key differs");

  const exchange = await boundedFetch(fetchImplementation, credentialUrl, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Accept-Encoding": "identity",
      Authorization: `Bearer ${delegation.token}`,
      "Content-Type": "application/json",
      DPoP: exchangeProof,
    },
    body: JSON.stringify({ space: config.space }),
  }, config.maximumJsonBytes, config.timeoutMilliseconds);
  const exchangeAttempt = attempt(delegation.attempts.length, "POST", credentialUrl, exchange.status, "credential-exchange");
  if (exchange.status !== 200) throw new Error("Space credential exchange refused");
  const credential = exactCredential(exchange.body);

  const requestedUrl = artifactUrl(config, request);
  const artifactProof = await createDpopProof(key, { htm: "GET", htu: requestedUrl, credential });
  const verifiedArtifact = await verifyDpopProof(artifactProof, { htm: "GET", htu: requestedUrl, credential, jkt: thumbprint });
  if (verifiedArtifact.jkt !== thumbprint) throw new Error("artifact proof key differs");
  const maximum = request.kind === "get_repo" ? config.maximumCarBytes : config.maximumJsonBytes;
  const response = await boundedFetch(fetchImplementation, requestedUrl, {
    method: "GET",
    headers: {
      Accept: request.kind === "get_repo" ? "application/vnd.ipld.car" : "application/json",
      "Accept-Encoding": "identity",
      Authorization: `DPoP ${credential}`,
      DPoP: artifactProof,
    },
  }, maximum, config.timeoutMilliseconds);
  const artifactAttempt = attempt(delegation.attempts.length + 1, "GET", requestedUrl, response.status, "artifact");
  if (response.status !== 200) throw new Error("Spaces artifact acquisition refused");

  const observedAt = now();
  if (!Number.isFinite(observedAt.getTime())) throw new Error("observation time invalid");
  const artifactDirectory = join(config.runtimeDirectory, "artifacts");
  await mkdir(artifactDirectory, { recursive: true, mode: 0o700 });
  await chmod(artifactDirectory, 0o700);
  const extension = request.kind === "get_repo" ? "car" : "json";
  const bodyFile = `${request.requestId}.${extension}`;
  const receiptFile = `${request.requestId}.receipt.json`;
  const receiptWithoutId = {
    method: ACQUISITION_METHOD as typeof ACQUISITION_METHOD,
    requestId: request.requestId,
    artifactKind: request.kind,
    space: config.space,
    repoDid: request.repoDid,
    requestedUrl,
    observedAt: observedAt.toISOString(),
    status: response.status,
    contentType: safeContentType(response.contentType),
    bodySha256: sha(response.body),
    bodyLength: response.body.length,
    bodyFile,
    delegationSha256: shaText(delegation.token),
    credentialSha256: shaText(credential),
    dpopKeyThumbprint: thumbprint,
    credentialExchangeProofSha256: shaText(exchangeProof),
    artifactProofSha256: shaText(artifactProof),
    proofClaimsSelfVerified: true as const,
    attempts: Object.freeze([...delegation.attempts, exchangeAttempt, artifactAttempt]),
    automaticArtifactRetries: 0 as const,
    redirectsFollowed: 0 as const,
    verifiedClaims: Object.freeze(["exact_http_response_bytes", "credential_bound_dpop_request"] as const),
    explicitNonClaims: NON_CLAIMS,
  };
  const receipt: AcquisitionReceipt = Object.freeze({ receiptId: `sha256:${sha(Buffer.from(stable(receiptWithoutId)))}`, ...receiptWithoutId });
  await atomicWrite(artifactDirectory, bodyFile, response.body);
  await atomicWrite(artifactDirectory, receiptFile, Buffer.from(`${stable(receipt)}\n`));
  return Object.freeze({ receipt, receiptFile: join(artifactDirectory, receiptFile), bodyFile: join(artifactDirectory, bodyFile) });
}

function validateRequest(request: AcquisitionRequest): void {
  if (!/^[A-Za-z0-9._-]{1,96}$/.test(request.requestId)) throw new Error("request ID is invalid");
  if (!/^did:(?:plc|web):[^\s/]+$/.test(request.repoDid)) throw new Error("repo DID is invalid");
  const keys = Object.keys(request).sort();
  const allowed = request.kind === "get_repo" ? ["kind", "repoDid", "requestId"] : ["cursor", "kind", "limit", "repoDid", "requestId", "since"];
  if (keys.some((key) => !allowed.includes(key))) throw new Error("acquisition request has unexpected fields");
  if (request.kind === "get_repo") {
    if (keys.length !== 3) throw new Error("full-repo request fields differ");
    return;
  }
  if (request.kind !== "list_repo_ops" || typeof request.since !== "string" || !/^[2-7a-z]{13}$/.test(request.since)) throw new Error("operation since revision is invalid");
  if (request.cursor !== undefined && (!request.cursor || /\s/.test(request.cursor))) throw new Error("operation cursor is invalid");
  const limit = request.limit ?? 100;
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 1000) throw new Error("operation limit is invalid");
}

function artifactUrl(config: ObserverConfig, request: AcquisitionRequest): string {
  const endpoint = request.kind === "get_repo" ? "com.atproto.space.getRepo" : "com.atproto.space.listRepoOps";
  const url = new URL(`/xrpc/${endpoint}`, config.repoHostOrigin);
  url.searchParams.set("space", config.space);
  url.searchParams.set("repo", request.repoDid);
  url.searchParams.set("excludeValues", "false");
  if (request.kind === "list_repo_ops") {
    url.searchParams.set("since", request.since!);
    url.searchParams.set("limit", String(request.limit ?? 100));
    if (request.cursor !== undefined) url.searchParams.set("cursor", request.cursor);
  }
  return url.toString();
}

async function boundedFetch(fetchImplementation: typeof fetch, url: string, init: RequestInit, maximum: number, timeoutMilliseconds: number): Promise<Readonly<{ status: number; body: Buffer; contentType: string | null }>> {
  const response = await fetchImplementation(url, { ...init, redirect: "manual", signal: AbortSignal.timeout(timeoutMilliseconds) });
  if (response.status >= 300 && response.status < 400) throw new Error("redirect refused");
  const declared = response.headers.get("content-length");
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > maximum)) throw new Error("response size refused");
  const reader = response.body?.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  if (reader) {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > maximum) { await reader.cancel(); throw new Error("response size refused"); }
      chunks.push(value);
    }
  }
  const body = Buffer.concat(chunks.map((chunk) => Buffer.from(chunk)), length);
  if (declared !== null && Number(declared) !== body.length) throw new Error("response length mismatch");
  return Object.freeze({ status: response.status, body, contentType: response.headers.get("content-type") });
}

function exactCredential(body: Buffer): string {
  let value: unknown;
  try { value = JSON.parse(body.toString("utf8")); } catch { throw new Error("credential response is not JSON"); }
  if (!value || typeof value !== "object" || Array.isArray(value) || JSON.stringify(Object.keys(value).sort()) !== JSON.stringify(["credential"])) throw new Error("credential response fields differ");
  const credential = (value as { credential?: unknown }).credential;
  if (typeof credential !== "string" || credential.split(".").length !== 3) throw new Error("credential response is invalid");
  return credential;
}

function attempt(ordinal: number, method: string, url: string, status: number | null, purpose: SafeTransportAttempt["purpose"]): SafeTransportAttempt {
  return Object.freeze({ ordinal, method, url, status, purpose });
}

function validateAttempts(attempts: readonly SafeTransportAttempt[]): void {
  if (!Array.isArray(attempts)) throw new Error("OAuth attempt evidence is invalid");
  attempts.forEach((item, ordinal) => {
    const parsed = new URL(item.url);
    if (item.ordinal !== ordinal || !["GET", "POST"].includes(item.method) || item.purpose !== "oauth-library" || parsed.username || parsed.password || (item.status !== null && (!Number.isInteger(item.status) || item.status < 100 || item.status > 599))) throw new Error("OAuth attempt evidence is invalid");
  });
}

function safeContentType(value: string | null): string | null {
  if (value === null) return null;
  if (value.length > 256 || /[\x00-\x1f\x7f]/.test(value)) throw new Error("response content type is invalid");
  return value;
}

function sha(value: Uint8Array): string { return createHash("sha256").update(value).digest("hex"); }
function shaText(value: string): string { return sha(Buffer.from(value)); }
function stable(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(",")}}`;
  throw new Error("receipt contains unsupported value");
}

async function atomicWrite(directory: string, name: string, body: Buffer): Promise<void> {
  const target = join(directory, name);
  const temporary = join(directory, `.write-${randomUUID()}`);
  try {
    await writeFile(temporary, body, { mode: 0o600, flag: "wx" });
    await link(temporary, target);
    await rm(temporary);
    await chmod(target, 0o600);
  } catch (error) {
    await rm(temporary, { force: true }).catch(() => undefined);
    throw error;
  }
}
