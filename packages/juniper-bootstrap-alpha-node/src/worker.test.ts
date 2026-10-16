import assert from "node:assert/strict";
import test from "node:test";
import { AUTHORITY_DID, SPACE_TYPE } from "./bootstrap.js";
import { OAuthCallbackError } from "@atproto/oauth-client-node";
import { LEXICON_SCOPE, SPACE_SCOPE, main, safeErrorClassification } from "./worker.js";

test("bootstrap OAuth profiles are narrow and independent", () => {
  assert.equal(
    LEXICON_SCOPE,
    "atproto repo:com.atproto.lexicon.schema?action=create",
  );
  assert.equal(
    SPACE_SCOPE,
    `atproto space:${SPACE_TYPE}?authority=${AUTHORITY_DID}&skey=self&manage=create`,
  );
  assert.ok(!LEXICON_SCOPE.includes("space:"));
  assert.ok(!SPACE_SCOPE.includes("repo:"));
});

test("invalid bootstrap configuration fails closed without echoing input", async () => {
  let stdout = "";
  let stderr = "";
  const oldOut = process.stdout.write;
  const oldErr = process.stderr.write;
  process.stdout.write = ((chunk: string | Uint8Array) => { stdout += String(chunk); return true; }) as typeof process.stdout.write;
  process.stderr.write = ((chunk: string | Uint8Array) => { stderr += String(chunk); return true; }) as typeof process.stderr.write;
  try {
    assert.equal(await main(["auth-start", "lexicons", "secret.invalid"], {}), 1);
  } finally {
    process.stdout.write = oldOut;
    process.stderr.write = oldErr;
  }
  assert.equal(stdout, "");
  assert.equal(stderr, '{"error":"juniper_bootstrap_refused"}\n');
  assert.ok(!stderr.includes("secret.invalid"));
});

test("safe OAuth classification never emits callback parameters or error prose", async () => {
  let stderr = "";
  const oldErr = process.stderr.write;
  process.stderr.write = ((chunk: string | Uint8Array) => { stderr += String(chunk); return true; }) as typeof process.stderr.write;
  try {
    assert.equal(await main(["auth-callback", "lexicons", "https://wrong.invalid/?code=synthetic-secret"], {
      JUNIPER_BOOTSTRAP_RUNTIME_DIR: "/tmp/juniper-bootstrap-test",
      JUNIPER_BOOTSTRAP_CALLBACK_ORIGIN: "http://127.0.0.1:8765",
      JUNIPER_BOOTSTRAP_LEXICON_DIR: "/tmp",
    }), 1);
  } finally {
    process.stderr.write = oldErr;
  }
  assert.equal(stderr, '{"error":"juniper_bootstrap_refused"}\n');
  assert.ok(!stderr.includes("synthetic-secret"));
  assert.ok(!stderr.includes("wrong.invalid"));
});

test("safe OAuth classification exposes phase and allowlisted error only", () => {
  const code = new URLSearchParams({ code: "synthetic-secret-code", state: "synthetic-secret-state" });
  assert.deepEqual(safeErrorClassification(new OAuthCallbackError(code, "secret prose")), [
    { kind: "oauth_callback_error", phase: "code_received", issuerParameter: "absent" },
  ]);
  const refusal = new URLSearchParams({ error: "invalid_scope", error_description: "secret prose", state: "synthetic-secret-state" });
  const evidence = safeErrorClassification(new OAuthCallbackError(refusal));
  assert.deepEqual(evidence, [{ kind: "oauth_callback_error", phase: "authorization_error", issuerParameter: "absent", oauthError: "invalid_scope" }]);
  const serialized = JSON.stringify(evidence);
  assert.ok(!serialized.includes("secret prose"));
  assert.ok(!serialized.includes("synthetic-secret-state"));
});

test("safe OAuth classification exposes resolver class without its message", () => {
  const cause = new Error("synthetic private resolver detail");
  cause.name = "OAuthResolverError";
  const error = new OAuthCallbackError(
    new URLSearchParams("code=synthetic-secret&state=synthetic-secret&iss=https://issuer.invalid"),
    "synthetic private callback detail",
    undefined,
    cause,
  );
  const classification = safeErrorClassification(error);
  assert.deepEqual(classification, [
    { kind: "oauth_callback_error", phase: "code_received", issuerParameter: "present" },
    { kind: "oauth_identity_resolution_error" },
  ]);
  assert.ok(!JSON.stringify(classification).includes("synthetic"));
});
