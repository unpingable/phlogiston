import type { LexMap } from "@atproto/lex-data";
import {
  ACCEPTANCE_CONTRACT,
  RECEIPT_CONTRACT,
  manifestDigest,
  prefixedSha256,
  publicationRecord,
  stable,
  type HumanAcceptance,
  type ManifestDocument,
  type PublicationManifest,
} from "./contract.js";

export type ExactRecord = Readonly<{ uri: string; cid: string; value: LexMap }>;

export interface LexiconRepository {
  create(input: Readonly<{ rkey: string; record: LexMap }>): Promise<Readonly<{ uri: string; cid: string }>>;
  get(input: Readonly<{ rkey: string }>): Promise<ExactRecord | null>;
}

export interface DnsTxtResolver {
  resolveTxt(name: string): Promise<readonly string[]>;
}

export type IntentPhase = "prepared" | "attempting" | "attempted_unknown" | "settled";
export type PublicationDisposition = "created" | "read_back";

export type PublicationIntent = Readonly<{
  contract: "pcv0-lexicon-publication-intent/1";
  manifestSha256: string;
  authorityDid: string;
  nsid: string;
  rkey: string;
  expectedUri: string;
  documentSha256: string;
  recordSha256: string;
  phase: IntentPhase;
  attempts: number;
  cid?: string;
  disposition?: PublicationDisposition;
}>;

export interface PublicationJournal {
  reserve(intent: PublicationIntent): Promise<PublicationIntent>;
  save(intent: PublicationIntent): Promise<void>;
}

export type PublishedLexicon = Readonly<{
  nsid: string;
  documentSha256: string;
  uri: string;
  cid: string;
  disposition: PublicationDisposition;
}>;

export type PublicationReceipt = Readonly<{
  contract: typeof RECEIPT_CONTRACT;
  manifestSha256: string;
  authorityDid: string;
  namespaceAuthority: string;
  dns: Readonly<{
    name: string;
    expected: string;
    answers: readonly string[];
    verified: true;
  }>;
  records: readonly PublishedLexicon[];
  completedAt: string;
  explicitNonClaims: readonly string[];
}>;

export async function publishAcceptedManifest(
  repository: LexiconRepository,
  resolver: DnsTxtResolver,
  journal: PublicationJournal,
  manifest: PublicationManifest,
  acceptance: HumanAcceptance,
  now: () => Date = () => new Date(),
): Promise<PublicationReceipt> {
  const digest = manifestDigest(manifest);
  if (
    acceptance.contract !== ACCEPTANCE_CONTRACT
    || acceptance.manifestSha256 !== digest
    || acceptance.authorityDid !== manifest.authorityDid
  ) {
    throw new Error("human acceptance does not bind the exact publication manifest");
  }

  const dnsAnswers = await verifyNamespaceDns(resolver, manifest);
  const results: PublishedLexicon[] = [];
  for (const document of manifest.documents) {
    results.push(await publishOne(repository, journal, manifest, document));
  }

  const completedAt = now().toISOString();
  return Object.freeze({
    contract: RECEIPT_CONTRACT,
    manifestSha256: digest,
    authorityDid: manifest.authorityDid,
    namespaceAuthority: manifest.namespaceAuthority,
    dns: Object.freeze({
      name: manifest.dnsName,
      expected: manifest.dnsTxt,
      answers: dnsAnswers,
      verified: true,
    }),
    records: Object.freeze(results),
    completedAt,
    explicitNonClaims: Object.freeze([
      "community_admission_authority",
      "community_moderation_authority",
      "participant_consent",
      "production_readiness",
    ]),
  });
}

export async function verifyNamespaceDns(
  resolver: DnsTxtResolver,
  manifest: PublicationManifest,
): Promise<readonly string[]> {
  const answers = Object.freeze([...(await resolver.resolveTxt(manifest.dnsName))].sort());
  const didAnswers = answers.filter((answer) => answer.startsWith("did="));
  if (didAnswers.length !== 1 || didAnswers[0] !== manifest.dnsTxt) {
    throw new Error("Lexicon namespace DNS does not resolve to the manifest authority DID");
  }
  return answers;
}

async function publishOne(
  repository: LexiconRepository,
  journal: PublicationJournal,
  manifest: PublicationManifest,
  item: ManifestDocument,
): Promise<PublishedLexicon> {
  const record = publicationRecord(item.document);
  if (prefixedSha256(record) !== item.recordSha256) {
    throw new Error("manifest record digest differs from embedded Lexicon");
  }
  const expected = preparedIntent(manifest, item);
  let intent = await journal.reserve(expected);
  requireSameOperation(intent, expected);

  if (intent.phase === "settled") {
    const existing = await repository.get({ rkey: item.rkey });
    requireExactReadback(existing, item, record);
    return published(item, existing, "read_back");
  }

  if (intent.phase === "attempting" || intent.phase === "attempted_unknown") {
    const existing = await repository.get({ rkey: item.rkey });
    if (existing) {
      requireExactReadback(existing, item, record);
      intent = settledIntent(intent, existing.cid, "read_back");
      await journal.save(intent);
      return published(item, existing, "read_back");
    }
    // A null readback is not proof that the prior create had no effect. Keep
    // this operation uncertain until exact readback can settle it; never
    // dispatch a second create from an attempted state.
    if (intent.phase === "attempting") {
      intent = Object.freeze({ ...intent, phase: "attempted_unknown" });
      await journal.save(intent);
    }
    throw new Error("Lexicon create outcome remains unknown after exact readback");
  }

  intent = Object.freeze({ ...intent, phase: "attempting", attempts: intent.attempts + 1 });
  await journal.save(intent);
  let created: Awaited<ReturnType<LexiconRepository["create"]>>;
  try {
    created = await repository.create({ rkey: item.rkey, record });
  } catch (cause) {
    intent = Object.freeze({ ...intent, phase: "attempted_unknown" });
    await journal.save(intent);
    const existing = await repository.get({ rkey: item.rkey });
    if (!existing) {
      throw new Error("Lexicon create failed and exact readback did not settle it", { cause });
    }
    requireExactReadback(existing, item, record);
    await journal.save(settledIntent(intent, existing.cid, "read_back"));
    return published(item, existing, "read_back");
  }

  intent = Object.freeze({ ...intent, phase: "attempted_unknown" });
  await journal.save(intent);
  requireIdentity(created, item.uri);
  const existing = await repository.get({ rkey: item.rkey });
  requireExactReadback(existing, item, record);
  if (existing.cid !== created.cid) {
    throw new Error("Lexicon create response CID differs from exact readback");
  }
  await journal.save(settledIntent(intent, existing.cid, "created"));
  return published(item, existing, "created");
}

function preparedIntent(manifest: PublicationManifest, item: ManifestDocument): PublicationIntent {
  return Object.freeze({
    contract: "pcv0-lexicon-publication-intent/1",
    manifestSha256: manifestDigest(manifest),
    authorityDid: manifest.authorityDid,
    nsid: item.nsid,
    rkey: item.rkey,
    expectedUri: item.uri,
    documentSha256: item.documentSha256,
    recordSha256: item.recordSha256,
    phase: "prepared",
    attempts: 0,
  });
}

function settledIntent(
  intent: PublicationIntent,
  cid: string,
  disposition: PublicationDisposition,
): PublicationIntent {
  return Object.freeze({ ...intent, phase: "settled", cid, disposition });
}

function requireSameOperation(actual: PublicationIntent, expected: PublicationIntent): void {
  const operationFields = [
    "contract", "manifestSha256", "authorityDid", "nsid", "rkey", "expectedUri",
    "documentSha256", "recordSha256",
  ] as const;
  for (const key of operationFields) {
    if (actual[key] !== expected[key]) throw new Error("publication intent conflicts with manifest");
  }
  if (!Number.isSafeInteger(actual.attempts) || actual.attempts < 0) {
    throw new Error("publication intent attempt count is invalid");
  }
}

function requireExactReadback(
  value: ExactRecord | null,
  item: ManifestDocument,
  record: LexMap,
): asserts value is ExactRecord {
  if (!value) throw new Error("published Lexicon is absent on exact readback");
  requireIdentity(value, item.uri);
  if (stable(value.value) !== stable(record)) {
    throw new Error("published Lexicon differs from frozen document");
  }
  if (prefixedSha256(value.value) !== item.recordSha256) {
    throw new Error("published Lexicon digest differs from frozen record digest");
  }
}

function requireIdentity(value: Readonly<{ uri: string; cid: string }>, expectedUri: string): void {
  if (value.uri !== expectedUri || !/^b[a-z2-7]+$/u.test(value.cid)) {
    throw new Error("repository returned substituted Lexicon identity");
  }
}

function published(
  item: ManifestDocument,
  record: ExactRecord,
  disposition: PublicationDisposition,
): PublishedLexicon {
  return Object.freeze({
    nsid: item.nsid,
    documentSha256: item.documentSha256,
    uri: record.uri,
    cid: record.cid,
    disposition,
  });
}
