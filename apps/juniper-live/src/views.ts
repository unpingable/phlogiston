import type { AuthorItem } from "./actions.js";
import type { ProjectionBundle, PublicEntry } from "./feed.js";

export function page(input: Readonly<{
  path: "/" | "/create" | "/mine" | "/post" | "/receipt";
  bundle: ProjectionBundle;
  signedInDid: string | null;
  actions: readonly AuthorItem[];
  projection?: string | undefined;
  notice?: string | undefined;
}>): string {
  const title = input.path === "/" ? "Juniper Commons" : `${label(input.path)} · Juniper Commons`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(title)}</title><link rel="stylesheet" href="/styles.css"></head><body>${header(input.signedInDid)}<main>${notice(input.notice)}${body(input)}</main>${footer()}</body></html>`;
}

function body(input: Parameters<typeof page>[0]): string {
  switch (input.path) {
    case "/": return home(input.bundle, input.signedInDid);
    case "/create": return create(input.signedInDid);
    case "/mine": return mine(input.signedInDid, input.actions, input.bundle);
    case "/post": return post(input.bundle, input.projection);
    case "/receipt": return receipt(input.bundle, input.projection);
  }
}

function header(did: string | null): string {
  return `<header class="top"><a class="brand" href="/"><span>J</span> Juniper Commons</a><nav><a href="/">Community</a><a href="/create">Create / submit</a>${did ? `<a href="/mine">What happened to my posts</a><form method="post" action="/oauth/logout"><button class="text-button">Sign out</button></form>` : ""}</nav></header>`;
}

function home(bundle: ProjectionBundle, did: string | null): string {
  const entries = bundle.ordinary?.entries ?? [];
  const active = entries.filter((entry) => entry.lifecycleState !== "removed" && entry.lifecycleState !== "author_withdrawn");
  return `<section class="community-hero"><div><p class="eyebrow">Juniper Commons</p><h1>Useful things neighbors chose to share.</h1><p>Repair notes, growing experiments, and small tools worth passing around.</p></div><a class="primary" href="/create">${did ? "Share something" : "Sign in to share"}</a></section><section class="feed-shell"><div class="section-title"><h2>Recently featured</h2><span>${active.length} ${active.length === 1 ? "item" : "items"}</span></div><div class="feed">${active.length ? active.map(card).join("") : emptyFeed()}</div>${entries.some((entry) => entry.lifecycleState === "removed" || entry.lifecycleState === "author_withdrawn") ? `<details class="history"><summary>Past community decisions</summary>${entries.filter((entry) => entry.lifecycleState === "removed" || entry.lifecycleState === "author_withdrawn").map(card).join("")}</details>` : ""}</section>`;
}

function card(entry: PublicEntry): string {
  const presentation = entry.presentation;
  const title = presentation?.title ?? lifecycleTitle(entry);
  const author = presentation?.authorDisplayReference ?? shortDid(entry.authorDid);
  return `<article class="post-card state-${escape(entry.lifecycleState)}"><div class="post-meta"><span>${escape(author)}</span><span>·</span><span>${escape(stateLabel(entry))}</span></div><h3><a href="/post?projection=${encodeURIComponent(entry.projectionIdentity)}">${escape(title)}</a></h3>${presentation ? `<p>${escape(presentation.body)}</p>` : `<p class="lifecycle-copy">${escape(lifecycleCopy(entry))}</p>`}<details class="why"><summary>Why is this here?</summary><div class="why-steps"><p><b>${escape(author)}</b> submitted an exact version of their post.</p><p><b>Juniper Commons</b> chose to feature that version.</p><p>${escape(lifecycleCopy(entry))}</p></div><a href="/receipt?projection=${encodeURIComponent(entry.projectionIdentity)}">Show receipt</a></details></article>`;
}

function create(did: string | null): string {
  if (!did) return `<section class="single"><p class="eyebrow">Create / submit</p><h1>Share a post with Juniper.</h1><p>You’ll sign in with a disposable Spaces Alpha account. The post stays under your account; submitting it asks Juniper to consider that exact version.</p><form method="post" action="/oauth/login" class="stack"><label>Your disposable Juniper handle<input name="handle" autocomplete="username" placeholder="author.juniper-pds.sp00ky.net" required></label><button class="primary">Continue with ATProto</button></form></section>`;
  return `<section class="single"><p class="eyebrow">Create / submit</p><h1>Share something useful.</h1><p class="plain-boundary">You keep control of the original. Juniper only decides whether one exact version belongs in its feed.</p><form method="post" action="/author/create-submit" class="stack"><label>Title<input name="title" maxlength="140" required></label><label>Post<textarea name="body" maxlength="20000" rows="8" required></textarea></label><label>How your name should appear<input name="authorDisplayReference" maxlength="512" value="${escape(shortDid(did))}" required></label><label class="consent"><input type="checkbox" name="consent" value="yes" required><span>I’m submitting this exact version for a public Juniper Commons presentation.</span></label><button class="primary">Create and submit</button></form></section>`;
}

function mine(did: string | null, actions: readonly AuthorItem[], bundle: ProjectionBundle): string {
  if (!did) return create(null);
  return `<section class="single wide"><p class="eyebrow">Your activity</p><h1>What has Juniper done with my posts?</h1><p>This view keeps your source actions separate from Juniper’s editorial decisions.</p>${actions.length ? actions.map((item) => authorItem(item, bundle)).join("") : `<div class="empty"><h2>No submissions yet</h2><p>Create one post to begin.</p><a class="primary" href="/create">Create / submit</a></div>`}</section>`;
}

function authorItem(item: AuthorItem, bundle: ProjectionBundle): string {
  const projected = bundle.ordinary?.entries.find((entry) => entry.sourceUri === item.post.uri);
  const sourceState = item.currentSource ? (item.currentSource.cid === item.post.cid ? "Original unchanged" : "You updated the original") : "You deleted the original";
  const communityState = projected ? stateLabel(projected) : "Waiting for Juniper’s decision";
  return `<article class="activity"><div><p class="post-meta">${escape(sourceState)} · ${escape(communityState)}</p><h2>${escape(item.title)}</h2><p>${escape(item.body)}</p></div>${item.currentSource ? `<form method="post" action="/author/edit" class="stack compact"><input type="hidden" name="itemId" value="${escape(item.itemId)}"><label>Edit title<input name="title" maxlength="140" value="${escape(item.title)}" required></label><label>Edit original<textarea name="body" maxlength="20000" rows="4" required>${escape(item.body)}</textarea></label><button>Update my original</button></form><form method="post" action="/author/delete"><input type="hidden" name="itemId" value="${escape(item.itemId)}"><button class="danger">Delete my original</button></form>` : ""}${projected && projected.lifecycleState !== "author_withdrawn" && projected.lifecycleState !== "removed" ? `<form method="post" action="/author/withdraw"><input type="hidden" name="itemId" value="${escape(item.itemId)}"><input type="hidden" name="projection" value="${escape(projected.projectionIdentity)}"><button class="quiet">Ask Juniper to stop featuring it</button></form>` : ""}${projected ? `<a href="/post?projection=${encodeURIComponent(projected.projectionIdentity)}">See the community view</a>` : ""}</article>`;
}

function post(bundle: ProjectionBundle, projection: string | undefined): string {
  const entry = find(bundle.ordinary, projection);
  if (!entry) return notFound("That community item is not in the published artifact.");
  return `<section class="single wide"><a href="/">← Community feed</a>${card(entry)}<aside class="distinction"><h2>Two controls, kept separate</h2><div><p><b>The author controls the original.</b> They can edit or delete it.</p><p><b>Juniper controls this feed.</b> It can feature or remove its own reference without changing the original.</p></div></aside></section>`;
}

function receipt(bundle: ProjectionBundle, projection: string | undefined): string {
  const entry = find(bundle.audit, projection);
  if (!entry) return notFound("No matching published audit receipt is available.");
  const receipts = Object.entries(entry.technicalReceipts ?? {}).filter(([, value]) => value !== null);
  return `<section class="single wide receipt"><p class="eyebrow">Technical receipt</p><h1>Who did what, to which version?</h1><ol class="receipt-story"><li>The author submitted <code>${escape(entry.sourceUri)}</code> at exact CID <code>${escape(entry.admittedSourceCid)}</code>.</li><li>Juniper admitted that occurrence at ${escape(humanTime(entry.admittedAt))}.</li><li>The qualified projection now reports <b>${escape(stateLabel(entry))}</b>.</li></ol><dl>${receipts.map(([key, value]) => `<div><dt>${escape(humanKey(key))}</dt><dd><code>${escape(value!)}</code></dd></div>`).join("")}</dl><p class="nonclaim">These references explain the bounded event chain. They are not a claim that the post is true, popular, or owned by Juniper.</p></section>`;
}

function find(feed: ProjectionBundle["ordinary"], projection: string | undefined): PublicEntry | undefined {
  return projection ? feed?.entries.find((entry) => entry.projectionIdentity === projection) : undefined;
}

function emptyFeed(): string {
  return `<div class="empty"><h3>Nothing has been featured yet.</h3><p>The first author submission will appear only after Juniper makes and the observer qualifies a separate editorial decision.</p></div>`;
}

function notFound(message: string): string { return `<section class="single"><h1>Not found</h1><p>${escape(message)}</p></section>`; }
function notice(value: string | undefined): string { return value ? `<div class="notice">${escape(value)}</div>` : ""; }
function footer(): string { return `<footer><p>Juniper Commons is a disposable Spaces Alpha community. Authors keep their originals; Juniper keeps its editorial receipts.</p></footer>`; }
function label(path: string): string { return ({ "/create": "Create", "/mine": "Your activity", "/post": "Community item", "/receipt": "Receipt" } as Record<string, string>)[path] ?? "Juniper"; }
function shortDid(did: string): string { return `${did.slice(0, 16)}…`; }
function stateLabel(entry: PublicEntry): string {
  if (entry.lifecycleState === "source_unavailable" && entry.sourceRelationship === "deleted_by_author") return "The author took down the original";
  return ({ added: "Featured by Juniper", changed_at_source: "The author updated the original", source_unavailable: "We can’t reach the original", author_withdrawn: "The author asked not to be featured", removed: "Removed by Juniper" })[entry.lifecycleState];
}
function lifecycleTitle(entry: PublicEntry): string {
  if (entry.lifecycleState === "source_unavailable" && entry.sourceRelationship === "deleted_by_author") return "The author took this post down";
  return ({ added: "Featured post", changed_at_source: "The admitted version and source now differ", source_unavailable: "Original currently unavailable", author_withdrawn: "Author withdrew this presentation", removed: "Juniper removed this item" })[entry.lifecycleState];
}
function lifecycleCopy(entry: PublicEntry): string {
  if (entry.lifecycleState === "source_unavailable" && entry.sourceRelationship === "deleted_by_author") return "The author deleted the original. Juniper keeps the editorial receipt, not replacement content.";
  return ({ added: "The source still matches the exact version Juniper admitted.", changed_at_source: "The author changed the original after Juniper made its decision. Juniper does not silently substitute the new version.", source_unavailable: "Juniper previously admitted an exact version, but the source cannot currently be observed. This may be temporary.", author_withdrawn: "The historical community decision remains inspectable, but the author’s presentation is no longer active.", removed: "Juniper stopped showing this item. The author’s source was not changed." })[entry.lifecycleState];
}
function humanTime(value: string): string { const date = new Date(value); return Number.isFinite(date.valueOf()) ? date.toLocaleString("en-US", { dateStyle: "long", timeStyle: "short", timeZone: "UTC" }) + " UTC" : value; }
function humanKey(value: string): string { return value.replace(/[A-Z]/g, (letter) => ` ${letter.toLowerCase()}`).replace(/Id$/, ""); }
function escape(value: string): string { return value.replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!); }
