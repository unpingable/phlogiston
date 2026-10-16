import assert from "node:assert/strict";
import test from "node:test";
import { LabelwatchDirectory, renderLabels } from "./labels.js";
const did = "did:plc:alice";
const manifest = { schema: "labelwatch.public-observations.v1", account: did, current_state: "unknown", frontier: "fixed", interval: { start: "2026-10-05T00:00:00Z", end: "2026-10-12T00:00:00Z", end_exclusive: true }, coverage: { status: "unknown", gaps: [{ reason: "not_observed" }] } };
const row = { labeler_did: "did:plc:labeler", uri: did, value: "<b>example</b>", action: "application_observed", source_timestamp: "2026-10-11T00:00:00Z", observed_at: "2026-10-11T00:01:00Z" };
function directory(page: unknown, initial: unknown = { manifest, cursor: "page1" }) {
  const calls: { url: string; init: RequestInit | undefined }[] = [];
  const reader = new LabelwatchDirectory((async (url, init) => {
    calls.push({ url: String(url), init });
    return Response.json(calls.length % 2 ? initial : page);
  }) as typeof fetch);
  return { reader, calls };
}
const page = { manifest, rows: [row], offset: 0, terminal: true };
test("Labelwatch binds fixed-origin export pages to signed-in DID and preserves observation semantics", async () => {
  const { reader, calls } = directory(page);
  const result = await reader.lookup(did);
  assert.ok(result); assert.equal(result.gaps, 1); assert.equal(result.partial, false);
  const html = renderLabels(result, did);
  assert.match(html, /&lt;b&gt;example&lt;\/b&gt;/); assert.match(html, /Current label state is unknown/);
  assert.match(html, /Source timestamp/); assert.match(html, /Observed by Labelwatch/);
  assert.equal(calls.length, 2); assert.match(calls[0]!.url, /^https:\/\/labelwatch.neutral.zone\/exports\?did=/);
  assert.equal(calls[0]!.init!.redirect, "error"); assert.deepEqual(calls[0]!.init!.headers, { Accept: "application/json" });
  assert.equal(await reader.lookup(did), result); assert.equal(calls.length, 2);
  assert.match(renderLabels(result, "did:plc:bob"), /Label context unavailable/);
});
test("Labelwatch refuses cross-account, cross-frontier, malformed and unknown event responses", async () => {
  for (const candidate of [
    { ...page, manifest: { ...manifest, account: "did:plc:bob" } },
    { ...page, manifest: { ...manifest, frontier: "other" } },
    { ...page, rows: [{ ...row, uri: "at://did:plc:bob/app.bsky.feed.post/one" }] },
    { ...page, rows: [{ ...row, action: "current_active" }] },
    { ...page, rows: [{ ...row, observed_at: "not-a-date" }] },
    { ...page, offset: 100 },
    { ...page, manifest: { ...manifest, coverage: { status: "complete", gaps: [] } } },
    { ...page, manifest: { ...manifest, filters: { labeler: "another" } } },
    { ...page, rows: [{ ...row, observed_at: manifest.interval.end }] },
    { ...page, rows: [{ ...row, observed_at: "2026-10-04T00:00:00Z" }] },
  ]) assert.equal(await directory(candidate).reader.lookup(did), null);
});
test("Partial and empty observation windows never become absence or current-state claims", async () => {
  const partial = await directory({ ...page, terminal: false }).reader.lookup(did);
  assert.ok(partial?.partial); assert.match(renderLabels(partial, did), /partial page/);
  const empty = await directory({ ...page, rows: [] }).reader.lookup(did);
  assert.match(renderLabels(empty, did), /Coverage is incomplete; labels may exist elsewhere/);
  const unavailable = new LabelwatchDirectory((async () => new Response("busy", { status: 503 })) as typeof fetch);
  assert.equal(await unavailable.lookup(did), null);
});
test("Oversized and non-JSON responses are unavailable, with no follow-up read", async () => {
  for (const response of [new Response("x".repeat(262145)), new Response("not json"), new Response("", { headers: { "content-length": "262145" } })]) {
    let reads = 0;
    const reader = new LabelwatchDirectory((async () => { reads++; return response; }) as typeof fetch);
    assert.equal(await reader.lookup(did), null); assert.equal(reads, 1);
  }
});

test("Removal and unknown-action observations retain their distinct meaning", async () => {
  for (const [action, wording] of [["removal_observed", "Removal observed"], ["unknown_action", "Action unknown"]]) {
    const result = await directory({ ...page, rows: [{ ...row, action }] }).reader.lookup(did);
    assert.ok(result); assert.ok(renderLabels(result, did).includes(wording!));
  }
});

test("Readable label cards precede collapsed provenance while unknown state remains visible", async () => {
  const result = await directory(page).reader.lookup(did);
  assert.ok(result);
  const html = renderLabels(result, did);
  const detailIndex = html.indexOf("<details>");
  assert.ok(html.indexOf('<article class="label-card">') < detailIndex);
  assert.ok(html.indexOf("Current label state is unknown") < detailIndex);
  assert.ok(html.indexOf("Coverage is unknown") < detailIndex);
  assert.match(html, /Showing 1 observed event/);
  assert.match(html, /11 Oct 2026, 00:00:00 UTC/);
  assert.match(html, /<time datetime="2026-10-11T00:01:00Z">11 Oct 2026, 00:01:00 UTC<\/time>/);
  assert.match(html, /<details><summary>Observation details<\/summary>/);
  assert.ok(html.indexOf("Observation window:") > detailIndex);
  assert.ok(html.indexOf("1 disclosed gaps") > detailIndex);
  assert.ok(html.indexOf("Retrieved") > detailIndex);
  assert.doesNotMatch(html, /<details open|class="notice"/);
});

test("Partial, other coverage and unavailable summaries do not imply complete current labels", async () => {
  const result = await directory({ ...page, terminal: false }).reader.lookup(did);
  assert.ok(result);
  const html = renderLabels({ ...result, coverage: "bounded" }, did);
  assert.ok(html.indexOf("Coverage may be incomplete") < html.indexOf("<details>"));
  assert.match(html, /partial page/);
  const unavailable = renderLabels(null, did);
  assert.match(unavailable, /Coverage is unknown\. Current label state is unknown/);
  assert.doesNotMatch(unavailable, /class="notice"/);
});


test("post context attributes observations to the inspected subject, not the reader", () => {
  const html = renderLabels(null, "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa", "post");
  assert.match(html, /this post and its author/);
  assert.match(html, /this account or post/);
  assert.doesNotMatch(html, /your account|your standing/);
});
