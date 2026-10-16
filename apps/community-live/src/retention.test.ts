import assert from "node:assert/strict";
import { mkdir, mkdtemp, readdir, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type { ContributionPlan } from "./contributions.js";
import { DAY_MS, HOUR_MS, retentionSweep } from "./retention.js";
import { ContributionPlanStore, SecretJsonFileStore, WebSessionStore } from "./storage.js";

const ALICE = "did:plc:alice";
const BOB = "did:plc:bob";

async function age(directory: string, ms: number, now: number): Promise<void> {
  for (const name of await readdir(directory)) await utimes(join(directory, name), (now - ms) / 1000, (now - ms) / 1000);
}

test("the sweep enforces the published retention and revokes only tokens no browser can use", async () => {
  const root = await mkdtemp(join(tmpdir(), "phlo-retention-"));
  const now = Date.now();
  const webSessions = new WebSessionStore(join(root, "web-sessions"));
  const plans = new ContributionPlanStore(join(root, "contribution-plans"));
  await webSessions.issue(ALICE, new Date(now));
  await webSessions.issue(BOB, new Date(now - 9 * HOUR_MS));
  const state = new SecretJsonFileStore<unknown>(join(root, "oauth", "state"));
  await state.set("abandoned", { iss: "x" });
  await age(join(root, "oauth", "state"), 2 * HOUR_MS, now);
  await state.set("in-flight", { iss: "x" });
  const tokens = new SecretJsonFileStore<unknown>(join(root, "oauth", "session"));
  await tokens.set(ALICE, { tokenSet: { sub: ALICE } });
  await tokens.set(BOB, { tokenSet: { sub: BOB } });
  await age(join(root, "oauth", "session"), 9 * HOUR_MS, now);
  await plans.save({ operationId: "old", authorDid: ALICE, createdAt: new Date(now - 31 * DAY_MS).toISOString() } as ContributionPlan);
  await plans.save({ operationId: "new", authorDid: ALICE, createdAt: new Date(now - DAY_MS).toISOString() } as ContributionPlan);
  await mkdir(join(root, "operations"));
  await writeFile(join(root, "operations", "old.json"), "{}");
  await age(join(root, "operations"), 31 * DAY_MS, now);
  await writeFile(join(root, "operations", "new.json"), "{}");

  const revoked: string[] = [];
  const result = await retentionSweep(root, { webSessions, plans }, async (did) => { revoked.push(did); }, now);

  assert.deepEqual(result, { sessions: 1, signIns: 1, tokens: 1, drafts: 1, journals: 1 });
  assert.deepEqual(revoked, [BOB], "Bob's browser session expired, so his provider tokens are revoked; Alice is still signed in");
  assert.equal((await readdir(join(root, "oauth", "state"))).length, 1);
  assert.deepEqual((await plans.byAuthor(ALICE)).map((plan) => plan.operationId), ["new"]);
  assert.deepEqual(await readdir(join(root, "operations")), ["new.json"]);
});

test("the sweep is harmless on an empty runtime directory", async () => {
  const root = await mkdtemp(join(tmpdir(), "phlo-retention-empty-"));
  const result = await retentionSweep(root, { webSessions: new WebSessionStore(join(root, "web-sessions")), plans: new ContributionPlanStore(join(root, "contribution-plans")) }, async () => undefined);
  assert.deepEqual(result, { sessions: 0, signIns: 0, tokens: 0, drafts: 0, journals: 0 });
});
