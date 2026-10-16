import { isValidPostUri } from "./html.js";
import { readCapped } from "./profiles.js";

// Post text hydrated from the operator-pinned AppView. This is presentation
// data only: it is never an authority input, and callers must show it only
// when its CID equals the exact CID the community record names.
export interface HydratedPost {
  uri: string;
  cid: string;
  text: string;
}

export interface PostDirectory {
  lookup(uris: readonly string[]): Promise<Map<string, HydratedPost>>;
}

const MAX_BATCH_SIZE = 25;
const MAX_CID_LENGTH = 256;
// app.bsky.feed.post text is at most 3000 bytes; anything longer is
// non-conforming and is shown truncated rather than whole.
export const MAX_POST_TEXT_LENGTH = 3_000;
// C0/C1 controls (except tab and newline), DEL, and bidirectional
// embedding/override/isolate controls are removed before display.
const UNSAFE_TEXT = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f‪-‮⁦-⁩]/g;

type CacheEntry =
  | { kind: "hit"; post: HydratedPost; expiresAt: number }
  | { kind: "miss"; expiresAt: number };

export class PostCache {
  private readonly entries = new Map<string, CacheEntry>();

  public constructor(
    private readonly maxEntries: number,
    private readonly hitTtlMs: number,
    private readonly missTtlMs: number,
    private readonly now: () => number,
  ) {}

  public fresh(uri: string): CacheEntry | undefined {
    const entry = this.entries.get(uri);
    if (entry === undefined) return undefined;
    if (entry.expiresAt <= this.now()) {
      this.entries.delete(uri);
      return undefined;
    }
    this.entries.delete(uri);
    this.entries.set(uri, entry);
    return entry;
  }

  public putHit(uri: string, post: HydratedPost): void {
    this.put(uri, { kind: "hit", post, expiresAt: this.now() + this.hitTtlMs });
  }

  public putMiss(uri: string): void {
    this.put(uri, { kind: "miss", expiresAt: this.now() + this.missTtlMs });
  }

  public get size(): number {
    return this.entries.size;
  }

  private put(uri: string, entry: CacheEntry): void {
    this.entries.delete(uri);
    this.entries.set(uri, entry);
    while (this.entries.size > this.maxEntries) {
      const oldest = this.entries.keys().next();
      if (oldest.done === true) break;
      this.entries.delete(oldest.value);
    }
  }
}

export interface AppViewPostOptions {
  timeoutMs?: number;
  maxResponseBytes?: number;
  maxBatchSize?: number;
  fetchFn?: typeof fetch;
}

export class AppViewPostDirectory implements PostDirectory {
  private readonly timeoutMs: number;
  private readonly maxResponseBytes: number;
  private readonly maxBatchSize: number;
  private readonly fetchFn: typeof fetch;

  public constructor(
    private readonly origin: string,
    private readonly cache: PostCache,
    options: AppViewPostOptions = {},
  ) {
    this.timeoutMs = options.timeoutMs ?? 3_000;
    this.maxResponseBytes = options.maxResponseBytes ?? 512 * 1024;
    this.maxBatchSize = Math.min(options.maxBatchSize ?? MAX_BATCH_SIZE, MAX_BATCH_SIZE);
    this.fetchFn = options.fetchFn ?? fetch;
  }

  public async lookup(uris: readonly string[]): Promise<Map<string, HydratedPost>> {
    const result = new Map<string, HydratedPost>();
    const missing: string[] = [];
    for (const uri of new Set(uris.filter(isValidPostUri))) {
      const entry = this.cache.fresh(uri);
      if (entry === undefined) missing.push(uri);
      else if (entry.kind === "hit") result.set(uri, entry.post);
    }
    for (let index = 0; index < missing.length; index += this.maxBatchSize) {
      const batch = missing.slice(index, index + this.maxBatchSize);
      const posts = await this.fetchBatch(batch);
      if (posts === null) {
        for (const uri of batch) this.cache.putMiss(uri);
        continue;
      }
      const found = new Set<string>();
      for (const value of posts) {
        const post = sanitizePost(value, batch);
        if (post === undefined) continue;
        found.add(post.uri);
        this.cache.putHit(post.uri, post);
        result.set(post.uri, post);
      }
      for (const uri of batch) {
        if (!found.has(uri)) this.cache.putMiss(uri);
      }
    }
    return result;
  }

  private async fetchBatch(batch: readonly string[]): Promise<unknown[] | null> {
    try {
      const target = new URL("/xrpc/app.bsky.feed.getPosts", this.origin);
      for (const uri of batch) target.searchParams.append("uris", uri);
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
      const posts = (parsed as Record<string, unknown>).posts;
      return Array.isArray(posts) ? posts : null;
    } catch {
      return null;
    }
  }
}

export function displayPostText(text: string): string {
  const cleaned = text.replace(UNSAFE_TEXT, "");
  return cleaned.length <= MAX_POST_TEXT_LENGTH ? cleaned : `${cleaned.slice(0, MAX_POST_TEXT_LENGTH)}…`;
}

function sanitizePost(value: unknown, requested: readonly string[]): HydratedPost | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const view = value as Record<string, unknown>;
  const uri = view.uri;
  if (typeof uri !== "string" || !isValidPostUri(uri) || !requested.includes(uri)) return undefined;
  const cid = view.cid;
  if (typeof cid !== "string" || cid === "" || cid.length > MAX_CID_LENGTH) return undefined;
  const record = view.record;
  if (typeof record !== "object" || record === null || Array.isArray(record)) return undefined;
  const text = (record as Record<string, unknown>).text;
  if (typeof text !== "string") return undefined;
  return { uri, cid, text: displayPostText(text) };
}
