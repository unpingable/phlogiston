import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { LEXICON_SCOPE } from "./contract.js";
import { main } from "./worker.js";

const ENV = {
  PCV0_LEXICON_RUNTIME_DIR: "/tmp/pcv0-lexicon-publisher-test-runtime",
  PCV0_LEXICON_CALLBACK_ORIGIN: "http://127.0.0.1:8765",
  PCV0_LEXICON_AUTHORITY_DID: "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
};

test("OAuth grant is create-only for the Lexicon collection", () => {
  assert.equal(LEXICON_SCOPE, "atproto repo:com.atproto.lexicon.schema?action=create");
  assert.ok(!LEXICON_SCOPE.includes("app.phlogiston.community"));
  assert.ok(!LEXICON_SCOPE.includes("action=update"));
  assert.ok(!LEXICON_SCOPE.includes("action=delete"));
});

test("manifest command writes a complete frozen review artifact", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pcv0-lexicon-manifest-"));
  const output = join(directory, "manifest.json");
  let stdout = "";
  const oldOut = process.stdout.write;
  process.stdout.write = ((chunk: string | Uint8Array) => {
    stdout += String(chunk);
    return true;
  }) as typeof process.stdout.write;
  try {
    assert.equal(await main(["manifest", output], ENV), 0);
  } finally {
    process.stdout.write = oldOut;
  }
  try {
    const manifest = JSON.parse(await readFile(output, "utf8")) as Record<string, unknown>;
    assert.equal(manifest.authorityDid, ENV.PCV0_LEXICON_AUTHORITY_DID);
    assert.equal((manifest.documents as unknown[]).length, 8);
    assert.ok(stdout.includes('"documents":8'));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("manual callback commands are unavailable and never echo callback parameters", async () => {
  let stdout = "";
  let stderr = "";
  const oldOut = process.stdout.write;
  const oldErr = process.stderr.write;
  process.stdout.write = ((chunk: string | Uint8Array) => {
    stdout += String(chunk);
    return true;
  }) as typeof process.stdout.write;
  process.stderr.write = ((chunk: string | Uint8Array) => {
    stderr += String(chunk);
    return true;
  }) as typeof process.stderr.write;
  try {
    assert.equal(
      await main(["auth-callback", "https://wrong.invalid/?code=synthetic-secret"], ENV),
      1,
    );
    assert.equal(await main(["auth-start", "secret.invalid"], ENV), 1);
  } finally {
    process.stdout.write = oldOut;
    process.stderr.write = oldErr;
  }
  assert.equal(stdout, "");
  assert.equal(
    stderr,
    '{"error":"pcv0_lexicon_publication_refused"}\n'.repeat(2),
  );
  assert.ok(!stderr.includes("synthetic-secret"));
  assert.ok(!stderr.includes("wrong.invalid"));
});
