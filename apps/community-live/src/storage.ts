import { createHash, randomBytes, randomUUID } from "node:crypto";
import { chmod, link, mkdir, readdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";

import type { ContributionPlan } from "./contributions.js";
import { HttpError } from "./http-error.js";

export class SecretJsonFileStore<T> {
  public constructor(public readonly directory: string) {}
  public async get(key: string): Promise<T | undefined> {
    try {
      return JSON.parse(await readFile(this.path(key), "utf8")) as T;
    } catch (error) {
      if (isMissing(error)) return undefined;
      throw error;
    }
  }
  public async set(key: string, value: T): Promise<void> {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    await chmod(this.directory, 0o700);
    const target = this.path(key);
    const temporary = join(this.directory, `.write-${randomUUID()}`);
    try {
      await writeFile(temporary, JSON.stringify(value), { encoding: "utf8", mode: 0o600, flag: "wx" });
      await rename(temporary, target);
      await chmod(target, 0o600);
    } catch (error) {
      await rm(temporary, { force: true }).catch(() => undefined);
      throw error;
    }
  }
  /** Store the value only if the key is absent; returns false when it already existed. */
  public async setIfAbsent(key: string, value: T): Promise<boolean> {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    await chmod(this.directory, 0o700);
    const temporary = join(this.directory, `.write-${randomUUID()}`);
    try {
      await writeFile(temporary, JSON.stringify(value), { encoding: "utf8", mode: 0o600, flag: "wx" });
      await link(temporary, this.path(key));
      return true;
    } catch (error) {
      if (typeof error === "object" && error !== null && "code" in error && error.code === "EEXIST") return false;
      throw error;
    } finally {
      await rm(temporary, { force: true }).catch(() => undefined);
    }
  }
  public async del(key: string): Promise<void> {
    await rm(this.path(key), { force: true });
  }
  /** Every stored value; in-progress temporary files and unreadable entries are skipped. */
  public async values(): Promise<T[]> {
    let names: string[];
    try {
      names = await readdir(this.directory);
    } catch (error) {
      if (isMissing(error)) return [];
      throw error;
    }
    const values: T[] = [];
    for (const name of names) {
      if (!/^[0-9a-f]{64}$/.test(name)) continue;
      try {
        values.push(JSON.parse(await readFile(join(this.directory, name), "utf8")) as T);
      } catch (error) {
        if (!isMissing(error) && !(error instanceof SyntaxError)) throw error;
      }
    }
    return values;
  }
  /** Delete every stored value the predicate selects (given the value and its file's age in ms); returns the count. */
  public async deleteWhere(select: (value: T | undefined, ageMs: number) => boolean | Promise<boolean>, now = Date.now()): Promise<number> {
    let names: string[];
    try {
      names = await readdir(this.directory);
    } catch (error) {
      if (isMissing(error)) return 0;
      throw error;
    }
    let deleted = 0;
    for (const name of names) {
      if (!/^[0-9a-f]{64}$/.test(name)) continue;
      const file = join(this.directory, name);
      let value: T | undefined;
      let ageMs: number;
      try {
        ageMs = now - (await stat(file)).mtimeMs;
        try { value = JSON.parse(await readFile(file, "utf8")) as T; } catch (error) { if (!(error instanceof SyntaxError)) throw error; }
      } catch (error) {
        if (isMissing(error)) continue;
        throw error;
      }
      if (await select(value, ageMs)) { await rm(file, { force: true }); deleted += 1; }
    }
    return deleted;
  }
  private path(key: string): string {
    return join(this.directory, sha256(key));
  }
}

export interface WebSession {
  did: string;
  csrf: string;
  expiresAt: string;
  grantedScopes?: string;
}

export class WebSessionStore {
  private readonly store: SecretJsonFileStore<WebSession>;
  public constructor(directory: string) {
    this.store = new SecretJsonFileStore(directory);
  }
  public async issue(did: string, now = new Date(), grantedScopes?: string): Promise<{ token: string; csrf: string }> {
    const token = randomBytes(32).toString("base64url");
    const csrf = randomBytes(32).toString("base64url");
    await this.store.set(sha256(token), {
      did,
      ...(grantedScopes === undefined ? {} : { grantedScopes }),
      csrf,
      expiresAt: new Date(now.valueOf() + 8 * 60 * 60 * 1000).toISOString(),
    });
    return { token, csrf };
  }
  public async resolve(token: string | undefined, now = new Date()): Promise<WebSession | null> {
    if (!token || token.length > 256) return null;
    const key = sha256(token);
    const value = await this.store.get(key);
    if (value === undefined) return null;
    if (Date.parse(value.expiresAt) <= now.valueOf()) {
      await this.store.del(key);
      return null;
    }
    return value;
  }
  public async revoke(token: string | undefined): Promise<void> {
    if (token && token.length <= 256) await this.store.del(sha256(token));
  }
  /** End every browser session of one account. */
  public async revokeAccount(did: string): Promise<number> {
    return this.store.deleteWhere((value) => value?.did === did);
  }
  /** Remove expired and unreadable sessions; returns the accounts that still have a live session. */
  public async sweep(now = new Date()): Promise<Set<string>> {
    const live = new Set<string>();
    await this.store.deleteWhere((value) => {
      if (value === undefined || !(Date.parse(value.expiresAt) > now.valueOf())) return true;
      live.add(value.did);
      return false;
    }, now.valueOf());
    return live;
  }
}

export class ContributionPlanStore {
  private readonly store: SecretJsonFileStore<ContributionPlan>;
  public constructor(directory: string) {
    this.store = new SecretJsonFileStore(directory);
  }
  public async save(plan: ContributionPlan): Promise<void> {
    await this.store.set(plan.operationId, plan);
  }
  /** Save a plan unless one with its ID exists; either way return the stored plan. */
  public async saveNew(plan: ContributionPlan): Promise<ContributionPlan> {
    if (await this.store.setIfAbsent(plan.operationId, plan)) return plan;
    return this.get(plan.operationId);
  }
  public async get(operationId: string): Promise<ContributionPlan> {
    if (!/^[a-zA-Z0-9:-]{1,200}$/.test(operationId)) throw new HttpError(400, "The operation ID is malformed.");
    const plan = await this.store.get(operationId);
    if (plan === undefined) throw new HttpError(404, "That operation is unknown.");
    return plan;
  }
  /** Delete one author's plans (account erasure). */
  public async deleteByAuthor(did: string): Promise<number> {
    return this.store.deleteWhere((plan) => plan?.authorDid === did);
  }
  /** Delete plans created more than maxAgeMs ago (retention). */
  public async expire(maxAgeMs: number, now = Date.now()): Promise<number> {
    return this.store.deleteWhere((plan) => plan === undefined || !(now - Date.parse(plan.createdAt) <= maxAgeMs), now);
  }
  /** One author's plans, derived by scanning the store; nothing is indexed. */
  public async byAuthor(did: string): Promise<ContributionPlan[]> {
    return (await this.store.values()).filter((plan) => typeof plan === "object" && plan !== null && plan.authorDid === did);
  }
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}
function isMissing(error: unknown): boolean {
  return typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT";
}
