import assert from "node:assert/strict";
import test from "node:test";

import { loadConfig } from "./config.js";
import { OAUTH_SCOPE, clientMetadata } from "./oauth.js";
import { CURATION_QUIET_SCOPE } from "./p0.js";

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
    assert.equal(metadata.scope, CURATION_QUIET_SCOPE);
    assert.equal(String(metadata.scope).split(" ").length, 11);
  }
});
