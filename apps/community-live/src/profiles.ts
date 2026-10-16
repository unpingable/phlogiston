import { HANDLE_PATTERN, isValidDid } from "./html.js";

export interface HydratedProfile {
  did: string;
  handle?: string;
  displayName?: string;
  avatar?: string;
}

export interface ProfileDirectory {
  lookup(dids: readonly string[]): Promise<Map<string, HydratedProfile>>;
}

const AVATAR_HOST = "cdn.bsky.app";

const MAX_BATCH_SIZE = 25;
const MAX_DISPLAY_NAME_LENGTH = 256;
const MAX_HANDLE_LENGTH = 253;
const MAX_AVATAR_URL_LENGTH = 2048;
// The AppView's placeholder for an account whose handle does not currently
// resolve; it is not a handle the account holds.
const UNRESOLVED_HANDLE = "handle.invalid";

export function validAvatarUrl(value: unknown): value is string {
  if (typeof value !== "string" || value.length > MAX_AVATAR_URL_LENGTH) return false;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:"
      && parsed.username === ""
      && parsed.password === ""
      && parsed.hostname === AVATAR_HOST;
  } catch {
    return false;
  }
}

type CacheEntry =
  | { kind: "hit"; profile: HydratedProfile; expiresAt: number }
  | { kind: "miss"; expiresAt: number };

export class ProfileCache {
  private readonly entries = new Map<string, CacheEntry>();

  public constructor(
    private readonly maxEntries: number,
    private readonly hitTtlMs: number,
    private readonly missTtlMs: number,
    private readonly now: () => number,
  ) {}

  public fresh(did: string): CacheEntry | undefined {
    const entry = this.entries.get(did);
    if (entry === undefined) return undefined;
    if (entry.expiresAt <= this.now()) {
      this.entries.delete(did);
      return undefined;
    }
    this.entries.delete(did);
    this.entries.set(did, entry);
    return entry;
  }

  public putHit(did: string, profile: HydratedProfile): void {
    this.put(did, { kind: "hit", profile, expiresAt: this.now() + this.hitTtlMs });
  }

  public putMiss(did: string): void {
    this.put(did, { kind: "miss", expiresAt: this.now() + this.missTtlMs });
  }

  public get size(): number {
    return this.entries.size;
  }

  private put(did: string, entry: CacheEntry): void {
    this.entries.delete(did);
    this.entries.set(did, entry);
    while (this.entries.size > this.maxEntries) {
      const oldest = this.entries.keys().next();
      if (oldest.done === true) break;
      this.entries.delete(oldest.value);
    }
  }
}

export interface AppViewProfileOptions {
  timeoutMs?: number;
  maxResponseBytes?: number;
  maxBatchSize?: number;
  fetchFn?: typeof fetch;
}

export class AppViewProfileDirectory implements ProfileDirectory {
  private readonly timeoutMs: number;
  private readonly maxResponseBytes: number;
  private readonly maxBatchSize: number;
  private readonly fetchFn: typeof fetch;

  public constructor(
    private readonly origin: string,
    private readonly cache: ProfileCache,
    options: AppViewProfileOptions = {},
  ) {
    this.timeoutMs = options.timeoutMs ?? 3_000;
    this.maxResponseBytes = options.maxResponseBytes ?? 512 * 1024;
    this.maxBatchSize = options.maxBatchSize ?? MAX_BATCH_SIZE;
    this.fetchFn = options.fetchFn ?? fetch;
  }

  public async lookup(dids: readonly string[]): Promise<Map<string, HydratedProfile>> {
    const result = new Map<string, HydratedProfile>();
    const missing: string[] = [];
    for (const did of new Set(dids.filter(isValidDid))) {
      const entry = this.cache.fresh(did);
      if (entry === undefined) missing.push(did);
      else if (entry.kind === "hit") result.set(did, entry.profile);
    }
    for (let index = 0; index < missing.length; index += this.maxBatchSize) {
      const batch = missing.slice(index, index + this.maxBatchSize);
      const profiles = await this.fetchBatch(batch);
      if (profiles === null) {
        for (const did of batch) this.cache.putMiss(did);
        continue;
      }
      const found = new Set<string>();
      for (const value of profiles) {
        const profile = sanitizeProfile(value, batch);
        if (profile === undefined) continue;
        found.add(profile.did);
        this.cache.putHit(profile.did, profile);
        result.set(profile.did, profile);
      }
      for (const did of batch) {
        if (!found.has(did)) this.cache.putMiss(did);
      }
    }
    return result;
  }

  private async fetchBatch(batch: readonly string[]): Promise<unknown[] | null> {
    try {
      const target = new URL("/xrpc/app.bsky.actor.getProfiles", this.origin);
      for (const did of batch) target.searchParams.append("actors", did);
      const response = await this.fetchFn(target, { signal: AbortSignal.timeout(this.timeoutMs) });
      if (!response.ok || response.body === null) return null;
      const declared = Number(response.headers.get("content-length") ?? 0);
      if (declared > this.maxResponseBytes) {
        await response.body.cancel().catch(() => undefined);
        return null;
      }
      const body = await readCapped(response.body, this.maxResponseBytes);
      if (body === null) return null;
      const parsed: unknown = JSON.parse(body);
      if (typeof parsed !== "object" || parsed === null) return null;
      const profiles = (parsed as Record<string, unknown>).profiles;
      return Array.isArray(profiles) ? profiles : null;
    } catch {
      return null;
    }
  }
}

function sanitizeProfile(value: unknown, requested: readonly string[]): HydratedProfile | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  const did = record.did;
  if (typeof did !== "string" || !isValidDid(did) || !requested.includes(did)) return undefined;
  const profile: HydratedProfile = { did };
  if (
    typeof record.handle === "string"
    && record.handle.length <= MAX_HANDLE_LENGTH
    && HANDLE_PATTERN.test(record.handle)
    && record.handle.toLowerCase() !== UNRESOLVED_HANDLE
  ) {
    profile.handle = record.handle;
  }
  if (typeof record.displayName === "string" && record.displayName.trim().length > 0 && record.displayName.length <= MAX_DISPLAY_NAME_LENGTH) {
    profile.displayName = record.displayName;
  }
  if (validAvatarUrl(record.avatar)) profile.avatar = record.avatar;
  return profile;
}

export async function readCapped(body: ReadableStream<Uint8Array>, maxBytes: number): Promise<string | null> {
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => undefined);
        return null;
      }
      chunks.push(value);
    }
  } catch {
    return null;
  }
  return Buffer.concat(chunks).toString("utf8");
}
