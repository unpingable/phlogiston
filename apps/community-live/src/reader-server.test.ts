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
import { P0_SCOPE, READER_SCOPE, QUIET_SCOPE, FEED_QUIET_SCOPE } from "./p0.js";

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
  const quiet = new QuietStore(join(directory,"quiet","history.sqlite"));
  const calls = { timeline: 0, effects: 0, root: ROOT, muted: false, auth: [] as {scope:string;state?:string}[] };
  const oauthSession = (did:string) => ({ did, getTokenInfo: async()=>({sub:did,
    aud:"https://phellinus.us-west.host.bsky.network",iss:"https://bsky.social",scope}), signOut:async()=>{} }) as unknown as OAuthSession;
  const transport: ReaderTransport = {
    preferences: async()=>({feedViewPrefs:{home:{hideReplies:false,hideRepliesByUnfollowed:false,hideRepliesByLikeCount:0,hideReposts:false,hideQuotePosts:false}},moderationPrefs:{adultContentEnabled:false,labels:{},labelers:[],mutedWords:[],hiddenPosts:[]}} as unknown as BskyPreferences),
    labelDefinitions:async()=>({}), timeline:async()=>{calls.timeline++;return {feed:[]};},
    postThread:async()=>({$type:"app.bsky.feed.defs#threadViewPost",post:{uri:calls.root,cid:"bafyreifake",author:{did:DID,handle:"fixture.test"},record:{$type:"app.bsky.feed.post",text:"Conversation fixture",createdAt:"2026-10-12T00:00:00Z"},indexedAt:"2026-10-12T00:00:00Z",viewer:{threadMuted:calls.muted}}}),
    muteThread:async()=>{calls.effects++;calls.muted=true;}, unmuteThread:async()=>{calls.effects++;calls.muted=false;},
  };
  const deps: Dependencies = {config,quiet,reader:s=>new Reader(s,transport),
    oauth:{authorize:async(_input,options)=>{calls.auth.push(options);return new URL("https://bsky.social/auth");},restore:async did=>oauthSession(did),callback:async()=>({session:oauthSession(DID)})},
    webSessions:sessions,plans:new ContributionPlanStore(join(directory,"plans")),
    activities:new ActivitySnapshots(Buffer.alloc(32,1),{get:async()=>0,advance:async()=>{}}),
    authority:{request:async()=>({ok:true})}, projection:{get:async()=>({discussions:[]}),getCapped:async()=>({discussions:[]})},profiles:{lookup:async()=>new Map()},p0Identity:async()=>true};
  const server=createServer(createHandler(deps));await new Promise<void>(r=>server.listen(0,"127.0.0.1",r));
  const origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const get=(path:string,who=signed)=>fetch(origin+path,{redirect:"manual",headers:{Cookie:`community_session=${who.token}`}});
  const post=(fields:Record<string,string>={},headers:Record<string,string>={})=>fetch(origin+"/quiet",{method:"POST",redirect:"manual",headers:{Origin:config.publicUrl,Cookie:`community_session=${signed.token}`,"Content-Type":"application/x-www-form-urlencoded",...headers},body:new URLSearchParams({csrf:signed.csrf,uri:ROOT,root:ROOT,action:"quiet",...fields})});
  return {config,signed,second,quiet,calls,get,post,origin,close:async()=>{await new Promise<void>(r=>server.close(()=>r()));quiet.close();await rm(directory,{recursive:true,force:true});}};
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
