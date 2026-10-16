import assert from "node:assert/strict";
import test from "node:test";
import type { OAuthSession } from "@atproto/oauth-client-node";
import type { AppBskyActorDefs, AppBskyFeedDefs, BskyPreferences } from "@atproto/api";
import { Reader, PublicBlockDirectory, validFeedUri, type ReaderTransport, type ThreadResult } from "./reader.js";

const DID = "did:plc:reader";
const ROOT = `at://${DID}/app.bsky.feed.post/root`;
const FEED = "at://did:plc:abcdefghijklmnopqrstuvwx/app.bsky.feed.generator/interesting";
const FEED2 = "at://did:plc:abcdefghijklmnopqrstuvwx/app.bsky.feed.generator/another";
const session = {did: DID} as unknown as OAuthSession;
const prefs = {
  feedViewPrefs: {home: {hideReplies: false, hideRepliesByUnfollowed: false,
    hideRepliesByLikeCount: 0, hideReposts: false, hideQuotePosts: false}},
  moderationPrefs: {adultContentEnabled: false, labels: {}, labelers: [], mutedWords: [], hiddenPosts: []},
} as unknown as BskyPreferences;
function post(uri: string, extra: Partial<AppBskyFeedDefs.PostView> = {}): AppBskyFeedDefs.PostView {
  return {uri, cid: "bafyreifkpymf7jb3jg5giimeyzab6lbokwi3ko5hdutcj7ift54i64zqxu", author: {did: DID, handle: "reader.test"},
    record: {$type: "app.bsky.feed.post", text: "A post"}, indexedAt: "2026-10-12T00:00:00Z", ...extra};
}
function item(uri: string, extra: Partial<AppBskyFeedDefs.FeedViewPost> = {}): AppBskyFeedDefs.FeedViewPost {
  return {post: post(uri), ...extra};
}
function thread(uri = ROOT, muted: boolean | "unknown" = false): ThreadResult {
  return {$type: "app.bsky.feed.defs#threadViewPost", post: post(uri,
    {viewer: muted === "unknown" ? {} : {threadMuted: muted}})};
}
function fixture(overrides: Partial<ReaderTransport> = {}): ReaderTransport {
  return {
    preferences: async () => prefs,
    savedFeedPreferences: async () => [],
    labelDefinitions: async () => ({}),
    timeline: async () => ({feed: [item(ROOT)]}),
    customFeed: async () => ({feed: [item(ROOT)]}),
    feedGenerators: async uri => [{uri, cid: "bafyreifkpymf7jb3jg5giimeyzab6lbokwi3ko5hdutcj7ift54i64zqxu", did: DID,
      creator: {did: DID, handle: "reader.test"}, displayName: "Interesting", indexedAt: "2026-10-12T00:00:00Z"}],
    postThread: async uri => thread(uri),
    muteThread: async () => {},
    unmuteThread: async () => {},
    ...overrides,
  };
}

test("Following bounds scan to three pages and fetches ahead only when moderation leaves a page empty", async () => {
  const calls: (string | undefined)[] = [];
  const muted = item(ROOT, {post: post(ROOT, {viewer: {threadMuted: true}})});
  const visible = item(`at://${DID}/app.bsky.feed.post/visible`);
  const transport = fixture({timeline: async cursor => {
    calls.push(cursor);
    if (!cursor) return {feed: [muted], cursor: "one"};
    if (cursor === "one") return {feed: [visible], cursor: "two"};
    throw new Error("must not prefetch unrendered page");
  }});
  const result = await new Reader(session, transport).following();
  assert.deepEqual(calls, [undefined, "one"]);
  assert.deepEqual(result.items.map(x => x.post.uri), [visible.post.uri]);
  assert.equal(result.cursor, "two");assert.equal(result.scanned, 2);
  const empty = await new Reader(session, fixture({timeline: async cursor => {
    if (!cursor) return {feed: [muted], cursor: "one"};
    if (cursor === "one") return {feed: [muted], cursor: "two"};
    if (cursor === "two") return {feed: [muted], cursor: "three"};
    throw new Error("fourth page forbidden");
  }})).following();
  assert.equal(empty.items.length, 0);assert.equal(empty.scanned, 3);assert.equal(empty.cursor, "three");
});

test("saved custom-feed catalog reads V2 or legacy without migration writes and isolates metadata failures", async () => {
  const rawV2 = [{$type: "app.bsky.actor.defs#savedFeedsPrefV2", items: [
    {id: "one", type: "feed", value: FEED, pinned: true},
    {id: "list", type: "list", value: "at://did:plc:abcdefghijklmnopqrstuvwx/app.bsky.graph.list/one", pinned: false},
    {id: "two", type: "feed", value: FEED2, pinned: false},
    {id: "duplicate", type: "feed", value: FEED, pinned: false},
    {id: "invalid", type: "feed", value: "https://example.test/feed", pinned: false},
  ]}, {$type: "app.bsky.actor.defs#savedFeedsPref", pinned: [FEED2], saved: [FEED2]}] as AppBskyActorDefs.Preferences;
  const calls: string[] = [];
  const reader = new Reader(session, fixture({savedFeedPreferences: async () => rawV2,
    feedGenerators: async uri => {calls.push(uri); if (uri === FEED2) throw new Error("metadata unavailable");
      return [{uri, cid: "bafyreifkpymf7jb3jg5giimeyzab6lbokwi3ko5hdutcj7ift54i64zqxu", did: DID, creator: {did: DID, handle: "reader.test"},
        displayName: "Interesting", indexedAt: "2026-10-12T00:00:00Z"}];}}));
  assert.deepEqual(await reader.savedFeeds(), [{uri: FEED, name: "Interesting"}, {uri: FEED2, name: FEED2}]);
  assert.deepEqual(calls, [FEED, FEED2]);
  const legacy = [{$type: "app.bsky.actor.defs#savedFeedsPref", pinned: [FEED2], saved: [FEED, FEED2]}] as AppBskyActorDefs.Preferences;
  assert.deepEqual((await new Reader(session, fixture({savedFeedPreferences: async () => legacy})).savedFeeds()).map(feed => feed.uri), [FEED2, FEED]);
  assert.deepEqual(await new Reader(session, fixture({savedFeedPreferences: async () =>
    [{$type: "app.bsky.actor.defs#savedFeedsPrefV2", items: []}, ...legacy] as AppBskyActorDefs.Preferences})).savedFeeds(), []);
});

test("custom feed preserves generator order and bounded pagination without home preference filtering", async () => {
  assert.equal(validFeedUri(FEED), true);
  for (const uri of ["https://example.test/feed", `${FEED}?q=x`, `${FEED}/more`, FEED.replace("app.bsky.feed.generator", "app.bsky.feed.post"),
    "at://did:plc:../app.bsky.feed.generator/x", "at://did:web:example..com/app.bsky.feed.generator/x",
    "at://did:plc:abcdefghijklmnopqrstuvwx/app.bsky.feed.generator/."])
    assert.equal(validFeedUri(uri), false);
  const old = prefs.feedViewPrefs.home!;
  prefs.feedViewPrefs.home = {...old, hideReplies: true, hideReposts: true, hideQuotePosts: true};
  const reply = item(`${ROOT}-reply`, {post: post(`${ROOT}-reply`, {record: {$type: "app.bsky.feed.post", reply: {root: {uri: ROOT}, parent: {uri: ROOT}}}})});
  const muted = item(`${ROOT}-muted`, {post: post(`${ROOT}-muted`, {viewer: {threadMuted: true}})});
  const calls: Array<string | undefined> = [];
  try {
    const result = await new Reader(session, fixture({customFeed: async (uri, cursor) => {
      assert.equal(uri, FEED);calls.push(cursor);
      if (!cursor) return {feed: [reply, muted], cursor: "next"};
      throw new Error("must not prefetch unrendered custom page");
    }})).feed(FEED);
    assert.deepEqual(result.items.map(x => x.post.uri), [reply.post.uri, muted.post.uri]);
    assert.equal(result.cursor, "next");assert.equal(result.scanned, 2);assert.deepEqual(calls, [undefined]);
    await assert.rejects(new Reader(session, fixture()).feed(`${FEED}?q=x`), /URI/);
    await assert.rejects(new Reader(session, fixture({customFeed: async () => ({feed: [], cursor: "repeat"})})).feed(FEED, "repeat"), /repeated/);
  } finally {prefs.feedViewPrefs.home = old;}
});

test("custom feed scans only filtered empty pages, retains next cursor, and refuses oversized pages", async () => {
  const blocked = item(ROOT, {post: post(ROOT, {author: {did: "did:plc:blocked", handle: "blocked.test",
    viewer: {blocking: "at://did:plc:reader/app.bsky.graph.block/one"}}})});
  const visible = item(`${ROOT}-visible`);
  const calls: Array<string | undefined> = [];
  const result = await new Reader(session, fixture({customFeed: async (_uri, cursor) => {
    calls.push(cursor);
    if (!cursor) return {feed: [blocked], cursor: "one"};
    if (cursor === "one") return {feed: [visible], cursor: "two"};
    throw new Error("unrendered third page fetched");
  }})).feed(FEED);
  assert.deepEqual(calls, [undefined, "one"]);
  assert.deepEqual(result.items.map(x => x.post.uri), [visible.post.uri]);
  assert.equal(result.cursor, "two");assert.equal(result.scanned, 2);
  const empty = await new Reader(session, fixture({customFeed: async (_uri, cursor) =>
    ({feed: [blocked], cursor: cursor === undefined ? "one" : cursor === "one" ? "two" : "three"})})).feed(FEED);
  assert.equal(empty.items.length, 0);assert.equal(empty.scanned, 3);assert.equal(empty.cursor, "three");
  await assert.rejects(new Reader(session, fixture({customFeed: async () => ({feed: Array.from({length: 31}, () => item(ROOT))})})).feed(FEED), /bound/);
});

test("SDK profile moderation evaluates reposter attribution independently", async () => {
  const labeler = "did:plc:fixturelabeler";
  const profile = {did: "did:plc:labelled", handle: "labelled.test", avatar: "https://cdn.bsky.app/img/avatar.jpg",
    labels: [{src: labeler, uri: "at://did:plc:labelled/app.bsky.actor.profile/self", val: "porn", cts: "2026-10-12T00:00:00Z"}]};
  const labelPrefs = {...prefs, moderationPrefs: {...prefs.moderationPrefs, adultContentEnabled: true,
    labels: {porn: "hide", sexual: "warn", nudity: "ignore", "graphic-media": "warn"},
    labelers: [{did: labeler, labels: {}}]}} as BskyPreferences;
  const reader = new Reader(session, fixture({preferences: async () => labelPrefs}));await reader.prepare();
  assert.equal(reader.actorDecision(profile, "avatar").blur, true);
  assert.equal(reader.actorDecision(profile, "displayName").blur, false);
});

test("Following rejects repeated cursors and oversized pages without inventing progress", async () => {
  await assert.rejects(new Reader(session, fixture({timeline: async () => ({feed: [], cursor: "same"})})).following("same"), /repeated/);
  await assert.rejects(new Reader(session, fixture({timeline: async () => ({feed: Array.from({length: 31}, () => item(ROOT))})})).following(), /bound/);
  await assert.rejects(new Reader(session, fixture()).following("x".repeat(2049)), /cursor/);
  const duplicate = await new Reader(session, fixture({timeline: async () => ({feed: [item(ROOT), item(ROOT)]})})).following();
  assert.equal(duplicate.scanned, 2);assert.equal(duplicate.items.length, 1);
});

test("home reply, repost, quote preferences and muted viewer state filter Following only", async () => {
  const old = prefs.feedViewPrefs.home!;
  prefs.feedViewPrefs.home = {...old, hideReplies: true, hideReposts: true, hideQuotePosts: true};
  try {
    const reply = item(`${ROOT}-reply`, {post: post(`${ROOT}-reply`, {record: {$type: "app.bsky.feed.post", reply: {root: {uri: ROOT}, parent: {uri: ROOT}}}})});
    const repost = item(`${ROOT}-repost`, {reason: {$type: "app.bsky.feed.defs#reasonRepost", by: {did: DID, handle: "reader.test"}, indexedAt: "2026-10-12T00:00:00Z"}});
    const quote = item(`${ROOT}-quote`, {post: post(`${ROOT}-quote`, {embed: {$type: "app.bsky.embed.record#view", record: {}} as NonNullable<AppBskyFeedDefs.PostView["embed"]>})});
    const muted = item(`${ROOT}-muted`, {post: post(`${ROOT}-muted`, {viewer: {threadMuted: true}})});
    const result = await new Reader(session, fixture({timeline: async () => ({feed: [reply, repost, quote, muted, item(ROOT)]})})).following();
    assert.equal(result.items.length, 1);assert.equal(result.scanned, 5);
  } finally { prefs.feedViewPrefs.home = old; }
});

test("SDK content-list moderation filters a blocked author without hiding ordinary posts", async () => {
  const blocked = item(ROOT, {post: post(ROOT, {author: {did: "did:plc:blocked", handle: "blocked.test",
    viewer: {blocking: "at://did:plc:reader/app.bsky.graph.block/one"}}})});
  const ordinary = item(`at://${DID}/app.bsky.feed.post/ordinary`);
  const result = await new Reader(session, fixture({timeline: async () => ({feed: [blocked, ordinary]})})).following();
  assert.deepEqual(result.items.map(x => x.post.uri), [ordinary.post.uri]);
});

test("SDK profile label can require an avatar blur even when post content stays visible", async () => {
  const labeler = "did:plc:fixturelabeler";
  const author = {did: "did:plc:labelled", handle: "labelled.test", avatar: "https://cdn.bsky.app/img/avatar.jpg",
    labels: [{src: labeler, uri: "at://did:plc:labelled/app.bsky.actor.profile/self", val: "porn", cts: "2026-10-12T00:00:00Z"}]};
  const labelled = post(ROOT, {author});
  const labelPrefs = {...prefs, moderationPrefs: {...prefs.moderationPrefs, adultContentEnabled: true,
    labels: {porn: "hide", sexual: "warn", nudity: "ignore", "graphic-media": "warn"},
    labelers: [{did: labeler, labels: {}}]}} as BskyPreferences;
  const reader = new Reader(session, fixture({preferences: async () => labelPrefs}));
  await reader.prepare();
  assert.equal(reader.decision(labelled, "contentList").blur, false);
  assert.equal(reader.decision(labelled, "avatar").blur, true);
  assert.equal(reader.decision(labelled, "displayName").blur, false);
});

test("exact root resolution, explicit quiet write/readback, and unknown state refusal", async () => {
  const REPLY = `at://${DID}/app.bsky.feed.post/reply`;
  const writes: string[] = [];
  let muted = false;
  const transport = fixture({postThread: async uri => uri === REPLY ?
    {$type: "app.bsky.feed.defs#threadViewPost", post: post(REPLY,
      {record: {$type: "app.bsky.feed.post", reply: {root: {uri: ROOT}, parent: {uri: ROOT}}}})} : thread(ROOT, muted),
    muteThread: async root => {writes.push(`mute:${root}`);muted = true;},
    unmuteThread: async root => {writes.push(`unmute:${root}`);muted = false;}});
  const reader = new Reader(session, transport);
  assert.equal(await reader.resolveRoot(REPLY), ROOT);
  await assert.rejects(reader.setQuiet(REPLY, true), /exact thread root/);
  await assert.rejects(reader.setQuiet(ROOT, true, async () => {throw new Error("paused");}), /paused/);
  assert.deepEqual(writes, []);
  await reader.setQuiet(ROOT, true);assert.equal(await reader.readQuiet(ROOT), true);
  await reader.setQuiet(ROOT, false);assert.equal(await reader.readQuiet(ROOT), false);
  assert.deepEqual(writes, [`mute:${ROOT}`, `unmute:${ROOT}`]);
  await assert.rejects(new Reader(session, fixture({postThread: async () => thread(ROOT, "unknown")})).readQuiet(ROOT), /unknown/);
  await assert.rejects(new Reader(session, fixture({postThread: async () => ({$type: "app.bsky.feed.defs#notFoundPost", uri: ROOT, notFound: true})})).resolveRoot(ROOT), /unavailable/);
});

test("reader time budget refuses stalled preference acquisition", async () => {
  const reader = new Reader(session, fixture({preferences: () => new Promise(() => {})}), 5);
  await assert.rejects(reader.following(), /time budget/);
});

test("normal Agent transport reads raw preferences without SDK migration write and caps response bytes", async () => {
  const calls: {url: string; method: string | undefined; proxy: string | null; labelers: string | null}[] = [];
  let oversized = false;
  const local = {did: DID, fetchHandler: async (url: string, init: RequestInit) => {
    const headers = new Headers(init.headers);
    calls.push({url, method: init.method, proxy: headers.get("atproto-proxy"), labelers: headers.get("atproto-accept-labelers")});
    const reply = url.startsWith("/xrpc/app.bsky.actor.getPreferences") ? {preferences: [
      {$type: "app.bsky.actor.defs#labelersPref", labelers: [{did: "did:plc:subscribed"}]},
    ]} :
      url.startsWith("/xrpc/app.bsky.labeler.getServices") ? {views: []} : {feed: []};
    return new Response(JSON.stringify(reply), {status: 200, headers: {
      "content-type": "application/json", ...(oversized ? {"content-length": "2097153"} : {}),
    }});
  }} as unknown as OAuthSession;
  const reader = new Reader(local);
  await reader.prepare();
  await reader.following();
  assert.deepEqual(calls.map(call => call.method), ["get", "get", "get"]);
  assert.ok(calls.every(call => call.proxy === "did:web:api.bsky.app#bsky_appview"));
  assert.ok(calls.every(call => !call.url.includes("putPreferences")));
  assert.match(calls[2]!.labelers ?? "", /did:plc:subscribed/);
  oversized = true;
  await assert.rejects(new Reader(local).prepare(), /byte limit/);
});

test("normal Agent custom feed uses only exact read RPCs through the AppView audience", async () => {
  const calls: Array<{url: string; method: string | undefined; proxy: string | null}> = [];
  const local = {did: DID, fetchHandler: async (url: string, init: RequestInit) => {
    const headers = new Headers(init.headers);
    calls.push({url, method: init.method, proxy: headers.get("atproto-proxy")});
    const response = url.startsWith("/xrpc/app.bsky.actor.getPreferences") ? {preferences: [
      {$type: "app.bsky.actor.defs#savedFeedsPrefV2", items: [{id: "one", type: "feed", value: FEED, pinned: true}]},
    ]} : url.startsWith("/xrpc/app.bsky.feed.getFeedGenerators") ? {feeds: [{uri: FEED,
      cid: "bafyreifkpymf7jb3jg5giimeyzab6lbokwi3ko5hdutcj7ift54i64zqxu", did: DID, creator: {did: DID, handle: "reader.test"},
      displayName: "Interesting", indexedAt: "2026-10-12T00:00:00Z"}]} :
      url.startsWith("/xrpc/app.bsky.feed.getFeed") ? {feed: [item(ROOT)]} : {views: []};
    return new Response(JSON.stringify(response), {status: 200, headers: {"content-type": "application/json"}});
  }} as unknown as OAuthSession;
  const reader = new Reader(local);
  assert.deepEqual(await reader.savedFeeds(), [{uri: FEED, name: "Interesting"}]);
  assert.deepEqual((await reader.feed(FEED)).items.map(x => x.post.uri), [ROOT]);
  assert.deepEqual(calls.map(call => call.method), ["get", "get", "get", "get"]);
  assert.deepEqual(calls.map(call => call.url.split("?")[0]), [
    "/xrpc/app.bsky.actor.getPreferences", "/xrpc/app.bsky.labeler.getServices",
    "/xrpc/app.bsky.feed.getFeedGenerators", "/xrpc/app.bsky.feed.getFeed",
  ]);
  assert.ok(calls.every(call => call.proxy === "did:web:api.bsky.app#bsky_appview"));
});

test("curator policy filters author/reposter/quote references during acquisition without changing home decisions",async()=>{
 const blocked='did:plc:excluded',blockedRoot=`at://${blocked}/app.bsky.feed.post/root`;
 const author=item(blockedRoot,{post:post(blockedRoot,{author:{did:blocked,handle:'excluded.test'}})});
 const repost=item(ROOT+'repost',{reason:{$type:'app.bsky.feed.defs#reasonRepost',by:{did:blocked,handle:'excluded.test'},indexedAt:'2026-10-12T00:00:00Z'}});
 const quote=item(ROOT+'quote',{post:post(ROOT+'quote',{record:{$type:'app.bsky.feed.post',text:'Quote',embed:{$type:'app.bsky.embed.record',record:{uri:blockedRoot,cid:post(ROOT).cid}}}})});
 const visible=item(ROOT+'visible');let calls=0;
 const result=await new Reader(session,fixture({timeline:async()=>++calls===1?{feed:[author,repost,quote],cursor:'next'}:{feed:[visible,visible],cursor:'after'}})).following(undefined,{excludedDids:new Set([blocked]),includeReplies:true,includeReposts:true});
 assert.equal(calls,2);assert.deepEqual(result.items.map(x=>x.post.uri),[visible.post.uri]);assert.equal(result.scanned,5);assert.deepEqual(result.omitted,{'curator-blocks':3,repeat:1});assert.equal(result.cursor,'after');
 const muted=item(ROOT,{post:post(ROOT,{viewer:{threadMuted:true}})});
 assert.equal((await new Reader(session,fixture({timeline:async()=>({feed:[muted]})})).following(undefined,{excludedDids:new Set(),includeReplies:true,includeReposts:true})).items.length,0);
 const reply=item(ROOT,{post:post(ROOT,{record:{$type:'app.bsky.feed.post',text:'Reply',reply:{root:{uri:ROOT,cid:post(ROOT).cid},parent:{uri:ROOT,cid:post(ROOT).cid}}}})});
 assert.deepEqual((await new Reader(session,fixture({timeline:async()=>({feed:[reply]})})).following(undefined,{excludedDids:new Set(),includeReplies:false,includeReposts:true})).omitted,{'feed-definition':1});
});

test("curator profile canonicalizes bounded identifiers and refuses substituted or blocked profiles",async()=>{
 const profile={did:DID,handle:'reader.test',indexedAt:'2026-10-12T00:00:00Z'};
 assert.deepEqual(await new Reader(session,fixture({curatorProfile:async()=>profile})).curatorProfile('reader.test'),{did:DID,handle:'reader.test'});
 await assert.rejects(new Reader(session,fixture({curatorProfile:async()=>({...profile,did:'did:plc:other'})})).curatorProfile(DID));
 await assert.rejects(new Reader(session,fixture({curatorProfile:async()=>({...profile,viewer:{blockedBy:true}})})).curatorProfile(DID));
 await assert.rejects(new Reader(session,fixture({curatorProfile:async()=>({...profile,handle:'other.test'})})).curatorProfile('reader.test'));
 await assert.rejects(new Reader(session,fixture()).curatorProfile('https://reader.test'));
});

function block(n:number,subject='did:plc:excluded') { return {uri:`at://${DID}/app.bsky.graph.block/${n}`,cid:post(ROOT).cid,value:{$type:'app.bsky.graph.block',subject,createdAt:'2026-10-12T00:00:00Z'}}; }
function blockDirectory(reply:(url:URL)=>unknown,budget=12000) {
 return new PublicBlockDirectory({resolvePds:async did=>({did,pds:'https://phlogiston.social'}),supportsPds:origin=>origin==='https://phlogiston.social',fetch:async(input,init)=>{assert.equal(init?.redirect,'error');assert.equal(init?.headers && (init.headers as Record<string,string>).Authorization,undefined);return new Response(JSON.stringify(reply(new URL(String(input)))),{headers:{'Content-Type':'application/json'}});}},budget);
}
test("public direct block enumeration requires exhaustion, deduplicates subjects and re-reads fresh without stale cache",async()=>{
 let calls=0;const directory=blockDirectory(url=>{calls++;assert.equal(url.searchParams.get('limit'),'100');assert.equal(url.searchParams.get('collection'),'app.bsky.graph.block');return url.searchParams.has('cursor')?{records:[block(2)],}:{records:[block(1)],cursor:'next'};});
 const result=await directory.read(DID);assert.deepEqual(result.excludedDids,['did:plc:excluded']);assert.equal(result.recordCount,2);assert.ok(Number.isFinite(Date.parse(result.checkedAt)));await directory.read(DID);assert.equal(calls,4);
 assert.equal((await blockDirectory(()=>({records:[]})).read(DID)).recordCount,0);
});
test("public block caps, cursor and provenance refusals never return partial exclusions",async()=>{
 let pages=0;await assert.rejects(blockDirectory(()=>({records:[block(++pages)],cursor:String(pages)})).read(DID));assert.equal(pages,50);
 await assert.rejects(blockDirectory(()=>({records:[block(1)],cursor:'same'})).read(DID));
 await assert.rejects(blockDirectory(()=>({records:[{...block(1),uri:'at://did:plc:other/app.bsky.graph.block/one'}]})).read(DID));
 await assert.rejects(blockDirectory(()=>({records:[{...block(1),value:{$type:'app.bsky.graph.block',subject:'handle.test',createdAt:'bad'}}]})).read(DID));
 await assert.rejects(blockDirectory(()=>({records:Array.from({length:101},(_,n)=>block(n))})).read(DID));
 await assert.rejects(new PublicBlockDirectory({resolvePds:async did=>({did,pds:'https://unsupported.test'}),supportsPds:()=>false,fetch:async()=>{throw Error('must not fetch');}}).read(DID));
 await assert.rejects(new PublicBlockDirectory({resolvePds:async()=>new Promise(()=>{}),supportsPds:()=>true},5).read(DID));
});

test("normal curator profile transport uses exact scoped AppView GET rather than an unavailable injection-only path",async()=>{
 const calls:Array<{url:string,proxy:string|null,method:string|undefined}>=[];
 const local={did:DID,fetchHandler:async(url:string,init:RequestInit)=>{
  calls.push({url,proxy:new Headers(init.headers).get('atproto-proxy'),method:init.method});
  const data=url.startsWith('/xrpc/app.bsky.actor.getPreferences')?{preferences:[]}:url.startsWith('/xrpc/app.bsky.actor.getProfile')?{did:DID,handle:'reader.test'}:{views:[]};
  return new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
 }} as unknown as OAuthSession;
 assert.deepEqual(await new Reader(local).curatorProfile('reader.test'),{did:DID,handle:'reader.test'});
 assert.ok(calls.some(x=>x.url.startsWith('/xrpc/app.bsky.actor.getProfile?actor=reader.test')));
 assert.ok(calls.every(x=>x.method==='get'&&x.proxy==='did:web:api.bsky.app#bsky_appview'));
});

test("Following accounts for every received item it does not show under one named cause", async () => {
  const old = prefs.feedViewPrefs.home!;
  prefs.feedViewPrefs.home = {...old, hideReposts: true};
  try {
    const curated = "did:plc:excluded", other = "did:plc:other";
    const u = (name: string) => `at://${DID}/app.bsky.feed.post/${name}`;
    const repost = item(u("repost"), {reason: {$type: "app.bsky.feed.defs#reasonRepost", by: {did: DID, handle: "reader.test"}, indexedAt: "2026-10-12T00:00:00Z"}});
    const muted = item(u("muted"), {post: post(u("muted"), {viewer: {threadMuted: true}})});
    const mine = item(u("mine"), {post: post(u("mine"), {author: {did: "did:plc:blocked", handle: "blocked.test",
      viewer: {blocking: "at://did:plc:reader/app.bsky.graph.block/one"}}})});
    const theirs = item(u("theirs"), {post: post(u("theirs"), {author: {did: other, handle: "other.test", viewer: {blockedBy: true}}})});
    const byCurator = item(`at://${curated}/app.bsky.feed.post/a`, {post: post(`at://${curated}/app.bsky.feed.post/a`, {author: {did: curated, handle: "excluded.test"}})});
    const reply = item(u("reply"), {post: post(u("reply"), {record: {$type: "app.bsky.feed.post", text: "Reply", reply: {root: {uri: ROOT, cid: post(ROOT).cid}, parent: {uri: ROOT, cid: post(ROOT).cid}}}})});
    const shown = item(u("shown"));
    const feed = [repost, muted, mine, theirs, byCurator, reply, shown, shown];
    const result = await new Reader(session, fixture({timeline: async () => ({feed})})).following(undefined,
      {excludedDids: new Set([curated]), includeReplies: false, includeReposts: true});
    assert.deepEqual(result.items.map(x => x.post.uri), [shown.post.uri]);
    assert.deepEqual(result.omitted, {"home-preferences": 1, "thread-muted": 1, moderation: 1, "other-account-block": 1,
      "curator-blocks": 1, "feed-definition": 1, repeat: 1});
    assert.equal(result.scanned, result.items.length + Object.values(result.omitted).reduce((a, b) => a + b, 0));
  } finally { prefs.feedViewPrefs.home = old; }
});

test("custom feed accounts for moderation and repeats without applying home preferences", async () => {
  const blocked = item(ROOT, {post: post(ROOT, {author: {did: "did:plc:blocked", handle: "blocked.test",
    viewer: {blocking: "at://did:plc:reader/app.bsky.graph.block/one"}}})});
  const ordinary = item(`at://${DID}/app.bsky.feed.post/ordinary`);
  const result = await new Reader(session, fixture({customFeed: async () => ({feed: [blocked, ordinary, ordinary]})})).feed(FEED);
  assert.deepEqual(result.omitted, {moderation: 1, repeat: 1});
  assert.equal(result.scanned, result.items.length + 2);
});

test("a post hidden by a label is counted apart from mutes and names the labeler as evidence", async () => {
  const LABELER = "did:plc:labeler";
  const labelled = {...prefs, moderationPrefs: {...prefs.moderationPrefs, labelers: [{did: LABELER, labels: {}}]}} as unknown as BskyPreferences;
  const uri = `at://${DID}/app.bsky.feed.post/labelled`;
  const hidden = item(uri, {post: post(uri, {author: {did: "did:plc:other", handle: "other.test"},
    labels: [{src: LABELER, uri, val: "!hide", cts: "2026-10-12T00:00:00Z"}]})});
  const result = await new Reader(session, fixture({preferences: async () => labelled, timeline: async () => ({feed: [hidden, hidden, item(ROOT)]})})).following();
  assert.deepEqual(result.omitted, {label: 1, repeat: 1});
  assert.deepEqual(result.labelers, [LABELER]);
  assert.deepEqual((await new Reader(session, fixture()).following()).labelers, []);
});
