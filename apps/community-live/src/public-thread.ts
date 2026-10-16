import { AppBskyFeedDefs, BSKY_LABELER_DID, DEFAULT_LABEL_SETTINGS, moderatePost, moderateProfile, type AppBskyActorDefs, type ModerationPrefs, type ModerationUI } from "@atproto/api";
import { isValidPostUri } from "./html.js";
import type { ThreadResult } from "./reader.js";

export interface PublicThreadOptions { fetchFn?: typeof fetch; timeoutMs?: number; maxBytes?: number; ttlMs?: number; maxEntries?: number; now?: () => number }

/**
 * Unauthenticated read of one public post's thread from the public AppView.
 * Callers pass only an admitted post's exact URI; this is not a general proxy.
 * Depth and parent height are fixed, and repeat views share a short cache.
 */
export class PublicThreadReader {
  private readonly fetchFn: typeof fetch;
  private readonly timeoutMs: number;
  private readonly maxBytes: number;
  private readonly ttlMs: number;
  private readonly maxEntries: number;
  private readonly now: () => number;
  private readonly cache = new Map<string, {at: number; thread: Promise<ThreadResult>}>();

  public constructor(private readonly origin: string, options: PublicThreadOptions = {}) {
    this.fetchFn = options.fetchFn ?? fetch;
    this.timeoutMs = options.timeoutMs ?? 4_000;
    this.maxBytes = options.maxBytes ?? 1024 * 1024;
    this.ttlMs = options.ttlMs ?? 30_000;
    this.maxEntries = options.maxEntries ?? 500;
    this.now = options.now ?? Date.now;
  }

  public size(): number { return this.cache.size; }

  public read(uri: string): Promise<ThreadResult> {
    if (!isValidPostUri(uri)) return Promise.reject(new Error("a post URI is required"));
    const now = this.now();
    const cached = this.cache.get(uri);
    if (cached && now - cached.at <= this.ttlMs) return cached.thread;
    this.cache.delete(uri);
    while (this.cache.size >= this.maxEntries) this.cache.delete(this.cache.keys().next().value!);
    const thread = this.fetchThread(uri);
    this.cache.set(uri, {at: now, thread});
    thread.catch(() => { if (this.cache.get(uri)?.thread === thread) this.cache.delete(uri); });
    return thread;
  }

  private async fetchThread(uri: string): Promise<ThreadResult> {
    const target = new URL("/xrpc/app.bsky.feed.getPostThread", this.origin);
    target.searchParams.set("uri", uri);
    target.searchParams.set("depth", "2");
    target.searchParams.set("parentHeight", "0");
    const response = await this.fetchFn(target, {signal: AbortSignal.timeout(this.timeoutMs), redirect: "error",
      headers: {Accept: "application/json", "atproto-accept-labelers": BSKY_LABELER_DID}});
    if (!response.ok || !response.body) { await response.body?.cancel(); throw new Error("public thread unavailable"); }
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let length = 0;
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.byteLength;
      if (length > this.maxBytes) { await reader.cancel(); throw new Error("public thread exceeded byte limit"); }
      chunks.push(part.value);
    }
    const thread = (JSON.parse(Buffer.concat(chunks).toString("utf8")) as {thread?: unknown}).thread;
    if (!AppBskyFeedDefs.isThreadViewPost(thread) && !AppBskyFeedDefs.isNotFoundPost(thread) && !AppBskyFeedDefs.isBlockedPost(thread)) throw new Error("public thread malformed");
    return thread as ThreadResult;
  }
}

const SIGNED_OUT_PREFS: ModerationPrefs = {adultContentEnabled: false, labels: {...DEFAULT_LABEL_SETTINGS},
  labelers: [{did: BSKY_LABELER_DID, labels: {}}], mutedWords: [], hiddenPosts: []};

/** Bluesky's default moderation with no viewer, so authors' signed-out opt-outs apply. */
export class SignedOutViewer {
  public decision(post: AppBskyFeedDefs.PostView, context: "contentList" | "contentView" | "contentMedia" | "avatar" | "displayName"): ModerationUI {
    return moderatePost(post, {userDid: undefined, prefs: SIGNED_OUT_PREFS, labelDefs: {}}).ui(context);
  }
  public actorDecision(profile: AppBskyActorDefs.ProfileViewBasic, context: "profileList" | "profileView" | "avatar" | "displayName"): ModerationUI {
    return moderateProfile(profile, {userDid: undefined, prefs: SIGNED_OUT_PREFS, labelDefs: {}}).ui(context);
  }
}
