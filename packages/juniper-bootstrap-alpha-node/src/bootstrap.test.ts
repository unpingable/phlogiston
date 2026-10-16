import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";
import type { LexMap } from "@atproto/lex-data";
import {
  AUTHORITY_DID,
  LEXICON_COLLECTION,
  LEXICON_IDS,
  NAMESPACE_AUTHORITY,
  SPACE_TYPE,
  SPACE_URI,
  createExactPublicSpace,
  nsidAuthority,
  publishExactLexicons,
  type LexiconRepository,
  type SpaceBootstrapClient,
} from "./bootstrap.js";

const CID = "bafyreicl6ujc6ncfktctxxroxognfn7d2fqavvrryoc2lv6m4i6hpbkfti";

async function documents(): Promise<LexMap[]> {
  const directory = new URL(
    "../../community-space-wire/src/community_space_wire/lexicons/",
    import.meta.url,
  );
  const result: LexMap[] = [];
  for (const name of (await readdir(directory)).filter((item) => item.endsWith(".json")).sort()) {
    result.push(JSON.parse(await readFile(new URL(name, directory), "utf8")) as LexMap);
  }
  return result;
}

test("publishes exact frozen Lexicons in declared order", async () => {
  const calls: string[] = [];
  const repository: LexiconRepository = {
    create: async ({ rkey }) => {
      calls.push(rkey);
      return { uri: `at://${AUTHORITY_DID}/${LEXICON_COLLECTION}/${rkey}`, cid: CID };
    },
    get: async () => { throw new Error("unused"); },
  };
  const result = await publishExactLexicons(repository, await documents());
  assert.deepEqual(calls, [...LEXICON_IDS]);
  assert.equal(result.length, 7);
  assert.ok(result.every((item) => item.created && item.documentSha256.startsWith("sha256:")));
  assert.ok(LEXICON_IDS.every((nsid) => nsidAuthority(nsid) === NAMESPACE_AUTHORITY));
});

test("ambiguous creates use exact readback once without a hidden retry", async () => {
  let creates = 0;
  const docs = await documents();
  const records = new Map<string, LexMap>(docs.map((document) => [String(document.id), { $type: LEXICON_COLLECTION, ...document }]));
  const repository: LexiconRepository = {
    create: async () => { creates += 1; throw new Error("lost response"); },
    get: async ({ rkey }) => ({ uri: `at://${AUTHORITY_DID}/${LEXICON_COLLECTION}/${rkey}`, cid: CID, value: records.get(rkey)! }),
  };
  const result = await publishExactLexicons(repository, docs);
  assert.equal(creates, 7);
  assert.ok(result.every((item) => !item.created));

  records.set(LEXICON_IDS[0]!, { ...records.get(LEXICON_IDS[0]!)!, defs: {} });
  await assert.rejects(publishExactLexicons(repository, docs), /differs/);
});

test("mutated, missing, duplicate, and substituted Lexicons refuse", async () => {
  const docs = await documents();
  await assert.rejects(publishExactLexicons({
    create: async ({ rkey }) => ({ uri: `at://did:plc:evil/${rkey}`, cid: CID }),
    get: async () => { throw new Error("missing"); },
  }, docs), /substituted/);
  await assert.rejects(publishExactLexicons({} as LexiconRepository, docs.slice(1)), /seven/);
  await assert.rejects(publishExactLexicons({} as LexiconRepository, [...docs.slice(0, -1), docs[0]!]), /duplicate/);
  await assert.rejects(publishExactLexicons({} as LexiconRepository, [{ ...docs[0]!, defs: {} }, ...docs.slice(1)]), /digest/);
});

test("creates exact public/open Space", async () => {
  let input: unknown;
  const client: SpaceBootstrapClient = {
    create: async (value) => { input = value; return { uri: SPACE_URI }; },
    get: async () => { throw new Error("unused"); },
  };
  const receipt = await createExactPublicSpace(client);
  assert.equal(receipt.created, true);
  assert.deepEqual(input, {
    type: SPACE_TYPE,
    skey: "self",
    policy: { $type: "com.atproto.simplespace.defs#publicPolicy" },
    appAccess: { $type: "com.atproto.simplespace.defs#open" },
  });
  assert.ok(receipt.explicitNonClaims.includes("governance_authority"));
});

test("substituted or conflicting Space refuses", async () => {
  await assert.rejects(createExactPublicSpace({
    create: async () => ({ uri: "at://did:plc:evil/space/type/self" }),
    get: async () => { throw new Error("missing"); },
  }), /substituted/);
  await assert.rejects(createExactPublicSpace({
    create: async () => { throw new Error("exists"); },
    get: async () => ({ uri: SPACE_URI, policy: { $type: "com.atproto.simplespace.defs#memberListPolicy" }, appAccess: { $type: "com.atproto.simplespace.defs#open" } }),
  }), /differs/);
});
