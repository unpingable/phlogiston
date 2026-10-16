import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { loadConfig } from "./config.js";
import { createHandler, type Dependencies } from "./server.js";
import { WebSessionStore } from "./storage.js";

const DID = "did:plc:displayfixture";
const PUBLIC_URL = "http://127.0.0.1:3210";

async function harness() {
  const directory = await mkdtemp(join(tmpdir(), "phlo-display-route-"));
  const config = loadConfig({
    COMMUNITY_PROFILE: "p0", COMMUNITY_READER_ENABLED: "true",
    COMMUNITY_PUBLIC_URL: PUBLIC_URL, COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "The Cabinet", COMMUNITY_PURPOSE: "Fixture collection",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator", COMMUNITY_RUNTIME_DIR: directory,
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080", COMMUNITY_AUTHORITY_SOCKET: join(directory, "socket"),
    COMMUNITY_SITE_PAUSE_PATH: join(directory, "site"), COMMUNITY_ADMISSION_PAUSE_PATH: join(directory, "admission"),
  });
  const webSessions = new WebSessionStore(join(directory, "sessions"));
  const signed = await webSessions.issue(DID, new Date());
  const deps = {config, webSessions} as Dependencies;
  const server = createServer(createHandler(deps));
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const get = (path: string, cookie?: string) => fetch(origin + path, {
    redirect: "manual", ...(cookie ? {headers: {Cookie: cookie}} : {}),
  });
  const post = (fields: Record<string, string>, cookie?: string, requestOrigin = PUBLIC_URL) => fetch(origin + "/display", {
    method: "POST", redirect: "manual",
    headers: {Origin: requestOrigin, "Content-Type": "application/x-www-form-urlencoded", ...(cookie ? {Cookie: cookie} : {})},
    body: new URLSearchParams(fields),
  });
  return {webSessions, signed, get, post, origin, close: async () => {
    await new Promise<void>(resolve => server.close(() => resolve()));
    await rm(directory, {recursive: true, force: true});
  }};
}

test("simultaneous display requests retain their own themes and private cache headers", async () => {
  const h = await harness();
  const original = h.webSessions.resolve.bind(h.webSessions);
  let arrivals = 0;
  let release!: () => void;
  const held = new Promise<void>(resolve => {release = resolve;});
  h.webSessions.resolve = async token => {
    if (++arrivals === 2) release();
    await held;
    return original(token);
  };
  try {
    const [light, dark] = await Promise.all([
      h.get("/display", "phlogiston_display=light"),
      h.get("/display", "phlogiston_display=dark"),
    ]);
    assert.equal(light.status, 200); assert.equal(dark.status, 200);
    assert.match(await light.text(), /<html lang="en" data-theme="light">/);
    assert.match(await dark.text(), /<html lang="en" data-theme="dark">/);
    for (const response of [light, dark]) {
      assert.equal(response.headers.get("vary"), "Cookie");
      assert.equal(response.headers.get("cache-control"), "private, no-cache");
    }
    const signed = await h.get("/display", `community_session=${h.signed.token}; phlogiston_display=light`);
    assert.equal(signed.headers.get("cache-control"), "no-store");
    assert.match(await signed.text(), /data-theme="light"/);
  } finally { release(); await h.close(); }
});

test("display POST enforces origin and signed CSRF, and refuses external return paths", async () => {
  const h = await harness();
  try {
    const missing = await fetch(h.origin + "/display", {method: "POST", body: new URLSearchParams({display: "dark"}), redirect: "manual"});
    assert.equal(missing.status, 403); assert.equal(missing.headers.get("set-cookie"), null);
    const wrong = await h.post({display: "dark"}, undefined, "https://elsewhere.example");
    assert.equal(wrong.status, 403); assert.equal(wrong.headers.get("set-cookie"), null);
    const invalid = await h.post({display: "sepia"});
    assert.equal(invalid.status, 400); assert.equal(invalid.headers.get("set-cookie"), null);
    const cookie = `community_session=${h.signed.token}`;
    const noCsrf = await h.post({display: "dark"}, cookie);
    assert.equal(noCsrf.status, 400); assert.equal(noCsrf.headers.get("set-cookie"), null);
    const wrongCsrf = await h.post({display: "dark", csrf: "wrong"}, cookie);
    assert.equal(wrongCsrf.status, 403); assert.equal(wrongCsrf.headers.get("set-cookie"), null);
    const escaped = await h.post({display: "dark", csrf: h.signed.csrf, return: "https://elsewhere.example/"}, cookie);
    assert.equal(escaped.status, 303); assert.equal(escaped.headers.get("location"), "/display");
    assert.match(escaped.headers.get("set-cookie") ?? "", /^phlogiston_display=dark; Path=\/; HttpOnly; SameSite=Lax; Max-Age=31536000$/);
    const settings = await h.post({display: "light", csrf: h.signed.csrf, return: "/settings"}, cookie);
    assert.equal(settings.status, 303); assert.equal(settings.headers.get("location"), "/settings");
  } finally { await h.close(); }
});

test("display choice remains browser-local after sign-out", async () => {
  const h = await harness();
  try {
    const chosen = await h.post({display: "dark"});
    assert.equal(chosen.status, 303);
    const displayCookie = (chosen.headers.get("set-cookie") ?? "").split(";", 1)[0]!;
    const signed = await h.get("/display", `community_session=${h.signed.token}; ${displayCookie}`);
    assert.match(await signed.text(), /data-theme="dark"/);
    const out = await fetch(h.origin + "/signout", {
      method: "POST", redirect: "manual",
      headers: {Origin: PUBLIC_URL, Cookie: `community_session=${h.signed.token}; ${displayCookie}`, "Content-Type": "application/x-www-form-urlencoded"},
      body: new URLSearchParams({csrf: h.signed.csrf}),
    });
    assert.equal(out.status, 303);
    assert.match(out.headers.get("set-cookie") ?? "", /^community_session=; /);
    assert.doesNotMatch(out.headers.get("set-cookie") ?? "", /phlogiston_display/);
    const anonymous = await h.get("/display", displayCookie);
    assert.equal(anonymous.status, 200);
    assert.match(await anonymous.text(), /data-theme="dark"/);
  } finally { await h.close(); }
});
