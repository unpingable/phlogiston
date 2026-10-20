import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { OAuthSession } from "@atproto/oauth-client-node";
import type { BskyPreferences } from "@atproto/api";
import { loadConfig } from "./config.js";
import { createHandler, type Dependencies } from "./server.js";
import { Reader, type ReaderTransport } from "./reader.js";
import { QuietStore } from "./quiet.js";
import { ContributionPlanStore, WebSessionStore } from "./storage.js";
import { ActivitySnapshots } from "./activity.js";
import { P0_SCOPE, READER_SCOPE, QUIET_SCOPE, FEED_QUIET_SCOPE, READER_INTERACTION_SCOPE } from "./p0.js";
import type { ObservedRecord, RecordAddress } from "./operations.js";

const DID = "did:plc:alice", OTHER = "did:plc:bob";
const ROOT = `at://${DID}/app.bsky.feed.post/root`;
async function harness(scope = QUIET_SCOPE) {
  const directory = await mkdtemp(join(tmpdir(), "phlo-reader-route-"));
  const config = loadConfig({ COMMUNITY_PROFILE: "p0", COMMUNITY_READER_ENABLED: "true",
    COMMUNITY_PUBLIC_URL: "http://127.0.0.1:3210", COMMUNITY_DID: "did:plc:community",
    COMMUNITY_NAME: "The Cabinet", COMMUNITY_PURPOSE: "Fixture collection",
    COMMUNITY_MODERATOR_DID: "did:plc:moderator", COMMUNITY_RUNTIME_DIR: directory,
    COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080", COMMUNITY_AUTHORITY_SOCKET: join(directory,"socket"),
    COMMUNITY_SITE_PAUSE_PATH: join(directory,"site"), COMMUNITY_ADMISSION_PAUSE_PATH: join(directory,"admission") });
  await writeFile(config.sitePausePath!, "open\n", {mode:0o600});
  const sessions = new WebSessionStore(join(directory,"sessions"));
  const signed = await sessions.issue(DID, new Date(), scope);
  const second = await sessions.issue(OTHER, new Date(), scope);
  const sameAccount = await sessions.issue(DID, new Date(), scope);
  const quiet = new QuietStore(join(directory,"quiet","history.sqlite"));
  const calls = { timeline: 0, effects: 0, writes: 0, deletes: 0, root: ROOT, cid:"bafyreifake", muted: false,
    scope, scopeSequence:[] as string[], callbackDid:DID, restoreDid:undefined as string|undefined, issuer:"https://bsky.social",aud:"https://phellinus.us-west.host.bsky.network",
    viewer:{} as Record<string,unknown>, authorViewer:{} as Record<string,unknown>, auth: [] as {scope:string;state?:string}[], revokes:0, revokeFails:false, beforeCreate:null as null|(()=>Promise<void>) };
  const records=new Map<string,ObservedRecord>();const recordKey=(a:RecordAddress)=>`${a.repo}/${a.collection}/${a.rkey}`;
  const oauthSession = (did:string) => ({ did, getTokenInfo: async()=>({sub:did,
    aud:calls.aud,iss:calls.issuer,scope:calls.scopeSequence.shift()??calls.scope}), signOut:async()=>{} }) as unknown as OAuthSession;
  const transport: ReaderTransport = {
    preferences: async()=>({feedViewPrefs:{home:{hideReplies:false,hideRepliesByUnfollowed:false,hideRepliesByLikeCount:0,hideReposts:false,hideQuotePosts:false}},moderationPrefs:{adultContentEnabled:false,labels:{},labelers:[],mutedWords:[],hiddenPosts:[]}} as unknown as BskyPreferences),
    labelDefinitions:async()=>({}), timeline:async()=>{calls.timeline++;return {feed:[]};},
    postThread:async()=>({$type:"app.bsky.feed.defs#threadViewPost",post:{uri:calls.root,cid:calls.cid,author:{did:DID,handle:"fixture.test",viewer:calls.authorViewer},record:{$type:"app.bsky.feed.post",text:"Conversation fixture",createdAt:"2026-10-12T00:00:00Z"},indexedAt:"2026-10-12T00:00:00Z",viewer:{threadMuted:calls.muted,...calls.viewer}}}),
    muteThread:async()=>{calls.effects++;calls.muted=true;}, unmuteThread:async()=>{calls.effects++;calls.muted=false;},
  };
  const deps: Dependencies = {config,quiet,reader:s=>new Reader(s,transport),repoWriter:(_session,did)=>({
    create:async(address,record)=>{assert.equal(address.repo,did);await calls.beforeCreate?.();calls.writes++;const saved={cid:`write-${calls.writes}`,record};records.set(recordKey(address),saved);return {cid:saved.cid};},
    get:async address=>records.get(recordKey(address))??null,
    delete:async address=>{assert.equal(address.repo,did);calls.deletes++;records.delete(recordKey(address));},
  }),
    oauth:{revoke:async()=>{calls.revokes++;if(calls.revokeFails)throw new Error("provider unavailable");calls.scope=READER_SCOPE;},authorize:async(_input,options)=>{calls.auth.push(options);return new URL("https://bsky.social/auth");},restore:async did=>oauthSession(calls.restoreDid??did),callback:async()=>{const state=calls.auth.at(-1)?.state;return {session:oauthSession(calls.callbackDid),...(state===undefined?{}:{state})};}},
    webSessions:sessions,plans:new ContributionPlanStore(join(directory,"plans")),
    activities:new ActivitySnapshots(Buffer.alloc(32,1),{get:async()=>0,advance:async()=>{}}),
    authority:{request:async()=>({ok:true})}, projection:{get:async()=>({discussions:[]}),getCapped:async()=>({discussions:[]})},profiles:{lookup:async()=>new Map()},p0Identity:async()=>true};
  let server=createServer(createHandler(deps));await new Promise<void>(r=>server.listen(0,"127.0.0.1",r));
  let origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const get=(path:string,who=signed)=>fetch(origin+path,{redirect:"manual",headers:{Cookie:`community_session=${who.token}`}});
  const post=(fields:Record<string,string>={},headers:Record<string,string>={})=>fetch(origin+"/quiet",{method:"POST",redirect:"manual",headers:{Origin:config.publicUrl,Cookie:`community_session=${signed.token}`,"Content-Type":"application/x-www-form-urlencoded",...headers},body:new URLSearchParams({csrf:signed.csrf,uri:ROOT,root:ROOT,action:"quiet",...fields})});
  const interact=(fields:Record<string,string>,who=signed,headers:Record<string,string>={})=>fetch(origin+"/interact",{method:"POST",redirect:"manual",headers:{Origin:config.publicUrl,Cookie:`community_session=${who.token}`,"Content-Type":"application/x-www-form-urlencoded",...headers},body:new URLSearchParams({csrf:who.csrf,operationId:"operation-route-0001",uri:ROOT,cid:calls.cid,...fields})});
  const restart=async()=>{await new Promise<void>(r=>server.close(()=>r()));server=createServer(createHandler({...deps,webSessions:new WebSessionStore(join(directory,"sessions"))}));await new Promise<void>(r=>server.listen(0,"127.0.0.1",r));origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;return origin;};
  return {config,directory,signed,second,sameAccount,sessions,quiet,calls,records,get,post,interact,origin,restart,close:async()=>{await new Promise<void>(r=>server.close(()=>r()));quiet.close();await rm(directory,{recursive:true,force:true});}};
}

test("signed-in root is Following; Community remains a first-class collection",async()=>{
  const h=await harness();try {
    const root=await h.get("/");assert.equal(root.status,303);assert.equal(root.headers.get("location"),"/home");
    const home=await h.get("/home");assert.equal(home.status,200);assert.match(await home.text(),/Following/);assert.equal(h.calls.timeline,1);
    const community=await h.get("/community");assert.equal(community.status,200);assert.match(await community.text(),/The Cabinet/);
  }finally{await h.close();}
});
test("old submission grant offers reconnect without reading API; read-only grant offers quiet step-up",async()=>{
  const old=await harness(P0_SCOPE);try {
    const page=await old.get("/home");assert.equal(page.status,200);assert.match(await page.text(),/Connect your Bluesky feed/);assert.equal(old.calls.timeline,0);
  }finally{await old.close();}
  const read=await harness(READER_SCOPE);try {
    const page=await read.get("/thread?uri="+encodeURIComponent(ROOT));assert.equal(page.status,200);assert.match(await page.text(),/access.*quiet|conversation controls/i);
    assert.equal((await read.post()).status,403);assert.equal(read.calls.effects,0);
  }finally{await read.close();}
});
test("CSRF, site pause and root mismatch prevent quiet dispatch",async()=>{
  const h=await harness();try {
    assert.equal((await h.post({csrf:"wrong"})).status,403);assert.equal(h.calls.effects,0);
    await writeFile(h.config.sitePausePath!,"paused\n");assert.equal((await h.post()).status,503);assert.equal(h.calls.effects,0);
    await writeFile(h.config.sitePausePath!,"open\n");
    assert.equal((await h.post({root:ROOT+"different"})).status,409);assert.equal(h.calls.effects,0);assert.deepEqual(h.quiet.list(DID),[]);
  }finally{await h.close();}
});
test("quiet and undo persist observed state; another account has no action history",async()=>{
  const h=await harness();try {
    assert.equal((await h.post()).status,303);assert.equal(h.calls.effects,1);assert.equal(h.quiet.list(DID)[0]?.status,"muted");
    assert.match(await (await h.get("/attention")).text(),/quieted/);
    assert.match(await (await h.get("/attention",h.second)).text(),/No conversation actions yet/);assert.deepEqual(h.quiet.list(OTHER),[]);
    assert.equal((await h.post({action:"restore"})).status,303);assert.equal(h.calls.effects,2);assert.equal(h.quiet.list(DID)[0]?.status,"unmuted");
  }finally{await h.close();}
});
test("login defaults to reader and explicit quiet step-up requests exact grant",async()=>{
  const h=await harness();try {
    for(const access of [undefined,"quiet"]) {
      const form=new URLSearchParams({handle:"fixture.test",return:"https://other.example/"});if(access)form.set("access",access);
      const response=await fetch(h.origin+"/oauth/login",{method:"POST",redirect:"manual",headers:{Origin:h.config.publicUrl,"Content-Type":"application/x-www-form-urlencoded"},body:form});assert.equal(response.status,303);
    }
    assert.equal(h.calls.auth[0]?.scope,READER_SCOPE);assert.equal(h.calls.auth[1]?.scope,FEED_QUIET_SCOPE);
    assert.doesNotMatch(h.calls.auth[0]?.state??"",/other\.example/);
  }finally{await h.close();}
});
test("content interaction is off by grant truth and exact step-up is explicit",async()=>{
 const off=await harness(READER_SCOPE);try{const settings=await off.get("/settings");const body=await settings.text();assert.match(body,/Content interaction/);assert.match(body,/<strong>Off/);assert.equal((await off.interact({action:"like"})).status,403);assert.equal(off.calls.writes,0);
  const form=new URLSearchParams({handle:DID,csrf:off.signed.csrf,return:"/settings",access:"reader-interaction"});const login=await fetch(off.origin+"/oauth/login",{method:"POST",redirect:"manual",headers:{Origin:off.config.publicUrl,"Content-Type":"application/x-www-form-urlencoded"},body:form});assert.equal(login.status,303);assert.equal(off.calls.auth.at(-1)?.scope,READER_INTERACTION_SCOPE);
 }finally{await off.close();}
 const on=await harness(READER_INTERACTION_SCOPE);try{const body=await (await on.get("/settings")).text();assert.match(body,/<strong>Enabled/);assert.match(body,/Disable interaction and disconnect/);assert.match(body,/repo:app\.bsky\.feed\.like\?action=create&amp;action=delete/);
 }finally{await on.close();}
});
test("interaction routes enforce CSRF, pause, exact CID and account-bound undo",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  assert.equal((await h.interact({action:"like",csrf:"wrong"})).status,403);assert.equal(h.calls.writes,0);
  await writeFile(h.config.sitePausePath!,"paused\n");assert.equal((await h.interact({action:"like"})).status,503);assert.equal(h.calls.writes,0);
  await writeFile(h.config.sitePausePath!,"open\n");assert.equal((await h.interact({action:"like",cid:"changed"})).status,409);assert.equal(h.calls.writes,0);
  const liked=await h.interact({action:"like"});assert.equal(liked.status,200);assert.equal(h.calls.writes,1);
  const concurrent=await Promise.all([h.interact({action:"repost",operationId:"operation-route-0003"}),h.interact({action:"repost",operationId:"operation-route-0003"})]);assert.deepEqual(concurrent.map(item=>item.status),[200,200]);assert.equal(h.calls.writes,2);
  const record=[...h.records.keys()].find(value=>value.includes("app.bsky.feed.like"))!;
  const foreign=`at://did:plc:mallory/${record.split("/").slice(1).join("/")}`;
  assert.equal((await h.interact({action:"unlike",record:foreign,operationId:"operation-route-0002"})).status,403);assert.equal(h.calls.deletes,0);
 }finally{await h.close();}
});
test("text post and exact-root reply use journaled account writes",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  const post=await h.interact({action:"post",text:"hello public",operationId:"operation-post-route"});assert.equal(post.status,200);assert.match(await post.text(),/provider confirmed/);
  const reply=await h.interact({action:"reply",text:"hello reply",operationId:"operation-reply-route"});assert.equal(reply.status,200);assert.equal(h.calls.writes,2);
  const values=[...h.records.values()].map(item=>item.record as {$type:string;reply?:{root:{uri:string};parent:{cid:string}};text?:string});assert.ok(values.some(value=>value.text==="hello public"&&!value.reply));assert.ok(values.some(value=>value.reply?.root.uri===ROOT&&value.reply.parent.cid===h.calls.cid));
 }finally{await h.close();}
});

test("interaction intent, duplicate, origin and cross-account resume refusals survive another browser",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  assert.equal((await h.interact({action:"like"},h.signed,{Origin:""})).status,403);assert.equal(h.calls.writes,0);
  assert.equal((await h.interact({action:"like",operationId:"operation-shared-kind"})).status,200);
  assert.equal((await h.interact({action:"repost",operationId:"operation-shared-kind"})).status,409);
  assert.equal((await h.interact({action:"like",operationId:"operation-second-like"},h.sameAccount)).status,409);
  assert.equal(h.calls.writes,1);
  assert.equal((await h.interact({action:"resume",operationId:"operation-shared-kind"},h.second)).status,403);
 }finally{await h.close();}
});

test("threadgate and moderation refuse writes and hide controls",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  const normal=await h.get("/thread?uri="+encodeURIComponent(ROOT));const normalBody=await normal.text();const ids=[...normalBody.matchAll(/name="operationId" value="([^"]+)"/g)].map(match=>match[1]);assert.equal(ids.length,3);assert.equal(new Set(ids).size,3);
  h.calls.viewer={replyDisabled:true};
  const thread=await h.get("/thread?uri="+encodeURIComponent(ROOT));const body=await thread.text();assert.doesNotMatch(body,/Post reply/);
  assert.equal((await h.interact({action:"reply",text:"no",operationId:"operation-disabled-reply"})).status,403);assert.equal(h.calls.writes,0);
  h.calls.viewer={};h.calls.authorViewer={blocking:`at://${DID}/app.bsky.graph.block/one`};
  const blocked=await h.get("/thread?uri="+encodeURIComponent(ROOT));assert.doesNotMatch(await blocked.text(),/Public interactions|Post reply/);
  assert.equal((await h.interact({action:"like",operationId:"operation-blocked-like"})).status,403);assert.equal(h.calls.writes,0);
 }finally{await h.close();}
});

test("unlike remains allowed when the liked subject is now blocked",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  const liked=await h.interact({action:"like",operationId:"operation-blocked-first"});assert.equal(liked.status,200);
  const record=[...h.records.keys()].find(value=>value.includes("app.bsky.feed.like"))!;
  h.calls.authorViewer={blocking:`at://${DID}/app.bsky.graph.block/one`};
  const removed=await h.interact({action:"unlike",record:`at://${record}`,operationId:"operation-blocked-undo"});
  assert.equal(removed.status,200);assert.equal(h.calls.deletes,1);
 }finally{await h.close();}
});

test("paused pages hide interaction controls and attempted-unknown resume is read-only",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  await writeFile(h.config.sitePausePath!,"paused\n");const page=await h.get("/thread?uri="+encodeURIComponent(ROOT));assert.doesNotMatch(await page.text(),/Public interactions|Post reply/);
  await writeFile(h.config.sitePausePath!,"open\n");h.calls.beforeCreate=async()=>{throw new Error("lost response")};
  const first=await h.interact({action:"post",text:"uncertain",operationId:"operation-resume-read"});assert.equal(first.status,200);assert.match(await first.text(),/outcome is unknown/);
  h.calls.beforeCreate=null;h.calls.scope=READER_SCOPE;await writeFile(h.config.sitePausePath!,"paused\n");
  const resumed=await h.interact({action:"resume",operationId:"operation-resume-read"});assert.equal(resumed.status,200);const resumedBody=await resumed.text();assert.match(resumedBody,/did not complete/);assert.match(resumedBody,/>Retry</);assert.equal(h.calls.writes,0);
  h.calls.scope=READER_INTERACTION_SCOPE;await writeFile(h.config.sitePausePath!,"open\n");
  const retried=await h.interact({action:"retry",operationId:"operation-resume-read"});assert.equal(retried.status,200);assert.match(await retried.text(),/provider confirmed/);assert.equal(h.calls.writes,1);
 }finally{await h.close();}
});

test("permission downgrade between prepare and dispatch leaves the operation prepared",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  h.calls.scopeSequence=[READER_INTERACTION_SCOPE,READER_INTERACTION_SCOPE,READER_SCOPE];
  const refused=await h.interact({action:"post",text:"do not send",operationId:"operation-mid-disable"});assert.equal(refused.status,403);assert.equal(h.calls.writes,0);
  const journal=JSON.parse(await (await import("node:fs/promises")).readFile(join(h.directory,"interactions",`${encodeURIComponent(DID)}.json`),"utf8"));assert.equal(journal.operations["operation-mid-disable"].phase,"prepared");
 }finally{await h.close();}
});

test("delete-post route removes only the app-created exact post",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  const created=await h.interact({action:"post",text:"temporary",operationId:"operation-delete-source"});const body=await created.text();
  const record=/name="record" value="([^"]+)"/.exec(body)?.[1],cid=/name="recordCid" value="([^"]+)"/.exec(body)?.[1];assert.ok(record&&cid);
  const removed=await h.interact({action:"delete-post",record,recordCid:cid,operationId:"operation-delete-route"});assert.equal(removed.status,200);assert.equal(h.calls.deletes,1);
 }finally{await h.close();}
});

test("disable disconnects all browser sessions, including while writes are paused",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  await writeFile(h.config.sitePausePath!,"paused\n");
  const disabled=await fetch(h.origin+"/interaction/disable",{method:"POST",headers:{Origin:h.config.publicUrl,Cookie:`community_session=${h.signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf:h.signed.csrf})});
  assert.equal(disabled.status,200);assert.match(await disabled.text(),/provider accepted/);assert.equal(h.calls.revokes,1);
  assert.equal(await h.sessions.resolve(h.signed.token),null);assert.equal(await h.sessions.resolve(h.sameAccount.token),null);assert.notEqual(await h.sessions.resolve(h.second.token),null);
  assert.equal((await h.interact({action:"post",text:"refused",operationId:"operation-after-disable"})).status,401);assert.equal(h.calls.writes,0);
 }finally{await h.close();}
});

test("step-up callback refuses a different subject and ends expected account access",async()=>{
 const h=await harness(READER_SCOPE);try{
  const login=await fetch(h.origin+"/oauth/login",{method:"POST",redirect:"manual",headers:{Origin:h.config.publicUrl,Cookie:`community_session=${h.signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({handle:DID,csrf:h.signed.csrf,return:"/settings",access:"reader-interaction"})});
  const loginCookie=/community_login=[^;]+/.exec(login.headers.get("set-cookie")??"")?.[0];assert.ok(loginCookie);h.calls.callbackDid=OTHER;
  const callback=await fetch(h.origin+"/oauth/callback?code=x",{redirect:"manual",headers:{Cookie:`${loginCookie}; community_session=${h.signed.token}`}});assert.equal(callback.status,400);assert.equal(await h.sessions.resolve(h.signed.token),null);
 }finally{await h.close();}
});

test("a fresh handler over the runtime directory honours the restored interaction grant",async()=>{
 const h=await harness(READER_SCOPE);try{
  const login=await fetch(h.origin+"/oauth/login",{method:"POST",redirect:"manual",headers:{Origin:h.config.publicUrl,Cookie:`community_session=${h.signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({handle:DID,csrf:h.signed.csrf,return:"/settings",access:"reader-interaction"})});
  const loginCookie=/community_login=[^;]+/.exec(login.headers.get("set-cookie")??"")?.[0];assert.ok(loginCookie);h.calls.scope=READER_INTERACTION_SCOPE;
  const callback=await fetch(h.origin+"/oauth/callback?code=x",{redirect:"manual",headers:{Cookie:`${loginCookie}; community_session=${h.signed.token}`}});assert.equal(callback.status,303);
  const token=/community_session=([^;]+)/.exec(callback.headers.get("set-cookie")??"")?.[1];assert.ok(token);const granted=await h.sessions.resolve(token);assert.ok(granted);
  const restarted=await h.restart();
  const settings=await fetch(restarted+"/settings",{headers:{Cookie:`community_session=${token}`}});assert.equal(settings.status,200);assert.match(await settings.text(),/<strong>Enabled/);
 }finally{await h.close();}
});

test("unexpected restored DID or PDS refuses interaction",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  h.calls.restoreDid=OTHER;assert.equal((await h.interact({action:"like",operationId:"operation-wrong-did"})).status,401);h.calls.restoreDid=undefined;
  const fresh=await h.sessions.issue(DID,new Date(),READER_INTERACTION_SCOPE);h.calls.aud="https://evil.example";assert.equal((await h.interact({action:"like",operationId:"operation-wrong-pds"},fresh)).status,401);assert.equal(h.calls.writes,0);
 }finally{await h.close();}
});

test("erase waits for an interaction and prevents its journal from being recreated",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  let release!:()=>void,entered=false;const gate=new Promise<void>(resolve=>{release=resolve});h.calls.beforeCreate=()=>{entered=true;return gate;};
  const writing=h.interact({action:"post",text:"in flight",operationId:"operation-erase-race"});
  while(!entered) await new Promise(resolve=>setTimeout(resolve,1));
  const erasing=fetch(h.origin+"/erase",{method:"POST",redirect:"manual",headers:{Origin:h.config.publicUrl,Cookie:`community_session=${h.signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf:h.signed.csrf})});
  release();assert.equal((await writing).status,200);assert.equal((await erasing).status,200);
  await assert.rejects(import("node:fs/promises").then(({readFile})=>readFile(join(h.directory,"interactions",`${encodeURIComponent(DID)}.json`))),/ENOENT/);
 }finally{await h.close();}
});


test("lost publication is discoverable after restart and Check outcome never redispatches",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  h.calls.beforeCreate=async()=>{throw new Error("lost response")};
  assert.equal((await h.interact({action:"post",text:"uncertain",operationId:"operation-lost-publication"})).status,200);
  await h.restart();const settings=await (await h.get("/settings")).text();assert.match(settings,/Recent content interactions/);assert.match(settings,/operation-lost-publication/);
  assert.equal((await h.interact({action:"post",text:"uncertain",operationId:"operation-new-form-id"})).status,409);
  h.calls.beforeCreate=null;
  for(let i=0;i<2;i++) assert.equal((await h.interact({action:"resume",operationId:"operation-lost-publication"})).status,200);
  assert.equal(h.calls.writes,0);
  assert.equal((await h.interact({action:"retry",operationId:"operation-lost-publication"})).status,200);assert.equal(h.calls.writes,1);
 }finally{await h.close();}
});

test("revocation failure is honest and still ends effective local write access",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  h.calls.revokeFails=true;
  const disabled=await fetch(h.origin+"/interaction/disable",{method:"POST",headers:{Origin:h.config.publicUrl,Cookie:`community_session=${h.signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf:h.signed.csrf})});
  assert.equal(disabled.status,200);assert.match(await disabled.text(),/revocation could not be confirmed/);assert.equal(await h.sessions.resolve(h.sameAccount.token),null);
  assert.equal((await h.interact({action:"post",text:"no",operationId:"operation-revoked-stale"})).status,401);
 }finally{await h.close();}
});

test("reader step-up preserves interaction and callback rejects a different effective grant",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  const login=await fetch(h.origin+"/oauth/login",{method:"POST",redirect:"manual",headers:{Origin:h.config.publicUrl,Cookie:`community_session=${h.signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({handle:DID,return:"/settings",access:"feeds"})});
  assert.equal(login.status,303);assert.match(h.calls.auth.at(-1)!.scope,/repo:app.bsky.feed.like/);
  const loginCookie=/community_login=[^;]+/.exec(login.headers.get("set-cookie")??"")?.[0];h.calls.scope=READER_SCOPE;
  const callback=await fetch(h.origin+"/oauth/callback?code=x",{redirect:"manual",headers:{Cookie:`${loginCookie}; community_session=${h.signed.token}`}});assert.equal(callback.status,403);assert.equal(await h.sessions.resolve(h.signed.token),null);
 }finally{await h.close();}
});

test("disable waits for a dispatched interaction and leaves no usable stale form",async()=>{
 const h=await harness(READER_INTERACTION_SCOPE);try{
  let release!:()=>void,entered=false;const gate=new Promise<void>(resolve=>{release=resolve});h.calls.beforeCreate=()=>{entered=true;return gate;};
  const writing=h.interact({action:"post",text:"already in flight",operationId:"operation-disconnect-race"});while(!entered)await new Promise(resolve=>setTimeout(resolve,1));
  const disabling=fetch(h.origin+"/interaction/disable",{method:"POST",headers:{Origin:h.config.publicUrl,Cookie:`community_session=${h.signed.token}`,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf:h.signed.csrf})});
  release();assert.equal((await writing).status,200);assert.equal((await disabling).status,200);assert.equal(h.calls.writes,1);
  assert.equal((await h.interact({action:"post",text:"stale",operationId:"operation-stale-form"},h.sameAccount)).status,401);assert.equal(h.calls.writes,1);
 }finally{await h.close();}
});

test("a reader consent callback cannot accept an unrequested interaction grant",async()=>{
 const h=await harness(READER_SCOPE);try{
  const login=await fetch(h.origin+"/oauth/login",{method:"POST",redirect:"manual",headers:{Origin:h.config.publicUrl,"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({handle:DID,access:"reader"})});
  const loginCookie=/community_login=[^;]+/.exec(login.headers.get("set-cookie")??"")?.[0];assert.ok(loginCookie);h.calls.scope=READER_INTERACTION_SCOPE;
  const callback=await fetch(h.origin+"/oauth/callback?code=x",{redirect:"manual",headers:{Cookie:loginCookie}});assert.equal(callback.status,403);assert.equal(h.calls.revokes,1);assert.equal(h.calls.writes,0);
 }finally{await h.close();}
});

test("Settings offers only the account-scoped grouping candidate and keeps interaction consent",async()=>{
  const h=await harness();try {
    const response=await h.get("/settings"),body=await response.text();assert.equal(response.status,200);
    assert.match(body,/data-lab-grouping/);assert.match(body,new RegExp(`data-workspace-did="${DID}"`));
    assert.match(body,/Compare ordinary and grouped Following/);assert.match(body,/\/static\/labs\.js/);
    assert.match(body,/Enable content interaction/);
    assert.doesNotMatch(body,/data-lab-editions|data-lab-discovery|action="\/labs"/);
  }finally{await h.close();}
});
