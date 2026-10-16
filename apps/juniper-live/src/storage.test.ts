import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { SecretJsonFileStore, sha256, WebSessionStore } from "./storage.js";

test("secret JSON store hashes keys and restricts filesystem permissions", async () => {
  const root = await mkdtemp(join(tmpdir(), "juniper-secret-store-"));
  const store = new SecretJsonFileStore<{ token: string }>(root);
  await store.set("plaintext-key", { token: "synthetic-runtime-only" });
  const names = await readdir(root);
  assert.deepEqual(names, [sha256("plaintext-key")]);
  assert.equal((await stat(root)).mode & 0o777, 0o700);
  assert.equal((await stat(join(root, names[0]!))).mode & 0o777, 0o600);
  assert.deepEqual(await store.get("plaintext-key"), {
    token: "synthetic-runtime-only",
  });
  await store.del("plaintext-key");
  assert.equal(await store.get("plaintext-key"), undefined);
});

test("opaque browser session stores only a hash of the cookie token", async () => {
  const root = await mkdtemp(join(tmpdir(), "juniper-web-session-"));
  const store = new WebSessionStore(root);
  const now = new Date("2026-08-24T12:00:00.000Z");
  const token = await store.issue("did:plc:aaaaaaaaaaaaaaaaaaaaaaaa", now);
  const names = await readdir(root);
  assert.equal(names.includes(token), false);
  assert.equal(await readFile(join(root, names[0]!), "utf8").then((v) => v.includes(token)), false);
  assert.equal(
    await store.resolve(token, new Date("2026-08-24T13:00:00.000Z")),
    "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
  );
  assert.equal(
    await store.resolve(token, new Date("2026-08-25T00:00:00.000Z")),
    null,
  );
});
