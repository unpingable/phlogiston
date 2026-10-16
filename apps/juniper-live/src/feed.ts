import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import { isAbsolute, join, relative, sep } from "node:path";

const MAX_FEED_BYTES = 5 * 1024 * 1024;
const SHA = /^sha256:[0-9a-f]{64}$/;
const SECRET = /(?:\bAuthorization\s*:\s*(?:Bearer|DPoP)|\bCookie\s*:|\bSet-Cookie\s*:|access[_ -]?token|refresh[_ -]?token|space[_ -]?credential|dpop[_ -]?private[_ -]?key|moderator[_ -]?private[_ -]?key)/i;

export type PublicPresentation = Readonly<{
  sourceReferenceId: string;
  sourceUri: string;
  sourceCid: string;
  title: string;
  body: string;
  authorDisplayReference: string;
}>;

export type PublicEntry = Readonly<{
  projectionIdentity: string;
  projectionStateId: string;
  lifecycleState:
    | "added"
    | "changed_at_source"
    | "source_unavailable"
    | "author_withdrawn"
    | "removed";
  sourceUri: string;
  admittedSourceCid: string;
  authorDid: string;
  admissionId: string;
  admittedAt: string;
  sourceRelationship: string;
  presentation: PublicPresentation | null;
  technicalReceipts: Record<string, string | null> | null;
  removalId: string | null;
  withdrawalId?: string;
}>;

export type PublicFeed = Readonly<{
  feedId: string;
  artifactId: string;
  channel: "ordinary_reader" | "technical_audit";
  publishedAt: string;
  communityActorDid: string;
  entries: readonly PublicEntry[];
}>;

export type ProjectionBundle = Readonly<{
  ordinary: PublicFeed | null;
  audit: PublicFeed | null;
}>;

export async function readProjectionBundle(directory: string): Promise<ProjectionBundle> {
  const publication = await publicationDirectory(directory);
  const [ordinary, audit] = await Promise.all([
    readFeed(join(publication, "ordinary.json"), "ordinary_reader"),
    readFeed(join(publication, "audit.json"), "technical_audit"),
  ]);
  if (ordinary && audit) {
    if (ordinary.communityActorDid !== audit.communityActorDid) {
      throw new Error("projection disclosure channels disagree about community");
    }
    const ordinaryKeys = ordinary.entries.map(entryOccurrence).sort();
    const auditKeys = audit.entries.map(entryOccurrence).sort();
    if (JSON.stringify(ordinaryKeys) !== JSON.stringify(auditKeys)) {
      throw new Error("projection disclosure channels disagree about occurrences");
    }
  }
  return { ordinary, audit };
}

async function publicationDirectory(directory: string): Promise<string> {
  try {
    const [current, generations] = await Promise.all([
      realpath(join(directory, "current")),
      realpath(join(directory, "generations")),
    ]);
    const generation = relative(generations, current);
    if (
      !/^[0-9a-f]{64}$/.test(generation)
      || generation.includes(sep)
      || isAbsolute(generation)
      || generation.startsWith("..")
    ) {
      throw new Error("current projection pointer escapes immutable generations");
    }
    return current;
  } catch (error) {
    if (isMissing(error)) return directory;
    if (error instanceof Error && error.message.includes("escapes immutable generations")) {
      throw error;
    }
    throw new Error("published projection pointer could not be resolved", { cause: error });
  }
}

async function readFeed(
  path: string,
  expectedChannel: PublicFeed["channel"],
): Promise<PublicFeed | null> {
  let bytes: Buffer;
  try {
    bytes = await readFile(path);
  } catch (error) {
    if (isMissing(error)) return null;
    throw new Error("published projection artifact could not be read", { cause: error });
  }
  if (bytes.length === 0 || bytes.length > MAX_FEED_BYTES) {
    throw new Error("published projection artifact has invalid size");
  }
  const raw = bytes.toString("utf8");
  if (SECRET.test(raw)) throw new Error("published projection contains secret-shaped material");
  const root = object(JSON.parse(raw), "feed");
  if (root.feedVersion !== "scv0-public-projection-feed/1") {
    throw new Error("unsupported public projection feed version");
  }
  if (root.channel !== expectedChannel || root.disclosureMode !== expectedChannel) {
    throw new Error("public projection disclosure channel mismatch");
  }
  const artifact = object(root.artifact, "artifact");
  const artifactId = sha(canonicalJson(artifact));
  if (root.artifactId !== artifactId || root.artifactBytesSha256 !== artifactId) {
    throw new Error("public projection artifact identity mismatch");
  }
  if (artifact.disclosureMode !== expectedChannel) {
    throw new Error("embedded artifact disclosure mode mismatch");
  }
  const entries = array(artifact.entries, "artifact entries").map(parseEntry);
  const communityActorDid = text(artifact.communityActorDid, "community actor DID");
  const feedId = sha(canonicalJson(root));
  return {
    feedId,
    artifactId,
    channel: expectedChannel,
    publishedAt: text(root.publishedAt, "published time"),
    communityActorDid,
    entries,
  };
}

function parseEntry(value: unknown): PublicEntry {
  const entry = object(value, "projection entry");
  const lifecycle = text(entry.lifecycleState, "lifecycle state");
  if (![
    "added",
    "changed_at_source",
    "source_unavailable",
    "author_withdrawn",
    "removed",
  ].includes(lifecycle)) throw new Error("unsupported projection lifecycle state");
  const presentation = entry.presentation === null
    ? null
    : parsePresentation(entry.presentation);
  const receipts = entry.technicalReceipts === null
    ? null
    : object(entry.technicalReceipts, "technical receipts") as Record<string, string | null>;
  return {
    projectionIdentity: digest(entry.projectionIdentity, "projection identity"),
    projectionStateId: digest(entry.projectionStateId, "projection state"),
    lifecycleState: lifecycle as PublicEntry["lifecycleState"],
    sourceUri: text(entry.sourceUri, "source URI"),
    admittedSourceCid: text(entry.admittedSourceCid, "source CID"),
    authorDid: text(entry.authorDid, "author DID"),
    admissionId: digest(entry.admissionId, "admission"),
    admittedAt: text(entry.admittedAt, "admitted time"),
    sourceRelationship: text(entry.sourceRelationship, "source relationship"),
    presentation,
    technicalReceipts: receipts,
    removalId: nullableDigest(entry.removalId, "removal"),
    ...(entry.withdrawalId === undefined
      ? {}
      : { withdrawalId: digest(entry.withdrawalId, "withdrawal") }),
  };
}

function parsePresentation(value: unknown): PublicPresentation {
  const input = object(value, "presentation");
  return {
    sourceReferenceId: digest(input.sourceReferenceId, "source reference"),
    sourceUri: text(input.sourceUri, "presentation source URI"),
    sourceCid: text(input.sourceCid, "presentation source CID"),
    title: text(input.title, "title", true),
    body: text(input.body, "body", true),
    authorDisplayReference: text(input.authorDisplayReference, "author display"),
  };
}

function entryOccurrence(entry: PublicEntry): string {
  return `${entry.projectionIdentity}\u0000${entry.admissionId}\u0000${entry.lifecycleState}`;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  throw new Error("projection artifact is outside canonical JSON");
}

function sha(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function object(value: unknown, name: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${name} must be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, name: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${name} must be an array`);
  return value;
}

function text(value: unknown, name: string, allowEmpty = false): string {
  if (typeof value !== "string" || (!allowEmpty && !value) || value.includes("\0")) {
    throw new Error(`${name} must be bounded text`);
  }
  return value;
}

function digest(value: unknown, name: string): string {
  if (typeof value !== "string" || !SHA.test(value)) throw new Error(`${name} must be a digest`);
  return value;
}

function nullableDigest(value: unknown, name: string): string | null {
  return value === null ? null : digest(value, name);
}

function isMissing(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}
