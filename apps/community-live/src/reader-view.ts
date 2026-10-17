import { AppBskyFeedDefs, AppBskyFeedPost, AppBskyEmbedImages, AppBskyEmbedExternal, AppBskyEmbedRecord, AppBskyEmbedRecordWithMedia, AppBskyEmbedVideo, AppBskyActorDefs, RichText, type ModerationUI, type ModerationCause } from "@atproto/api";
import { escapeHtml as esc, externalHttpsUrl, isValidPostUri, bskyPostUrl } from "./html.js";
import type { Reader, ThreadResult } from "./reader.js";
import { marker } from "./attention.js";

const UNREADABLE_POST = marker({established: false}, "Phlogiston could not read this post. Nothing here says it was removed.");
const MAX_REPLIES = 30;
/** Only what rendering needs: a moderation decision per post. Signed-out views supply Bluesky defaults. */
type Viewer = Pick<Reader, "decision">;
/** Reader links go to signed-in routes; public pages link only to Bluesky. */
type Links = "reader" | "public";
export type InteractionControls = (post: AppBskyFeedDefs.PostView) => string;

export function threadHref(uri: string): string { return `/thread?uri=${encodeURIComponent(uri)}`; }
function safeLink(value: string): string | undefined { try { return externalHttpsUrl(value); } catch { return undefined; } }
function originUrl(value: string, origin: string): string | undefined {
  const link = safeLink(value);
  if (!link) return undefined;
  const url = new URL(link);
  return url.origin === origin && !url.username && !url.password ? link : undefined;
}
function imageUrl(value: string): string | undefined {
  return originUrl(value, "https://cdn.bsky.app");
}
function date(value: string): string {
  const d = new Date(value);
  return Number.isFinite(d.getTime()) ? d.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) : "Date unavailable";
}
function rich(record: AppBskyFeedPost.Record, limit = Infinity): string {
  const text = new RichText({ text: record.text, ...(record.facets ? { facets: record.facets } : {}) });
  let remaining = limit;
  let truncated = false;
  const parts: string[] = [];
  for (const segment of text.segments()) {
    const characters = [...segment.text];
    const visible = characters.slice(0, remaining).join("");
    remaining -= [...visible].length;
    truncated ||= visible.length !== segment.text.length;
    const href = segment.link ? safeLink(segment.link.uri) : segment.mention ? `https://bsky.app/profile/${encodeURIComponent(segment.mention.did)}` : undefined;
    if (visible) parts.push(href ? `<a href="${esc(href)}" rel="noreferrer noopener">${esc(visible)}</a>` : esc(visible));
  }
  return parts.join("") + (truncated ? "…" : "");
}

function causes(ui: ModerationUI): ModerationCause[] {
  return [...(Array.isArray(ui.filters) ? ui.filters : []), ...(Array.isArray(ui.blurs) ? ui.blurs : []), ...(Array.isArray(ui.alerts) ? ui.alerts : []), ...(Array.isArray(ui.informs) ? ui.informs : [])];
}
function causeText(cause: ModerationCause): string {
  if (cause.type === "label") {
    return `Label ${cause.label.val} on ${cause.target}, from ${cause.label.src}; viewing setting: ${cause.setting}.`;
  }
  return ({blocking:"You blocked this account.", "blocked-by":"This account blocks you.",
    "block-other":"Account block context.", muted:"Muted account.", "mute-word":"Muted word matched.",
    hidden:"Hidden by your viewing preferences."})[cause.type];
}
/** A label is evidence its labeler supplied; the account's moderation settings, possibly defaults, hid the post. */
function hiddenText(ui: ModerationUI): string {
  const label = causes(ui).find(cause => cause.type === "label");
  return label?.type === "label" ? `Hidden by your Bluesky moderation settings, based on a label from ${label.label.src}.` : "Post hidden by your viewing settings.";
}
/** An author's signed-out opt-out is the author's decision, not the viewer's settings. */
function hiddenMarker(ui: ModerationUI): string {
  const why = [...new Set(causes(ui).slice(0, 16).map(causeText))];
  if (causes(ui).some(cause => cause.type === "label" && cause.label.val === "!no-unauthenticated")) {
    return marker({established: true, decidedBy: "account"}, "The author asked that this not be shown to signed-out readers.");
  }
  return marker({established: true, decidedBy: "viewer"}, hiddenText(ui), why);
}
function contextDisclosure(ui: ModerationUI, uri: string): string {
  const items = causes(ui);
  if (!items.length) return "";
  const unique = [...new Set(items.slice(0, 16).map(causeText))];
  const caption = items.some(cause => cause.type === "label") ? "Label context" : "Viewing context";
  return `<div class="post-context"><a class="context-badge" href="/context?uri=${encodeURIComponent(uri)}">${esc(caption)}</a><details><summary>Details</summary><ul>${unique.map(text => `<li>${esc(text)}</li>`).join("")}</ul></details></div>`;
}
function warning(ui: ModerationUI, kind: string): string {
  const labels = [...new Set(causes(ui).filter(cause => cause.type === "label").map(cause => cause.label.val))];
  return `${kind} warning${labels.length ? `: ${labels.slice(0,4).join(", ")}` : ""}`;
}
function declaredRoot(post: AppBskyFeedDefs.PostView): string | undefined {
  const record = post.record as {reply?: {root?: {uri?: unknown}}};
  const root = record.reply === undefined ? post.uri : record.reply?.root?.uri;
  return typeof root === "string" && isValidPostUri(root) ? root : undefined;
}
function postAttributes(post: AppBskyFeedDefs.PostView, quoted: boolean): string {
  const root = declaredRoot(post);
  return `data-post-uri="${esc(post.uri)}"${root ? ` data-thread-root="${esc(root)}"` : ""} data-quoted="${quoted}"`;
}
function quotePost(value: AppBskyEmbedRecord.ViewRecord): AppBskyFeedDefs.PostView | undefined {
  if (!isValidPostUri(value.uri) || !AppBskyActorDefs.validateProfileViewBasic(value.author).success ||
      value.uri.split("/")[2] !== value.author.did || !AppBskyFeedPost.validateRecord(value.value).success ||
      !AppBskyEmbedRecord.validateViewRecord(value).success) return undefined;
  return {uri:value.uri,cid:value.cid,author:value.author,record:value.value,indexedAt:value.indexedAt,
    ...(value.labels ? {labels:value.labels} : {}), ...(value.embeds?.[0] ? {embed:value.embeds[0]} : {}),
    ...(value.replyCount !== undefined ? {replyCount:value.replyCount} : {})};
}

function embed(reader: Viewer, value: unknown, depth: number, parentUri: string, links: Links): string {
  if (AppBskyEmbedImages.isView(value)) {
    const images = value as AppBskyEmbedImages.View;
    if (!AppBskyEmbedImages.validateView(images).success) return '<p class="feed-notice">Images unavailable.</p>';
    return `<div class="feed-images">${images.images.slice(0,4).map(item => {
      const src = imageUrl(item.thumb);
      return src ? `<img src="${esc(src)}" alt="${esc(item.alt)}" loading="lazy" referrerpolicy="no-referrer">` : "";
    }).join("")}</div>`;
  }
  if (AppBskyEmbedExternal.isView(value)) {
    if (!AppBskyEmbedExternal.validateView(value).success) return '<p class="feed-notice">Preview unavailable.</p>';
    const external = (value as AppBskyEmbedExternal.View).external;
    const href = safeLink(external.uri), thumb = imageUrl(external.thumb ?? "");
    return href ? `<a class="feed-external" href="${esc(href)}" rel="noreferrer noopener">${thumb ? `<img src="${esc(thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}<strong>${esc(external.title)}</strong><span>${esc(external.description.slice(0,500))}</span><small>${esc(new URL(href).hostname)}</small></a>` : "";
  }
  if (AppBskyEmbedVideo.isView(value)) {
    if (!AppBskyEmbedVideo.validateView(value).success) return '<p class="feed-notice">Video unavailable.</p>';
    const video = value as AppBskyEmbedVideo.View;
    const playlist = originUrl(video.playlist,"https://video.bsky.app");
    const poster = imageUrl(video.thumbnail ?? "") ?? originUrl(video.thumbnail ?? "","https://video.bsky.app");
    if (!playlist) return '<p class="feed-notice">Video unavailable.</p>';
    return `<div class="feed-video"><video controls preload="none"${poster ? ` poster="${esc(poster)}"` : ""} aria-label="${esc(video.alt || "Post video")}"><source src="${esc(playlist)}" type="application/vnd.apple.mpegurl"></video><a href="${esc(bskyPostUrl(parentUri))}" rel="noreferrer noopener">Open video in Bluesky</a></div>`;
  }
  if (AppBskyEmbedRecord.isView(value)) {
    const record = (value as AppBskyEmbedRecord.View).record;
    if (AppBskyEmbedRecord.isViewBlocked(record)) return '<p class="feed-notice">Quoted post blocked.</p>';
    if (AppBskyEmbedRecord.isViewNotFound(record)) return '<p class="feed-notice">Quoted post deleted or unavailable.</p>';
    if (AppBskyEmbedRecord.isViewDetached(record)) return '<p class="feed-notice">Quoted post detached.</p>';
    const uri = "uri" in record && typeof record.uri === "string" ? record.uri : "";
    const fallback = !isValidPostUri(uri) ? '<p class="feed-notice">Quoted post unavailable.</p>' : links === "public"
      ? `<p class="feed-quote"><a href="${esc(bskyPostUrl(uri))}" rel="noreferrer noopener">Read quoted post on Bluesky</a></p>` : `<p class="feed-quote"><a href="${esc(threadHref(uri))}">Read quoted post</a></p>`;
    if (!AppBskyEmbedRecord.isViewRecord(record) || depth >= 1) return fallback;
    const post = quotePost(record);
    return post ? `<blockquote class="feed-quote">${renderPost(reader,post,"contentList",false,depth+1,links)}</blockquote>` : fallback;
  }
  if (AppBskyEmbedRecordWithMedia.isView(value)) {
    if (!AppBskyEmbedRecordWithMedia.validateView(value).success) return '<p class="feed-notice">Embedded content unavailable.</p>';
    const combined = value as AppBskyEmbedRecordWithMedia.View;
    return embed(reader,combined.media,depth,parentUri,links) + embed(reader,combined.record,depth,parentUri,links);
  }
  return "";
}
export function renderPost(reader: Viewer, post: AppBskyFeedDefs.PostView, context: "contentList" | "contentView" = "contentList", focus = false, quoteDepth = 0, links: Links = "reader", interactions?: InteractionControls): string {
  const decision = reader.decision(post, context);
  const attributes = postAttributes(post, quoteDepth > 0);
  if (decision.filter || decision.noOverride) return `<article class="feed-post withheld" ${attributes}>${hiddenMarker(decision)}</article>`;
  if (!AppBskyFeedPost.isRecord(post.record) || !isValidPostUri(post.uri)) return UNREADABLE_POST;
  const record = post.record as unknown as AppBskyFeedPost.Record;
  if (typeof record.text !== "string" || typeof record.createdAt !== "string") return UNREADABLE_POST;
  const media = reader.decision(post, "contentMedia");
  const renderedMedia = media.filter || media.noOverride ? marker({established: true, decidedBy: "viewer"}, "Media hidden by your viewing settings.", [...new Set(causes(media).slice(0, 16).map(causeText))]) : embed(reader, post.embed, quoteDepth, post.uri, links);
  const mediaHtml = media.blur && renderedMedia ? `<details class="content-warning"><summary>${esc(warning(media,"Media"))}: Show media</summary>${contextDisclosure(media,post.uri)}${renderedMedia}</details>` : renderedMedia;
  const avatarDecision = reader.decision(post, "avatar");
  const nameDecision = reader.decision(post, "displayName");
  const avatar = avatarDecision.blur || avatarDecision.filter || avatarDecision.noOverride
    ? undefined : imageUrl(post.author.avatar ?? "");
  const avatarHtml = avatar
    ? `<img class="feed-avatar" src="${esc(avatar)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : '<span class="feed-avatar feed-avatar-placeholder" aria-hidden="true"></span>';
  const name = nameDecision.blur || nameDecision.filter || nameDecision.noOverride
    ? post.author.handle : post.author.displayName?.trim() || post.author.handle;
  const showHandle = name !== post.author.handle;
  const fullDate = Number.isFinite(new Date(record.createdAt).getTime()) ? new Date(record.createdAt).toUTCString() : "Date unavailable";
  const author = `<div class="feed-author"><strong title="${esc(name)}">${esc(name)}</strong>${showHandle ? `<span class="feed-handle" title="@${esc(post.author.handle)}">@${esc(post.author.handle)}</span>` : ""}<time class="feed-date" datetime="${esc(record.createdAt)}" title="${esc(fullDate)}">${esc(focus ? fullDate : date(record.createdAt))}</time></div>`;
  const contextLine = contextDisclosure(decision,post.uri);
  const conversationLink = focus || links === "public" ? "" : `<a href="${esc(threadHref(post.uri))}">${post.replyCount ? `${post.replyCount} replies` : "Conversation"}</a>`;
  const content = `<div class="feed-row">${avatarHtml}<div class="feed-body">${author}<div class="feed-text">${rich(record,quoteDepth ? 600 : Infinity)}</div>${mediaHtml}${contextLine}<div class="feed-actions">${conversationLink}${links === "public" ? "" : `<a href="/context?uri=${esc(encodeURIComponent(post.uri))}">Context</a>`}<a href="${esc(bskyPostUrl(post.uri))}" rel="noreferrer noopener">Open in Bluesky</a></div>${quoteDepth === 0 ? interactions?.(post) ?? "" : ""}</div></div>`;
  return `<article class="feed-post" ${attributes}>${decision.blur ? `<details class="content-warning"><summary>${esc(warning(decision,"Content"))}: Show post</summary>${content}</details>` : content}</article>`;
}
function repostContext(reader: Reader, actor: AppBskyActorDefs.ProfileViewBasic): string {
  if (typeof reader.actorDecision !== "function") return "Reposted";
  const profile = reader.actorDecision(actor,"profileList");
  const display = reader.actorDecision(actor,"displayName");
  if (profile.blur || profile.filter || profile.noOverride || display.blur || display.filter || display.noOverride) return "Reposted";
  return `Reposted by ${actor.displayName?.trim() || actor.handle}`;
}
export function renderFeed(reader: Reader, items: AppBskyFeedDefs.FeedViewPost[], interactions?: InteractionControls): string {
  return `<section class="following-feed" aria-label="Following posts">${items.map(item => `${AppBskyFeedDefs.isReasonRepost(item.reason) ? `<p class="feed-context">${esc(repostContext(reader,item.reason.by))}</p>` : item.reply ? '<p class="feed-context">In a conversation</p>' : ""}${renderPost(reader,item.post,"contentList",false,0,"reader",interactions)}`).join("")}</section>`;
}
/** Only an outcome Bluesky actually reported names a decider; anything else is an observation limit. */
function unavailableNode(node: unknown, noun: "conversation" | "reply"): string {
  if (AppBskyFeedDefs.isBlockedPost(node)) {
    const viewer = (node as AppBskyFeedDefs.BlockedPost).author?.viewer;
    if (viewer?.blocking || viewer?.blockingByList) return marker({established: true, decidedBy: "viewer"}, `You block this account, so this ${noun} is not shown.`);
    if (viewer?.blockedBy) return marker({established: true, decidedBy: "account"}, `This account blocks you, so this ${noun} is not shown.`);
    // Bluesky reported a block without saying whose; the party is left unnamed rather than guessed.
    return marker({established: true, decidedBy: "source"}, `A block prevents this ${noun} from being displayed.`);
  }
  if (AppBskyFeedDefs.isNotFoundPost(node)) return marker({established: true, decidedBy: "source"},
    "Bluesky reports this post was not found. It may have been deleted or may never have been indexed; Phlogiston cannot tell which.");
  return marker({established: false}, `Phlogiston could not read this ${noun}. No decision about it is known.`);
}
export function renderThread(reader: Viewer, thread: ThreadResult, controls = "", interactions?: InteractionControls): string {
  if (!AppBskyFeedDefs.isThreadViewPost(thread)) return unavailableNode(thread, "conversation");
  const parents: AppBskyFeedDefs.PostView[] = [];
  let parent = thread.parent;
  while (AppBskyFeedDefs.isThreadViewPost(parent) && parents.length < 6) { parents.unshift(parent.post); parent = parent.parent; }
  return `<section class="conversation" aria-label="Conversation">${parents.map(post => renderPost(reader, post, "contentView",false,0,"reader",interactions)).join("")}<div class="thread-focus">${renderPost(reader, thread.post, "contentView", true,0,"reader",interactions)}</div>${controls}${renderReplies(reader, thread,"reader",interactions)}</section>`;
}
/** Replies beneath a received post, with Phlogiston's own display bounds disclosed. */
export function renderReplies(reader: Viewer, thread: AppBskyFeedDefs.ThreadViewPost, links: Links = "reader", interactions?: InteractionControls): string {
  let remaining = MAX_REPLIES;
  let capped = false, deeper = false;
  const replies = (nodes: typeof thread.replies, depth: number): string => {
    if (!nodes?.length) return "";
    if (depth > 2) { deeper = true; return ""; }
    if (nodes.length > MAX_REPLIES) capped = true;
    return nodes.slice(0, MAX_REPLIES).map(node => {
      if (remaining-- <= 0) { capped = true; return ""; }
      if (!AppBskyFeedDefs.isThreadViewPost(node)) return unavailableNode(node, "reply");
      return `<div class="thread-reply">${renderPost(reader, node.post, "contentView", false, 0, links, interactions)}${replies(node.replies, depth + 1)}</div>`;
    }).join("");
  };
  const rendered = replies(thread.replies, 1);
  const bounds = [capped ? `Phlogiston shows the first ${MAX_REPLIES} replies it received; more were received and are not shown here.` : "",
    deeper ? "Phlogiston received deeper replies than it shows here." : ""].filter(Boolean).join(" ");
  const bounded = bounds ? `${marker({established: true, decidedBy: "app"}, bounds)}<p class="feed-notice"><a href="${esc(bskyPostUrl(thread.post.uri))}" rel="noreferrer noopener">Open the whole conversation in Bluesky</a></p>` : "";
  return `${rendered}${bounded}`;
}
