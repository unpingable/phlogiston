import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import type { LexMap } from "@atproto/lex-data";

export const LEXICON_COLLECTION = "com.atproto.lexicon.schema";
export const LEXICON_SCOPE = "atproto repo:com.atproto.lexicon.schema?action=create";
export const NAMESPACE_AUTHORITY = "community.phlogiston.app";
export const DNS_NAME = "_lexicon.community.phlogiston.app";
export const MANIFEST_CONTRACT = "pcv0-lexicon-publication-manifest/1";
export const ACCEPTANCE_CONTRACT = "pcv0-lexicon-publication-acceptance/1";
export const RECEIPT_CONTRACT = "pcv0-lexicon-publication-receipt/1";

export const LEXICON_IDS = Object.freeze([
  "app.phlogiston.community.profile",
  "app.phlogiston.community.submit",
  "app.phlogiston.community.admission",
  "app.phlogiston.community.modAction",
  "app.phlogiston.community.memberAction",
  "app.phlogiston.community.replyPolicy",
  "app.phlogiston.community.replyAdmission",
  "app.phlogiston.community.replyAction",
] as const);

const DOCUMENT_SHA256 = Object.freeze<Record<string, string>>({
  "app.phlogiston.community.admission": "fe9b1a8bdf4b60e7b7cb588b862c624e7ee71f70bb77c1a4a723d8a3d8baedd9",
  "app.phlogiston.community.modAction": "e7879aed2706e35a65ebf97cd5c94fdd3c8e4f54cb84e00a5d821c704f94915f",
  "app.phlogiston.community.memberAction": "549ef10d92c04dbf5b020003bcbd62c8edc9e2eb0397268cbf85e23898038fe1",
  "app.phlogiston.community.profile": "e1c9a1e30aefab5f579bef2cc2caa069fe1c102a2692776b47f96db32b537d3a",
  "app.phlogiston.community.replyAction": "0353e6f3c8af0c7760952009eff377966009600ea32bbd147fea2e5b69070bdb",
  "app.phlogiston.community.replyAdmission": "4f8e4cd50d9f39768a04ec281d26cc02bfceb5796d7752e0f8f4a27606aef6e1",
  "app.phlogiston.community.replyPolicy": "5f8b5a724339d0893b6612bb0ac656e305eb117b390459c6773f09215b8c7332",
  "app.phlogiston.community.submit": "0d1cb4ed8b80a77332904f24ed701d8731950f491999dbbf46ff7c604b6d3c96",
});

export type LexiconDocument = LexMap & Readonly<{
  lexicon: 1;
  id: string;
  defs: LexMap;
}>;

export type ManifestDocument = Readonly<{
  nsid: string;
  rkey: string;
  documentSha256: string;
  recordSha256: string;
  uri: string;
  document: LexiconDocument;
}>;

export type PublicationManifest = Readonly<{
  contract: typeof MANIFEST_CONTRACT;
  namespaceAuthority: typeof NAMESPACE_AUTHORITY;
  dnsName: typeof DNS_NAME;
  dnsTxt: string;
  authorityDid: string;
  collection: typeof LEXICON_COLLECTION;
  documents: readonly ManifestDocument[];
}>;

export type HumanAcceptance = Readonly<{
  contract: typeof ACCEPTANCE_CONTRACT;
  manifestSha256: string;
  authorityDid: string;
  acceptedBy: string;
  acceptedAt: string;
}>;

export async function loadPackagedDocuments(
  directory = new URL("../lexicons/", import.meta.url),
): Promise<readonly LexiconDocument[]> {
  const names = (await readdir(directory)).filter((name) => name.endsWith(".json")).sort();
  const documents: unknown[] = [];
  for (const name of names) {
    documents.push(JSON.parse(await readFile(new URL(name, directory), "utf8")) as unknown);
  }
  return parsePackagedDocuments(documents);
}

export function parsePackagedDocuments(rawDocuments: readonly unknown[]): readonly LexiconDocument[] {
  if (rawDocuments.length !== LEXICON_IDS.length) {
    throw new Error("exactly eight frozen PCV0 Lexicons are required");
  }
  const byId = new Map<string, LexiconDocument>();
  for (const value of rawDocuments) {
    const raw = object(value, "Lexicon must be an object");
    if (
      Object.keys(raw).sort().join(",") !== "defs,id,lexicon"
      || raw.lexicon !== 1
      || typeof raw.id !== "string"
      || !raw.defs
      || typeof raw.defs !== "object"
      || Array.isArray(raw.defs)
      || !LEXICON_IDS.includes(raw.id as (typeof LEXICON_IDS)[number])
    ) {
      throw new Error("Lexicon differs from frozen PCV0 document envelope");
    }
    if (byId.has(raw.id)) throw new Error("duplicate PCV0 Lexicon");
    if (nsidAuthority(raw.id) !== NAMESPACE_AUTHORITY) {
      throw new Error("Lexicon namespace authority differs from community.phlogiston.app");
    }
    const digest = sha256(raw);
    if (DOCUMENT_SHA256[raw.id] !== digest) {
      throw new Error("Lexicon content differs from frozen canonical digest");
    }
    byId.set(raw.id, raw as LexiconDocument);
  }
  return Object.freeze(LEXICON_IDS.map((id) => {
    const document = byId.get(id);
    if (!document) throw new Error("missing frozen PCV0 Lexicon");
    return document;
  }));
}

export function createManifest(
  authorityDid: string,
  documents: readonly LexiconDocument[],
): PublicationManifest {
  requireDid(authorityDid);
  const exact = parsePackagedDocuments(documents);
  return Object.freeze({
    contract: MANIFEST_CONTRACT,
    namespaceAuthority: NAMESPACE_AUTHORITY,
    dnsName: DNS_NAME,
    dnsTxt: `did=${authorityDid}`,
    authorityDid,
    collection: LEXICON_COLLECTION,
    documents: Object.freeze(exact.map((document) => {
      const record = publicationRecord(document);
      return Object.freeze({
        nsid: document.id,
        rkey: document.id,
        documentSha256: prefixedSha256(document),
        recordSha256: prefixedSha256(record),
        uri: `at://${authorityDid}/${LEXICON_COLLECTION}/${document.id}`,
        document,
      });
    })),
  });
}

export function parseManifest(
  value: unknown,
  documents: readonly LexiconDocument[],
): PublicationManifest {
  const raw = object(value, "publication manifest must be an object");
  const authorityDid = text(raw.authorityDid, "manifest authority DID is invalid");
  const expected = createManifest(authorityDid, documents);
  if (stable(raw) !== stable(expected)) {
    throw new Error("publication manifest differs from frozen schema set");
  }
  return expected;
}

export function parseAcceptance(value: unknown, manifest: PublicationManifest): HumanAcceptance {
  const raw = object(value, "human acceptance must be an object");
  const keys = Object.keys(raw).sort().join(",");
  if (keys !== "acceptedAt,acceptedBy,authorityDid,contract,manifestSha256") {
    throw new Error("human acceptance fields differ from frozen contract");
  }
  const acceptedBy = text(raw.acceptedBy, "human acceptor is invalid");
  if (acceptedBy.length > 200 || /[\u0000-\u001f\u007f]/u.test(acceptedBy)) {
    throw new Error("human acceptor is invalid");
  }
  const acceptedAt = text(raw.acceptedAt, "human acceptance time is invalid");
  if (!/(?:Z|[+-]\d\d:\d\d)$/u.test(acceptedAt) || Number.isNaN(Date.parse(acceptedAt))) {
    throw new Error("human acceptance time is invalid");
  }
  const expectedDigest = manifestDigest(manifest);
  if (
    raw.contract !== ACCEPTANCE_CONTRACT
    || raw.authorityDid !== manifest.authorityDid
    || raw.manifestSha256 !== expectedDigest
  ) {
    throw new Error("human acceptance does not bind the exact publication manifest");
  }
  return Object.freeze({
    contract: ACCEPTANCE_CONTRACT,
    manifestSha256: expectedDigest,
    authorityDid: manifest.authorityDid,
    acceptedBy,
    acceptedAt,
  });
}

export function publicationRecord(document: LexiconDocument): LexMap {
  return { $type: LEXICON_COLLECTION, ...document } satisfies LexMap;
}

export function manifestDigest(manifest: PublicationManifest): string {
  return prefixedSha256(manifest);
}

export function prefixedSha256(value: unknown): string {
  return `sha256:${sha256(value)}`;
}

export function sha256(value: unknown): string {
  return createHash("sha256").update(stable(value), "utf8").digest("hex");
}

export function nsidAuthority(nsid: string): string {
  const segments = nsid.split(".");
  if (segments.length < 3) throw new Error("invalid NSID");
  return segments.slice(0, -1).reverse().join(".");
}

export function requireDid(value: string): void {
  if (!/^did:(?:plc|web):[A-Za-z0-9._:%-]+(?::[A-Za-z0-9._:%-]+)*$/u.test(value)) {
    throw new Error("schema authority DID is invalid");
  }
}

export function stable(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`)
      .join(",")}}`;
  }
  throw new Error("value is outside bounded canonical JSON");
}

export async function readJson(path: string): Promise<unknown> {
  return JSON.parse(await readFile(path, "utf8")) as unknown;
}

export function packagedLexiconPath(nsid: string): string {
  return join("lexicons", `${nsid}.json`);
}

function object(value: unknown, message: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(message);
  return value as Record<string, unknown>;
}

function text(value: unknown, message: string): string {
  if (typeof value !== "string" || !value) throw new Error(message);
  return value;
}
