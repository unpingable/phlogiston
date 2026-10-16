import { bskyPostUrl, bskyProfileUrl, escapeHtml, isValidDid } from "./html.js";
import type { HydratedProfile } from "./profiles.js";

export interface IdentityOptions {
  avatars: boolean;
  /** Keep the DID in visible text beside a known name (moderator surfaces). */
  showDid?: boolean;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ISO_INSTANT_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;

/**
 * A human UTC date like "24 Sep 2026, 14:05 UTC" from an ISO instant. Only
 * zoned ISO input is converted, so the result never depends on the process
 * time zone; anything else is returned unchanged.
 */
export function humanDate(value: string): string {
  if (!ISO_INSTANT_PATTERN.test(value)) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}, ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}

function timeElement(value: string): string {
  return `<time datetime="${escapeHtml(value)}">${escapeHtml(humanDate(value))}</time>`;
}

export const COMMUNITY_VIEW_BADGE = '<span class="layer">Community view</span>';

export function renderIdentity(
  did: string,
  profiles: ReadonlyMap<string, HydratedProfile>,
  options: IdentityOptions,
): string {
  const profile = profiles.get(did);
  const href = isValidDid(did) ? bskyProfileUrl(did) : undefined;
  const link = (label: string): string => href === undefined
    ? escapeHtml(label)
    : `<a class="profile" href="${escapeHtml(href)}" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
  if (profile === undefined) return `<span class="identity">${link(did)}</span>`;
  const avatar = options.avatars && profile.avatar !== undefined
    ? `<img class="avatar" src="${escapeHtml(profile.avatar)}" alt="" width="24" height="24">`
    : "";
  const name = profile.displayName ?? (profile.handle === undefined ? undefined : `@${profile.handle}`);
  if (name === undefined) return `<span class="identity" title="${escapeHtml(did)}">${avatar}${link(did)}</span>`;
  const visibleDid = options.showDid === true ? ` <span class="did">${escapeHtml(did)}</span>` : "";
  return `<span class="identity" title="${escapeHtml(did)}">${avatar}<span class="name">${link(name)}</span>${visibleDid}</span>`;
}

export function publicPostLink(uri: string, label = "Public post on Bluesky"): string {
  try {
    const href = bskyPostUrl(uri);
    return `<a class="external" href="${escapeHtml(href)}" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
  } catch {
    return "";
  }
}

export function whyHere(admittedAt: string, subjectUri: string): string {
  const when = admittedAt === "" ? "at an unrecorded time" : `on ${timeElement(admittedAt)}`;
  const link = publicPostLink(subjectUri);
  const original = link === ""
    ? "The original is the author’s public record."
    : `The original is the author’s public record: ${link}.`;
  return `<details class="why"><summary>Why is this here?</summary><p>Admitted to this community’s view ${when}. ${original} Community removal changes only this view.</p></details>`;
}

export function snippet(text: string, maxLength = 140): string {
  const firstLine = text.split("\n", 1)[0] ?? "";
  return firstLine.length <= maxLength ? firstLine : `${firstLine.slice(0, maxLength)}…`;
}

export function postedAt(createdAt: string): string {
  return createdAt === "" ? "" : `posted ${timeElement(createdAt)}`;
}
