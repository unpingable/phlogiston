import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, rmSync, statSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import test from "node:test";
import { LocalQuietStore } from "./local-quiet.js";
import { HttpError } from "./http-error.js";

const did = "did:plc:fixtureaccount", other = "did:plc:otheraccount";
const root = "at://did:plc:postowner/app.bsky.feed.post/3test";
const feed = "at://did:plc:feedowner/app.bsky.feed.generator/curiosities";
const status = (code: number) => (e: unknown) => e instanceof HttpError && e.status === code;
function fixture() {
  const dir = mkdtempSync(join(tmpdir(), "phlo-local-hide-")), path = join(dir, "local.sqlite");
  return { dir, path, store: new LocalQuietStore(path) };
}

test("local hide persists with independent DID and selected-feed scope; repeated set/remove are idempotent", () => {
  const f = fixture();
  try {
    f.store.set(did, "following", root);
    f.store.set(did, "following", root);
    assert.deepEqual(f.store.list(did, "following"), [root]);
    assert.deepEqual(f.store.list(did, feed), []);
    assert.deepEqual(f.store.list(other, "following"), []);
    f.store.set(did, feed, root);
    f.store.set(other, "following", root);
    f.store.remove(did, "following", root);
    f.store.remove(did, "following", root);
    assert.deepEqual(f.store.list(did, "following"), []);
    assert.deepEqual(f.store.list(did, feed), [root]);
    assert.deepEqual(f.store.list(other, "following"), [root]);
    f.store.close();
    const reopened = new LocalQuietStore(f.path);
    try { assert.deepEqual(reopened.list(did, feed), [root]); }
    finally { reopened.close(); }
    assert.equal(statSync(f.path).mode & 0o777, 0o600);
    assert.equal(statSync(f.dir).mode & 0o777, 0o700);
  } finally { rmSync(f.dir, { recursive: true }); }
});

test("100 account-wide slots include all feeds; existing entries work at capacity and removal releases a slot", () => {
  const f = fixture();
  try {
    for (let i = 0; i < 99; i++) f.store.set(did, "following", root + i);
    f.store.set(did, feed, root);
    assert.throws(() => f.store.set(did, feed, root + "overflow"), status(409));
    f.store.set(did, "following", root + "0");
    assert.equal(f.store.list(did, "following").length, 99);
    f.store.set(other, feed, root);
    f.store.remove(did, "following", root + "0");
    f.store.set(did, feed, root + "overflow");
    assert.deepEqual(f.store.list(did, feed), [root, root + "overflow"]);
  } finally { f.store.close(); rmSync(f.dir, { recursive: true }); }
});

test("separate open connections observe the same committed cap and never reserve a 101st slot", () => {
  const f = fixture(), second = new LocalQuietStore(f.path);
  try {
    for (let i = 0; i < 99; i++) f.store.set(did, "following", root + i);
    second.set(did, feed, root);
    assert.throws(() => f.store.set(did, feed, root + "last"), status(409));
    second.remove(did, feed, root);
    f.store.set(did, feed, root + "last");
    assert.deepEqual(second.list(did, feed), [root + "last"]);
  } finally { second.close(); f.store.close(); rmSync(f.dir, { recursive: true }); }
});

test("invalid identities, feed keys and post roots refuse before content mutation", () => {
  const f = fixture();
  try {
    for (const account of ["account.example", "did:", "did:plc:" + "x".repeat(2048)]) assert.throws(() => f.store.set(account, "following", root), status(400));
    for (const key of ["home", "following?cursor=one", "at://handle.example/app.bsky.feed.generator/one", root, feed + "?cursor=one", feed.replace("curiosities", "..")]) {
      assert.throws(() => f.store.set(did, key, root), status(400));
      assert.throws(() => f.store.list(did, key), status(400));
    }
    for (const subject of [feed, "at://handle.example/app.bsky.feed.post/one", root + "#part", root.replace("3test", ".")]) assert.throws(() => f.store.set(did, "following", subject), status(400));
    assert.deepEqual(f.store.list(did, "following"), []);
  } finally { f.store.close(); rmSync(f.dir, { recursive: true }); }
});

test("protected storage rejects permissive files, pathname symlinks and existing provider state", () => {
  const f = fixture(); f.store.close();
  try {
    chmodSync(f.path, 0o644);
    assert.throws(() => new LocalQuietStore(f.path), /private/);
    chmodSync(f.path, 0o600);
    const link = join(f.dir, "link.sqlite"); symlinkSync(f.path, link);
    assert.throws(() => new LocalQuietStore(link));
    const provider = join(f.dir, "provider.sqlite"), db = new DatabaseSync(provider);
    db.exec("CREATE TABLE quiet(did TEXT, root TEXT, status TEXT)"); db.close(); chmodSync(provider, 0o600);
    assert.throws(() => new LocalQuietStore(provider), /own database/);
    const check = new DatabaseSync(provider);
    try { assert.equal(check.prepare("SELECT count(*) AS n FROM sqlite_master WHERE name='local_quiet'").get()!.n, 0); }
    finally { check.close(); }
    chmodSync(f.dir, 0o755);
    assert.throws(() => new LocalQuietStore(f.path), /private/);
  } finally { rmSync(f.dir, { recursive: true }); }
});
