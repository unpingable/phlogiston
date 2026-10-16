import { l } from "@atproto/lex-schema";

const params = l.params();
export const createSpace = l.procedure(
  "com.atproto.simplespace.createSpace",
  params,
  l.jsonPayload({
    type: l.string({ format: "nsid" }),
    skey: l.optional(l.string({ format: "record-key" })),
    policy: l.lexMap(),
    appAccess: l.lexMap(),
  }),
  l.jsonPayload({ uri: l.string({ format: "space-ref" }) }),
  ["SpaceAlreadyExists", "UnsupportedPolicy", "UnsupportedAppAccess"],
);
export const getSpace = l.query(
  "com.atproto.simplespace.getSpace",
  l.params({ space: l.string({ format: "space-ref" }) }),
  l.jsonPayload({ uri: l.string({ format: "space-ref" }), policy: l.lexMap(), appAccess: l.lexMap() }),
  ["SpaceNotFound"],
);
