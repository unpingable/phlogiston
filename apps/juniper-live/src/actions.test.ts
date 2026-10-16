import assert from "node:assert/strict";
import { mkdtemp, readFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { AuthorActionStore } from "./actions.js";

const DID = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa";
const CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti";

test("author activity retains original admission subject across source edit and deletion", async () => {
  const root = await mkdtemp(join(tmpdir(), "juniper-actions-"));
  const path = join(root, "actions.json");
  const store = new AuthorActionStore(path);
  const item = await store.recordCreation({
    authorDid: DID,
    result: {
      post: { uri: "at://source/post/1", cid: CID },
      submission: { uri: "at://source/submission/1", cid: CID },
      consentProfile: "scv0-exact-public-presentation-consent/1",
    },
    title: "A useful post",
    body: "Original admitted presentation.",
    authorDisplayReference: "@alex.invalid.test",
    createdAt: "2026-08-24T12:00:00.000Z",
  });
  await store.recordEdit({
    authorDid: DID,
    itemId: item.itemId,
    source: { uri: item.post.uri, cid: CID.replace(/i$/, "j") },
    title: "A changed post",
    body: "The source is different now.",
    updatedAt: "2026-08-24T12:05:00.000Z",
  });
  let current = (await store.list(DID))[0]!;
  assert.deepEqual(current.post, item.post);
  assert.notDeepEqual(current.currentSource, item.post);
  await store.recordDeletion(DID, item.itemId, "2026-08-24T12:06:00.000Z");
  current = (await store.list(DID))[0]!;
  assert.equal(current.currentSource, null);
  assert.deepEqual(current.post, item.post);
  assert.equal((await stat(path)).mode & 0o777, 0o600);
  assert.equal((await readFile(path, "utf8")).includes("access_token"), false);
});

test("another author cannot mutate an occurrence", async () => {
  const root = await mkdtemp(join(tmpdir(), "juniper-actions-hostile-"));
  const store = new AuthorActionStore(join(root, "actions.json"));
  const item = await store.recordCreation({
    authorDid: DID,
    result: {
      post: { uri: "at://source/post/1", cid: CID },
      submission: { uri: "at://source/submission/1", cid: CID },
      consentProfile: "scv0-exact-public-presentation-consent/1",
    },
    title: "A useful post",
    body: "Original.",
    authorDisplayReference: "@alex.invalid.test",
    createdAt: "2026-08-24T12:00:00.000Z",
  });
  await assert.rejects(
    store.recordDeletion("did:plc:cccccccccccccccccccccccc", item.itemId, "2026-08-24T12:05:00.000Z"),
    /not found/,
  );
});
