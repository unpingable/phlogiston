import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { FilePublicationJournal } from "./journal.js";
import type { PublicationIntent } from "./publication.js";

const INTENT: PublicationIntent = Object.freeze({
  contract: "pcv0-lexicon-publication-intent/1",
  manifestSha256: `sha256:${"1".repeat(64)}`,
  authorityDid: "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
  nsid: "app.phlogiston.community.profile",
  rkey: "app.phlogiston.community.profile",
  expectedUri: "at://did:plc:aaaaaaaaaaaaaaaaaaaaaaaa/com.atproto.lexicon.schema/app.phlogiston.community.profile",
  documentSha256: `sha256:${"2".repeat(64)}`,
  recordSha256: `sha256:${"3".repeat(64)}`,
  phase: "prepared",
  attempts: 0,
});

test("intent journal persists exact operation before attempts and preserves it", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pcv0-lexicon-journal-"));
  try {
    const journal = new FilePublicationJournal(directory);
    assert.deepEqual(await journal.reserve(INTENT), INTENT);
    const attempting = Object.freeze({ ...INTENT, phase: "attempting" as const, attempts: 1 });
    await journal.save(attempting);
    assert.deepEqual(await journal.reserve(INTENT), attempting);
    const files = await import("node:fs/promises").then((fs) => fs.readdir(directory));
    assert.equal(files.length, 1);
    const filename = files[0];
    assert.ok(filename);
    assert.equal((await stat(join(directory, filename))).mode & 0o777, 0o600);
    assert.ok(!(await readFile(join(directory, filename), "utf8")).includes("token"));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
