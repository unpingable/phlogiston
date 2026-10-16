import { escapeHtml as esc } from "./html.js";

/** Who caused an effect. Failing to establish something is not a decider; see Standing. */
export type Decider = "viewer" | "curator" | "account" | "source" | "app";

/** Who decided is kept apart from what Phlogiston could establish. */
export type Standing =
  | { established: true; decidedBy: Decider; appliedBy?: "viewer" }
  | { established: false };

/** Reasons Phlogiston does not show an item it received. Upstream omissions are never counted here. */
export const OMISSION_CAUSES = [
  "local-quiet", "thread-muted", "home-preferences", "moderation", "label", "feed-definition",
  "curator-blocks", "other-account-block", "repeat",
] as const;
export type OmissionCause = typeof OMISSION_CAUSES[number];
export type Omissions = Partial<Record<OmissionCause, number>>;

const STANDING: Record<OmissionCause, Standing & {established: true}> = {
  "local-quiet": {established: true, decidedBy: "viewer"},
  "thread-muted": {established: true, decidedBy: "viewer"},
  "home-preferences": {established: true, decidedBy: "viewer"},
  "moderation": {established: true, decidedBy: "viewer"},
  // The labeler supplies evidence; the account's moderation settings, possibly defaults, decide the effect.
  "label": {established: true, decidedBy: "viewer"},
  "feed-definition": {established: true, decidedBy: "viewer"},
  "curator-blocks": {established: true, decidedBy: "curator", appliedBy: "viewer"},
  "other-account-block": {established: true, decidedBy: "account"},
  "repeat": {established: true, decidedBy: "app"},
};

export function omissionStanding(cause: OmissionCause): Standing & {established: true} { return STANDING[cause]; }
export function count(omitted: Omissions, cause: OmissionCause): void { omitted[cause] = (omitted[cause] ?? 0) + 1; }
export function omittedTotal(omitted: Omissions): number {
  return OMISSION_CAUSES.reduce((sum, cause) => sum + (omitted[cause] ?? 0), 0);
}

function attributes(standing: Standing): string {
  if (!standing.established) return 'data-observation="not-established"';
  return `data-decided-by="${standing.decidedBy}"${standing.appliedBy ? ` data-applied-by="${standing.appliedBy}"` : ""}`;
}

/** One placement and one tap-for-why shape for every affected item in the reader. */
export function marker(standing: Standing, text: string, why: readonly string[] = []): string {
  const details = why.length ? `<details><summary>Why?</summary><ul>${why.map(item => `<li>${esc(item)}</li>`).join("")}</ul></details>` : "";
  return `<div class="feed-notice attention-marker" ${attributes(standing)}><p>${esc(text)}</p>${details}</div>`;
}

export interface OmissionContext { curatorHandle?: string; editHref?: string; labelers?: readonly string[] }

function explain(cause: OmissionCause, context: OmissionContext): string {
  const edit = context.editHref ? ` <a href="${esc(context.editHref)}">Edit this feed</a>.` : "";
  switch (cause) {
    case "local-quiet": return "in conversations you quieted in this feed. Kept in Phlogiston only; review or undo under “Quieted in this feed”.";
    case "thread-muted": return 'in conversations you muted in Bluesky. This is account state at Bluesky. <a href="/attention">Conversation controls</a>.';
    case "home-preferences": return "replies, reposts or quote posts turned off in your Bluesky Following preferences. Change them in Bluesky.";
    case "moderation": return "hidden by your Bluesky mutes, blocks, muted words or hidden posts.";
    case "label": return `hidden by your Bluesky moderation settings, based on ${context.labelers?.length ? `labels from ${context.labelers.map(esc).join(", ")}` : "a label"}.`;
    case "feed-definition": return `replies or reposts turned off in this feed’s definition.${edit}`;
    case "curator-blocks": return `by authors @${esc(context.curatorHandle ?? "the selected curator")} blocks. The blocks are theirs; applying them here is your choice.${edit}`;
    case "other-account-block": return "involving a block that Bluesky reports and that you did not place.";
    case "repeat": return "repeats of a post already on this page, left out by Phlogiston.";
  }
}

/** States totals for the received page only; an untouched page stays ordinary reading. */
export function renderOmissions(shown: number, omitted: Omissions, context: OmissionContext = {}): string {
  const total = omittedTotal(omitted);
  if (total === 0) return "";
  const by = (decider: Decider) => OMISSION_CAUSES.filter(cause => STANDING[cause].decidedBy === decider).reduce((sum, cause) => sum + (omitted[cause] ?? 0), 0);
  const viewer = by("viewer"), curator = by("curator"), account = by("account"), app = by("app");
  const line = [
    `Showing ${shown} of the ${shown + total} ${shown + total === 1 ? "post" : "posts"} received for this page.`,
    viewer ? `${viewer} hidden by your settings.` : "",
    curator ? `${curator} excluded by blocks from @${esc(context.curatorHandle ?? "the selected curator")}, which you chose to apply.` : "",
    account ? `${account} not shown because of a block you did not place.` : "",
    app ? `${app} ${app === 1 ? "repeat" : "repeats"} left out by Phlogiston.` : "",
  ].filter(Boolean).join(" ");
  const rows = OMISSION_CAUSES.filter(cause => omitted[cause]).map(cause =>
    `<li data-cause="${cause}" ${attributes(STANDING[cause])}>${omitted[cause]} ${explain(cause, context)}</li>`).join("");
  return `<div class="attention-summary"><p>${line}</p><details><summary>Why?</summary><ul>${rows}</ul><p>These counts cover only the posts Phlogiston received for this page, not the whole feed. Posts Bluesky did not send are not counted; Phlogiston cannot see or explain them.</p></details></div>`;
}
