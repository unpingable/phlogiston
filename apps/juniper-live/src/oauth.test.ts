import assert from "node:assert/strict";
import test from "node:test";
import { type AppConfig } from "./config.js";
import { OAUTH_SCOPE } from "./constants.js";
import { clientMetadata } from "./oauth.js";

const base: AppConfig = {
  publicUrl: "https://juniper.invalid.test",
  spaceUri: "at://did:plc:authority/type/self",
  communityActorDid: "did:plc:bbbbbbbbbbbbbbbbbbbbbbbb",
  runtimeDirectory: "/tmp/juniper-runtime",
  projectionDirectory: "/tmp/juniper-projection",
  port: 3210,
};

test("hosted metadata requests only the pinned alpha scope", () => {
  const metadata = clientMetadata(base);
  assert.equal(metadata.scope, OAUTH_SCOPE);
  assert.equal(metadata.dpop_bound_access_tokens, true);
  assert.deepEqual(metadata.redirect_uris, [
    "https://juniper.invalid.test/oauth/callback",
  ]);
  assert.equal(JSON.stringify(metadata).includes("token"), true);
  assert.equal(JSON.stringify(metadata).includes("secret"), false);
});

test("loopback metadata is explicit development behavior", () => {
  const metadata = clientMetadata({ ...base, publicUrl: "http://127.0.0.1:3210" });
  assert.equal(metadata.scope, OAUTH_SCOPE);
  assert.deepEqual(metadata.redirect_uris, ["http://127.0.0.1:3210/oauth/callback"]);
});
