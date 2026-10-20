import { createHash } from "node:crypto";
import { AppBskyEmbedExternal, AppBskyEmbedRecordWithMedia, AppBskyFeedDefs, AppBskyFeedPost } from "@atproto/api";
import { isValidPostUri } from "./html.js";

export type GroupKind = "source" | "conversation" | "single";
export interface GroupMember<T> { value: T; uri: string; createdAt: string; position: number }
export interface ReadingGroup<T> {
  id: string;
  kind: GroupKind;
  key: string;
  representative: GroupMember<T>;
  members: readonly GroupMember<T>[];
  firstPosition: number;
}
export interface GroupCandidate<T> {
  value: T;
  uri: string;
  createdAt: string;
  conversationRoots?: readonly string[];
  sourceUrl?: string;
}
export interface FeedGroupingHint { uri: string; kind: GroupKind; key: string; createdAt: string }

const TRACKING = new Set(["fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "mkt_tok", "_ga", "_gl", "ref_src"]);

/** Conservative equality for presentation only; invalid and non-web URLs do not group. */
export function canonicalSourceUrl(value: string): string | undefined {
  try {
    const url = new URL(value.trim());
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || !url.hostname) return undefined;
    url.protocol = "https:";
    url.hostname = url.hostname.toLowerCase().replace(/^www\./, "");
    if (url.port === "80" || url.port === "443") url.port = "";
    url.hash = "";
    const entries = [...url.searchParams.entries()].filter(([name]) => !name.toLowerCase().startsWith("utm_") && !TRACKING.has(name.toLowerCase()));
    entries.sort(([aName, aValue], [bName, bValue]) => aName.localeCompare(bName) || aValue.localeCompare(bValue));
    url.search = "";
    for (const [name, item] of entries) url.searchParams.append(name, item);
    return url.href;
  } catch { return undefined; }
}

function identity(kind: GroupKind, key: string): string {
  return `labs-${kind}-${createHash("sha256").update(`${kind}\0${key}`).digest("hex").slice(0, 24)}`;
}
function exactRoot(candidates: readonly string[] | undefined): string | undefined {
  if (!candidates?.length || candidates.some(value => !isValidPostUri(value))) return undefined;
  const roots = new Set(candidates);
  return roots.size === 1 ? candidates[0] : undefined;
}
function time(value: string): number {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : -Infinity;
}

function rawGroups<T>(input: readonly GroupCandidate<T>[]): readonly Omit<ReadingGroup<T>,"id">[] {
  const buckets = new Map<string, {kind: GroupKind; key: string; members: GroupMember<T>[]}>();
  input.forEach((candidate, position) => {
    const source = candidate.sourceUrl ? canonicalSourceUrl(candidate.sourceUrl) : undefined;
    const root = exactRoot(candidate.conversationRoots);
    const kind: GroupKind = source ? "source" : root ? "conversation" : "single";
    const key = source ?? root ?? candidate.uri;
    const bucketKey = `${kind}\0${key}`;
    const member = {value:candidate.value, uri:candidate.uri, createdAt:candidate.createdAt, position};
    const bucket = buckets.get(bucketKey);
    if (bucket) bucket.members.push(member); else buckets.set(bucketKey, {kind,key,members:[member]});
  });
  return [...buckets.values()].map(bucket => {
    const members = bucket.members.toSorted((a,b) => time(b.createdAt) - time(a.createdAt) || a.position - b.position || a.uri.localeCompare(b.uri));
    return {kind:bucket.kind,key:bucket.key,representative:members[0]!,members,firstPosition:Math.min(...members.map(member => member.position))};
  }).sort((a,b) => a.firstPosition - b.firstPosition || a.kind.localeCompare(b.kind) || a.key.localeCompare(b.key));
}

/** Groups one bounded snapshot without dropping, ranking, or semantically inferring any member. */
export function groupSnapshot<T>(input: readonly GroupCandidate<T>[]): readonly ReadingGroup<T>[] {
  return rawGroups(input).map(group => ({...group,id:identity(group.kind,group.key)}));
}

function externalUrl(embed: unknown): string | undefined {
  if (AppBskyEmbedExternal.isView(embed) && AppBskyEmbedExternal.validateView(embed).success) return (embed as AppBskyEmbedExternal.View).external.uri;
  if (AppBskyEmbedRecordWithMedia.isView(embed) && AppBskyEmbedRecordWithMedia.validateView(embed).success) return externalUrl((embed as AppBskyEmbedRecordWithMedia.View).media);
  return undefined;
}
function lineage(item: AppBskyFeedDefs.FeedViewPost): string[] | undefined {
  if (!AppBskyFeedPost.isRecord(item.post.record)) return undefined;
  const record = item.post.record as AppBskyFeedPost.Record;
  if (record.reply === undefined) return [item.post.uri];
  const declared = record.reply?.root?.uri;
  if (typeof declared !== "string" || !isValidPostUri(declared)) return undefined;
  const roots = [declared];
  const contextual = item.reply?.root;
  if (AppBskyFeedDefs.isPostView(contextual)) roots.push(contextual.uri);
  else if (contextual !== undefined) return undefined;
  return roots;
}

export function groupFeedItems(items: readonly AppBskyFeedDefs.FeedViewPost[]): readonly ReadingGroup<AppBskyFeedDefs.FeedViewPost>[] {
  return groupSnapshot(feedCandidates(items));
}

function feedCandidates(items: readonly AppBskyFeedDefs.FeedViewPost[]): readonly GroupCandidate<AppBskyFeedDefs.FeedViewPost>[] {
  return items.map(item => {
    const rawCreated = AppBskyFeedPost.isRecord(item.post.record) ? item.post.record.createdAt : item.post.indexedAt;
    const conversationRoots = lineage(item), sourceUrl = externalUrl(item.post.embed);
    return {value:item,uri:item.post.uri,createdAt:typeof rawCreated === "string" ? rawCreated : item.post.indexedAt,
      ...(conversationRoots ? {conversationRoots} : {}), ...(sourceUrl ? {sourceUrl} : {})};
  });
}

/** Raw deterministic presentation keys; the browser forms groups without receiving server hashes. */
export function feedGroupingHints(items: readonly AppBskyFeedDefs.FeedViewPost[]): readonly FeedGroupingHint[] {
  return rawGroups(feedCandidates(items)).flatMap(group => group.members.map(member => ({
    uri: member.uri,
    kind: group.kind,
    key: group.key,
    createdAt: member.createdAt,
  })));
}
