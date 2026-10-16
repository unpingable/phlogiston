import assert from "node:assert/strict";
import test from "node:test";
import { OMISSION_CAUSES, omissionStanding, omittedTotal, renderOmissions, marker, type Omissions } from "./attention.js";

test("every omission cause names who decided; a curator's blocks also name the viewer who applied them", () => {
  for (const cause of OMISSION_CAUSES) assert.equal(omissionStanding(cause).established, true, cause);
  assert.deepEqual(omissionStanding("curator-blocks"), {established: true, decidedBy: "curator", appliedBy: "viewer"});
  assert.deepEqual(omissionStanding("other-account-block"), {established: true, decidedBy: "account"});
  assert.deepEqual(omissionStanding("repeat"), {established: true, decidedBy: "app"});
  assert.deepEqual(omissionStanding("local-quiet"), {established: true, decidedBy: "viewer"});
});

test("an unestablished observation is marked as such and never carries a decider", () => {
  const unknown = marker({established: false}, "Phlogiston could not read this post.");
  assert.match(unknown, /data-observation="not-established"/);
  assert.doesNotMatch(unknown, /data-decided-by/);
  const known = marker({established: true, decidedBy: "curator", appliedBy: "viewer"}, "Excluded <b>");
  assert.match(known, /data-decided-by="curator"/);
  assert.match(known, /data-applied-by="viewer"/);
  assert.doesNotMatch(known, /data-observation|<b>/);
});

test("a page with nothing suppressed shows no attention summary", () => {
  assert.equal(renderOmissions(12, {}), "");
  assert.equal(renderOmissions(12, {"local-quiet": 0}), "");
});

test("summary states shown and received totals and separates viewer choices from the selected curator", () => {
  const omitted: Omissions = {"local-quiet": 3, "home-preferences": 2, "curator-blocks": 4, "other-account-block": 1, repeat: 1};
  assert.equal(omittedTotal(omitted), 11);
  const body = renderOmissions(8, omitted, {curatorHandle: "cur<ator.test", editHref: "/feeds?edit=abc"});
  assert.match(body, /Showing 8 of the 19 posts received for this page\./);
  assert.match(body, /5 hidden by your settings\./);
  assert.match(body, /4 excluded by blocks from @cur&lt;ator\.test, which you chose to apply\./);
  assert.match(body, /1 not shown because of a block you did not place\./);
  assert.match(body, /1 repeat left out by Phlogiston\./);
  assert.doesNotMatch(body, /cur<ator/);
  assert.match(body, /<li data-cause="local-quiet" data-decided-by="viewer">3 /);
  assert.match(body, /<li data-cause="curator-blocks" data-decided-by="curator" data-applied-by="viewer">4 /);
  assert.match(body, /href="\/feeds\?edit=abc"/);
});

test("summary bounds its claim to received posts and disclaims upstream omissions and ranking", () => {
  const body = renderOmissions(1, {moderation: 1});
  assert.match(body, /only the posts Phlogiston received for this page/);
  assert.match(body, /Posts Bluesky did not send are not counted/);
  assert.doesNotMatch(body, /whole feed is|ranked because/);
});

test("label-based hiding is attributed to moderation settings with the labeler named as evidence", () => {
  assert.deepEqual(omissionStanding("label"), {established: true, decidedBy: "viewer"});
  const named = renderOmissions(1, {label: 2}, {labelers: ["did:plc:lab<", "did:plc:other"]});
  assert.match(named, /2 hidden by your settings\./);
  assert.match(named, /<li data-cause="label" data-decided-by="viewer">2 hidden by your Bluesky moderation settings, based on labels from did:plc:lab&lt;, did:plc:other\./);
  assert.doesNotMatch(named, /you chose|your choice/);
  assert.match(renderOmissions(1, {label: 1}), /based on a label\./);
});

test("a single received post is counted in the singular", () => {
  assert.match(renderOmissions(0, {moderation: 1}), /Showing 0 of the 1 post received for this page\./);
});
