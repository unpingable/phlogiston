import assert from "node:assert/strict";
import test from "node:test";
import { chmod, mkdtemp, symlink, writeFile, rm, readFile } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import { spawn, spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import type { OAuthSession } from "@atproto/oauth-client-node";
import { loadConfig } from "./config.js";
import { clientMetadata, createOAuthClient } from "./oauth.js";
import { P0Reservations, P0_SCOPE, READER_SCOPE, QUIET_SCOPE, FEED_SCOPE, FEED_QUIET_SCOPE, CURATION_SCOPE, CURATION_QUIET_SCOPE, hasCurationScope, blueskyOrigin, hasReaderScope, hasQuietScope, hasFeedScope, requireBlueskySession, requireSiteWrites } from "./p0.js";
import { DurableWriteJournal } from "./operations.js";
import { ContributionPlanStore, WebSessionStore } from "./storage.js";
import { createHandler, type Dependencies } from "./server.js";
import { ActivitySnapshots } from "./activity.js";
import { ContributionService } from "./contributions.js";

const DID="did:plc:alice", COMMUNITY="did:plc:community";
function config(root:string,extra:NodeJS.ProcessEnv={}) { return loadConfig({COMMUNITY_PROFILE:"p0",COMMUNITY_SITE_PAUSE_PATH:join(root,"site"),COMMUNITY_ADMISSION_PAUSE_PATH:join(root,"admission"),COMMUNITY_PUBLIC_URL:"http://127.0.0.1:3210",COMMUNITY_DID:COMMUNITY,COMMUNITY_NAME:"Fixture collection",COMMUNITY_PURPOSE:"Local qualification fixture",COMMUNITY_MODERATOR_DID:"did:plc:moderator",COMMUNITY_RUNTIME_DIR:root,COMMUNITY_OBSERVER_URL:"http://127.0.0.1:8080",COMMUNITY_AUTHORITY_SOCKET:join(root,"sock"),...extra}); }
function session(did=DID,aud="https://phellinus.us-west.host.bsky.network",iss="https://bsky.social",scope=P0_SCOPE):OAuthSession {return {did,getTokenInfo:async()=>({sub:did,aud,iss,scope}),signOut:async()=>{}} as unknown as OAuthSession;}
async function temporary(fn:(root:string)=>Promise<void>) { const root=await mkdtemp(join(tmpdir(),"p0-app-fixture-"));try{await fn(root);}finally{await rm(root,{recursive:true,force:true});} }

test("P0 config narrows scope and refuses public/provider exception misuse",async()=>temporary(async root=>{
 const c=config(root);assert.equal(clientMetadata(c).scope,P0_SCOPE);assert.doesNotMatch(P0_SCOPE,/app.bsky.feed.post/);
 assert.throws(()=>config(root,{COMMUNITY_PROFILE:"unknown"}));
 assert.throws(()=>config(root,{COMMUNITY_SITE_PAUSE_PATH:"relative"}));
 assert.throws(()=>config(root,{COMMUNITY_P0_TEST_PDS_ORIGIN:"https://juche.social",COMMUNITY_PUBLIC_URL:"https://phlogiston.app"}));
 assert.throws(()=>config(root,{COMMUNITY_P0_TEST_PDS_ORIGIN:"https://other.invalid"}));
 assert.equal(config(root,{COMMUNITY_P0_TEST_PDS_ORIGIN:"https://juche.social"}).p0TestPdsOrigin,"https://juche.social");
 assert.equal(config(root,{COMMUNITY_P0_HOSTED_PDS_ORIGIN:"https://phlogiston.social"}).p0HostedPdsOrigin,"https://phlogiston.social");
 for(const origin of ["https://other.social","http://phlogiston.social","https://phlogiston.social:444","https://phlogiston.social/path"])
  assert.throws(()=>config(root,{COMMUNITY_P0_HOSTED_PDS_ORIGIN:origin}));
 assert.throws(()=>config(root,{COMMUNITY_PROFILE:"legacy",COMMUNITY_P0_HOSTED_PDS_ORIGIN:"https://phlogiston.social"}));
 assert.throws(()=>config(root,{COMMUNITY_P0_TEST_PDS_ORIGIN:"https://juche.social",COMMUNITY_P0_HOSTED_PDS_ORIGIN:"https://phlogiston.social"}));
 assert.throws(()=>config(root,{COMMUNITY_P0_ALLOW_BLUESKY:"true"}));
 assert.throws(()=>config(root,{COMMUNITY_P0_HOSTED_PDS_ORIGIN:"https://phlogiston.social",COMMUNITY_P0_ALLOW_BLUESKY:"false"}));
 assert.equal(config(root,{COMMUNITY_P0_HOSTED_PDS_ORIGIN:"https://phlogiston.social",COMMUNITY_P0_ALLOW_BLUESKY:"true"}).p0AllowBluesky,true);
}));
test("reader grant is opt-in P0 only and exact scoped grants preserve submission sessions",async()=>temporary(async root=>{
 const disabled=config(root);assert.equal(disabled.readerEnabled,undefined);
 assert.throws(()=>config(root,{COMMUNITY_READER_ENABLED:"false"}));
 assert.throws(()=>config(root,{COMMUNITY_READER_ENABLED:"1"}));
 assert.throws(()=>config(root,{COMMUNITY_PROFILE:"legacy",COMMUNITY_READER_ENABLED:"true"}));
 const enabled=config(root,{COMMUNITY_READER_ENABLED:"true"});
 assert.equal(enabled.readerEnabled,true);assert.equal(clientMetadata(enabled).scope,CURATION_QUIET_SCOPE);
 assert.match(READER_SCOPE,/rpc:app\.bsky\.feed\.getTimeline\?aud=did:web:api\.bsky\.app%23bsky_appview/);
 assert.equal(READER_SCOPE.split(" ").length,6);assert.equal(QUIET_SCOPE.split(" ").length,8);
 for(const scope of [P0_SCOPE,READER_SCOPE,QUIET_SCOPE]) assert.equal(await requireBlueskySession(session(DID,undefined,undefined,scope),DID,enabled),scope);
 assert.equal(hasReaderScope(P0_SCOPE,enabled),false);assert.equal(hasReaderScope(READER_SCOPE,enabled),true);
 assert.equal(hasReaderScope(QUIET_SCOPE,enabled),true);assert.equal(hasQuietScope(READER_SCOPE,enabled),false);
 assert.equal(hasQuietScope(QUIET_SCOPE,enabled),true);
 assert.equal(FEED_SCOPE.split(" ").length,8);assert.equal(FEED_QUIET_SCOPE.split(" ").length,10);
 for(const scope of [FEED_SCOPE,FEED_QUIET_SCOPE]) assert.equal(await requireBlueskySession(session(DID,undefined,undefined,scope),DID,enabled),scope);
 assert.equal(hasFeedScope(READER_SCOPE,enabled),false);assert.equal(hasFeedScope(QUIET_SCOPE,enabled),false);
 assert.equal(hasFeedScope(FEED_SCOPE,enabled),true);assert.equal(hasFeedScope(FEED_QUIET_SCOPE,enabled),true);
 assert.equal(hasReaderScope(FEED_SCOPE,enabled),true);assert.equal(hasQuietScope(FEED_SCOPE,enabled),false);
 assert.equal(hasQuietScope(FEED_QUIET_SCOPE,enabled),true);
 for(const scope of [CURATION_SCOPE,CURATION_QUIET_SCOPE]) {
  assert.equal(await requireBlueskySession(session(DID,undefined,undefined,scope),DID,enabled),scope);
  assert.equal(hasCurationScope(scope,enabled),true);assert.equal(hasReaderScope(scope,enabled),true);assert.equal(hasFeedScope(scope,enabled),true);
 }
 assert.equal(CURATION_SCOPE.split(" ").length,9);assert.equal(CURATION_QUIET_SCOPE.split(" ").length,11);
 assert.equal(hasQuietScope(CURATION_SCOPE,enabled),false);assert.equal(hasQuietScope(CURATION_QUIET_SCOPE,enabled),true);
 assert.equal(hasCurationScope(FEED_SCOPE,enabled),false);assert.equal(hasCurationScope(CURATION_SCOPE,disabled),false);
 for(const scope of [CURATION_SCOPE+" "+CURATION_SCOPE.split(" ").at(-1),CURATION_SCOPE.replace("app.bsky.actor.getProfile","app.bsky.actor.getProfiles"),CURATION_SCOPE.replace("%23bsky_appview","%23other")]) {
  assert.equal(hasCurationScope(scope,enabled),false);await assert.rejects(requireBlueskySession(session(DID,undefined,undefined,scope),DID,enabled));
 }
 assert.equal(hasReaderScope(READER_SCOPE,disabled),false);assert.equal(hasQuietScope(QUIET_SCOPE,disabled),false);
 assert.equal(hasFeedScope(FEED_SCOPE,disabled),false);
 await assert.rejects(requireBlueskySession(session(DID,undefined,undefined,READER_SCOPE),DID,disabled));
 for(const scope of [QUIET_SCOPE+" rpc:app.bsky.feed.getPosts?aud=did:web:api.bsky.app%23bsky_appview",READER_SCOPE+" "+READER_SCOPE.split(" ")[2],READER_SCOPE.replace("%23bsky_appview","%23other"),READER_SCOPE.replace("app.bsky.actor.getPreferences", "app.bsky.feed.getPosts")]) {
  assert.equal(hasReaderScope(scope,enabled),false);await assert.rejects(requireBlueskySession(session(DID,undefined,undefined,scope),DID,enabled));
 }
 for(const scope of [FEED_SCOPE+" rpc:app.bsky.feed.getActorFeeds?aud=did:web:api.bsky.app%23bsky_appview",FEED_SCOPE.replace("app.bsky.feed.getFeedGenerators","app.bsky.feed.getPosts")]) {
  assert.equal(hasFeedScope(scope,enabled),false);await assert.rejects(requireBlueskySession(session(DID,undefined,undefined,scope),DID,enabled));
 }
}));
test("combined providers require explicit selection and paired issuer/audience custody",async()=>temporary(async root=>{
 const c=config(root,{COMMUNITY_P0_HOSTED_PDS_ORIGIN:"https://phlogiston.social",COMMUNITY_P0_ALLOW_BLUESKY:"true"});
 assert.equal(await requireBlueskySession(session(),DID,c),P0_SCOPE);
 assert.equal(await requireBlueskySession(session(DID,"https://phlogiston.social","https://phlogiston.social"),DID,c),P0_SCOPE);
 for(const [aud,iss] of [["https://phlogiston.social","https://bsky.social"],["https://phellinus.us-west.host.bsky.network","https://phlogiston.social"],["https://juche.social","https://juche.social"]])
  await assert.rejects(requireBlueskySession(session(DID,aud,iss),DID,c));
 const client=createOAuthClient(c);
 assert.throws(()=>client.oauthResolver.getResourceServerMetadata("https://juche.social"),/unsupported PDS/);
 assert.throws(()=>client.oauthResolver.getAuthorizationServerMetadata("https://juche.social"),/unsupported authorization/);
}));
test("DID-bound token issuer/audience/grant checks refuse other custody and overbroad grants",async()=>{
 assert.ok(blueskyOrigin("https://phellinus.us-west.host.bsky.network"));
 for(const host of ["-bad","bad-","", "a..b", "a".repeat(64)]) assert.equal(blueskyOrigin(`https://${host}.host.bsky.network`),false);
 for(const origin of ["https://bsky.social","https://juche.social","https://x.host.bsky.network.evil","http://x.host.bsky.network","https://u@x.host.bsky.network","https://x.host.bsky.network/path","https://x.host.bsky.network:123"])assert.equal(blueskyOrigin(origin),false);
 assert.equal(await requireBlueskySession(session(),DID),P0_SCOPE);
 await assert.rejects(requireBlueskySession(session(),"did:plc:other"));
 await assert.rejects(requireBlueskySession(session(DID,"https://juche.social"),DID));
 await assert.rejects(requireBlueskySession(session(DID,undefined,undefined,`${P0_SCOPE} repo:app.bsky.feed.post?action=create`),DID));
 const hosted={p0HostedPdsOrigin:"https://phlogiston.social"} as ReturnType<typeof config>;
 assert.equal(await requireBlueskySession(session(DID,"https://phlogiston.social","https://phlogiston.social"),DID,hosted),P0_SCOPE);
 for(const [aud,iss] of [["https://phellinus.us-west.host.bsky.network","https://bsky.social"],["https://phlogiston.social.evil","https://phlogiston.social"],["https://phlogiston.social","https://bsky.social"]])
  await assert.rejects(requireBlueskySession(session(DID,aud,iss),DID,hosted));
} );
test("unsupported DID custody is refused before OAuth authorization dispatch",async()=>temporary(async root=>{
 const client=createOAuthClient(config(root));let discoveries=0;
 client.oauthResolver.resolveIdentity=async()=>{discoveries++;return {did:DID,handle:"custom.example",didDoc:{id:DID,service:[{id:"#atproto_pds",type:"AtprotoPersonalDataServer",serviceEndpoint:"https://juche.social"}]}};};
 await assert.rejects(client.authorize("custom.example",{scope:P0_SCOPE}),/unsupported identity custody/);assert.equal(discoveries,1);
 assert.throws(()=>client.oauthResolver.getResourceServerMetadata("https://juche.social"),/unsupported PDS/);
 assert.throws(()=>client.oauthResolver.getAuthorizationServerMetadata("https://juche.social"),/unsupported authorization/);
}));
test("hosted P0 OAuth refuses other DID custody and authorization issuers before dispatch",async()=>temporary(async root=>{
 const client=createOAuthClient(config(root,{COMMUNITY_P0_HOSTED_PDS_ORIGIN:"https://phlogiston.social"}));
 client.oauthResolver.resolveIdentity=async()=>({did:DID,handle:"alice.phlogiston.social",didDoc:{id:DID,service:[{id:"#atproto_pds",type:"AtprotoPersonalDataServer",serviceEndpoint:"https://phellinus.us-west.host.bsky.network"}]}});
 await assert.rejects(client.authorize("alice.phlogiston.social",{scope:P0_SCOPE}),/unsupported identity custody/);
 assert.throws(()=>client.oauthResolver.getResourceServerMetadata("https://phellinus.us-west.host.bsky.network"),/unsupported PDS/);
 assert.throws(()=>client.oauthResolver.getAuthorizationServerMetadata("https://bsky.social"),/unsupported authorization/);
}));
test("site pause defaults fail closed, checks fresh dispatch, permits unknown readback",async()=>temporary(async root=>{
 const c=config(root);await assert.rejects(requireSiteWrites(c));await writeFile(c.sitePausePath!,"open\n",{mode:0o600});await requireSiteWrites(c);
 const j=new DurableWriteJournal(join(root,"journal.json"),()=>requireSiteWrites(c));
 await j.prepare({repo:DID,collection:"app.phlogiston.community.submit",rkey:"r"},{x:1},"op");
 let creates=0;const writer={create:async()=>{creates++;throw new Error("lost response");},get:async()=>({cid:"exact",record:{x:1}})};
 await writeFile(c.sitePausePath!,"paused\n",{mode:0o600});await assert.rejects(j.run("op",writer));assert.equal(creates,0);assert.equal((await j.get("op")).phase,"prepared");
 await writeFile(c.sitePausePath!,"open\n",{mode:0o600});assert.equal((await j.run("op",writer)).phase,"attempted_unknown");
 await writeFile(c.sitePausePath!,"paused\n",{mode:0o600});assert.equal((await new DurableWriteJournal(join(root,"journal.json"),()=>requireSiteWrites(c)).run("op",writer)).phase,"committed");assert.equal(creates,1);
}));
test("durable per-DID active quotas, duplicate exact subject and restart keep reservations",async()=>temporary(async root=>{
 const store=new P0Reservations(root);const subject=(i:number)=>({uri:`at://${DID}/app.bsky.feed.post/${i}`,cid:`cid${i}`});
 for(let i=0;i<3;i++)await store.reserve(DID,COMMUNITY,subject(i),`op${i}`);
 const duplicate=await new P0Reservations(root).reserve(DID,COMMUNITY,subject(0),"other-op");assert.equal(duplicate.operationId,"op0");
 await assert.rejects(store.reserve(DID,COMMUNITY,subject(3),"op3"));
 await store.reserve("did:plc:bob",COMMUNITY,{uri:"at://did:plc:bob/app.bsky.feed.post/1",cid:"b"},"bob");
 assert.equal((await new P0Reservations(root).byAuthor(DID)).filter(e=>e.active).length,3);
}));
test("rolling site-intent limit persists while external candidates do not take daily charges",async()=>temporary(async root=>{
 let now=100000000;const store=new P0Reservations(root,()=>now);
 for(let i=0;i<10;i++){await store.reserve(DID,COMMUNITY,{uri:`at://${DID}/app.bsky.feed.post/${i}`,cid:`c${i}`},`o${i}`);await store.update(`o${i}`,{active:false,decision:"declined"});}
 await assert.rejects(store.reserve(DID,COMMUNITY,{uri:`at://${DID}/app.bsky.feed.post/new`,cid:"new"},"new"));
 await store.reserve(DID,COMMUNITY,{uri:`at://${DID}/app.bsky.feed.post/external`,cid:"external"},"external",false);
 now+=86400001;await store.reserve(DID,COMMUNITY,{uri:`at://${DID}/app.bsky.feed.post/later`,cid:"later"},"later");
}));
test("global active bound and concurrent transaction refusal preserve on-disk capacity",async()=>temporary(async root=>{
 const s=new P0Reservations(root);
 for(let i=0;i<100;i++)await s.reserve(`did:plc:u${i}`,COMMUNITY,{uri:`at://did:plc:u${i}/app.bsky.feed.post/1`,cid:"c"},`o${i}`,false);
 await assert.rejects(s.reserve("did:plc:next",COMMUNITY,{uri:"at://did:plc:next/app.bsky.feed.post/1",cid:"c"},"next"));
 const result=await Promise.allSettled([s.update("o0",{active:false}),new P0Reservations(root).update("o1",{active:false})]);assert.ok(result.some(r=>r.status==="fulfilled"));
 const db=new DatabaseSync(join(root,"intake.sqlite3"));try{assert.ok(Number((db.prepare("SELECT count(*) n FROM reservations WHERE active=1").get() as {n:number}).n)<=100);}finally{db.close();}
}));

test("P0 handler refuses composition, omits replies, writes only submit and keeps honest status",async()=>temporary(async root=>{
 const c=config(root);await writeFile(c.sitePausePath!,"open\n",{mode:0o600});await writeFile(c.admissionPausePath!,"open\n",{mode:0o600});
 const sessions=new WebSessionStore(join(root,"sessions"));const signed=await sessions.issue(DID);let creates=0;let decision="none";let authorityUnknown=false;const records=new Map<string,{cid:string;record:unknown}>();
 const subject={uri:`at://${DID}/app.bsky.feed.post/existing`,cid:"post-cid"};
 const deps:Dependencies={config:c,oauth:{authorize:async()=>new URL("https://bsky.social/auth"),callback:async()=>({session:session()}),restore:async did=>session(did)},webSessions:sessions,plans:new ContributionPlanStore(join(root,"plans")),activities:new ActivitySnapshots(Buffer.alloc(32,1),{get:async()=>0,advance:async()=>{}}),p0Identity:async()=>true,authority:{request:async envelope=>{if(authorityUnknown)throw new Error("fixture authority unavailable");if(envelope.action === "root_decline")decision="declined";return {ok:true,result:{decision,subject:decision === "submission_unavailable" ? null : subject,admission:null,submission:envelope.target,reason:decision === "declined" ? "private reason" : null}};}},projection:{get:async path=>path.includes("/discussions/")?{discussion:{discussion:{uri:`at://${COMMUNITY}/app.phlogiston.community.admission/one`,cid:"admit"},root:subject,post:{text:"root"},authorDid:DID,status:"visible"},replies:[{post:{text:"forbidden reply"}}]}:path.includes("moderation-queue") ? {submissions:[],nextCursor:"author-sequence",coverage:{kind:"candidates"}} : {discussions:[],submissions:[]},getCapped:async()=>({discussions:[]})},profiles:{lookup:async()=>new Map()},repoWriter:()=>({get:async address=>address.collection==="app.bsky.feed.post"?{cid:subject.cid,record:{text:"existing"}}:records.get(address.rkey)??null,create:async(address,record)=>{assert.equal(address.collection,"app.phlogiston.community.submit");creates++;records.set(address.rkey,{cid:"submit-cid",record});return {cid:"submit-cid"};}})};
 const server=createServer(createHandler(deps));await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));const origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
 const post=async(path:string,form:Record<string,string>)=>fetch(origin+path,{method:"POST",headers:{Origin:c.publicUrl,Cookie:`community_session=${signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf:signed.csrf,...form})});
 try {
  assert.equal((await post("/contribute",{text:"new"})).status,403);assert.equal(creates,0);
  const capped=deps.projection.getCapped;deps.projection.getCapped=async()=>{throw new Error("fixture observer unavailable");};
  const outage=await fetch(origin+"/");assert.equal(outage.status,503);const outageBody=await outage.text();assert.match(outageBody,/Independent observation is unavailable/);assert.match(outageBody,/action="\/oauth\/login"/);
  const signedOutage=await fetch(origin+"/",{headers:{Cookie:`community_session=${signed.token}`}});assert.equal(signedOutage.status,503);assert.match(await signedOutage.text(),/did:plc:alice/);
  deps.projection.getCapped=capped;
  const detail=await(await fetch(origin+"/d/one")).text();assert.doesNotMatch(detail,/forbidden reply|Sign in to reply|action="\/contribute"/);
  const submit=await post("/submit-existing",{post:subject.uri});assert.equal(submit.status,200);assert.match(await submit.text(),/Awaiting independent observation/);assert.equal(creates,1);
  assert.equal((await post("/submit-existing",{post:subject.uri})).status,200);assert.equal(creates,1);
  await writeFile(c.sitePausePath!,"paused\n",{mode:0o600});assert.equal((await post("/submit-existing",{post:subject.uri})).status,503);assert.equal(creates,1);
  const mine=await(await fetch(origin+"/mine",{headers:{Cookie:`community_session=${signed.token}`}})).text();assert.match(mine,/Awaiting independently verified observation/);
  const intake=new P0Reservations(join(root,"p0-intake"),()=>Date.now(),JSON.stringify([COMMUNITY,c.publicUrl,"bluesky"]));
  authorityUnknown=true;await fetch(origin+"/mine",{headers:{Cookie:`community_session=${signed.token}`}});assert.equal((await intake.find(COMMUNITY,DID,subject))?.active,true);authorityUnknown=false;
  decision="submission_unavailable";
  const unavailable=await(await fetch(origin+"/mine",{headers:{Cookie:`community_session=${signed.token}`}})).text();
  assert.match(unavailable,/no longer current or available.*not a decline/);assert.equal((await intake.find(COMMUNITY,DID,subject))?.active,false);
  decision="none";
  const moderator=await sessions.issue("did:plc:moderator");
  const authorPage=await(await fetch(origin+"/moderation?authorDid="+encodeURIComponent(DID),{headers:{Cookie:`community_session=${moderator.token}`}})).text();
  assert.match(authorPage,/cursor=author-sequence&amp;authorDid=did%3Aplc%3Aalice/);
  const submitKey=[...records.keys()][0]!;
  const decline=await fetch(origin+"/moderate",{method:"POST",headers:{Origin:c.publicUrl,Cookie:`community_session=${moderator.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf:moderator.csrf,kind:"decline-root",uri:`at://${DID}/app.phlogiston.community.submit/${submitKey}`,cid:"submit-cid",reason:"private reason"})});assert.equal(decline.status,200);assert.match(await decline.text(),/Declined privately/);
  const privatePage=await(await fetch(origin+"/mine",{headers:{Cookie:`community_session=${signed.token}`}})).text();assert.match(privatePage,/Declined for this site.*private reason/);
  const anonymous=await(await fetch(origin+"/")).text();assert.doesNotMatch(anonymous,/private reason/);
  c.p0TestPdsOrigin="https://juche.social";const fixturePage=await(await fetch(origin+"/")).text();assert.match(fixturePage,/Isolated integration qualification.*https:\/\/juche.social/);delete c.p0TestPdsOrigin;
  await writeFile(c.sitePausePath!,"open\n",{mode:0o600});assert.equal((await post("/submit-existing",{post:subject.uri})).status,409);assert.equal(creates,1);
 }finally{await new Promise<void>((resolve,reject)=>server.close(e=>e?reject(e):resolve()));}
}));


for (const scenario of ["prepared", "foreign-community", "altered-address", "terminal", "unknown-present", "unknown-absent", "committed", "matching-conflict", "incompatible-conflict", "malformed-conflict", "unreadable-conflict"] as const) {
 test(`P0 resume reservation and conservative conflict qualification: ${scenario}`, async()=>temporary(async root=>{
  const c=config(root);
  await writeFile(c.sitePausePath!,"open\n",{mode:0o600});
  await writeFile(c.admissionPausePath!,"open\n",{mode:0o600});
  const sessions=new WebSessionStore(join(root,"sessions"));
  const signed=await sessions.issue(DID);
  const subject={uri:`at://${DID}/app.bsky.feed.post/existing`,cid:"post-cid"};
  let creates=0;
  let current:{cid:string;record:unknown}|null=null;
  let unreadable=false;
  const writer={get:async()=>{if(unreadable)throw new Error("unavailable fixture read");return current;},create:async()=>{creates++;throw new Error("fixture response unknown");}};
  const journalPath=join(root,"operations",`${encodeURIComponent(DID)}.json`);
  const journal=new DurableWriteJournal(journalPath);
  const service=new ContributionService(journal,writer);
  const plan=service.planExisting({authorDid:DID,communityDid:scenario === "foreign-community" ? "did:plc:other" : COMMUNITY,subject,createdAt:"2026-10-11T00:00:00.000Z"});
  if(scenario === "altered-address")plan.context.rkey="different";
  const plans=new ContributionPlanStore(join(root,"plans"));await plans.save(plan);
  const expected={$type:"app.phlogiston.community.submit",community:plan.communityDid,subject,createdAt:plan.createdAt};
  await journal.prepare(plan.context,expected,plan.contextOperationId);
  const intake=new P0Reservations(join(root,"p0-intake"),()=>Date.now(),JSON.stringify([COMMUNITY,c.publicUrl,"bluesky"]));
  const isConflict=scenario.endsWith("conflict");
  if(isConflict || scenario === "terminal") {
   await intake.reserve(DID,COMMUNITY,subject,plan.operationId);
   if(scenario === "terminal")await intake.update(plan.operationId,{active:false,decision:"declined"});
  }
  if(scenario === "committed")await journal.run(plan.contextOperationId,{get:async()=>null,create:async()=>({cid:"committed-submit"})});
  if(scenario.startsWith("unknown-") || isConflict) {
   await journal.run(plan.contextOperationId,writer);
   creates=0; // The prior fixture dispatch is deliberately outside this resume.
   if(scenario === "unknown-present")current={cid:"exact-submit",record:expected};
   if(isConflict)current={cid:"current-submit",record:{...expected,createdAt:"2026-10-10T00:00:00.000Z",...(scenario === "incompatible-conflict" ? {subject:{...subject,cid:"different-post"}} : {}),...(scenario === "malformed-conflict" ? {unknownField:true} : {})}};
   if(scenario === "unreadable-conflict") {
    // Establish a durable conflict first, then lose current readback availability.
    await journal.reconcile(plan.contextOperationId,writer);unreadable=true;
   }
  }
  const deps:Dependencies={config:c,oauth:{authorize:async()=>new URL("https://bsky.social/auth"),callback:async()=>({session:session()}),restore:async did=>session(did)},webSessions:sessions,plans,activities:new ActivitySnapshots(Buffer.alloc(32,1),{get:async()=>0,advance:async()=>{}}),p0Identity:async()=>true,authority:{request:async envelope=>({ok:true,result:{decision:"none",subject,submission:envelope.target}})},projection:{get:async()=>({submissions:[]}),getCapped:async()=>({discussions:[]})},profiles:{lookup:async()=>new Map()},repoWriter:()=>writer};
  const server=createServer(createHandler(deps));await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
  const origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try {
   const response=await fetch(origin+"/operation/resume",{method:"POST",headers:{Origin:c.publicUrl,Cookie:`community_session=${signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf:signed.csrf,operationId:plan.operationId})});
   assert.equal(response.status,scenario === "foreign-community" || scenario === "altered-address" ? 403 : scenario === "prepared" || scenario === "terminal" || scenario === "unknown-absent" ? 409 : 200);
   assert.equal(creates,0,"resume must not dispatch from an unreserved or conflicted plan");
   if(isConflict) {
    const entry=await intake.find(COMMUNITY,DID,subject);
    assert.equal(entry?.active,scenario !== "incompatible-conflict");
    if(scenario === "matching-conflict")assert.equal(entry?.submission?.cid,"current-submit");
    if(scenario === "incompatible-conflict") {
     assert.equal(entry?.decision,"submission_conflict");
     const mine=await(await fetch(origin+"/mine",{headers:{Cookie:`community_session=${signed.token}`}})).text();
     assert.match(mine,/local submission attempt ended.*not a decline or admission/);
    }
   }
  } finally {await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}
 }));
}

for (const state of ["inactive-full", "pending-alias"] as const) {
 test(`terminal and duplicate candidates cannot bypass active intake: ${state}`,async()=>temporary(async root=>{
  const c=config(root);await writeFile(c.sitePausePath!,"open\n",{mode:0o600});await writeFile(c.admissionPausePath!,"open\n",{mode:0o600});
  const intake=new P0Reservations(join(root,"p0-intake"),()=>Date.now(),JSON.stringify([COMMUNITY,c.publicUrl,"bluesky"]));
  const subject={uri:`at://${DID}/app.bsky.feed.post/one`,cid:"post"};
  const first={uri:`at://${DID}/app.phlogiston.community.submit/first`,cid:"first"};
  const alias=state === "inactive-full" ? first : {uri:`at://${DID}/app.phlogiston.community.submit/alias`,cid:"alias"};
  const plan=new ContributionService(new DurableWriteJournal("unused"),{get:async()=>null,create:async()=>{throw new Error("inert");}}).planExisting({authorDid:DID,communityDid:COMMUNITY,subject,createdAt:"2026-10-11T00:00:00Z"});
  await intake.reserve(DID,COMMUNITY,subject,plan.operationId,false);
  await intake.update(plan.operationId,{submission:first,...(state === "inactive-full" ? {active:false,decision:"submission_unavailable"} : {})});
  for(let i=0;i<(state === "inactive-full" ? 100 : 99);i++)await intake.reserve(`did:plc:capacity${i}`,COMMUNITY,{uri:`at://did:plc:capacity${i}/app.bsky.feed.post/one`,cid:"post"},`capacity${i}`,false);
  assert.equal((await intake.active()).length,100);
  let unavailable=false,admissions=0;
  const sessions=new WebSessionStore(join(root,"sessions"));const moderator=await sessions.issue("did:plc:moderator");const participant=await sessions.issue(DID);
  const deps:Dependencies={config:c,oauth:{authorize:async()=>new URL("https://bsky.social/auth"),callback:async()=>({session:session()}),restore:async did=>session(did)},webSessions:sessions,plans:new ContributionPlanStore(join(root,"plans")),activities:new ActivitySnapshots(Buffer.alloc(32,1),{get:async()=>0,advance:async()=>{}}),p0Identity:async()=>true,authority:{request:async envelope=>{
   if(envelope.action === "root_admit")admissions++;
   const gone=unavailable && envelope.target.uri === alias.uri;
   return {ok:true,result:{decision:gone ? "submission_unavailable" : state === "pending-alias" && envelope.target.uri === first.uri ? "admit_pending" : "none",submission:envelope.target,subject:gone ? null : subject,admission:null}};
  }},projection:{get:async()=>({submissions:[{authorDid:DID,subject,submission:alias}],coverage:{kind:"candidates"}}),getCapped:async()=>({discussions:[]})},profiles:{lookup:async()=>new Map()}};
  const server=createServer(createHandler(deps));await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));const origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try {
   const queue=await(await fetch(origin+"/moderation",{headers:{Cookie:`community_session=${moderator.token}`}})).text();
   assert.doesNotMatch(queue,/name="kind" value="admit-root"/);assert.match(queue,state === "inactive-full" ? /ended local intake/ : /alias deferred/);
   const admission=await fetch(origin+"/moderate",{method:"POST",headers:{Origin:c.publicUrl,Cookie:`community_session=${moderator.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf:moderator.csrf,kind:"admit-root",uri:alias.uri,cid:alias.cid})});
   assert.equal(admission.status,409);assert.equal(admissions,0);assert.equal((await intake.active()).length,100);
   if(state === "pending-alias") {
    await assert.rejects(intake.update(plan.operationId,{submission:alias}),/first qualified submission/);
    unavailable=true;
    await fetch(origin+"/moderation",{headers:{Cookie:`community_session=${moderator.token}`}});
    const mine=await(await fetch(origin+"/mine",{headers:{Cookie:`community_session=${participant.token}`}})).text();
    assert.match(mine,/Admission outcome is unknown/);
    const preserved=await intake.find(COMMUNITY,DID,subject);assert.deepEqual(preserved?.submission,first);assert.equal(preserved?.active,true);assert.equal((await intake.active()).length,100);
   }
  } finally {await new Promise<void>((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}
 }));
}

test("execution release retries concurrent SQLite lock and recovers without restarting",async()=>temporary(async root=>{
 const store=new P0Reservations(root);
 await store.reserve(DID,COMMUNITY,{uri:`at://${DID}/app.bsky.feed.post/one`,cid:"one"},"one");
 const lock=new DatabaseSync(join(root,"intake.sqlite3"));
 try {
  const result=await store.execute(DID,async()=>{
   await assert.rejects(new P0Reservations(root).execute(DID,async()=>"must remain fenced"),/already running/);
   lock.exec("BEGIN IMMEDIATE");
   setTimeout(()=>lock.exec("COMMIT"),250);
   return "completed effect";
  });
  assert.equal(result,"completed effect");
  assert.equal(await new P0Reservations(root).execute(DID,async()=>"next action"),"next action");
  assert.equal(lock.prepare("SELECT count(*) n FROM execution").get()!.n,0);
 } finally {lock.close();}
}));

test("SQLite reservation and execution claims recover after producer process loss without deleting locks",async()=>temporary(async root=>{
 const module=new URL("./p0.ts",import.meta.url).href;
 const script=join(root,"producer.mjs");
 await writeFile(script,`import {P0Reservations} from ${JSON.stringify(module)}; const s=new P0Reservations(${JSON.stringify(root)}); await s.reserve("did:plc:lost","did:plc:community",{uri:"at://did:plc:lost/app.bsky.feed.post/one",cid:"exact"},"lost"); await s.execute("did:plc:lost",async()=>{process.exit(0);});`);
 const child=spawnSync(process.execPath,["--import",new URL("../node_modules/tsx/dist/loader.mjs",import.meta.url).href,script],{encoding:"utf8"});assert.equal(child.status,0,child.stderr);
 const reopened=new P0Reservations(root);assert.equal((await reopened.byAuthor("did:plc:lost"))[0]?.active,true);
 assert.equal(await reopened.execute("did:plc:lost",async()=>"readback first"),"readback first");
}));
test("pause controls refuse symlinks, nonregular objects and group writable state",async()=>temporary(async root=>{
 const c=config(root);await writeFile(c.sitePausePath!,"open\n",{mode:0o600});await chmod(c.sitePausePath!,0o660);await assert.rejects(requireSiteWrites(c));await chmod(c.sitePausePath!,0o600);await requireSiteWrites(c);
 await rm(c.sitePausePath!);const other=join(root,"other");await writeFile(other,"open\n");await symlink(other,c.sitePausePath!);await assert.rejects(requireSiteWrites(c));
}));
test("intake state cannot be rebound from isolated provider to public mode",async()=>temporary(async root=>{
 await new P0Reservations(root,()=>Date.now(),"community:test-juche").reserve(DID,COMMUNITY,{uri:`at://${DID}/app.bsky.feed.post/one`,cid:"c"},"o");
 await assert.rejects(new P0Reservations(root,()=>Date.now(),"community:public-bluesky").byAuthor(DID),/another community/);
}));
test("hosted PDS intake cannot reuse default Bluesky reservation state",async()=>temporary(async root=>{
 await new P0Reservations(root,()=>Date.now(),JSON.stringify([COMMUNITY,"https://phlogiston.app","bluesky"])).reserve(DID,COMMUNITY,{uri:`at://${DID}/app.bsky.feed.post/one`,cid:"c"},"o");
 await assert.rejects(new P0Reservations(root,()=>Date.now(),JSON.stringify([COMMUNITY,"https://phlogiston.app","hosted:https://phlogiston.social"])).byAuthor(DID),/another community/);
}));


test("concurrent local processes cannot exceed the shared DID reservation bound",async()=>temporary(async root=>{
 const store=new P0Reservations(root);await store.reserve("did:plc:seed",COMMUNITY,{uri:"at://did:plc:seed/app.bsky.feed.post/one",cid:"seed"},"seed",false);
 const module=new URL("./p0.ts",import.meta.url).href,loader=new URL("../node_modules/tsx/dist/loader.mjs",import.meta.url).href;
 const script=join(root,"writer.mjs");await writeFile(script,`import {P0Reservations} from ${JSON.stringify(module)}; const s=new P0Reservations(${JSON.stringify(root)});for(let i=0;i<12;i++){try{await s.reserve("did:plc:shared","did:plc:community",{uri:"at://did:plc:shared/app.bsky.feed.post/"+process.argv[2]+i,cid:"exact"},process.argv[2]+i);}catch{}}`);
 await Promise.all(["lane-a","lane-b"].map(lane=>new Promise<void>((resolve,reject)=>{const child=spawn(process.execPath,["--import",loader,script,lane],{stdio:"ignore"});child.on("error",reject);child.on("exit",code=>code===0?resolve():reject(new Error(`fixture writer exit ${code}`)));})));
 const active=(await new P0Reservations(root).byAuthor("did:plc:shared")).filter(e=>e.active);assert.equal(active.length,3);
}));
