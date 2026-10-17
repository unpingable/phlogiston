import assert from "node:assert/strict";
import test from "node:test";
import type { AppBskyFeedDefs, ModerationUI } from "@atproto/api";
import type { Reader, ThreadResult } from "./reader.js";
import { renderPost, renderThread } from "./reader-view.js";
const uri="at://did:plc:alice/app.bsky.feed.post/one";
function post(): AppBskyFeedDefs.PostView { return { uri,cid:"cid",author:{did:"did:plc:alice",handle:"alice.test",displayName:"<script>"},record:{$type:"app.bsky.feed.post",text:"private-looking <b>text</b>",createdAt:"2026-10-12T00:00:00Z"},indexedAt:"2026-10-12T00:00:00Z" }; }
function reader(state:Partial<ModerationUI>={}):Reader { return { decision:()=>({filter:false,blur:false,noOverride:false,alert:false,inform:false,...state}) } as unknown as Reader; }
test("view escapes content, restricts remote images and never expands quoted content without its own moderation",()=>{
 const p=post();p.author.avatar="https://other.test/a.png";p.embed={$type:"app.bsky.embed.record#view",record:{$type:"app.bsky.embed.record#viewRecord",uri,cid:"quoted",author:p.author,value:{text:"UNMODERATED_QUOTE"},indexedAt:p.indexedAt}};
 const body=renderPost(reader(),p);assert.match(body,/&lt;script&gt;/);assert.match(body,/&lt;b&gt;/);assert.doesNotMatch(body,/<script>|other.test|UNMODERATED_QUOTE/);assert.match(body,/Read quoted post/);
});
test("noOverride and filtered content cannot be revealed; warnings require disclosure",()=>{
 for(const state of [{filter:true},{noOverride:true}]) {const body=renderPost(reader(state),post());assert.doesNotMatch(body,/private-looking|alice.test/);assert.match(body,/hidden/);}
 const body=renderPost(reader({blur:true}),post());assert.match(body,/<details class="content-warning">/);assert.match(body,/Show post/);
});
test("interaction controls render only for eligible non-quoted post cards",()=>{
 const control=(value:AppBskyFeedDefs.PostView)=>`<form data-interact="${value.uri}"><button>Like</button></form>`;
 assert.match(renderPost(reader(),post(),"contentList",false,0,"reader",control),/data-interact/);
 assert.doesNotMatch(renderPost(reader({filter:true}),post(),"contentList",false,0,"reader",control),/data-interact|<button>Like/);
 assert.doesNotMatch(renderPost(reader(),post(),"contentList",false,1,"reader",control),/data-interact|<button>Like/);
});
test("thread moderates parent, selected post and each reply independently",()=>{
 const root=post(),child={...post(),uri:uri+"child",record:{...post().record,text:"HIDDEN_REPLY"}};
 const r={decision:(p:AppBskyFeedDefs.PostView)=>({filter:p.uri.endsWith("child"),blur:false,noOverride:false})} as unknown as Reader;
 const tree={$type:"app.bsky.feed.defs#threadViewPost",post:root,replies:[{$type:"app.bsky.feed.defs#threadViewPost",post:child}]} as ThreadResult;
 const body=renderThread(r,tree);assert.match(body,/private-looking/);assert.doesNotMatch(body,/HIDDEN_REPLY/);assert.match(body,/hidden/);
});

test("repost attribution does not disclose an independently muted actor", async()=>{
 const { renderFeed }=await import("./reader-view.js");
 const item:AppBskyFeedDefs.FeedViewPost={post:post(),reason:{$type:"app.bsky.feed.defs#reasonRepost",by:{did:"did:plc:muted",handle:"MUTED_REPOSTER.test",displayName:"MUTED_REPOSTER",viewer:{muted:true}},indexedAt:"2026-10-12T00:00:00Z"}};
 const body=renderFeed(reader(),[item]);assert.match(body,/Reposted/);assert.doesNotMatch(body,/MUTED_REPOSTER/);
});


test("compact metadata preserves full identity and timestamp without invented actions", () => {
  const p = post();
  p.author.displayName = "A very long display name";
  p.author.handle = "long.account.example";
  const body = renderPost(reader(), p);
  assert.match(body, /class="feed-row"/);
  assert.match(body, /feed-avatar-placeholder/);
  assert.match(body, /title="A very long display name"/);
  assert.match(body, /class="feed-handle" title="@long.account.example"/);
  assert.match(body, /title="Mon, 12 Oct 2026 00:00:00 GMT"/);
  assert.match(body, /datetime="2026-10-12T00:00:00Z" title="Mon, 12 Oct 2026 00:00:00 GMT">Oct 12<\/time>/);
  assert.match(body, />Conversation<\/a>/);
  assert.doesNotMatch(body, /<button|Like|Repost<|0 replies/);
});


test("missing display name appears once; focused post exposes full metadata and controls before replies", () => {
  const p = post();
  delete p.author.displayName;
  const list = renderPost(reader(), p);
  assert.doesNotMatch(list, /class="feed-handle"/);
  assert.doesNotMatch(list, /<a class="feed-date"/);
  const tree = {$type:"app.bsky.feed.defs#threadViewPost",post:p,replies:[{$type:"app.bsky.feed.defs#threadViewPost",post:{...p,uri:uri+"reply"}}]} as ThreadResult;
  const body = renderThread(reader(), tree, '<section id="controls">Quiet this conversation</section>');
  const focus = body.slice(body.indexOf('class="thread-focus"'), body.indexOf('id="controls"'));
  assert.match(focus, />Mon, 12 Oct 2026 00:00:00 GMT<\/time>/);
  assert.doesNotMatch(focus, />Conversation<\/a>/);
  assert.ok(body.indexOf('id="controls"') < body.indexOf('class="thread-reply"'));
});


test("avatar and display-name context decisions omit withheld source values", () => {
  const p = post();
  p.author.avatar = "https://cdn.bsky.app/SENSITIVE_AVATAR.png";
  p.author.displayName = "SENSITIVE_DISPLAY_NAME";
  for (const state of [{blur:true}, {filter:true}, {noOverride:true}]) {
    const r = {decision: (_post: AppBskyFeedDefs.PostView, context: string) => ({filter:false,blur:false,noOverride:false,...(["avatar","displayName"].includes(context) ? state : {})})} as unknown as Reader;
    const body = renderPost(r, p);
    assert.doesNotMatch(body, /SENSITIVE_AVATAR|SENSITIVE_DISPLAY_NAME/);
    assert.match(body, /feed-avatar-placeholder/);
    assert.match(body, /alice.test/);
    assert.match(body, /private-looking/);
  }
});

const realCid = "bafyreifkpymf7jb3jg5giimeyzab6lbokwi3ko5hdutcj7ift54i64zqxu";
function withQuote(text = "VISIBLE_QUOTE"): AppBskyFeedDefs.PostView {
  const p = post();
  p.embed = {$type:"app.bsky.embed.record#view",record:{$type:"app.bsky.embed.record#viewRecord",
    uri:uri+"quote",cid:realCid,author:{did:"did:plc:alice",handle:"alice.test"},
    value:{$type:"app.bsky.feed.post",text,createdAt:"2026-10-12T00:00:00Z"},indexedAt:p.indexedAt}};
  return p;
}
test("empty cause arrays render no boilerplate; actual label context shows source and escaped value", () => {
  const empty = renderPost(reader({alerts:[],informs:[],blurs:[]}),post());
  assert.doesNotMatch(empty,/context-badge|Label or account context|Viewing settings are respected/);
  assert.match(empty, /href="\/context\?uri=at%3A%2F%2Fdid%3Aplc%3Aalice[^"]*">Context<\/a>/);
  const focused = renderPost(reader({alerts:[],informs:[],blurs:[]}),post(),"contentView",true);
  assert.match(focused, />Context<\/a>/);
  const cause = {type:"label",label:{val:"<label>",src:"did:plc:labeler"},target:"content",setting:"warn"} as unknown as import("@atproto/api").ModerationCause;
  const body = renderPost(reader({alerts:[cause]}),post());
  assert.match(body,/class="context-badge" href="\/context\?uri=/);
  assert.match(body,/&lt;label&gt; on content, from did:plc:labeler/);
  assert.doesNotMatch(body,/<label>|Labelwatch/);
});
test("valid quote displays bounded content under its own moderation and structural metadata", () => {
  const calls: string[] = [];
  const r = {decision:(p:AppBskyFeedDefs.PostView,context:string)=>{calls.push(p.uri+":"+context);return {filter:false,blur:false,noOverride:false,alerts:[],informs:[],blurs:[]};}} as unknown as Reader;
  const body = renderPost(r,withQuote("VISIBLE_QUOTE "+"a\u0301\u0308".repeat(280)));
  assert.match(body,/VISIBLE_QUOTE/);assert.match(body,/<blockquote/);assert.match(body,/data-quoted="true"/);
  assert.ok(calls.includes(uri+"quote:contentList"));assert.ok(calls.includes(uri+"quote:avatar"));assert.ok(calls.includes(uri+"quote:displayName"));
  assert.doesNotMatch(body,/(a\u0301\u0308){280}/);assert.match(body,/…/);
  const filtered = {decision:(p:AppBskyFeedDefs.PostView)=>({filter:p.uri.endsWith("quote"),blur:false,noOverride:false})} as unknown as Reader;
  assert.doesNotMatch(renderPost(filtered,withQuote()),/VISIBLE_QUOTE/);
});
test("blocked, deleted, detached and mismatched quote identity never disclose quote content", () => {
  for (const record of [
    {$type:"app.bsky.embed.record#viewBlocked",uri:uri+"quote",blocked:true,author:{did:"did:plc:alice"}},
    {$type:"app.bsky.embed.record#viewNotFound",uri:uri+"quote",notFound:true},
    {$type:"app.bsky.embed.record#viewDetached",uri:uri+"quote",detached:true},
  ]) {
    const p = post();p.embed={$type:"app.bsky.embed.record#view",record};
    assert.doesNotMatch(renderPost(reader(),p),/VISIBLE_QUOTE/);assert.match(renderPost(reader(),p),/Quoted post/);
  }
  const p=withQuote();const embedded=(p.embed as import("@atproto/api").AppBskyEmbedRecord.View).record;
  if ("author" in embedded) (embedded.author as AppBskyFeedDefs.PostView["author"]).did="did:plc:other";
  assert.doesNotMatch(renderPost(reader(),p),/VISIBLE_QUOTE/);
});
test("declared thread root is metadata, never manufactured from an invalid reply reference", () => {
  const p=post();p.record.reply={root:{uri:uri+"root",cid:realCid},parent:{uri,cid:realCid}};
  const body=renderPost(reader(),p);assert.match(body,/data-post-uri="at:\/\/did:plc:alice/);assert.match(body,/data-thread-root="at:\/\/did:plc:alice\/app.bsky.feed.post\/oneroot"/);
  p.record.reply={root:{uri:"https://other.test/"}};
  assert.doesNotMatch(renderPost(reader(),p),/data-thread-root=/);
});
test("external thumbnails and native video use exact allowed origins with fallback", () => {
  const p=post();p.embed={$type:"app.bsky.embed.external#view",external:{uri:"https://example.test/page",title:"<Title>",description:"Preview",thumb:"https://cdn.bsky.app/preview.jpg"}};
  assert.match(renderPost(reader(),p),/src="https:\/\/cdn.bsky.app\/preview.jpg"/);assert.match(renderPost(reader(),p),/&lt;Title&gt;/);
  p.embed={$type:"app.bsky.embed.video#view",cid:realCid,playlist:"https://video.bsky.app/watch/playlist.m3u8",thumbnail:"https://video.bsky.app/watch/thumbnail.jpg",alt:"Fixture video"};
  const video=renderPost(reader(),p);assert.match(video,/<video controls preload="none"/);assert.match(video,/Open video in Bluesky/);
  for (const url of ["https://video.bsky.app.other.test/watch.m3u8","https://user@video.bsky.app/watch.m3u8","http://video.bsky.app/watch.m3u8"]) {
    (p.embed as import("@atproto/api").AppBskyEmbedVideo.View).playlist=url;
    assert.doesNotMatch(renderPost(reader(),p),/<video|<source/);
  }
});
test("repost actor attribution requires qualified profile and display-name decisions", async () => {
  const {renderFeed}=await import("./reader-view.js");
  const item:AppBskyFeedDefs.FeedViewPost={post:post(),reason:{$type:"app.bsky.feed.defs#reasonRepost",by:{did:"did:plc:reposter",handle:"reposter.test",displayName:"Qualified reposter"},indexedAt:post().indexedAt}};
  const visible={decision:()=>({filter:false,blur:false,noOverride:false}),actorDecision:()=>({filter:false,blur:false,noOverride:false})} as unknown as Reader;
  assert.match(renderFeed(visible,[item]),/Reposted by Qualified reposter/);
  const hidden={decision:visible.decision,actorDecision:()=>({filter:true,blur:false,noOverride:false})} as unknown as Reader;
  assert.doesNotMatch(renderFeed(hidden,[item]),/Qualified reposter|reposter.test/);
});

test("real SDK quote moderation retains profile labels and omits a blurred quoted avatar", async () => {
  const {Reader} = await import("./reader.js");
  const prefs = {feedViewPrefs:{home:{}},moderationPrefs:{adultContentEnabled:true,labels:{},labelers:[{did:"did:plc:labeler",labels:{porn:"warn"}}],mutedWords:[],hiddenPosts:[]}} as unknown as import("@atproto/api").BskyPreferences;
  const transport: import("./reader.js").ReaderTransport = {
    preferences:async()=>prefs,labelDefinitions:async()=>({}),timeline:async()=>({feed:[]}),
    postThread:async()=>{throw new Error("unused");},muteThread:async()=>{},unmuteThread:async()=>{},
  };
  const r = new Reader({did:"did:plc:viewer"} as unknown as import("@atproto/oauth-client-node").OAuthSession,transport);
  await r.prepare();
  const p=withQuote();const view=(p.embed as import("@atproto/api").AppBskyEmbedRecord.View).record as import("@atproto/api").AppBskyEmbedRecord.ViewRecord;
  view.author.avatar="https://cdn.bsky.app/QUOTED_AVATAR.jpg";
  view.author.labels=[{src:"did:plc:labeler",uri:"at://did:plc:alice/app.bsky.actor.profile/self",val:"porn",cts:"2026-10-12T00:00:00Z"}];
  const body=renderPost(r,p);
  assert.doesNotMatch(body,/QUOTED_AVATAR/);
  assert.match(body,/VISIBLE_QUOTE/);
  assert.match(body,/data-quoted="true"/);
});

test("hidden post names the viewer's settings and offers the reasons without revealing content", () => {
  const r = { decision: () => ({filter: true, blur: false, noOverride: false, filters: [{type: "muted"}], blurs: [], alerts: [], informs: []}) } as unknown as Reader;
  const body = renderPost(r, post());
  assert.match(body, /data-decided-by="viewer"/);
  assert.match(body, /<details><summary>Why\?<\/summary>/);
  assert.match(body, /Muted account\./);
  assert.doesNotMatch(body, /private-looking|alice\.test|data-observation/);
});

test("a post Phlogiston cannot read is an observation limit, not a removal by anyone", () => {
  const p = post(); p.record = {$type: "app.bsky.feed.post", text: 5} as unknown as typeof p.record;
  const body = renderPost(reader(), p);
  assert.match(body, /data-observation="not-established"/);
  assert.match(body, /Phlogiston could not read this post\. Nothing here says it was removed\./);
  assert.doesNotMatch(body, /data-decided-by/);
});

test("blocked, not-found and unreadable conversations are distinct and only evidenced outcomes name the source", () => {
  const blocked = renderThread(reader(), {$type: "app.bsky.feed.defs#blockedPost", uri, blocked: true, author: {did: "did:plc:alice"}} as ThreadResult);
  assert.match(blocked, /data-decided-by="source"/);
  assert.match(blocked, /A block prevents this conversation from being displayed\./);
  assert.doesNotMatch(blocked, /data-decided-by="(account|viewer)"|blocks you|You block/);
  const theirs = renderThread(reader(), {$type: "app.bsky.feed.defs#blockedPost", uri, blocked: true, author: {did: "did:plc:alice", viewer: {blockedBy: true}}} as ThreadResult);
  assert.match(theirs, /data-decided-by="account"/);
  assert.match(theirs, /This account blocks you/);
  const mine = renderThread(reader(), {$type: "app.bsky.feed.defs#blockedPost", uri, blocked: true, author: {did: "did:plc:alice", viewer: {blocking: "at://did:plc:me/app.bsky.graph.block/x"}}} as ThreadResult);
  assert.match(mine, /data-decided-by="viewer"/);
  assert.match(mine, /You block this account/);
  const missing = renderThread(reader(), {$type: "app.bsky.feed.defs#notFoundPost", uri, notFound: true} as ThreadResult);
  assert.match(missing, /data-decided-by="source"/);
  assert.match(missing, /Bluesky reports this post was not found/);
  assert.match(missing, /cannot tell/);
  const odd = renderThread(reader(), {$type: "app.bsky.feed.defs#somethingElse"} as unknown as ThreadResult);
  assert.match(odd, /data-observation="not-established"/);
  assert.doesNotMatch(odd, /data-decided-by|blocked|deleted/);
});

test("a bounded conversation says more was received than shown without inventing a count", () => {
  const node = (n: number) => ({$type: "app.bsky.feed.defs#threadViewPost", post: {...post(), uri: `${uri}r${n}`}});
  const full = {$type: "app.bsky.feed.defs#threadViewPost", post: post(), replies: Array.from({length: 31}, (_, n) => node(n))} as ThreadResult;
  const body = renderThread(reader(), full);
  assert.equal(body.match(/class="thread-reply"/g)?.length, 30);
  assert.match(body, /data-decided-by="app"/);
  assert.match(body, /Phlogiston shows the first 30 replies it received/);
  assert.doesNotMatch(body, /\b1 more\b|\d+ more repl/);
  const exact = {$type: "app.bsky.feed.defs#threadViewPost", post: post(), replies: Array.from({length: 30}, (_, n) => node(n))} as ThreadResult;
  assert.doesNotMatch(renderThread(reader(), exact), /data-decided-by="app"/);
});

test("replies received below the displayed depth are disclosed as not shown", () => {
  const leaf = {$type: "app.bsky.feed.defs#threadViewPost", post: {...post(), uri: uri + "deep", record: {...post().record, text: "DEEP_REPLY"}}};
  const mid = {$type: "app.bsky.feed.defs#threadViewPost", post: {...post(), uri: uri + "mid"}, replies: [leaf]};
  const top = {$type: "app.bsky.feed.defs#threadViewPost", post: {...post(), uri: uri + "top"}, replies: [mid]};
  const body = renderThread(reader(), {$type: "app.bsky.feed.defs#threadViewPost", post: post(), replies: [top]} as ThreadResult);
  assert.doesNotMatch(body, /DEEP_REPLY/);
  assert.match(body, /data-decided-by="app"/);
  assert.match(body, /deeper replies/);
});

test("a post hidden by a label says the settings acted on a label and names its source", () => {
  const filters = [{type: "label", label: {val: "spam", src: "did:plc:lab"}, target: "content", setting: "hide"}];
  const r = { decision: () => ({filter: true, blur: false, noOverride: false, filters, blurs: [], alerts: [], informs: []}) } as unknown as Reader;
  const body = renderPost(r, post());
  assert.match(body, /Hidden by your Bluesky moderation settings, based on a label from did:plc:lab\./);
  assert.match(body, /data-decided-by="viewer"/);
  assert.doesNotMatch(body, /private-looking|you chose/);
});

test("a post its author keeps from signed-out readers says so rather than blaming viewer settings", () => {
  const filters = [{type: "label", label: {val: "!no-unauthenticated", src: "did:plc:alice"}, target: "account", setting: "hide"}];
  const r = { decision: () => ({filter: true, blur: false, noOverride: false, filters, blurs: [], alerts: [], informs: []}) } as unknown as Reader;
  const body = renderPost(r, post());
  assert.match(body, /The author asked that this not be shown to signed-out readers\./);
  assert.match(body, /data-decided-by="account"/);
  assert.doesNotMatch(body, /your viewing settings|your Bluesky moderation/);
});

test("public rendering offers only the Bluesky link, not reader-only routes", () => {
  const body = renderPost(reader(), post(), "contentView", false, 0, "public");
  assert.match(body, /Open in Bluesky/);
  assert.doesNotMatch(body, /href="\/thread|href="\/context/);
});
