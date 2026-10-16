import { escapeHtml, isValidDid } from "./html.js";

export const LABELWATCH_ORIGIN = "https://labelwatch.neutral.zone";
const SCHEMA = "labelwatch.public-observations.v1";
const MAX_BYTES = 256 * 1024;
export interface LabelObservation {
  labeler: string; uri: string; value: string; action: string; sourceTime: string; observedTime: string;
}
export interface LabelContext {
  did: string; start: string; end: string; coverage: string; gaps: number;
  rows: LabelObservation[]; partial: boolean; fetchedAt: string;
}
export interface LabelDirectory { lookup(did: string): Promise<LabelContext | null> }
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid object");
  return value as Record<string, unknown>;
}
function string(value: unknown, max = 2048): string {
  if (typeof value !== "string" || value.length > max) throw new Error("invalid string");
  return value;
}
function date(value: unknown): string {
  const result = string(value, 64);
  if (!Number.isFinite(Date.parse(result))) throw new Error("invalid date");
  return result;
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  return JSON.stringify(value);
}
function manifest(value: unknown, did: string): Record<string, unknown> {
  const m = object(value);
  if (m.schema !== SCHEMA || m.account !== did || m.current_state !== "unknown") throw new Error("wrong observation subject or contract");
  const interval = object(m.interval);
  if (interval.end_exclusive !== true || Date.parse(date(interval.start)) >= Date.parse(date(interval.end))) throw new Error("invalid interval");
  string(m.frontier, 256);
  return m;
}

/** Fixed public read origin, bounded requests, no OAuth credentials or authority dependency. */
export class LabelwatchDirectory implements LabelDirectory {
  private active = 0;
  private readonly cache = new Map<string, { until: number; result: Promise<LabelContext | null> }>();
  public constructor(private readonly request: typeof fetch = fetch) {}
  public async lookup(did: string): Promise<LabelContext | null> {
    if (!isValidDid(did)) return null;
    const old = this.cache.get(did);
    if (old && old.until > Date.now()) return old.result;
    if (this.active >= 4) return null;
    if (this.cache.size >= 128) this.cache.delete(this.cache.keys().next().value!);
    const result = this.load(did).catch(() => null);
    this.cache.set(did, { until: Date.now() + 30_000, result });
    return result;
  }
  private async load(did: string): Promise<LabelContext> {
    this.active++;
    const signal = AbortSignal.timeout(8_000);
    try {
      const initial = await this.read(`/exports?${new URLSearchParams({ did, days: "7" })}`, signal);
      const first = manifest(initial.manifest, did);
      const cursor = string(initial.cursor, 4096);
      if (!cursor) throw new Error("missing cursor");
      const page = await this.read(`/exports?${new URLSearchParams({ cursor })}`, signal);
      const m = manifest(page.manifest, did);
      if (canonical(m) !== canonical(first) ||
          page.offset !== 0 || typeof page.terminal !== "boolean" || !Array.isArray(page.rows) || page.rows.length > 1000) throw new Error("page mismatch");
      const interval = object(m.interval), coverage = object(m.coverage);
      if (!Array.isArray(coverage.gaps)) throw new Error("missing coverage");
      const rows = page.rows.slice(0, 50).map(raw => {
        const row = object(raw), labeler = string(row.labeler_did), uri = string(row.uri);
        if (!isValidDid(labeler) || !(uri === did || uri.startsWith(`at://${did}/`))) throw new Error("wrong event identity");
        const action = string(row.action, 64);
        if (!["application_observed", "removal_observed", "unknown_action"].includes(action)) throw new Error("unknown action");
        const observedTime = date(row.observed_at);
        if (Date.parse(observedTime) < Date.parse(date(interval.start)) || Date.parse(observedTime) >= Date.parse(date(interval.end))) throw new Error("event outside observation window");
        return { labeler, uri, action, value: string(row.value, 256), sourceTime: date(row.source_timestamp), observedTime };
      });
      return { did, start: date(interval.start), end: date(interval.end), coverage: string(coverage.status, 128), gaps: coverage.gaps.length,
        rows, partial: page.terminal !== true || page.rows.length > 50, fetchedAt: new Date().toISOString() };
    } finally { this.active--; }
  }
  private async read(path: string, signal: AbortSignal): Promise<Record<string, unknown>> {
    const response = await this.request(new URL(path, LABELWATCH_ORIGIN), { signal, redirect: "error", headers: { Accept: "application/json" } });
    if (!response.ok || !response.body) { await response.body?.cancel(); throw new Error("unavailable"); }
    if (Number(response.headers.get("content-length") ?? 0) > MAX_BYTES) { await response.body.cancel(); throw new Error("too large"); }
    const reader = response.body.getReader(), chunks: Uint8Array[] = [];
    let total = 0;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BYTES) { await reader.cancel(); throw new Error("too large"); }
      chunks.push(value);
    }
    return object(JSON.parse(Buffer.concat(chunks).toString("utf8")));
  }
}

function readableTime(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return escapeHtml(value);
  const display = new Intl.DateTimeFormat("en-GB", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit",
    minute: "2-digit", second: "2-digit", timeZone: "UTC", hour12: false,
  }).format(date);
  return `<time datetime="${escapeHtml(value)}">${escapeHtml(display)} UTC</time>`;
}

export function renderLabels(context: LabelContext | null, did: string, view: "account" | "post" = "account"): string {
  const source = `${LABELWATCH_ORIGIN}/account?${new URLSearchParams({ did, days: "7" })}`;
  const intro = view === "post" ? '<p class="lede">Recent label observations concerning this post and its author.</p>' : '<p class="lede">Recent label observations on your account and records.</p>';
  if (!context || context.did !== did) return intro + `<h2>Label context unavailable</h2><p class="meta">Coverage is unknown. Current label state is unknown.</p><p>Labelwatch could not provide a usable response right now. This does not mean ${view === "post" ? "this account or post has" : "your account has"} no labels.</p>`;
  const rows = context.rows.map(row => {
    const kind = row.uri === did ? "Account" : row.uri.startsWith(`at://${did}/app.bsky.feed.post/`) ? "Post" : "Record";
    const postRkey = kind === "Post" ? row.uri.slice(`at://${did}/app.bsky.feed.post/`.length) : "";
    const target = postRkey && /^[a-zA-Z0-9._:-]{1,512}$/.test(postRkey)
      ? `<a href="https://bsky.app/profile/${encodeURIComponent(did)}/post/${encodeURIComponent(postRkey)}" rel="noopener noreferrer">View post</a>` : escapeHtml(row.uri);
    return `<article class="label-card"><h2>${escapeHtml(row.value)}</h2><p>${kind} · ${row.action === "removal_observed" ? "Removal observed" : row.action === "application_observed" ? "Application observed" : "Action unknown"}</p><p>Labeler: <a href="https://bsky.app/profile/${encodeURIComponent(row.labeler)}" rel="noopener noreferrer">${escapeHtml(row.labeler)}</a></p><details><summary>Source and timing</summary><p>${target}</p><dl><dt>Source timestamp</dt><dd>${readableTime(row.sourceTime)}</dd><dt>Observed by Labelwatch</dt><dd>${readableTime(row.observedTime)}</dd></dl></details></article>`;
  }).join("");
  const coverage = context.coverage === "unknown" ? "Coverage is unknown." : "Coverage may be incomplete.";
  const summary = `<p class="meta">${coverage} Current label state is unknown.</p>`;
  const observations = rows
    ? `<p>Showing ${context.rows.length} observed ${context.rows.length === 1 ? "event" : "events"}.</p>${rows}`
    : '<p>No events found in this observation window. Coverage is incomplete; labels may exist elsewhere.</p>';
  const details = `<details><summary>Observation details</summary><p>These are observations, not a verdict or a list of currently effective labels. They do not change community admission or moderation decisions.</p><p>Observation window: ${readableTime(context.start)} to ${readableTime(context.end)} (end excluded).</p><p>Coverage: ${escapeHtml(context.coverage)}. ${context.gaps} disclosed gaps. This covers recorded observations only, not every labeler.</p><p>Retrieved ${readableTime(context.fetchedAt)}. ${context.partial ? "Showing a partial page of up to 50 events; more may exist. Inspect Labelwatch for the full bounded export." : "The export reached its terminal page; coverage gaps still apply."}</p><p><a href="${escapeHtml(source)}" rel="noopener noreferrer">Inspect the source at Labelwatch</a></p></details>`;
  return intro + summary + observations + details;
}
