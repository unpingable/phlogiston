import assert from "node:assert/strict";
import test from "node:test";
import { ADMISSION, performWrite, type AuthorityClient, type WriteRequest } from "./write.js";

const CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti";
const request: WriteRequest = {
  space: "at://did:plc:authority/space/type/self",
  actorDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb",
  collection: ADMISSION,
  rkey: "a".repeat(64),
  record: {
    $type: ADMISSION,
    submission: { uri: "at://submission", cid: CID },
    subject: { uri: "at://post", cid: CID },
    authorizationOccurrence: `sha256:${"a".repeat(64)}`,
    sourceObservationReceipt: `sha256:${"b".repeat(64)}`,
    createdAt: "2026-08-24T12:00:00Z",
  },
};
const uri = `${request.space}/${request.actorDid}/${request.collection}/${request.rkey}`;

test("authority transport performs one exact create", async () => {
  let creates = 0;
  const client: AuthorityClient = {
    create: async () => { creates += 1; return { uri, cid: CID }; },
    get: async () => { throw new Error("not used"); },
  };
  assert.deepEqual(await performWrite(client, request), { uri, cid: CID, created: true });
  assert.equal(creates, 1);
});

test("ambiguous write uses exact readback without retry", async () => {
  let creates = 0;
  const client: AuthorityClient = {
    create: async () => { creates += 1; throw new Error("lost response"); },
    get: async () => ({ uri, cid: CID, value: request.record }),
  };
  assert.deepEqual(await performWrite(client, request), { uri, cid: CID, created: false });
  assert.equal(creates, 1);
});

test("collection substitution and conflicting readback refuse", async () => {
  const client: AuthorityClient = {
    create: async () => { throw new Error("lost response"); },
    get: async () => ({ uri, cid: CID, value: { ...request.record, createdAt: "other" } }),
  };
  await assert.rejects(performWrite(client, { ...request, collection: "evil.invalid.authority" }), /cannot write/);
  await assert.rejects(performWrite(client, request), /conflicting/);
});
