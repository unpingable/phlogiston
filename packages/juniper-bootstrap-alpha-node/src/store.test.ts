import assert from "node:assert/strict";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { SecretStore } from "./store.js";

test("session store accepts a DID key without exposing it in the filename", async () => {
  const directory = await mkdtemp(join(tmpdir(), "juniper-secret-store-"));
  try {
    const store = new SecretStore<{ scope: string }>(directory);
    const did = "did:plc:wklgd4ebjiajx4gj3fthp62m";
    await store.set(did, { scope: "synthetic" });
    assert.deepEqual(await store.get(did), { scope: "synthetic" });
    const names = await readdir(directory);
    assert.equal(names.length, 1);
    assert.match(names[0]!, /^[a-f0-9]{64}\.json$/);
    assert.ok(!names[0]!.includes("did"));
    await store.del(did);
    assert.equal(await store.get(did), undefined);
  } finally {
    await rm(directory, { recursive: true });
  }
});

test("session store refuses an empty key", async () => {
  const store = new SecretStore<unknown>(join(tmpdir(), "juniper-unused-store"));
  await assert.rejects(store.set("", {}), /empty store key/);
});
