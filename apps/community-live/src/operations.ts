import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

export type WritePhase =
  | "prepared"
  | "attempted_unknown"
  | "committed"
  | "conflict"
  | "refused";

export interface RecordAddress {
  repo: string;
  collection: string;
  rkey: string;
}

export interface PlannedWrite extends RecordAddress {
  operationId: string;
  record: unknown;
  expectedHash: string;
  phase: WritePhase;
  createdAt: string;
  updatedAt: string;
  reason?: string | undefined;
  committedCid?: string | undefined;
}

export interface ObservedRecord {
  cid: string;
  record: unknown;
}

export interface PublicRepoWriter {
  create(address: RecordAddress, record: unknown): Promise<{ cid: string }>;
  get(address: RecordAddress): Promise<ObservedRecord | null>;
}

export interface WriteResult {
  phase: WritePhase;
  operation: PlannedWrite;
  reason?: string | undefined;
  cid?: string | undefined;
}

interface JournalDocument {
  version: 1;
  operations: Record<string, PlannedWrite>;
}

export class DurableWriteJournal {
  private document: JournalDocument = { version: 1, operations: {} };
  private loaded = false;

  public constructor(private readonly path: string, private readonly beforeDispatch?: (operation: PlannedWrite) => Promise<void>) {}

  public async prepare(
    address: RecordAddress,
    record: unknown,
    operationId: string = randomUUID(),
  ): Promise<PlannedWrite> {
    await this.load();
    const existing = this.document.operations[operationId];
    if (existing !== undefined) {
      if (
        existing.repo !== address.repo ||
        existing.collection !== address.collection ||
        existing.rkey !== address.rkey ||
        existing.expectedHash !== digest(record)
      ) {
        throw new Error(`operation ${operationId} was reused with different intent`);
      }
      return existing;
    }
    const now = new Date().toISOString();
    const operation: PlannedWrite = {
      ...address,
      operationId,
      record,
      expectedHash: digest(record),
      phase: "prepared",
      createdAt: now,
      updatedAt: now,
    };
    this.document.operations[operationId] = operation;
    await this.flush();
    return operation;
  }

  public async get(operationId: string): Promise<PlannedWrite> {
    const operation = await this.find(operationId);
    if (operation === undefined) {
      throw new Error(`unknown operation ${operationId}`);
    }
    return operation;
  }

  /** The recorded write, or undefined when the operation was never prepared. */
  public async find(operationId: string): Promise<PlannedWrite | undefined> {
    await this.load();
    return this.document.operations[operationId];
  }

  public async run(
    operationId: string,
    writer: PublicRepoWriter,
  ): Promise<WriteResult> {
    const operation = await this.get(operationId);
    if (operation.phase === "attempted_unknown") {
      return this.reconcile(operationId, writer);
    }
    if (operation.phase !== "prepared") {
      return {
        phase: operation.phase,
        operation,
        reason: operation.reason,
        cid: operation.committedCid,
      };
    }
    await this.beforeDispatch?.(operation);
    const attempted = await this.mark(operationId, "attempted_unknown");
    try {
      const created = await writer.create(attempted, attempted.record);
      const committed = await this.mark(operationId, "committed", undefined, created.cid);
      return { phase: "committed", operation: committed, cid: created.cid };
    } catch {
      return { phase: "attempted_unknown", operation: attempted };
    }
  }

  public async reconcile(
    operationId: string,
    writer: PublicRepoWriter,
  ): Promise<WriteResult> {
    const operation = await this.get(operationId);
    if (operation.phase !== "attempted_unknown") {
      return {
        phase: operation.phase,
        operation,
        reason: operation.reason,
        cid: operation.committedCid,
      };
    }
    let observed: ObservedRecord | null;
    try {
      observed = await writer.get(operation);
    } catch {
      return { phase: "attempted_unknown", operation };
    }
    if (observed === null) {
      const refused = await this.mark(operationId, "refused", "confirmed_absent");
      return { phase: "refused", operation: refused, reason: refused.reason };
    }
    if (digest(observed.record) !== operation.expectedHash) {
      const conflict = await this.mark(operationId, "conflict", "record_mismatch");
      return { phase: "conflict", operation: conflict, reason: conflict.reason };
    }
    const committed = await this.mark(operationId, "committed", undefined, observed.cid);
    return { phase: "committed", operation: committed, cid: observed.cid };
  }

  public async retryConfirmedAbsent(operationId: string): Promise<PlannedWrite> {
    const operation = await this.get(operationId);
    if (operation.phase !== "refused" || operation.reason !== "confirmed_absent") {
      throw new Error("only an exact, confirmed-absent write may be retried");
    }
    return this.mark(operationId, "prepared");
  }

  private async mark(
    operationId: string,
    phase: WritePhase,
    reason?: string,
    committedCid?: string,
  ): Promise<PlannedWrite> {
    const operation = await this.get(operationId);
    const updated: PlannedWrite = {
      ...operation,
      phase,
      reason,
      committedCid,
      updatedAt: new Date().toISOString(),
    };
    this.document.operations[operationId] = updated;
    await this.flush();
    return updated;
  }

  private async load(): Promise<void> {
    if (this.loaded) return;
    try {
      const raw = await readFile(this.path, "utf8");
      const parsed = JSON.parse(raw) as JournalDocument;
      if (parsed.version !== 1 || typeof parsed.operations !== "object") {
        throw new Error("unsupported operation journal");
      }
      this.document = parsed;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    this.loaded = true;
  }

  private async flush(): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    const temporary = `${this.path}.${process.pid}.${randomUUID()}.tmp`;
    const file = await open(temporary,"wx",0o600);
    try { await file.writeFile(`${JSON.stringify(this.document, null, 2)}\n`); await file.sync(); } finally { await file.close(); }
    await rename(temporary, this.path);
    const directory = await open(dirname(this.path),"r");
    try { await directory.sync(); } finally { await directory.close(); }
  }
}

export function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a.localeCompare(b),
    );
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new Error("record contains a non-JSON value");
  return encoded;
}

export function digest(value: unknown): string {
  return createHash("sha256").update(canonical(value)).digest("hex");
}
