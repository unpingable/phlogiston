import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { readProjectionBundle } from "./feed.js";

const DIGEST = `sha256:${"a".repeat(64)}`;

test("ordinary and audit publication channels retain one occurrence", async () => {
  const root = await mkdtemp(join(tmpdir(), "juniper-feed-"));
  await write(root, "ordinary_reader", null);
  await write(root, "technical_audit", {
    sourceQualificationReceiptId: DIGEST,
    admissionId: DIGEST,
    removalId: null,
  });
  const bundle = await readProjectionBundle(root);
  assert.equal(bundle.ordinary?.entries[0]?.lifecycleState, "added");
  assert.equal(bundle.audit?.entries[0]?.technicalReceipts?.admissionId, DIGEST);
  assert.notEqual(bundle.ordinary?.artifactId, bundle.audit?.artifactId);
});

test("artifact mutation and secret-shaped publication refuse", async () => {
  const root = await mkdtemp(join(tmpdir(), "juniper-feed-hostile-"));
  await write(root, "ordinary_reader", null);
  const path = join(root, "ordinary.json");
  const value = JSON.parse(await import("node:fs/promises").then(({ readFile }) => readFile(path, "utf8")));
  value.artifact.entries[0].presentation.title = "mutated";
  await writeFile(path, JSON.stringify(value));
  await assert.rejects(readProjectionBundle(root), /identity mismatch/);

  value.artifact.entries[0].presentation.title = "Authorization: Bearer synthetic";
  await writeFile(path, JSON.stringify(value));
  await assert.rejects(readProjectionBundle(root), /secret-shaped/);
});

test("atomic current pointer selects one immutable generation and cannot escape", async () => {
  const root = await mkdtemp(join(tmpdir(), "juniper-generation-"));
  const generation = "b".repeat(64);
  const target = join(root, "generations", generation);
  await mkdir(target, { recursive: true });
  await write(target, "ordinary_reader", null);
  await write(target, "technical_audit", { admissionId: DIGEST });
  await symlink(join("generations", generation), join(root, "current"));
  const bundle = await readProjectionBundle(root);
  assert.equal(bundle.ordinary?.entries[0]?.lifecycleState, "added");

  const hostile = await mkdtemp(join(tmpdir(), "juniper-generation-hostile-"));
  await mkdir(join(hostile, "generations"));
  await symlink(target, join(hostile, "current"));
  await assert.rejects(
    readProjectionBundle(hostile),
    /escapes immutable generations/,
  );
});

async function write(
  directory: string,
  mode: "ordinary_reader" | "technical_audit",
  receipts: Record<string, string | null> | null,
): Promise<void> {
  const artifact = {
    compilerVersion: "scv0-projection-artifact-compiler/1",
    communityIdentityId: DIGEST,
    communityActorDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb",
    spaceIdentityId: DIGEST,
    projectionVersion: "scv0-projection-lifecycle-reducer/1",
    disclosureMode: mode,
    disclosurePolicyId: DIGEST,
    disclosurePolicyReferenceId: DIGEST,
    publicationReferenceId: DIGEST,
    entries: [{
      projectionIdentity: DIGEST,
      projectionStateId: DIGEST,
      lifecycleState: "added",
      communityIdentityId: DIGEST,
      postReferenceId: DIGEST,
      sourceUri: "at://did:plc:authority/type/self/did:plc:author/collection/post",
      admittedSourceCid: "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti",
      authorDid: "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa",
      admissionId: DIGEST,
      admittedAt: "2026-08-24T12:00:00Z",
      sourceObservationId: DIGEST,
      sourceRelationship: "exact",
      presentation: {
        profile: "scv0-test-presentation/1",
        sourceReferenceId: DIGEST,
        sourceUri: "at://did:plc:authority/type/self/did:plc:author/collection/post",
        sourceCid: "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti",
        title: "The useful object",
        body: "Feed content first.",
        authorDisplayReference: "@alex.invalid.test",
      },
      technicalReceipts: receipts,
      availableLifecycleLinks: mode === "technical_audit" ? [DIGEST] : [],
      removalId: null,
      explicitNonClaims: ["reader_authorization"],
    }],
    explicitNonClaims: ["reader_authorization"],
  };
  const artifactId = digest(stable(artifact));
  const feed = {
    feedVersion: "scv0-public-projection-feed/1",
    artifactId,
    artifactBytesSha256: artifactId,
    communityIdentityId: DIGEST,
    publicationReferenceId: DIGEST,
    channel: mode,
    disclosureMode: mode,
    publishedAt: "2026-08-24T12:00:00Z",
    artifact,
    verifiedClaims: ["exact_artifact_embedded"],
    explicitNonClaims: ["reader_authorization"],
  };
  await writeFile(join(directory, mode === "ordinary_reader" ? "ordinary.json" : "audit.json"), stable(feed));
}

function stable(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${stable(record[key])}`).join(",")}}`;
}

function digest(value: string): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}
