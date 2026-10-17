import assert from "node:assert/strict";
import test from "node:test";

import { loadConfig } from "./config.js";
import { OAUTH_SCOPE, clientMetadata, guardProviderSession } from "./oauth.js";
import { CURATION_QUIET_INTERACTION_SCOPE } from "./p0.js";

function config(publicUrl: string) {
  return loadConfig({
    COMMUNITY_PUBLIC_URL: publicUrl,
    COMMUNITY_DID: "did:plc:exampleparticipantabcdef",
    COMMUNITY_NAME: "Example Garden",
    COMMUNITY_PURPOSE: "Testing the consent page name",
    COMMUNITY_MODERATOR_DID: "did:plc:testmoderatoraccount",
    COMMUNITY_RUNTIME_DIR: "/var/lib/community-web",
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080",
    COMMUNITY_AUTHORITY_SOCKET: "/run/community-authority/communityd.sock",
    COMMUNITY_SNAPSHOT_SECRET: "test-secret",
  });
}

test("public client metadata shows the community's own name on the consent page", () => {
  const metadata = clientMetadata(config("https://community.phlogiston.app"));
  assert.equal(metadata.client_name, "Example Garden");
  assert.equal(metadata.client_id, "https://community.phlogiston.app/oauth-client-metadata.json");
  assert.equal(metadata.client_uri, "https://community.phlogiston.app");
  assert.deepEqual(metadata.redirect_uris, ["https://community.phlogiston.app/oauth/callback"]);
  assert.equal(metadata.scope, OAUTH_SCOPE);
  assert.equal(metadata.token_endpoint_auth_method, "none");
  assert.equal(metadata.dpop_bound_access_tokens, true);
});

test("loopback metadata keeps the atproto loopback client shape", () => {
  const metadata = clientMetadata(config("http://127.0.0.1:3210"));
  assert.equal(metadata.client_name, undefined);
  assert.match(String(metadata.client_id), /^http:\/\/localhost/);
  assert.deepEqual(metadata.redirect_uris, ["http://127.0.0.1:3210/oauth/callback"]);
  assert.equal(metadata.scope, OAUTH_SCOPE);
});

test("reader-enabled P0 metadata advertises the maximum grant under Phlogiston identity", () => {
  for (const publicUrl of ["https://phlogiston.app", "http://127.0.0.1:3210"]) {
    const base = config(publicUrl);
    const metadata = clientMetadata({
      ...base,
      profile: "p0",
      readerEnabled: true,
      sitePausePath: "/tmp/reader-site-control",
      admissionPausePath: "/tmp/reader-admission-control",
    });
    assert.equal(metadata.client_name, "Phlogiston");
    assert.equal(metadata.scope, CURATION_QUIET_INTERACTION_SCOPE);
    assert.equal(String(metadata.scope).split(" ").length, 14);
    assert.match(String(metadata.scope),/repo:app\.bsky\.feed\.post\?action=create&action=delete/);
  }
});


test("provider revocation failures are not swallowed by the SDK boundary",async()=>{
 const server={request:async()=>{throw new Error("revocation unavailable")},refresh:async()=>({scope:"atproto"})};
 guardProviderSession(server as never);
 await assert.rejects((server as unknown as {revoke:(token:string)=>Promise<void>}).revoke("disposable-test-token"),/revocation unavailable/);
});

test("provider refresh cannot introduce interaction authority without a consent callback",async()=>{
 const revoked:string[]=[];
 const server={request:async(_endpoint:string,body:{token:string})=>{revoked.push(body.token);},refresh:async()=>({scope:"atproto repo:app.bsky.feed.post?action=create&action=delete",refresh_token:"fixture-new-token"})};
 guardProviderSession(server as never);
 await assert.rejects((server.refresh as unknown as (previous:unknown)=>Promise<unknown>)({sub:"did:plc:fixture",scope:"atproto"}),/changed permissions during refresh/);
 assert.deepEqual(revoked,["fixture-new-token"]);
});
