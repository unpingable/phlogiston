import { l } from "@atproto/lex-schema";

const params = l.params();
const result = l.jsonPayload({
  uri: l.string({ format: "at-uri" }),
  cid: l.string({ format: "cid" }),
  validationStatus: l.optional(l.string()),
});

export const createSpaceRecord = l.procedure(
  "com.atproto.space.createRecord",
  params,
  l.jsonPayload({
    space: l.string({ format: "space-ref" }),
    repo: l.string({ format: "did" }),
    collection: l.string({ format: "nsid" }),
    rkey: l.optional(l.string({ format: "record-key", maxLength: 512 })),
    validate: l.optional(l.boolean()),
    record: l.lexMap(),
  }),
  result,
  ["SpaceNotFound", "RecordAlreadyExists"],
);

export const putSpaceRecord = l.procedure(
  "com.atproto.space.putRecord",
  params,
  l.jsonPayload({
    space: l.string({ format: "space-ref" }),
    repo: l.string({ format: "did" }),
    collection: l.string({ format: "nsid" }),
    rkey: l.string({ format: "record-key", maxLength: 512 }),
    validate: l.optional(l.boolean()),
    record: l.lexMap(),
  }),
  result,
  ["SpaceNotFound"],
);

export const deleteSpaceRecord = l.procedure(
  "com.atproto.space.deleteRecord",
  params,
  l.jsonPayload({
    space: l.string({ format: "space-ref" }),
    repo: l.string({ format: "did" }),
    collection: l.string({ format: "nsid" }),
    rkey: l.string({ format: "record-key", maxLength: 512 }),
  }),
  l.jsonPayload({}),
  ["SpaceNotFound"],
);
