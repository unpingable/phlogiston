import assert from "node:assert/strict";
import test from "node:test";
import type { AppBskyFeedDefs } from "@atproto/api";
import { canonicalSourceUrl, feedGroupingHints, groupFeedItems, groupSnapshot } from "./grouping.js";

const root = "at://did:plc:alice/app.bsky.feed.post/root";
const candidate = (uri:string, createdAt:string, extra:Partial<{conversationRoots:string[];sourceUrl:string}>={}) => ({value:uri,uri,createdAt,...extra});

test("distinct commentary on one canonical source stays present in stable chronology", () => {
  const items=[candidate(root+"/older","2026-10-14T10:00:00Z",{sourceUrl:"http://www.example.test/story?utm_source=mail&part=1#top"}),candidate(root+"/newer","2026-10-15T10:00:00Z",{sourceUrl:"https://example.test/story?part=1&fbclid=nope"})];
  const first=groupSnapshot(items), again=groupSnapshot(items.toReversed());
  assert.equal(first.length,1);assert.equal(first[0]?.kind,"source");assert.deepEqual(first[0]?.members.map(x=>x.value),[root+"/newer",root+"/older"]);
  assert.equal(first[0]?.id,again[0]?.id);assert.deepEqual(new Set(first[0]?.members.map(x=>x.value)),new Set(items.map(x=>x.value)));
});

test("separate sources and substantive URL parameters do not collide", () => {
  const groups=groupSnapshot([candidate(root+"/a","2026-10-15T10:00:00Z",{sourceUrl:"https://one.test/story?id=1"}),candidate(root+"/b","2026-10-15T09:00:00Z",{sourceUrl:"https://two.test/story?id=1"}),candidate(root+"/c","2026-10-15T08:00:00Z",{sourceUrl:"https://one.test/story?id=2"})]);
  assert.equal(groups.length,3);assert.equal(new Set(groups.map(group=>group.id)).size,3);
  assert.notEqual(canonicalSourceUrl("https://one.test/story?id=1"),canonicalSourceUrl("https://one.test/story?id=2"));
});

test("roots, replies, and reposted replies share only exact non-conflicting lineage", () => {
  const post=(uri:string,reply?:string):AppBskyFeedDefs.PostView=>({uri,cid:"cid",author:{did:"did:plc:alice",handle:"alice.test"},record:{$type:"app.bsky.feed.post",text:uri,createdAt:"2026-10-15T10:00:00Z",...(reply?{reply:{root:{uri:reply,cid:"rootcid"},parent:{uri:reply,cid:"parentcid"}}}:{})},indexedAt:"2026-10-15T10:00:00Z"});
  const rootPost=post(root), reply=post(root+"reply",root), reposted=post(root+"reposted",root), conflict=post(root+"conflict",root);
  const items:AppBskyFeedDefs.FeedViewPost[]=[{post:rootPost},{post:reply},{post:reposted,reason:{$type:"app.bsky.feed.defs#reasonRepost",by:{did:"did:plc:bob",handle:"bob.test"},indexedAt:"2026-10-15T11:00:00Z"}},{post:conflict,reply:{root:post(root+"other"),parent:rootPost}}];
  const groups=groupFeedItems(items);const conversation=groups.find(group=>group.kind==="conversation"&&group.members.length===3);
  assert.deepEqual(conversation?.members.map(member=>member.uri),[root,root+"reply",root+"reposted"]);assert.equal(groups.find(group=>group.members[0]?.uri===root+"conflict")?.kind,"single");
});

test("missing or conflicting lineage is never guessed", () => {
  const groups=groupSnapshot([candidate(root+"/missing","bad",{}),candidate(root+"/conflict","bad",{conversationRoots:[root,root+"other"]}),candidate(root+"/invalid","bad",{conversationRoots:["not-an-at-uri"]})]);
  assert.deepEqual(groups.map(group=>group.kind),["single","single","single"]);assert.equal(groups.flatMap(group=>group.members).length,3);
});

test("identity survives page boundaries and expansion order is deterministic", () => {
  const older=candidate(root+"/old","2026-10-14T10:00:00Z",{conversationRoots:[root]}),newer=candidate(root+"/new","2026-10-15T10:00:00Z",{conversationRoots:[root]});
  const pageOne=groupSnapshot([newer])[0]!,pageTwo=groupSnapshot([older])[0]!,together=groupSnapshot([older,newer])[0]!;
  assert.equal(pageOne.id,pageTwo.id);assert.equal(pageOne.id,together.id);assert.equal(together.representative.uri,newer.uri);assert.deepEqual(together.members.map(member=>member.uri),[newer.uri,older.uri]);
});

test("tracking variants collide visibly while paths and retained queries stay separate", () => {
  const a=canonicalSourceUrl("http://www.example.test/news?b=2&utm_campaign=x&a=1#part"),b=canonicalSourceUrl("https://example.test/news?a=1&b=2&fbclid=x");
  assert.equal(a,b);assert.notEqual(a,canonicalSourceUrl("https://example.test/news/"));assert.notEqual(a,canonicalSourceUrl("https://example.test/news?a=9&b=2"));
  assert.equal(canonicalSourceUrl("javascript:alert(1)"),undefined);assert.equal(canonicalSourceUrl("https://user:pass@example.test/news"),undefined);
});

test("raw browser hints carry the supplied timestamps in Date.parse chronology", () => {
  const make=(name:string,createdAt:string):AppBskyFeedDefs.FeedViewPost=>({post:{uri:`${root}/${name}`,cid:`cid-${name}`,author:{did:"did:plc:alice",handle:"alice.test"},record:{$type:"app.bsky.feed.post",text:name,createdAt},indexedAt:createdAt,embed:{$type:"app.bsky.embed.external#view",external:{uri:"https://example.test/story",title:"Story",description:"Fixture"}}}});
  const hints=feedGroupingHints([make("older","2026-10-15T09:00:00-02:00"),make("newer","2026-10-15T12:00:00Z")]);
  assert.deepEqual(hints.map(hint=>[hint.uri,hint.createdAt]),[[`${root}/newer`,"2026-10-15T12:00:00Z"],[`${root}/older`,"2026-10-15T09:00:00-02:00"]]);
  assert.deepEqual(new Set(hints.map(hint=>hint.key)),new Set(["https://example.test/story"]));
});


test("malformed lineage remains a singleton instead of breaking the feed",()=>{
  for(const reply of [{},{root:{}},{root:{uri:123}},null]) {
    const item={post:{uri:root,cid:"cid",author:{did:"did:plc:alice",handle:"alice.test"},record:{$type:"app.bsky.feed.post",text:"fixture",createdAt:"2026-10-20T00:00:00Z",reply},indexedAt:"2026-10-20T00:00:00Z"}} as unknown as AppBskyFeedDefs.FeedViewPost;
    assert.equal(feedGroupingHints([item])[0]?.kind,"single");
  }
});
