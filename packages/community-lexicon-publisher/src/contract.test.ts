import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";
import {
  ACCEPTANCE_CONTRACT,
  DNS_NAME,
  LEXICON_IDS,
  MANIFEST_CONTRACT,
  NAMESPACE_AUTHORITY,
  createManifest,
  loadPackagedDocuments,
  manifestDigest,
  parseAcceptance,
  parseManifest,
  parsePackagedDocuments,
  stable,
} from "./contract.js";

const AUTHORITY_DID = "did:plc:aaaaaaaaaaaaaaaaaaaaaaaa";

test("packages exactly the eight community-model schemas at frozen canonical digests", async () => {
  const documents = await loadPackagedDocuments();
  assert.deepEqual(documents.map((document) => document.id), [...LEXICON_IDS]);

  const modelDirectory = new URL(
    "../../community-model/src/community_model/schemas/",
    import.meta.url,
  );
  const modelDocuments = [];
  for (const name of (await readdir(modelDirectory)).filter((item) => item.endsWith(".json"))) {
    modelDocuments.push(JSON.parse(await readFile(new URL(name, modelDirectory), "utf8")) as unknown);
  }
  const model = parsePackagedDocuments(modelDocuments);
  assert.deepEqual(model.map(stable), documents.map(stable));
});

test("manifest binds documents, canonical digests, authority, URIs, and DNS", async () => {
  const documents = await loadPackagedDocuments();
  const manifest = createManifest(AUTHORITY_DID, documents);
  assert.equal(manifest.contract, MANIFEST_CONTRACT);
  assert.equal(manifest.namespaceAuthority, NAMESPACE_AUTHORITY);
  assert.equal(manifest.dnsName, DNS_NAME);
  assert.equal(manifest.dnsTxt, `did=${AUTHORITY_DID}`);
  assert.equal(manifest.documents.length, 8);
  assert.ok(manifest.documents.every((item) => item.nsid === item.rkey));
  assert.ok(manifest.documents.every((item) => item.documentSha256.startsWith("sha256:")));
  assert.ok(manifest.documents.every((item) => item.recordSha256.startsWith("sha256:")));
  assert.ok(manifest.documents.every((item) => item.uri.startsWith(`at://${AUTHORITY_DID}/`)));
  assert.match(manifestDigest(manifest), /^sha256:[a-f0-9]{64}$/u);
  assert.deepEqual(parseManifest(JSON.parse(stable(manifest)), documents), manifest);
});

test("manifest rejects drift, missing schemas, duplicate schemas, and authority substitution", async () => {
  const documents = await loadPackagedDocuments();
  await assert.rejects(
    async () => parsePackagedDocuments(documents.slice(1)),
    /exactly eight/u,
  );
  await assert.rejects(
    async () => parsePackagedDocuments([...documents.slice(0, -1), documents[0]]),
    /duplicate/u,
  );
  await assert.rejects(
    async () => parsePackagedDocuments([{ ...documents[0], defs: {} }, ...documents.slice(1)]),
    /digest/u,
  );
  const manifest = createManifest(AUTHORITY_DID, documents);
  await assert.rejects(
    async () => parseManifest({ ...manifest, authorityDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb" }, documents),
    /differs/u,
  );
});

test("human acceptance must bind the exact manifest and authority", async () => {
  const manifest = createManifest(AUTHORITY_DID, await loadPackagedDocuments());
  const acceptance = {
    contract: ACCEPTANCE_CONTRACT,
    manifestSha256: manifestDigest(manifest),
    authorityDid: AUTHORITY_DID,
    acceptedBy: "maintainer@example.invalid",
    acceptedAt: "2026-09-08T12:00:00Z",
  };
  assert.deepEqual(parseAcceptance(acceptance, manifest), acceptance);
  assert.throws(
    () => parseAcceptance({ ...acceptance, manifestSha256: `sha256:${"0".repeat(64)}` }, manifest),
    /does not bind/u,
  );
  assert.throws(
    () => parseAcceptance({ ...acceptance, extra: true }, manifest),
    /fields/u,
  );
});

test("superseded namespace and acceptance cannot authorize product-owned publication", async () => {
  const documents = await loadPackagedDocuments();
  assert.throws(
    () => parsePackagedDocuments(documents.map((doc) => ({
      ...doc, id: doc.id.replace("app.phlogiston.community", "zone.neutral.community"),
    }))),
    /envelope/u,
  );
  const manifest = createManifest(AUTHORITY_DID, documents);
  assert.throws(
    () => parseManifest({ ...manifest, namespaceAuthority: "community.neutral.zone",
      dnsName: "_lexicon.community.neutral.zone" }, documents),
    /differs/u,
  );
  assert.throws(
    () => parseAcceptance({ contract: ACCEPTANCE_CONTRACT,
      manifestSha256: `sha256:${"0".repeat(64)}`, authorityDid: AUTHORITY_DID,
      acceptedBy: "campaign-owner:jbeck", acceptedAt: "2026-10-03T18:00:00Z" }, manifest),
    /does not bind/u,
  );
});
