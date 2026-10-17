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
  action?: "create" | "delete";
  operationId: string;
  record: unknown;
  expectedHash: string;
  phase: WritePhase;
  createdAt: string;
  updatedAt: string;
  reason?: string | undefined;
  committedCid?: string | undefined;
  /** Feature-level immutable intent, independent of timestamps in the record. */
  intentDigest?: string | undefined;
}

export interface ObservedRecord {
  cid: string;
  record: unknown;
}

export interface PublicRepoWriter {
  create(address: RecordAddress, record: unknown): Promise<{ cid: string }>;
  get(address: RecordAddress): Promise<ObservedRecord | null>;
  delete?(address: RecordAddress, swapRecord?: string): Promise<void>;
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
    intentDigest?: string,
  ): Promise<PlannedWrite> {
    await this.load();
    const existing = this.document.operations[operationId];
    if (existing !== undefined) {
      if (
        existing.repo !== address.repo ||
        existing.collection !== address.collection ||
        existing.rkey !== address.rkey ||
        existing.expectedHash !== digest(record) ||
        existing.intentDigest !== intentDigest
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
      ...(intentDigest === undefined ? {} : { intentDigest }),
    };
    this.document.operations[operationId] = operation;
    await this.flush();
    return operation;
  }

  public async prepareDelete(address: RecordAddress, expected: ObservedRecord, operationId: string = randomUUID(), intentDigest?: string): Promise<PlannedWrite> {
    await this.load();
    const prior = this.document.operations[operationId];
    if (prior !== undefined) {
      if (prior.action !== "delete" || prior.repo !== address.repo || prior.collection !== address.collection ||
          prior.rkey !== address.rkey || prior.committedCid !== expected.cid || prior.expectedHash !== digest(expected.record) || prior.intentDigest !== intentDigest) {
        throw new Error(`operation ${operationId} was reused with different intent`);
      }
      return prior;
    }
    const now = new Date().toISOString();
    const operation: PlannedWrite = {...address,action:"delete",operationId,record:expected.record,
      expectedHash:digest(expected.record),committedCid:expected.cid,phase:"prepared",createdAt:now,updatedAt:now,
      ...(intentDigest===undefined?{}:{intentDigest})};
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
      if (attempted.action === "delete") {
        if (!writer.delete) throw new Error("writer does not support delete");
        const observed = await writer.get(attempted);
        if (!observed || observed.cid !== attempted.committedCid || digest(observed.record) !== attempted.expectedHash) {
          const conflict = await this.mark(operationId, "conflict", "delete_target_mismatch", attempted.committedCid);
          return { phase: "conflict", operation: conflict, reason: conflict.reason };
        }
        await writer.delete(attempted, attempted.committedCid);
        const committed = await this.mark(operationId, "committed", undefined, attempted.committedCid);
        return { phase: "committed", operation: committed, cid: attempted.committedCid };
      }
      const created = await writer.create(attempted, attempted.record);
      const committed = await this.mark(operationId, "committed", undefined, created.cid);
      return { phase: "committed", operation: committed, cid: created.cid };
    } catch (error) {
      if (error instanceof ProviderRefusalError) {
        // A refused retry can follow a late commit of the original request.
        // Classify the whole operation by exact readback before calling it refused.
        const checked = await this.reconcile(operationId,writer);
        if (checked.phase === "committed" || checked.phase === "conflict" || checked.phase === "attempted_unknown") return checked;
        const refused = await this.mark(operationId, "refused", `provider_refused:${error.message}`);
        return { phase: "refused", operation: refused, reason: refused.reason };
      }
      if (error instanceof RecordConflictError) {
        const conflict = await this.mark(operationId, "conflict", "delete_target_mismatch", attempted.committedCid);
        return { phase: "conflict", operation: conflict, reason: conflict.reason };
      }
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
    if (operation.action === "delete") {
      if (observed === null) {
        const committed = await this.mark(operationId, "committed", undefined, operation.committedCid);
        return { phase: "committed", operation: committed, cid: operation.committedCid };
      }
      if (observed.cid !== operation.committedCid || digest(observed.record) !== operation.expectedHash) {
        const conflict = await this.mark(operationId, "conflict", "delete_target_mismatch", operation.committedCid);
        return { phase: "conflict", operation: conflict, reason: conflict.reason };
      }
      const refused = await this.mark(operationId, "refused", "confirmed_present", operation.committedCid);
      return { phase: "refused", operation: refused, reason: refused.reason };
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
    if (operation.phase !== "refused" || !["confirmed_absent", "confirmed_present"].includes(operation.reason ?? "")) {
      throw new Error("only an exact, confirmed observation may be retried");
    }
    return this.mark(operationId, "prepared");
  }

  public async findCommittedCreate(address: RecordAddress, cid?: string): Promise<PlannedWrite | undefined> {
    await this.load();
    return Object.values(this.document.operations).find(operation => operation.action !== "delete" && operation.phase === "committed" &&
      operation.repo === address.repo && operation.collection === address.collection && operation.rkey === address.rkey &&
      (cid === undefined || operation.committedCid === cid));
  }

  public async recentCount(repo: string, sinceMs: number): Promise<number> {
    await this.load();
    return Object.values(this.document.operations).filter(operation => operation.repo === repo && Date.parse(operation.createdAt) >= sinceMs).length;
  }

  public async entries(repo: string): Promise<PlannedWrite[]> {
    await this.load();
    return Object.values(this.document.operations).filter(item => item.repo === repo)
      .sort((a,b) => b.createdAt.localeCompare(a.createdAt));
  }

  /** Remove terminal entries only after their own completion/update age. */
  public async pruneFinished(beforeMs: number, preserve: ReadonlySet<string> = new Set()): Promise<number> {
    await this.load();
    let removed = 0;
    for (const [id, operation] of Object.entries(this.document.operations)) {
      if (!preserve.has(id) && !(operation.intentDigest && operation.phase === "refused" && ["confirmed_absent","confirmed_present"].includes(operation.reason ?? "")) && ["committed","conflict","refused"].includes(operation.phase) && Date.parse(operation.updatedAt) < beforeMs) {
        delete this.document.operations[id]; removed += 1;
      }
    }
    if (removed > 0) await this.flush();
    return removed;
  }

  public async findCreate(collection: string, subject: {uri:string;cid:string}, writer: PublicRepoWriter): Promise<PlannedWrite | undefined> {
    await this.load();
    const operations = Object.values(this.document.operations);
    for (const operation of operations) {
      if (operation.action === "delete" || operation.collection !== collection ||
          !["prepared","committed","attempted_unknown"].includes(operation.phase) && !(operation.phase === "refused" && operation.reason === "confirmed_absent") || !sameSubject(operation.record,subject)) continue;
      const deleted = operations.some(candidate => candidate.action === "delete" && candidate.phase === "committed" &&
        candidate.repo === operation.repo && candidate.collection === operation.collection && candidate.rkey === operation.rkey &&
        Date.parse(candidate.updatedAt) >= Date.parse(operation.updatedAt));
      if (deleted) continue;
      try {
        const observed = await writer.get(operation);
        if (observed === null) {
          if (operation.phase === "attempted_unknown") { await this.reconcile(operation.operationId,writer); return operation; }
          if (operation.phase !== "committed") return operation;
          continue;
        }
      } catch {
        // An unreadable attempted write is still genuinely uncertain; a
        // committed record also remains duplicate evidence until disproved.
      }
      return operation;
    }
    return undefined;
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
      committedCid: committedCid ?? operation.committedCid,
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

export class RecordConflictError extends Error {}
export class ProviderRefusalError extends Error {}

function sameSubject(record: unknown, subject: {uri:string;cid:string}): boolean {
  const value = record as {subject?:{uri?:unknown;cid?:unknown}} | null;
  return value?.subject?.uri === subject.uri && value.subject.cid === subject.cid;
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
