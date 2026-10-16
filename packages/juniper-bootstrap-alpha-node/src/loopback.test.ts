import assert from "node:assert/strict";
import test from "node:test";
import { startLoopbackCallbackServer } from "./loopback.js";

test("one-shot loopback callback consumes the exact path without disclosing its query", async () => {
  let observed = "";
  const listener = await startLoopbackCallbackServer(
    new URL("http://127.0.0.1:0/lexicons-callback"),
    async (callback) => { observed = callback.searchParams.get("code") ?? ""; },
    5_000,
  );
  const callback = new URL(listener.callbackUrl);
  callback.searchParams.set("code", "synthetic-secret-code");
  const response = await fetch(callback);
  assert.equal(response.status, 200);
  const body = await response.text();
  assert.equal(body, "Juniper bootstrap authorization completed. You may close this tab.\n");
  await listener.completion;
  assert.equal(observed, "synthetic-secret-code");
  assert.ok(!body.includes("synthetic-secret-code"));
});

test("loopback callback refuses a substituted path", async () => {
  let called = false;
  const listener = await startLoopbackCallbackServer(
    new URL("http://127.0.0.1:0/space-callback"),
    async () => { called = true; },
    5_000,
  );
  const substituted = new URL("/other-callback", listener.callbackUrl);
  const response = await fetch(substituted);
  assert.equal(response.status, 404);
  assert.equal(called, false);
  await listener.close();
});

test("loopback callback does not mislabel every OAuth failure as refusal", async () => {
  const listener = await startLoopbackCallbackServer(
    new URL("http://127.0.0.1:0/lexicons-callback"),
    async () => { throw new Error("This request has expired"); },
    5_000,
  );
  const completion = listener.completion.catch((error: unknown) => error);
  const response = await fetch(listener.callbackUrl);
  assert.equal(response.status, 400);
  assert.equal(
    await response.text(),
    "Juniper bootstrap authorization did not complete. Check the terminal for the bounded reason, then close this tab.\n",
  );
  assert.match(String(await completion), /expired/);
});
