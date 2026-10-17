import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type { ContributionPlan } from "./contributions.js";
import { DAY_MS, HOUR_MS, retentionSweep } from "./retention.js";
import { ContributionPlanStore, SecretJsonFileStore, WebSessionStore } from "./storage.js";
import { DurableWriteJournal } from "./operations.js";
import { withInteractionLock } from "./interaction-lock.js";
import { P0Reservations } from "./p0.js";

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
  const journalPath=join(root,"interactions",`${encodeURIComponent(ALICE)}.json`);
  const journal=new DurableWriteJournal(journalPath);const address={repo:ALICE,collection:"app.bsky.feed.post",rkey:"one"};
  await journal.prepare(address,{$type:"app.bsky.feed.post",text:"old"},"operation-old-0001");
  await journal.run("operation-old-0001",{get:async()=>null,create:async()=>({cid:"old-cid"})});
  await journal.prepare({...address,rkey:"two"},{$type:"app.bsky.feed.post",text:"new"},"operation-new-0001");
  await journal.run("operation-new-0001",{get:async()=>null,create:async()=>({cid:"new-cid"})});
  const document=JSON.parse(await readFile(journalPath,"utf8"));document.operations["operation-old-0001"].updatedAt=new Date(now-31*DAY_MS).toISOString();
  await writeFile(journalPath,JSON.stringify(document));

  const revoked: string[] = [];
  const result = await retentionSweep(root, { webSessions, plans }, async (did) => { revoked.push(did); }, now);

  assert.deepEqual(result, { sessions: 1, signIns: 1, tokens: 1, drafts: 1, journals: 1 });
  assert.deepEqual(revoked, [BOB], "Bob's browser session expired, so his provider tokens are revoked; Alice is still signed in");
  assert.equal((await readdir(join(root, "oauth", "state"))).length, 1);
  assert.deepEqual((await plans.byAuthor(ALICE)).map((plan) => plan.operationId), ["new"]);
  const retained=new DurableWriteJournal(journalPath);await assert.rejects(retained.get("operation-old-0001"),/unknown/);assert.equal((await retained.get("operation-new-0001")).committedCid,"new-cid");
});

test("the sweep is harmless on an empty runtime directory", async () => {
  const root = await mkdtemp(join(tmpdir(), "phlo-retention-empty-"));
  const result = await retentionSweep(root, { webSessions: new WebSessionStore(join(root, "web-sessions")), plans: new ContributionPlanStore(join(root, "contribution-plans")) }, async () => undefined);
  assert.deepEqual(result, { sessions: 0, signIns: 0, tokens: 0, drafts: 0, journals: 0 });
});

test("the sweep retains finished contribution operations while their plan exists", async () => {
  const root = await mkdtemp(join(tmpdir(), "phlo-retention-plan-")), now = Date.now();
  const webSessions = new WebSessionStore(join(root,"web-sessions")), plans = new ContributionPlanStore(join(root,"contribution-plans"));
  const operationId = "retained:context";
  await plans.save({operationId:"retained",sourceOperationId:"retained:source",contextOperationId:operationId,authorDid:ALICE,createdAt:new Date(now-DAY_MS).toISOString()} as ContributionPlan);
  const path=join(root,"operations",`${encodeURIComponent(ALICE)}.json`),journal=new DurableWriteJournal(path);
  await journal.prepare({repo:ALICE,collection:"app.phlogiston.community.submit",rkey:"one"},{$type:"app.phlogiston.community.submit"},operationId);
  await journal.run(operationId,{get:async()=>null,create:async()=>({cid:"context-cid"})});
  const document=JSON.parse(await readFile(path,"utf8"));document.operations[operationId].updatedAt=new Date(now-31*DAY_MS).toISOString();await writeFile(path,JSON.stringify(document));
  const result=await retentionSweep(root,{webSessions,plans},async()=>undefined,now);
  assert.equal(result.journals,0);assert.equal((await new DurableWriteJournal(path).get(operationId)).committedCid,"context-cid");
});

test("interaction pruning waits for an in-process write on the same DID", async () => {
  const root=await mkdtemp(join(tmpdir(),"phlo-retention-race-")),now=Date.now(),path=join(root,"interactions",`${encodeURIComponent(ALICE)}.json`);
  const seed=new DurableWriteJournal(path),address={repo:ALICE,collection:"app.bsky.feed.post",rkey:"old"};
  await seed.prepare(address,{$type:"app.bsky.feed.post",text:"old"},"operation-race-old");await seed.run("operation-race-old",{get:async()=>null,create:async()=>({cid:"old-cid"})});
  const document=JSON.parse(await readFile(path,"utf8"));document.operations["operation-race-old"].updatedAt=new Date(now-31*DAY_MS).toISOString();await writeFile(path,JSON.stringify(document));
  let entered=false,release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve});
  const writing=withInteractionLock(ALICE,async()=>{entered=true;await gate;const journal=new DurableWriteJournal(path);await journal.prepare({...address,rkey:"new"},{$type:"app.bsky.feed.post",text:"new"},"operation-race-new");await journal.run("operation-race-new",{get:async()=>null,create:async()=>({cid:"new-cid"})});});
  while(!entered) await new Promise(resolve=>setTimeout(resolve,1));
  let finished=false;const sweeping=retentionSweep(root,{webSessions:new WebSessionStore(join(root,"web-sessions")),plans:new ContributionPlanStore(join(root,"plans"))},async()=>undefined,now,{interactions:withInteractionLock,operations:(_did,action)=>action()}).then(()=>{finished=true;});
  await new Promise(resolve=>setTimeout(resolve,10));assert.equal(finished,false);release();await writing;await sweeping;
  const retained=new DurableWriteJournal(path);await assert.rejects(retained.get("operation-race-old"),/unknown/);assert.equal((await retained.get("operation-race-new")).committedCid,"new-cid");
});

test("contribution pruning is refused while the reservation execution fence is held", async () => {
  const root=await mkdtemp(join(tmpdir(),"phlo-retention-execute-")),path=join(root,"operations",`${encodeURIComponent(ALICE)}.json`),reservations=new P0Reservations(join(root,"p0-intake"));
  const seed=new DurableWriteJournal(path);await seed.prepare({repo:ALICE,collection:"app.phlogiston.community.submit",rkey:"old"},{$type:"app.phlogiston.community.submit"},"operation-execute-old");
  let entered=false,release!:()=>void;const gate=new Promise<void>(resolve=>{release=resolve});
  const writing=reservations.execute(ALICE,async()=>{entered=true;await gate;const journal=new DurableWriteJournal(path);await journal.prepare({repo:ALICE,collection:"app.phlogiston.community.submit",rkey:"new"},{$type:"app.phlogiston.community.submit"},"operation-execute-new");});
  while(!entered) await new Promise(resolve=>setTimeout(resolve,1));
  const sweep=retentionSweep(root,{webSessions:new WebSessionStore(join(root,"web-sessions")),plans:new ContributionPlanStore(join(root,"plans"))},async()=>undefined,Date.now(),{interactions:(_did,action)=>action(),operations:(did,action)=>reservations.execute(did,action)});
  await assert.rejects(sweep,/already running/);release();await writing;
  assert.equal((await new DurableWriteJournal(path).get("operation-execute-new")).phase,"prepared");
});
