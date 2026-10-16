import { createHash } from "node:crypto";
import type { LexMap } from "@atproto/lex-data";

export const AUTHORITY_DID = "did:plc:wklgd4ebjiajx4gj3fthp62m";
export const PREFIX = "net.sp00ky.juniper-pds.authority";
export const NAMESPACE_AUTHORITY = "authority.juniper-pds.sp00ky.net";
export const SPACE_TYPE = `${PREFIX}.juniperCommunity` as const;
export const PERMISSION_SET = `${PREFIX}.juniperPermissions` as const;
export const SPACE_URI = `at://${AUTHORITY_DID}/space/${SPACE_TYPE}/self`;
export const LEXICON_COLLECTION = "com.atproto.lexicon.schema";
export const LEXICON_IDS = Object.freeze([
  SPACE_TYPE,
  PERMISSION_SET,
  `${PREFIX}.juniperPost`,
  `${PREFIX}.juniperSubmission`,
  `${PREFIX}.juniperAdmission`,
  `${PREFIX}.juniperRemoval`,
  `${PREFIX}.juniperWithdrawal`,
]);

const DOCUMENT_SHA256 = Object.freeze<Record<string, string>>({
  [`${PREFIX}.juniperAdmission`]: "93ea2057423c92468362abe3c9e5b923963ced48c7e29a8b53ed0dfadc8a86b2",
  [SPACE_TYPE]: "b1d56a9bca6466272126e6d7387ed62384a2ed1a8fe50dad7e8170a8455c0403",
  [PERMISSION_SET]: "a086384a5caf5eced4169327676a339e985feaa7f6cbc1cf1e8be1a3028f269d",
  [`${PREFIX}.juniperPost`]: "e934ad4626ff418ac7d5b80f550d225db9fcffe2f975f1fbf7eaa9db9379edf4",
  [`${PREFIX}.juniperRemoval`]: "844d2a39b61ce7990529e25882237ffec98c05e21bddf8003bb4136efa3b6060",
  [`${PREFIX}.juniperSubmission`]: "296a96b48e8ce4206c520de461faccb53fc90573353841260d9152e37a9cf600",
  [`${PREFIX}.juniperWithdrawal`]: "f6627d409a6d96aca323fc76432c474e05f850832090db4a2398576c403e1ea9",
});

export type LexiconDocument = LexMap & Readonly<{ lexicon: 1; id: string; defs: LexMap }>;
export type ExactRecord = Readonly<{ uri: string; cid: string }>;
export interface LexiconRepository {
  create(input: Readonly<{ rkey: string; record: LexMap }>): Promise<ExactRecord>;
  get(input: Readonly<{ rkey: string }>): Promise<ExactRecord & { value: LexMap }>;
}
export type PublishedLexicon = Readonly<{
  nsid: string;
  documentSha256: string;
  uri: string;
  cid: string;
  created: boolean;
}>;

export async function publishExactLexicons(
  repository: LexiconRepository,
  rawDocuments: readonly unknown[],
): Promise<readonly PublishedLexicon[]> {
  const documents = parseLexicons(rawDocuments);
  const results: PublishedLexicon[] = [];
  for (const document of documents) {
    const record = { $type: LEXICON_COLLECTION, ...document } satisfies LexMap;
    const expectedUri = `at://${AUTHORITY_DID}/${LEXICON_COLLECTION}/${document.id}`;
    let created: ExactRecord;
    try {
      created = await repository.create({ rkey: document.id, record });
    } catch (cause) {
      let existing: Awaited<ReturnType<LexiconRepository["get"]>>;
      try {
        existing = await repository.get({ rkey: document.id });
      } catch {
        throw new Error("Lexicon create failed and exact readback did not settle it", { cause });
      }
      requireRecord(existing, expectedUri);
      if (stable(existing.value) !== stable(record)) {
        throw new Error("published Lexicon differs from frozen document", { cause });
      }
      results.push(receipt(document, existing, false));
      continue;
    }
    requireRecord(created, expectedUri);
    results.push(receipt(document, created, true));
  }
  return Object.freeze(results);
}

export interface SpaceBootstrapClient {
  create(input: Readonly<{
    type: typeof SPACE_TYPE;
    skey: "self";
    policy: LexMap;
    appAccess: LexMap;
  }>): Promise<Readonly<{ uri: string }>>;
  get(space: string): Promise<Readonly<{ uri: string; policy: LexMap; appAccess: LexMap }>>;
}
export type SpaceBootstrapReceipt = Readonly<{
  uri: string;
  type: typeof SPACE_TYPE;
  skey: "self";
  policy: "public";
  appAccess: "open";
  created: boolean;
  compatibilityProfile: "atproto-spaces-89deb9f";
  verifiedClaims: readonly string[];
  explicitNonClaims: readonly string[];
}>;
const POLICY = Object.freeze({ $type: "com.atproto.simplespace.defs#publicPolicy" });
const APP_ACCESS = Object.freeze({ $type: "com.atproto.simplespace.defs#open" });

export async function createExactPublicSpace(client: SpaceBootstrapClient): Promise<SpaceBootstrapReceipt> {
  let created = true;
  let result: Awaited<ReturnType<SpaceBootstrapClient["get"]>> | undefined;
  let output: Awaited<ReturnType<SpaceBootstrapClient["create"]>>;
  try {
    output = await client.create({ type: SPACE_TYPE, skey: "self", policy: POLICY, appAccess: APP_ACCESS });
  } catch (cause) {
    created = false;
    try { result = await client.get(SPACE_URI); }
    catch { throw new Error("Space create failed and exact readback did not settle it", { cause }); }
    output = { uri: SPACE_URI };
  }
  if (created) {
    if (output.uri !== SPACE_URI) throw new Error("Space host substituted URI");
    result = { uri: output.uri, policy: POLICY, appAccess: APP_ACCESS };
  }
  if (!result || result.uri !== SPACE_URI || stable(result.policy) !== stable(POLICY) || stable(result.appAccess) !== stable(APP_ACCESS)) {
    throw new Error("existing Space differs from frozen public/open contract");
  }
  return Object.freeze({
    uri: SPACE_URI,
    type: SPACE_TYPE,
    skey: "self",
    policy: "public",
    appAccess: "open",
    created,
    compatibilityProfile: "atproto-spaces-89deb9f",
    verifiedClaims: Object.freeze(["space_uri_matches_frozen_contract", "space_policy_is_public", "space_app_access_is_open"]),
    explicitNonClaims: Object.freeze(["community_membership", "community_standing", "governance_authority", "production_readiness"]),
  });
}

export function parseLexicons(rawDocuments: readonly unknown[]): readonly LexiconDocument[] {
  if (rawDocuments.length !== LEXICON_IDS.length) throw new Error("exactly seven frozen Juniper Lexicons are required");
  const byId = new Map<string, LexiconDocument>();
  for (const value of rawDocuments) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Lexicon must be an object");
    const raw = value as Record<string, unknown>;
    if (Object.keys(raw).sort().join(",") !== "defs,id,lexicon" || raw.lexicon !== 1 || typeof raw.id !== "string" || !raw.defs || typeof raw.defs !== "object" || Array.isArray(raw.defs) || !LEXICON_IDS.includes(raw.id)) {
      throw new Error("Lexicon differs from frozen Juniper document envelope");
    }
    if (byId.has(raw.id)) throw new Error("duplicate Juniper Lexicon");
    if (nsidAuthority(raw.id) !== NAMESPACE_AUTHORITY) {
      throw new Error("Lexicon namespace authority differs from frozen handle");
    }
    const digest = createHash("sha256").update(stable(raw)).digest("hex");
    if (DOCUMENT_SHA256[raw.id] !== digest) throw new Error("Lexicon content differs from frozen digest");
    byId.set(raw.id, raw as LexiconDocument);
  }
  return Object.freeze(LEXICON_IDS.map((id) => {
    const document = byId.get(id);
    if (!document) throw new Error("missing frozen Juniper Lexicon");
    return document;
  }));
}

export function nsidAuthority(nsid: string): string {
  const segments = nsid.split(".");
  if (segments.length < 3) throw new Error("invalid NSID");
  return segments.slice(0, -1).reverse().join(".");
}

function receipt(document: LexiconDocument, record: ExactRecord, created: boolean): PublishedLexicon {
  return Object.freeze({ nsid: document.id, documentSha256: `sha256:${DOCUMENT_SHA256[document.id]}`, uri: record.uri, cid: record.cid, created });
}
function requireRecord(record: ExactRecord, uri: string): void {
  if (record.uri !== uri || !/^b[a-z2-7]+$/.test(record.cid)) throw new Error("repository returned substituted Lexicon identity");
}
export function stable(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(",")}}`;
  throw new Error("value is outside bounded canonical JSON");
}
