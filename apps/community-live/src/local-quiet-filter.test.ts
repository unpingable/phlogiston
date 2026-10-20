import assert from "node:assert/strict";
import test from "node:test";
import { isLocallyQuiet, localQuietRoot } from "./local-quiet-filter.js";

const root = "at://did:plc:alice/app.bsky.feed.post/root";
const other = "at://did:plc:alice/app.bsky.feed.post/other";
const child = "at://did:plc:bob/app.bsky.feed.post/child";
const roots = new Set([root]);
const ref = (uri: unknown) => ({uri});
const post = (uri: unknown, record: unknown = {}) => ({post: {uri, record}});
const reply = (uri: unknown = root, parent: unknown = root) =>
  post(child, {reply: {root: ref(uri), parent: ref(parent)}});

test("exact roots, declared replies and reposts are quieted without author-wide filtering", () => {
  assert.equal(isLocallyQuiet(post(root), roots), true);
  assert.equal(isLocallyQuiet(reply(), roots), true);
  assert.equal(isLocallyQuiet({...reply(), reply: {root: ref(root), parent: ref(root)}}, roots), true);
  assert.equal(isLocallyQuiet({...reply(), reason: {$type: "app.bsky.feed.defs#reasonRepost"}}, roots), true);
  assert.equal(isLocallyQuiet(post(other), roots), false);
  assert.equal(isLocallyQuiet(reply(other, other), roots), false);
  assert.equal(isLocallyQuiet(post(root), new Set()), false);
});

test("quote targets never become the containing post's local quiet root", () => {
  const quote = {...post(other), embed: {record: {uri: root}}};
  quote.post.record = {embed: {record: ref(root)}};
  assert.equal(localQuietRoot(quote), other);
  assert.equal(isLocallyQuiet(quote, roots), false);
});

test("raw and hydrated contradictory roots or parents stay visible for either rule", () => {
  for (const item of [
    {...reply(), reply: {root: ref(other), parent: ref(root)}},
    {...reply(), reply: {root: ref(root), parent: ref(other)}},
    {...post(root), reply: {root: ref(other), parent: ref(other)}},
  ]) {
    assert.equal(localQuietRoot(item), undefined);
    assert.equal(isLocallyQuiet(item, new Set([root, other, child])), false);
  }
});

test("missing or malformed lineage is not replaced by a hydrated root or own post URI", () => {
  for (const item of [
    {...post(child), reply: {root: ref(root)}},
    {...post(child, {reply: {parent: ref(root)}}), reply: {root: ref(root)}},
    {...reply(), reply: {}},
    {...reply(), reply: null},
    {...reply(), reply: []},
    post(root, {reply: null}),
    post(root, {reply: []}),
    post(root, {reply: "unreadable"}),
    post(root, {reply: {root: ref(root), parent: ref(other)}}),
    post(root, {reply: {root: ref(root), parent: null}}),
    {...reply(), reply: {root: ref(root), parent: {}}},
    post(root, null),
    post(root, []),
    {}, null,
  ]) {
    assert.equal(localQuietRoot(item), undefined);
    assert.equal(isLocallyQuiet(item, new Set([root, child])), false);
  }
});

test("invalid post, root and present parent URIs do not suppress", () => {
  for (const invalid of [undefined, null, 3, "", root + "#fragment", root + "?query",
    root.replace("root", "."), root.replace("root", ".."), root.replace("root", "not valid"),
    root.replace("did:plc:alice", "alice.test"), root.replace("feed.post", "feed.generator")]) {
    for (const item of [
      post(invalid), post(child, {reply: {root: ref(invalid)}}),
      post(child, {reply: {root: ref(root), parent: ref(invalid)}}),
      {...reply(), reply: {root: ref(invalid)}},
      {...reply(), reply: {root: ref(root), parent: ref(invalid)}},
    ]) assert.equal(localQuietRoot(item), undefined);
  }
});

test("optional hydration and unavailable root content do not erase an uncontradicted declaration", () => {
  assert.equal(localQuietRoot(post(child, {reply: {root: ref(root)}})), root);
  for (const type of ["notFoundPost", "blockedPost"]) {
    assert.equal(localQuietRoot({...reply(), reply: {
      root: {$type: `app.bsky.feed.defs#${type}`, uri: root},
      parent: {$type: `app.bsky.feed.defs#${type}`, uri: root},
    }}), root);
  }
});
