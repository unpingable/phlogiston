import { readdir } from "node:fs/promises";
import { join } from "node:path";

import { SecretJsonFileStore, type ContributionPlanStore, type WebSessionStore } from "./storage.js";
import { DurableWriteJournal } from "./operations.js";

export const HOUR_MS = 60 * 60 * 1000;
export const DAY_MS = 24 * HOUR_MS;
/** Published in /privacy; change both together. */
export const RETENTION = {
  abandonedSignInMs: HOUR_MS,
  idleTokensMs: 8 * HOUR_MS,
  draftsMs: 30 * DAY_MS,
} as const;

export interface SweepResult { sessions: number; signIns: number; tokens: number; drafts: number; journals: number }
export interface RetentionFences {
  interactions<T>(did: string, action: () => Promise<T>): Promise<T>;
  operations<T>(did: string, action: () => Promise<T>): Promise<T>;
}
const directFences: RetentionFences = {
  interactions: (_did,action) => action(),
  operations: (_did,action) => action(),
};

/**
 * Enforce the published retention: expired browser sessions, abandoned sign-ins, provider tokens no
 * browser can use any more (revoked at the provider first), submission drafts, and each terminal
 * write-journal operation 30 days after that operation finished.
 */
export async function retentionSweep(
  runtimeDirectory: string,
  stores: { webSessions: WebSessionStore; plans: ContributionPlanStore },
  revoke: (did: string) => Promise<void>,
  now = Date.now(),
  fences: RetentionFences = directFences,
): Promise<SweepResult> {
  const before = await countFiles(join(runtimeDirectory, "web-sessions"));
  const live = await stores.webSessions.sweep(new Date(now));
  const sessions = before - await countFiles(join(runtimeDirectory, "web-sessions"));
  const signIns = await new SecretJsonFileStore<unknown>(join(runtimeDirectory, "oauth", "state"))
    .deleteWhere((_value, ageMs) => ageMs > RETENTION.abandonedSignInMs, now);
  const idle: string[] = [];
  const unreadable = await new SecretJsonFileStore<{ tokenSet?: { sub?: unknown } }>(join(runtimeDirectory, "oauth", "session"))
    .deleteWhere((value, ageMs) => {
      if (ageMs <= RETENTION.idleTokensMs) return false;
      const sub = value?.tokenSet?.sub;
      if (typeof sub !== "string") return true;
      if (!live.has(sub)) idle.push(sub);
      return false;
    }, now);
  for (const did of idle) await revoke(did).catch(() => undefined);
  const drafts = await stores.plans.expire(RETENTION.draftsMs, now);
  const retainedOperations = await stores.plans.retainedOperationIds();
  let journals = 0;
  for (const directoryName of ["operations","interactions"]) {
    const directory = join(runtimeDirectory, directoryName);
    for (const name of await list(directory)) {
      if (!name.endsWith(".json")) continue;
      const did = decodeURIComponent(name.slice(0,-5));
      const prune = () => new DurableWriteJournal(join(directory,name)).pruneFinished(
        now - RETENTION.draftsMs, directoryName === "operations" ? retainedOperations : undefined,
      );
      journals += await (directoryName === "operations" ? fences.operations(did,prune) : fences.interactions(did,prune));
    }
  }
  return { sessions, signIns, tokens: unreadable + idle.length, drafts, journals };
}

async function list(directory: string): Promise<string[]> {
  try { return await readdir(directory); } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
}
async function countFiles(directory: string): Promise<number> {
  return (await list(directory)).filter((name) => /^[0-9a-f]{64}$/.test(name)).length;
}
