import assert from "node:assert/strict";
import test from "node:test";
import type { ProjectionBundle, PublicEntry, PublicFeed } from "./feed.js";
import { page } from "./views.js";

const DIGEST = `sha256:${"a".repeat(64)}`;

test("qualified deletion and transport unavailability explain different facts", () => {
  const deleted = render("deleted_by_author");
  assert.match(deleted, /author deleted the original/i);
  assert.match(deleted, /editorial receipt/i);
  assert.doesNotMatch(deleted, /may be temporary/i);

  const unavailable = render("unavailable");
  assert.match(unavailable, /can’t reach the original/i);
  assert.match(unavailable, /may be temporary/i);
  assert.doesNotMatch(unavailable, /author deleted the original/i);
});

function render(sourceRelationship: string): string {
  const entry: PublicEntry = {
    projectionIdentity: DIGEST,
    projectionStateId: DIGEST,
    lifecycleState: "source_unavailable",
    sourceUri: "at://did:plc:authority/type/self/did:plc:author/post/1",
    admittedSourceCid: "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti",
    authorDid: "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
    admissionId: DIGEST,
    admittedAt: "2026-08-24T12:00:00Z",
    sourceRelationship,
    presentation: null,
    technicalReceipts: null,
    removalId: null,
  };
  const feed: PublicFeed = {
    feedId: DIGEST,
    artifactId: DIGEST,
    channel: "ordinary_reader",
    publishedAt: "2026-08-24T12:01:00Z",
    communityActorDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb",
    entries: [entry],
  };
  const bundle: ProjectionBundle = { ordinary: feed, audit: null };
  return page({ path: "/", bundle, signedInDid: null, actions: [] });
}
