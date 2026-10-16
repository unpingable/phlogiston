import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { stable } from "./contract.js";
import type { PublicationIntent, PublicationJournal } from "./publication.js";

export class FilePublicationJournal implements PublicationJournal {
  public readonly directory: string;

  public constructor(directory: string) {
    this.directory = resolve(directory);
  }

  public async reserve(intent: PublicationIntent): Promise<PublicationIntent> {
    const existing = await this.read(intent.nsid);
    if (existing) return existing;
    await this.write(intent);
    return intent;
  }

  public async save(intent: PublicationIntent): Promise<void> {
    const existing = await this.read(intent.nsid);
    if (!existing) throw new Error("publication intent was not durably reserved");
    await this.write(intent);
  }

  private path(nsid: string): string {
    const digest = createHash("sha256").update(nsid, "utf8").digest("hex");
    return join(this.directory, `${digest}.json`);
  }

  private async read(nsid: string): Promise<PublicationIntent | null> {
    try {
      return parseIntent(JSON.parse(await readFile(this.path(nsid), "utf8")) as unknown);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw error;
    }
  }

  private async write(intent: PublicationIntent): Promise<void> {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const path = this.path(intent.nsid);
    const temporary = `${path}.${process.pid}.${Date.now()}.tmp`;
    await writeFile(temporary, `${stable(intent)}\n`, { mode: 0o600, flag: "wx" });
    await rename(temporary, path);
  }
}

export function parseIntent(value: unknown): PublicationIntent {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("publication intent is invalid");
  }
  const raw = value as Record<string, unknown>;
  const base = [
    "attempts", "authorityDid", "contract", "documentSha256", "expectedUri",
    "manifestSha256", "nsid", "phase", "recordSha256", "rkey",
  ];
  const optional = raw.phase === "settled" ? ["cid", "disposition"] : [];
  if (Object.keys(raw).sort().join(",") !== [...base, ...optional].sort().join(",")) {
    throw new Error("publication intent fields are invalid");
  }
  if (
    raw.contract !== "pcv0-lexicon-publication-intent/1"
    || typeof raw.attempts !== "number"
    || !Number.isSafeInteger(raw.attempts)
    || raw.attempts < 0
    || !["prepared", "attempting", "attempted_unknown", "settled"].includes(String(raw.phase))
  ) {
    throw new Error("publication intent state is invalid");
  }
  for (const key of [
    "authorityDid", "documentSha256", "expectedUri", "manifestSha256", "nsid", "recordSha256", "rkey",
  ]) {
    if (typeof raw[key] !== "string" || !raw[key]) throw new Error("publication intent identity is invalid");
  }
  if (raw.phase === "settled") {
    if (typeof raw.cid !== "string" || !["created", "read_back"].includes(String(raw.disposition))) {
      throw new Error("settled publication intent is invalid");
    }
  }
  return Object.freeze(raw as PublicationIntent);
}
