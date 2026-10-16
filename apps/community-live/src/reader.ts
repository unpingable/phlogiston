import {
  Agent, AppBskyActorDefs, AppBskyFeedDefs, DEFAULT_LABEL_SETTINGS, moderateFeedGenerator, moderatePost, moderateProfile,
  type AppBskyFeedGetPostThread,
  type BskyPreferences, type InterpretedLabelValueDefinition, type LabelPreference,
  type ModerationUI,
} from "@atproto/api";
import type { OAuthSession } from "@atproto/oauth-client-node";
import { count, type OmissionCause, type Omissions } from "./attention.js";

const APPVIEW_DID = "did:web:api.bsky.app";
const MAX_PAGES = 3;
const PAGE_SIZE = 30;
const MAX_SAVED_FEEDS = 24;
const MAX_NAMED_LABELERS = 5;
const DEFAULT_BUDGET_MS = 8_000;
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const READER_RPCS = new Set([
  "app.bsky.feed.getTimeline", "app.bsky.feed.getPostThread", "app.bsky.actor.getProfile",
  "app.bsky.feed.getFeed", "app.bsky.feed.getFeedGenerators",
  "app.bsky.actor.getPreferences", "app.bsky.labeler.getServices",
  "app.bsky.graph.muteThread", "app.bsky.graph.unmuteThread",
]);

export type ThreadResult = AppBskyFeedGetPostThread.OutputSchema["thread"];
export interface FollowingResult {
  items: AppBskyFeedDefs.FeedViewPost[];
  cursor?: string;
  /** Items received from upstream, including repeats; never an estimate of the wider feed. */
  scanned: number;
  /** Every received item not in `items`, by cause: scanned === items.length + the sum of these. */
  omitted: Omissions;
  /** Sources of the labels behind any `label` omissions on this page; evidence, not deciders. */
  labelers: string[];
}

/** The injection seam is transport-only and has no policy or authority of its own. */
export interface ReaderTransport {
  preferences(): Promise<BskyPreferences>;
  savedFeedPreferences?(): Promise<AppBskyActorDefs.Preferences>;
  labelDefinitions(prefs: BskyPreferences): Promise<Record<string, InterpretedLabelValueDefinition[]>>;
  timeline(cursor: string | undefined, signal: AbortSignal): Promise<{feed: AppBskyFeedDefs.FeedViewPost[]; cursor?: string}>;
  customFeed?(uri: string, cursor: string | undefined, signal: AbortSignal): Promise<{feed: AppBskyFeedDefs.FeedViewPost[]; cursor?: string}>;
  feedGenerators?(uri: string, signal: AbortSignal): Promise<AppBskyFeedDefs.GeneratorView[]>;
  curatorProfile?(actor: string, signal: AbortSignal): Promise<AppBskyActorDefs.ProfileViewDetailed>;
  postThread(uri: string, signal: AbortSignal): Promise<ThreadResult>;
  muteThread(root: string, signal: AbortSignal): Promise<void>;
  unmuteThread(root: string, signal: AbortSignal): Promise<void>;
}

async function cappedResponse(response: Response): Promise<Response> {
  const claimed = response.headers.get("content-length");
  if (claimed !== null && Number(claimed) > MAX_RESPONSE_BYTES) {
    await response.body?.cancel();
    throw new Error("reader response exceeded byte limit");
  }
  if (!response.body) return response;
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.byteLength;
      if (length > MAX_RESPONSE_BYTES) throw new Error("reader response exceeded byte limit");
      chunks.push(part.value);
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new Response(bytes, {status: response.status, statusText: response.statusText, headers: response.headers});
}

function normalTransport(session: OAuthSession, deadline: number): ReaderTransport {
  const agent = new Agent({
    did: session.did,
    fetchHandler: async (url, init) => {
      const method = new URL(url, "https://reader.invalid").pathname;
      if (!url.startsWith("/xrpc/") || !READER_RPCS.has(method.slice("/xrpc/".length))) {
        throw new Error("reader RPC is outside its exact allowlist");
      }
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new Error("reader time budget exceeded");
      const signal = AbortSignal.any([init.signal ?? AbortSignal.timeout(remaining), AbortSignal.timeout(remaining)]);
      return cappedResponse(await session.fetchHandler(url, {...init, signal}));
    },
  }).withProxy("bsky_appview", APPVIEW_DID);
  let rawPreferences: Promise<AppBskyActorDefs.Preferences> | undefined;
  const readRaw = () => rawPreferences ??= agent.app.bsky.actor.getPreferences({}).then(result => result.data.preferences);
  return {
    // @atproto/api 0.20.42 (MIT), Agent.getPreferences() performs an automatic
    // saved-feed migration write. Adapt only its moderation/home defaults and
    // labeler subscription from the raw read response; no migration or write.
    preferences: async () => readOnlyPreferences(await readRaw(), agent),
    savedFeedPreferences: readRaw,
    labelDefinitions: prefs => agent.getLabelDefinitions(prefs),
    timeline: async (cursor, signal) => (await agent.app.bsky.feed.getTimeline({limit: PAGE_SIZE, ...(cursor ? {cursor} : {})}, {signal})).data,
    customFeed: async (uri, cursor, signal) => (await agent.app.bsky.feed.getFeed({feed: uri, limit: PAGE_SIZE, ...(cursor ? {cursor} : {})}, {signal})).data,
    feedGenerators: async (uri, signal) => (await agent.app.bsky.feed.getFeedGenerators({feeds: [uri]}, {signal})).data.feeds,
    curatorProfile: async (actor, signal) => (await agent.app.bsky.actor.getProfile({actor}, {signal})).data,
    postThread: async (uri, signal) => (await agent.app.bsky.feed.getPostThread({uri, depth: 2, parentHeight: 6}, {signal})).data.thread,
    muteThread: async (root, signal) => { await agent.app.bsky.graph.muteThread({root}, {signal}); },
    unmuteThread: async (root, signal) => { await agent.app.bsky.graph.unmuteThread({root}, {signal}); },
  };
}

function readOnlyPreferences(raw: AppBskyActorDefs.Preferences, agent: Agent): BskyPreferences {
  const moderationPrefs: BskyPreferences["moderationPrefs"] = {
    adultContentEnabled: false,
    labels: {...DEFAULT_LABEL_SETTINGS},
    labelers: agent.appLabelers.map(did => ({did, labels: {}})),
    mutedWords: [], hiddenPosts: [],
  };
  const feedViewPrefs: BskyPreferences["feedViewPrefs"] = {home: {
    hideReplies: false, hideRepliesByUnfollowed: true, hideRepliesByLikeCount: 0,
    hideReposts: false, hideQuotePosts: false,
  }};
  const labelPrefs: AppBskyActorDefs.ContentLabelPref[] = [];
  for (const pref of raw) {
    if (AppBskyActorDefs.isAdultContentPref(pref)) moderationPrefs.adultContentEnabled = pref.enabled;
    else if (AppBskyActorDefs.isContentLabelPref(pref)) labelPrefs.push(pref);
    else if (AppBskyActorDefs.isLabelersPref(pref)) {
      moderationPrefs.labelers = [...agent.appLabelers.map(did => ({did, labels: {}})),
        ...pref.labelers.map(item => ({did: item.did, labels: {}}))];
    } else if (AppBskyActorDefs.isFeedViewPref(pref)) {
      feedViewPrefs[pref.feed] = {...feedViewPrefs.home!, ...pref};
    } else if (AppBskyActorDefs.isMutedWordsPref(pref)) {
      moderationPrefs.mutedWords = pref.items.map(word => ({...word, actorTarget: word.actorTarget || "all"}));
    } else if (AppBskyActorDefs.isHiddenPostsPref(pref)) moderationPrefs.hiddenPosts = pref.items;
  }
  for (const pref of labelPrefs) {
    let visibility: LabelPreference;
    if (pref.visibility === "show" || pref.visibility === "ignore") visibility = "ignore";
    else if (pref.visibility === "warn") visibility = "warn";
    else if (pref.visibility === "hide") visibility = "hide";
    else throw new Error("unsupported label preference");
    if (pref.labelerDid) {
      const labeler = moderationPrefs.labelers.find(item => item.did === pref.labelerDid);
      if (labeler) labeler.labels[pref.label] = visibility;
    } else moderationPrefs.labels[pref.label] = visibility;
  }
  for (const [oldName, newName] of Object.entries({gore: "graphic-media", nsfw: "porn", suggestive: "sexual"})) {
    if (moderationPrefs.labels[oldName]) moderationPrefs.labels[newName] = moderationPrefs.labels[oldName];
  }
  const subscribed = raw.filter(AppBskyActorDefs.isLabelersPref).at(-1)?.labelers.map(item => item.did) ?? [];
  agent.configureLabelers(subscribed);
  return {feedViewPrefs, moderationPrefs} as BskyPreferences;
}

function postUri(uri: string): boolean {
  return /^at:\/\/did:(?:plc|web):[^/\s]+\/app\.bsky\.feed\.post\/[A-Za-z0-9._~-]+$/.test(uri);
}

/** Exact generator collection and record key; no query, fragment, handle, or path suffix. */
export function validFeedUri(uri: string): boolean {
  return uri.length <= 1024 && /^at:\/\/did:(?:plc:[a-z2-7]{24}|web:[A-Za-z0-9][A-Za-z0-9.:%-]{0,254})\/app\.bsky\.feed\.generator\/[A-Za-z0-9._~-]{1,512}$/.test(uri) &&
    !uri.includes("..") && !uri.endsWith("/.");
}

function savedFeedUris(raw: AppBskyActorDefs.Preferences): string[] {
  const v2 = raw.filter(AppBskyActorDefs.isSavedFeedsPrefV2).at(-1);
  const legacy = raw.filter(AppBskyActorDefs.isSavedFeedsPref).at(-1);
  const candidates = v2 ? v2.items.filter(item => item.type === "feed").map(item => item.value) :
    legacy ? [...legacy.pinned, ...legacy.saved] : [];
  const unique = new Set<string>();
  for (const uri of candidates) {
    if (validFeedUri(uri)) unique.add(uri);
    if (unique.size >= MAX_SAVED_FEEDS) break;
  }
  return [...unique];
}

function isThreadPost(value: ThreadResult): value is AppBskyFeedDefs.ThreadViewPost {
  return value.$type === "app.bsky.feed.defs#threadViewPost" && "post" in value;
}

function quotePost(post: AppBskyFeedDefs.PostView): boolean {
  const kind = post.embed?.$type;
  return kind === "app.bsky.embed.record#view" || kind === "app.bsky.embed.recordWithMedia#view";
}

function sameOrFollowing(profile: AppBskyFeedDefs.PostView["author"], userDid: string): boolean {
  return profile.did === userDid || Boolean(profile.viewer?.following);
}

/** A per-request reader. Caller checks exact P0 OAuth grant before construction. */
export class Reader {
  private readonly transport: ReaderTransport;
  private readonly userDid: string;
  private readonly budgetMs: number;
  private readonly deadline: number;
  private prepared?: Promise<void>;
  private prefs?: BskyPreferences;
  private labelDefs?: Record<string, InterpretedLabelValueDefinition[]>;

  constructor(session: OAuthSession, transport?: ReaderTransport, budgetMs = DEFAULT_BUDGET_MS) {
    if (!session.did || !session.did.startsWith("did:")) throw new Error("reader requires an authenticated DID");
    if (!Number.isInteger(budgetMs) || budgetMs < 1 || budgetMs > 30_000) throw new Error("reader time budget is invalid");
    this.userDid = session.did;
    this.budgetMs = budgetMs;
    this.deadline = Date.now() + budgetMs;
    this.transport = transport ?? normalTransport(session, this.deadline);
  }

  async prepare(): Promise<void> {
    this.prepared ??= (async () => {
      const prefs = await this.withDeadline(this.transport.preferences(), this.deadline);
      const labelDefs = await this.withDeadline(this.transport.labelDefinitions(prefs), this.deadline);
      this.prefs = prefs;
      this.labelDefs = labelDefs;
    })();
    await this.prepared;
  }

  decision(post: AppBskyFeedDefs.PostView, context: "contentList" | "contentView" | "contentMedia" | "avatar" | "displayName"): ModerationUI {
    if (!this.prefs || !this.labelDefs) throw new Error("reader moderation preferences are unavailable");
    return moderatePost(post, {userDid: this.userDid, prefs: this.prefs.moderationPrefs, labelDefs: this.labelDefs}).ui(context);
  }

  actorDecision(profile: AppBskyActorDefs.ProfileViewBasic | AppBskyActorDefs.ProfileViewDetailed, context: "profileList" | "profileView" | "avatar" | "displayName"): ModerationUI {
    if (!this.prefs || !this.labelDefs) throw new Error("reader moderation preferences are unavailable");
    return moderateProfile(profile, {userDid: this.userDid, prefs: this.prefs.moderationPrefs, labelDefs: this.labelDefs}).ui(context);
  }

  async savedFeeds(): Promise<Array<{uri: string; name: string}>> {
    await this.prepare();
    if (!this.transport.savedFeedPreferences || !this.transport.feedGenerators) throw new Error("saved feeds are unavailable");
    const feedGenerators = this.transport.feedGenerators;
    const uris = savedFeedUris(await this.withDeadline(this.transport.savedFeedPreferences(), this.deadline));
    const result: Array<{uri: string; name: string}> = [];
    for (let offset = 0; offset < uris.length; offset += 4) {
      const batch = uris.slice(offset, offset + 4);
      const named = await Promise.all(batch.map(async uri => {
        if (this.deadline <= Date.now()) return {uri, name: uri};
        try {
          const views = await this.withDeadline(feedGenerators(uri,
            AbortSignal.timeout(Math.max(1, this.deadline - Date.now()))), this.deadline);
          const view = views.find(item => item.uri === uri);
          if (!view || !this.prefs || !this.labelDefs) return {uri, name: uri};
          const decision = moderateFeedGenerator(view,
            {userDid: this.userDid, prefs: this.prefs.moderationPrefs, labelDefs: this.labelDefs}).ui("contentList");
          return {uri, name: decision.blur || decision.filter || decision.noOverride ? uri :
            view.displayName.trim().slice(0, 120) || uri};
        } catch { return {uri, name: uri}; }
      }));
      result.push(...named);
    }
    return result;
  }

  async feed(uri: string, cursor?: string): Promise<FollowingResult> {
    if (!validFeedUri(uri)) throw new Error("invalid saved feed URI");
    if (cursor !== undefined && (cursor.length === 0 || cursor.length > 2048)) throw new Error("invalid feed cursor");
    if (!this.transport.customFeed) throw new Error("saved feeds are unavailable");
    const customFeed = this.transport.customFeed;
    await this.prepare();
    const items: AppBskyFeedDefs.FeedViewPost[] = [];
    const seen = new Set<string>(cursor ? [cursor] : []);
    const seenPosts = new Set<string>();
    let next = cursor;
    let scanned = 0;
    const omitted: Omissions = {};
    const labelers = new Set<string>();
    for (let page = 0; page < MAX_PAGES; page++) {
      const response = await this.withDeadline(customFeed(uri, next,
        AbortSignal.timeout(Math.max(1, this.deadline - Date.now()))), this.deadline);
      if (response.feed.length > PAGE_SIZE) throw new Error("feed page exceeded the requested bound");
      scanned += response.feed.length;
      for (const item of response.feed) {
        if (seenPosts.has(item.post.uri)) { count(omitted, "repeat"); continue; }
        seenPosts.add(item.post.uri);
        const moderated = this.moderationOmission(item.post, labelers);
        if (moderated) count(omitted, moderated); else items.push(item);
      }
      const returned = response.cursor;
      if (returned !== undefined && (returned.length === 0 || returned.length > 2048 || seen.has(returned))) {
        throw new Error("feed returned a repeated or invalid cursor");
      }
      if (!returned || items.length > 0) return {items, scanned, omitted, labelers: [...labelers], ...(returned ? {cursor: returned} : {})};
      seen.add(returned);
      next = returned;
    }
    return {items, scanned, omitted, labelers: [...labelers], ...(next ? {cursor: next} : {})};
  }

  async curatorProfile(actor: string): Promise<{did: string; handle: string}> {
    if (typeof actor !== "string" || actor.length > 2048 || !(validCuratorDid(actor) || validCuratorHandle(actor))) throw new Error("invalid curator identity");
    if (!this.transport.curatorProfile) throw new Error("curator profile is unavailable");
    await this.prepare();
    const profile = await this.withDeadline(this.transport.curatorProfile(actor, AbortSignal.timeout(Math.max(1, this.deadline - Date.now()))), this.deadline);
    if (!validCuratorDid(profile.did) || !validCuratorHandle(profile.handle) || (actor.startsWith("did:") ? profile.did !== actor : profile.handle.toLowerCase() !== actor.toLowerCase())) throw new Error("curator identity mismatched");
    const decision = this.actorDecision(profile, "profileView");
    if (profile.viewer?.blockedBy || profile.viewer?.blocking || profile.viewer?.muted || decision.filter || decision.noOverride || decision.blur) throw new Error("curator profile is hidden by viewing settings");
    return {did: profile.did, handle: profile.handle};
  }

  async following(cursor?: string, policy?: FollowingPolicy): Promise<FollowingResult> {
    if (cursor !== undefined && (cursor.length === 0 || cursor.length > 2048)) throw new Error("invalid Following cursor");
    if (policy && (typeof policy.includeReplies !== "boolean" || typeof policy.includeReposts !== "boolean" || !(policy.excludedDids instanceof Set) || policy.excludedDids.size > 5000 || [...policy.excludedDids].some(did => !validCuratorDid(did)))) throw new Error("invalid Following policy");
    const omitted: Omissions = {};
    const labelers = new Set<string>();
    await this.withDeadline(this.prepare(), this.deadline);
    const items: AppBskyFeedDefs.FeedViewPost[] = [];
    const seen = new Set<string>(cursor ? [cursor] : []);
    const seenPosts = new Set<string>();
    let next = cursor;
    let scanned = 0;
    for (let page = 0; page < MAX_PAGES; page++) {
      const signal = AbortSignal.timeout(Math.max(1, this.deadline - Date.now()));
      const response = await this.withDeadline(this.transport.timeline(next, signal), this.deadline);
      if (response.feed.length > PAGE_SIZE) throw new Error("Following page exceeded the requested bound");
      scanned += response.feed.length;
      for (const item of response.feed) {
        if (seenPosts.has(item.post.uri)) { count(omitted, "repeat"); continue; }
        seenPosts.add(item.post.uri);
        if (policy && ((!policy.includeReposts && AppBskyFeedDefs.isReasonRepost(item.reason)) || (!policy.includeReplies && ((item.post.record as {reply?: unknown}).reply !== undefined || item.reply !== undefined)))) { count(omitted, "feed-definition"); continue; }
        if (policy && excludesItem(item, policy.excludedDids)) { count(omitted, "curator-blocks"); continue; }
        const cause = this.followingOmission(item, labelers);
        if (cause) count(omitted, cause); else items.push(item);
      }
      const returned = response.cursor;
      if (returned !== undefined && (returned.length === 0 || returned.length > 2048 || seen.has(returned))) {
        throw new Error("Following returned a repeated or invalid cursor");
      }
      if (!returned || items.length > 0) return {items, scanned, omitted, labelers: [...labelers], ...(returned ? {cursor: returned} : {})};
      seen.add(returned);
      next = returned;
    }
    return {items, scanned, omitted, labelers: [...labelers], ...(next ? {cursor: next} : {})};
  }

  async thread(uri: string): Promise<ThreadResult> {
    if (!postUri(uri)) throw new Error("invalid post URI");
    await this.prepare();
    return this.withDeadline(this.transport.postThread(uri,
      AbortSignal.timeout(Math.max(1, this.deadline - Date.now()))), this.deadline);
  }

  async resolveRoot(uri: string): Promise<string> {
    const thread = await this.thread(uri);
    if (!isThreadPost(thread) || thread.post.uri !== uri) throw new Error("thread source is unavailable");
    const record = thread.post.record as { $type?: unknown; reply?: {root?: {uri?: unknown}} };
    if (record.$type !== "app.bsky.feed.post") throw new Error("thread source is not a post record");
    const root = record.reply === undefined ? uri : record.reply.root?.uri;
    if (typeof root !== "string" || !postUri(root)) throw new Error("thread root is unavailable");
    if (record.reply !== undefined && root === uri) throw new Error("reply cannot establish its own root");
    if (root !== uri) {
      const check = await this.thread(root);
      if (!isThreadPost(check) || check.post.uri !== root) throw new Error("thread root is unavailable");
      const rootRecord = check.post.record as { $type?: unknown; reply?: unknown };
      if (rootRecord.$type !== "app.bsky.feed.post" || rootRecord.reply !== undefined) {
        throw new Error("thread root is not an original post");
      }
    }
    return root;
  }

  async readQuiet(root: string): Promise<boolean> {
    if (!postUri(root)) throw new Error("invalid thread root");
    const thread = await this.thread(root);
    if (!isThreadPost(thread) || thread.post.uri !== root || typeof thread.post.viewer?.threadMuted !== "boolean") {
      throw new Error("thread mute state is unknown");
    }
    return thread.post.viewer.threadMuted;
  }

  async setQuiet(root: string, desired: boolean, beforeDispatch?: () => Promise<void>): Promise<void> {
    if (typeof desired !== "boolean" || await this.resolveRoot(root) !== root) throw new Error("exact thread root required");
    await beforeDispatch?.();
    const signal = AbortSignal.timeout(Math.max(1, this.deadline - Date.now()));
    await this.withDeadline(desired ? this.transport.muteThread(root, signal) : this.transport.unmuteThread(root, signal), this.deadline);
  }

  /** A block the viewer did not place is not attributed to the viewer's settings. */
  private moderationOmission(post: AppBskyFeedDefs.PostView, labelers: Set<string>): OmissionCause | undefined {
    const decision = this.decision(post, "contentList");
    if (!decision.filter) return undefined;
    const first = decision.filters?.[0];
    if (first?.type === "blocked-by" || first?.type === "block-other") return "other-account-block";
    if (first?.type !== "label") return "moderation";
    if (labelers.size < MAX_NAMED_LABELERS) labelers.add(first.label.src);
    return "label";
  }

  private followingOmission(item: AppBskyFeedDefs.FeedViewPost, labelers: Set<string>): OmissionCause | undefined {
    const post = item.post;
    if (post.viewer?.threadMuted === true) return "thread-muted";
    const moderated = this.moderationOmission(post, labelers);
    if (moderated) return moderated;
    const pref = this.prefs!.feedViewPrefs.home;
    if (!pref) throw new Error("home feed preferences are unavailable");
    const reason = item.reason;
    const repost = reason?.$type === "app.bsky.feed.defs#reasonRepost";
    if (pref.hideReposts && repost) return "home-preferences";
    if (pref.hideQuotePosts && quotePost(post)) return "home-preferences";
    const record = post.record as {reply?: unknown};
    if (record.reply && !repost) {
      if (pref.hideReplies) return "home-preferences";
      if (pref.hideRepliesByLikeCount > (post.likeCount ?? 0)) return "home-preferences";
      if (pref.hideRepliesByUnfollowed) {
        const parent = item.reply?.parent;
        if (!parent || !AppBskyFeedDefs.isPostView(parent) || !sameOrFollowing(parent.author, this.userDid)) return "home-preferences";
      }
    }
    return undefined;
  }

  private async withDeadline<T>(promise: Promise<T>, deadline: number): Promise<T> {
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new Error("reader time budget exceeded");
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([promise, new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error("reader time budget exceeded")), remaining);
      })]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
}

export interface FollowingPolicy { excludedDids: ReadonlySet<string>; includeReplies: boolean; includeReposts: boolean }
function validCuratorDid(value: string): boolean { return typeof value === "string" && value.length <= 2048 && /^did:(?:plc|web):[A-Za-z0-9._:%-]+$/.test(value); }
function validCuratorHandle(value: string): boolean { return typeof value === "string" && value.length <= 253 && /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z](?:[a-z0-9-]*[a-z0-9])?$/i.test(value); }
function excludesItem(item: AppBskyFeedDefs.FeedViewPost, excluded: ReadonlySet<string>): boolean {
  if (excluded.has(item.post.author.did) || (AppBskyFeedDefs.isReasonRepost(item.reason) && excluded.has(item.reason.by.did))) return true;
  if (excluded.size === 0) return false;
  let nodes = 0;
  function visit(value: unknown, depth: number): boolean {
    if (!value || typeof value !== "object") return false;
    if (++nodes > 128 || depth > 8) return true; // Refuse an unbounded quoted projection.
    const object = value as Record<string, unknown>;
    if (typeof object.did === "string" && excluded.has(object.did)) return true;
    if (typeof object.uri === "string" && object.uri.startsWith("at://")) {
      const did = object.uri.slice(5).split("/")[0]!;
      if (excluded.has(did)) return true;
    }
    return Object.values(object).some(child => visit(child, depth + 1));
  }
  return visit(item.post.embed, 0) || visit((item.post.record as {embed?: unknown}).embed, 0) || visit(item.reply, 0);
}

export interface PublicBlockBindings {
  resolvePds(did: string, signal: AbortSignal): Promise<{did: string; pds: string}>;
  supportsPds(origin: string): boolean;
  fetch?: typeof fetch;
}
export interface PublicBlockResult { excludedDids: string[]; checkedAt: string; recordCount: number }
/** Fresh direct public block enumeration, not an atomic repository snapshot. */
export class PublicBlockDirectory {
  constructor(private readonly bindings: PublicBlockBindings, private readonly budgetMs = 12_000) {
    if (!Number.isInteger(budgetMs) || budgetMs < 1 || budgetMs > 12_000) throw new Error("invalid public block budget");
  }
  async read(did: string): Promise<PublicBlockResult> {
    if (!validCuratorDid(did)) throw new Error("invalid curator DID");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.budgetMs);
    try { return await this.enumerate(did, controller.signal); } finally { clearTimeout(timer); }
  }
  private async enumerate(did: string, signal: AbortSignal): Promise<PublicBlockResult> {
    const bounded = async <T>(promise: Promise<T>): Promise<T> => {
      signal.throwIfAborted();
      let abort: (() => void) | undefined;
      try { return await Promise.race([promise, new Promise<never>((_, reject) => { abort = () => reject(new Error("public block time budget exceeded")); signal.addEventListener("abort", abort, {once:true}); })]); }
      finally { if (abort) signal.removeEventListener("abort", abort); }
    };
    const resolved = await bounded(this.bindings.resolvePds(did, signal));
    if (resolved.did !== did || !this.bindings.supportsPds(resolved.pds)) throw new Error("unsupported curator repository");
    const origin = new URL(resolved.pds);
    if (origin.protocol !== "https:" || origin.pathname !== "/" || origin.search || origin.hash || origin.username || origin.password) throw new Error("invalid curator PDS origin");
    const excluded = new Set<string>(), records = new Set<string>(), cursors = new Set<string>();
    let cursor: string | undefined, count = 0;
    for (let page = 0; page < 50; page++) {
      const url = new URL("/xrpc/com.atproto.repo.listRecords", origin);
      url.searchParams.set("repo", did); url.searchParams.set("collection", "app.bsky.graph.block"); url.searchParams.set("limit", "100"); if (cursor) url.searchParams.set("cursor", cursor);
      const response = await bounded((this.bindings.fetch ?? fetch)(url, {redirect:"error",signal,headers:{Accept:"application/json"}}));
      if (!response.ok || (response.url && new URL(response.url).origin !== origin.origin)) throw new Error("curator block read unavailable");
      const data = await bounded((await bounded(cappedResponse(response))).json()) as {records?: unknown; cursor?: unknown};
      if (!Array.isArray(data.records) || data.records.length > 100) throw new Error("invalid public block page");
      for (const row of data.records) {
        if (!row || typeof row !== "object") throw new Error("invalid public block record");
        const record = row as {uri?: unknown; cid?: unknown; value?: {$type?: unknown; subject?: unknown; createdAt?: unknown}};
        if (typeof record.uri !== "string" || record.uri.length > 4096 || record.uri.slice(`at://${did}/app.bsky.graph.block/`.length).length > 512 || !record.uri.startsWith(`at://${did}/app.bsky.graph.block/`) || !/^[A-Za-z0-9._~:-]+$/.test(record.uri.slice(`at://${did}/app.bsky.graph.block/`.length)) || [".",".."].includes(record.uri.split("/").at(-1)!) || records.has(record.uri) || typeof record.cid !== "string" || record.cid.length > 256 || record.cid.length === 0 || record.value?.$type !== "app.bsky.graph.block" || !validCuratorDid(record.value.subject as string) || typeof record.value.createdAt !== "string" || !Number.isFinite(Date.parse(record.value.createdAt))) throw new Error("invalid public block provenance");
        records.add(record.uri); excluded.add(record.value.subject as string); count++;
      }
      if (data.cursor === undefined) return {excludedDids:[...excluded],checkedAt:new Date().toISOString(),recordCount:count};
      if (typeof data.cursor !== "string" || data.cursor.length === 0 || data.cursor.length > 2048 || cursors.has(data.cursor)) throw new Error("invalid public block cursor");
      cursors.add(data.cursor); cursor = data.cursor;
    }
    throw new Error("public block enumeration incomplete at5000record/50page bound");
  }
}
