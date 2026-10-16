import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";

import { LocalQuietStore } from "./local-quiet.js";
import { PersonalFeedStore } from "./personal-feeds.js";
import { QuietStore } from "./quiet.js";

const ME = "did:plc:me";
const THEM = "did:plc:them";
const ROOT = "at://did:plc:author/app.bsky.feed.post/3kroot";

test("account erasure removes exactly one account's rows from every per-account store", async () => {
  const dir = await mkdtemp(join(tmpdir(), "phlo-erase-"));
  const local = new LocalQuietStore(join(dir, "local.sqlite"));
  local.set(ME, "following", ROOT);
  local.set(ME, "at://did:plc:generator/app.bsky.feed.generator/feed-a", ROOT);
  local.set(THEM, "following", ROOT);
  assert.equal(local.eraseAccount(ME), 2);
  assert.deepEqual(local.list(ME, "following"), []);
  assert.deepEqual(local.list(THEM, "following"), [ROOT]);
  local.close();

  const quietPath = join(dir, "quiet.sqlite");
  new QuietStore(quietPath).close();
  const rawQuiet = new DatabaseSync(quietPath);
  rawQuiet.prepare("INSERT INTO quiet(did,root,status,updatedAt) VALUES(?,?,?,?)").run(ME, ROOT, "muted", new Date().toISOString());
  rawQuiet.prepare("INSERT INTO quiet(did,root,status,updatedAt) VALUES(?,?,?,?)").run(THEM, ROOT, "muted", new Date().toISOString());
  rawQuiet.close();
  const quiet = new QuietStore(quietPath);
  assert.equal(quiet.eraseAccount(ME), 1);
  assert.deepEqual(quiet.list(ME), []);
  assert.equal(quiet.list(THEM).length, 1);
  quiet.close();

  const feedsPath = join(dir, "feeds.sqlite");
  new PersonalFeedStore(feedsPath).close();
  const rawFeeds = new DatabaseSync(feedsPath);
  rawFeeds.prepare("INSERT INTO personal_feeds(owner_did,id,definition) VALUES(?,?,?)").run(ME, "f1", "{}");
  rawFeeds.prepare("INSERT INTO personal_feeds(owner_did,id,definition) VALUES(?,?,?)").run(THEM, "f1", "{}");
  rawFeeds.close();
  const feeds = new PersonalFeedStore(feedsPath);
  assert.equal(feeds.eraseAccount(ME), 1);
  assert.equal(feeds.eraseAccount(ME), 0);
  feeds.close();
  const check = new DatabaseSync(feedsPath);
  assert.deepEqual(check.prepare("SELECT owner_did FROM personal_feeds").all().map((row) => (row as { owner_did: string }).owner_did), [THEM]);
  check.close();
});
