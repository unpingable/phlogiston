import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { loadConfig } from "./config.js";
import { publicPage, sourceRevision, SOURCE_URL } from "./public-pages.js";
import { DAY_MS, HOUR_MS, RETENTION } from "./retention.js";
import { createHandler, type Dependencies } from "./server.js";
import { WebSessionStore } from "./storage.js";

async function app() {
  const directory = await mkdtemp(join(tmpdir(), "phlo-public-pages-"));
  const config = loadConfig({
    COMMUNITY_PROFILE: "p0", COMMUNITY_READER_ENABLED: "true",
    COMMUNITY_PUBLIC_URL: "https://phlogiston.example", COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "The Cabinet", COMMUNITY_PURPOSE: "Fixture collection",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator", COMMUNITY_RUNTIME_DIR: directory,
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080", COMMUNITY_AUTHORITY_SOCKET: join(directory, "socket"),
    COMMUNITY_SITE_PAUSE_PATH: join(directory, "site"), COMMUNITY_ADMISSION_PAUSE_PATH: join(directory, "admission"),
  });
  const deps = { config, webSessions: new WebSessionStore(join(directory, "sessions")) } as Dependencies;
  const server = createServer(createHandler(deps));
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return { origin, close: () => new Promise<void>((resolve) => server.close(() => resolve())) };
}

test("About, Privacy and Terms are readable signed out and linked from every page's footer", async () => {
  const h = await app();
  try {
    for (const [path, heading] of [["/about", "About Phlogiston"], ["/privacy", "Privacy"], ["/terms", "Terms and community rules"]] as const) {
      const response = await fetch(h.origin + path);
      assert.equal(response.status, 200, path);
      const body = await response.text();
      assert.match(body, new RegExp(`<h1>${heading}</h1>`));
      assert.match(body, /<footer class="site-footer">.*href="\/privacy".*href="\/terms"/s);
      assert.doesNotMatch(body, /<script/);
    }
    const signin = await (await fetch(h.origin + "/signin")).text();
    assert.match(signin, /href="\/about">What signing in allows/);
    assert.doesNotMatch(signin, /compatible ATProto/);
  } finally {
    await h.close();
  }
});

test("the pages name the running release's commit only when it is known", () => {
  const revision = "4a71a9648718d55ff2847d8c9ec434fd623c8baf";
  assert.equal(sourceRevision(`file:///opt/phlogiston-app/web-releases/${revision}/community-live/src/public-pages.ts`), revision);
  assert.equal(sourceRevision("file:///home/someone/checkout/apps/community-live/src/public-pages.ts"), undefined);
  assert.match(publicPage("/about", revision).body, new RegExp(`${SOURCE_URL}/tree/${revision}`));
  assert.match(publicPage("/about", undefined).body, /exact commit is not shown/);
});

test("the published retention matches what the sweep enforces", () => {
  assert.equal(RETENTION.idleTokensMs, 8 * HOUR_MS);
  assert.equal(RETENTION.abandonedSignInMs, HOUR_MS);
  assert.equal(RETENTION.draftsMs, 30 * DAY_MS);
  const privacy = publicPage("/privacy").body;
  assert.match(privacy, /8 hours after your last session ends/);
  assert.match(privacy, /<td>Unfinished sign-ins<\/td><td>Complete the sign-in<\/td><td>1 hour<\/td>/);
  assert.match(privacy, /<td>30 days, or until you use Delete my Phlogiston data<\/td>/);
  assert.match(privacy, /no backups/);
});

test("Terms and Privacy state the 18+ eligibility", () => {
  assert.match(publicPage("/terms").body, /You must be 18 or older to sign in\./);
  assert.match(publicPage("/privacy").body, /you must be 18 or older to sign in\./);
  assert.doesNotMatch(publicPage("/privacy").body, /under 16/);
});
