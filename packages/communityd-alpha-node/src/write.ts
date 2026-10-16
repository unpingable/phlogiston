import type { LexMap } from "@atproto/lex-data";

export const ADMISSION = "net.sp00ky.juniper-pds.authority.juniperAdmission";
export const REMOVAL = "net.sp00ky.juniper-pds.authority.juniperRemoval";

export type WriteRequest = Readonly<{
  space: string;
  actorDid: string;
  collection: typeof ADMISSION | typeof REMOVAL;
  rkey: string;
  record: LexMap;
}>;
export type WriteResult = Readonly<{ uri: string; cid: string; created: boolean }>;

export interface AuthorityClient {
  create(input: WriteRequest): Promise<{ uri: string; cid: string }>;
  get(input: Omit<WriteRequest, "record">): Promise<{ uri: string; cid: string; value: LexMap }>;
}

export async function performWrite(client: AuthorityClient, raw: unknown): Promise<WriteResult> {
  const input = parse(raw);
  try {
    const result = await client.create(input);
    requireExpectedUri(input, result.uri);
    return { ...result, created: true };
  } catch (cause) {
    let existing: Awaited<ReturnType<AuthorityClient["get"]>>;
    try { existing = await client.get(input); }
    catch { throw new Error("authority write failed and exact readback did not settle it", { cause }); }
    requireExpectedUri(input, existing.uri);
    if (stable(existing.value) !== stable(input.record)) {
      throw new Error("authority rkey contains conflicting record", { cause });
    }
    return { uri: existing.uri, cid: existing.cid, created: false };
  }
}

function parse(value: unknown): WriteRequest {
  const input = object(value);
  const keys = Object.keys(input).sort();
  if (JSON.stringify(keys) !== JSON.stringify(["actorDid", "collection", "record", "rkey", "space"])) throw new Error("authority request fields differ");
  const space = text(input.space);
  const actorDid = text(input.actorDid);
  const collection = text(input.collection);
  const rkey = text(input.rkey);
  if (!space.startsWith("at://did:") || !/^did:(?:plc|web):[^/\s]+$/.test(actorDid)) throw new Error("authority identity binding is invalid");
  if (collection !== ADMISSION && collection !== REMOVAL) throw new Error("communityd transport cannot write this collection");
  if (!/^[a-z0-9._~:-]{1,512}$/.test(rkey)) throw new Error("authority rkey is invalid");
  const record = object(input.record) as LexMap;
  const required = collection === ADMISSION
    ? ["$type", "authorizationOccurrence", "createdAt", "sourceObservationReceipt", "subject", "submission"]
    : ["$type", "admission", "authorizationOccurrence", "createdAt", "reason", "subject"];
  if (JSON.stringify(Object.keys(record).sort()) !== JSON.stringify(required) || record.$type !== collection) throw new Error("authority record shape differs");
  return { space, actorDid, collection, rkey, record };
}

function requireExpectedUri(input: WriteRequest, uri: string): void {
  if (uri !== `${input.space}/${input.actorDid}/${input.collection}/${input.rkey}`) throw new Error("authority writer returned substituted URI");
}
function object(value: unknown): Record<string, unknown> { if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("authority request must be an object"); return value as Record<string, unknown>; }
function text(value: unknown): string { if (typeof value !== "string" || !value || value.includes("\0")) throw new Error("authority request contains invalid text"); return value; }
function stable(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(",")}}`;
  throw new Error("authority record is outside bounded JSON");
}
