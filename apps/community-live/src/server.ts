import { AsyncLocalStorage } from "node:async_hooks";
import { displayPreference, parseDisplayPreference, displayPreferenceCookie, type DisplayPreference } from "./display.js";
import type { OAuthSession } from "@atproto/oauth-client-node";
import { createHash, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import { readFile, rm } from "node:fs/promises";
import { HOUR_MS, retentionSweep } from "./retention.js";
import { PUBLIC_PAGE_PATHS, publicFooter, publicPage } from "./public-pages.js";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { join } from "node:path";

import { LabelwatchDirectory, renderLabels, type LabelDirectory } from "./labels.js";

import { intakeOpen, supportedPds, isP0, P0_SCOPE, READER_SCOPE, QUIET_SCOPE, FEED_SCOPE, FEED_QUIET_SCOPE, CURATION_SCOPE, CURATION_QUIET_SCOPE, hasCurationScope, hasFeedScope, hasReaderScope, hasQuietScope, P0Reservations, requireBlueskySession, requireSiteWrites } from "./p0.js";
import { ActivitySnapshots, FileSeenStore, type DiscussionActivity } from "./activity.js";
import { loadConfig, type AppConfig } from "./config.js";
import {
  ContributionService,
  deterministicTid,
  existingPostOperationId,
  POST_COLLECTION,
  submissionRkey,
  SUBMIT_COLLECTION,
  userMessage,
  type ContributionPlan,
  type StrongRef,
} from "./contributions.js";
import { escapeHtml, externalHttpsUrl, isValidPostUri, parsePostReference, PostReferenceError, type PostReference } from "./html.js";
import { HttpError } from "./http-error.js";
import { TrustedModeratorBroker, UnixAuthorityRequester, type AuthorityRequester, type ModeratorCommand } from "./moderation.js";
import { clientMetadata, createOAuthClient, OAUTH_SCOPE } from "./oauth.js";
import { ObserverClient, ProjectionTooLargeError, type CommunityProjection } from "./observer.js";
import { DurableWriteJournal, type PublicRepoWriter, type RecordAddress } from "./operations.js";
import { renderIdentity, COMMUNITY_VIEW_BADGE, humanDate, postedAt, publicPostLink, snippet, whyHere } from "./presentation.js";
import { AppViewProfileDirectory, ProfileCache, type HydratedProfile, type ProfileDirectory } from "./profiles.js";
import { AppViewPostDirectory, PostCache, type HydratedPost, type PostDirectory } from "./posts.js";
import { OAuthPublicRepoWriter } from "./repo-writer.js";
import { PostCommitFaultWriter } from "./faults.js";
import { ContributionPlanStore, WebSessionStore, type WebSession } from "./storage.js";

import { Reader, PublicBlockDirectory , type ThreadResult } from "./reader.js";
import { renderFeed, renderPost, renderReplies, renderThread, threadHref } from "./reader-view.js";
import { AppBskyFeedDefs } from "@atproto/api";
import { QuietStore } from "./quiet.js";
import { marker, renderOmissions, type Omissions } from "./attention.js";
import { PublicThreadReader, SignedOutViewer } from "./public-thread.js";
import { LocalQuietStore } from "./local-quiet.js";
import { PersonalFeedStore, type PersonalFeedInput } from "./personal-feeds.js";
import { personalFeedForm, personalFeedList, curationDetails, READER_HELP } from "./personal-feed-view.js";

const displayContext = new AsyncLocalStorage<{ theme: DisplayPreference; path: string }>();

const COOKIE = "community_session";
// Binds an OAuth callback to the browser that started the sign-in: the nonce
// travels in the OAuth state and, separately, in this short-lived cookie.
const LOGIN_COOKIE = "community_login";
const LOGIN_COOKIE_MAX_AGE = 600;
const MAX_FORM_BYTES = 64 * 1024;
const DISCUSSIONS_PAGE_SIZE = 25;
const REMOVED_ROOT_TITLE = "Removed from the community";
const UNFINISHED_ACTIONS_LIMIT = 25;
// Same record-key character class as the post AT URI pattern in html.ts.
const RKEY_PATTERN = /^[a-zA-Z0-9._:-]{1,512}$/;

interface OAuthFacade {
  authorize(input: string, options: { scope: string; state?: string }): Promise<URL>;
  callback(params: URLSearchParams): Promise<{ session: OAuthSession; state?: string | null }>;
  restore(did: string): Promise<OAuthSession>;
  /** Revoke the account's tokens at its provider (best effort) and delete them here. */
  revoke?(did: string): Promise<void>;
}

export interface Dependencies {
  config: AppConfig;
  labels?: LabelDirectory;
  quiet?: QuietStore;
  localQuiet?: LocalQuietStore;
  personalFeeds?: PersonalFeedStore;
  publicBlocks?: { read(did: string): Promise<{excludedDids: string[]; checkedAt: string; recordCount: number}> };
  reader?: (session: OAuthSession) => Reader;
  /** Unauthenticated public thread reads, used only for an admitted post's exact URI. */
  publicThreads?: { read(uri: string): Promise<ThreadResult> };
  oauth: OAuthFacade;
  webSessions: WebSessionStore;
  plans: ContributionPlanStore;
  activities: ActivitySnapshots;
  authority: AuthorityRequester;
  projection: CommunityProjection;
  profiles: ProfileDirectory;
  /** Test seam; production writes through the participant's OAuth session. */
  repoWriter?: (session: OAuthSession, did: string) => PublicRepoWriter;
  posts?: PostDirectory;
  /** Read-only DID custody qualification; fake implementations are local fixtures only. */
  p0Identity?: (did: string) => Promise<boolean>;
}

export function createHandler(deps: Dependencies) {
  return async (request: IncomingMessage, response: ServerResponse): Promise<void> => {
    return displayContext.run({ theme: parseDisplayPreference(request.headers.cookie), path: (request.url ?? "/").split("?")[0] ?? "/" }, async () => {
    try {
      await route(deps, request, response);
    } catch (error) {
      const status = error instanceof HttpError && ((error.status >= 400 && error.status < 500) || error.status === 503)
        ? error.status
        : 500;
      if (status === 401 && request.method === "GET" && isP0(deps.config) && deps.config.readerEnabled) {
        const url = new URL(request.url ?? "/", deps.config.publicUrl);
        if (SIGNIN_DOCUMENT_PATHS.has(url.pathname)) {
          noStore(response);
          return redirect(response, signinHref(returnPath(url.pathname + url.search, true) ?? returnPath(url.pathname, true) ?? "/home"), deps.config);
        }
      }
      html(response, status, page(deps.config, null, errorTitle(status, error), errorBody(status, error, deps.config)), deps.config);
    }
    });
  };
}

/** Place-level failure: the community's projection could not be read for `/` or `/d/`. */
class CommunityUnavailableError extends HttpError {
  public constructor() {
    super(500, "Try again in a moment.");
    this.name = "CommunityUnavailableError";
  }
}

function communityUnavailable(error: unknown): never {
  if (error instanceof HttpError || error instanceof ProjectionTooLargeError) throw error;
  throw new CommunityUnavailableError();
}

function errorTitle(status: number, error: unknown): string {
  if (error instanceof CommunityUnavailableError) return "This community can't be shown right now";
  switch (status) {
    case 400: return "That request was not understood";
    case 401: return "Sign in is required";
    case 403: return "That is not permitted";
    case 404: return "Not found";
    case 409: return "That action could not be confirmed";
    case 503: return "That could not be checked right now";
    default: return "Something went wrong";
  }
}

function errorBody(status: number, error: unknown, config: AppConfig): string {
  const message = error instanceof CommunityUnavailableError || (error instanceof HttpError && status !== 500)
    ? error.message
    : "An unexpected error interrupted that step. Try again.";
  const signin = status === 401 ? (isP0(config) && config.readerEnabled ? '<p><a href="/signin">Sign in to Phlogiston</a></p>' : signInForm(config)) : "";
  return `<p class="error-message">${escapeHtml(message)}</p>${signin}<p><a href="/">Return to the community</a></p>`;
}

async function route(deps: Dependencies, request: IncomingMessage, response: ServerResponse): Promise<void> {
  const method = request.method ?? "GET";
  const url = new URL(request.url ?? "/", deps.config.publicUrl);
  if (method === "GET" && url.pathname === "/healthz") return text(response, 200, "ok\n", deps.config);
  if (method === "GET" && url.pathname === "/oauth-client-metadata.json") {
    return json(response, 200, clientMetadata(deps.config), deps.config);
  }
  if (method === "GET" && ["/static/workspace.js", "/static/workspace-state.js", "/static/forget.js"].includes(url.pathname)) {
    const body = await readFile(new URL(`../static/${url.pathname.split("/").at(-1)}`, import.meta.url));
    secure(response, deps.config); response.setHeader("Content-Type", "text/javascript; charset=utf-8"); response.setHeader("Cache-Control", "no-cache"); response.end(body); return;
  }
  if (method === "GET" && url.pathname === "/static/app.css") return stylesheet(response, deps.config);
  if (method === "POST") requireOrigin(request, deps.config.publicUrl);

  if (method === "POST" && url.pathname === "/oauth/login") {
    const form = await readForm(request);
    const handle = required(form, "handle").replace(/^@/, "");
    const returnTo = returnPath(form.get("return"), deps.config.readerEnabled);
    const nonce = randomBytes(16).toString("base64url");
    let target: URL;
    try {
      target = await deps.oauth.authorize(handle, { scope: isP0(deps.config) ? (deps.config.readerEnabled ? (form.get("access") === "curation-quiet" ? CURATION_QUIET_SCOPE : form.get("access") === "curation" ? CURATION_SCOPE : form.get("access") === "quiet" ? FEED_QUIET_SCOPE : form.get("access") === "feeds" ? FEED_SCOPE : READER_SCOPE) : P0_SCOPE) : OAUTH_SCOPE, state: loginState(nonce, returnTo) });
    } catch {
      throw new HttpError(400, "That handle could not be found. Check it and try again.");
    }
    response.setHeader("Set-Cookie", loginCookie(nonce, deps.config.publicUrl));
    return redirect(response, target.toString(), deps.config);
  }
  if (method === "GET" && url.pathname === "/oauth/callback") {
    const incomplete = (): HttpError => {
      response.setHeader("Set-Cookie", clearedLoginCookie(deps.config.publicUrl));
      return new HttpError(400, "Sign-in was not completed. Nothing changed.");
    };
    const expected = cookieValue(request.headers.cookie, LOGIN_COOKIE);
    if (expected === undefined) throw incomplete();
    let result: { session: OAuthSession; state?: string | null };
    try {
      result = await deps.oauth.callback(url.searchParams);
    } catch {
      throw incomplete();
    }
    const state = parseLoginState(result.state, deps.config.readerEnabled);
    if (state === undefined || !sameToken(state.nonce, expected)) {
      // The authorization server answered for a sign-in this browser did not
      // start; the session it produced is not kept.
      try {
        await result.session.signOut();
      } catch {
        // Best effort; the session is not used either way.
      }
      throw incomplete();
    }
    let grantedScopes: string | undefined;
    if (isP0(deps.config)) {
      try { grantedScopes = await requireBlueskySession(result.session, result.session.did, deps.config); } catch (error) { await result.session.signOut().catch(() => undefined); throw error; }
    }
    const issued = await deps.webSessions.issue(result.session.did, new Date(), grantedScopes);
    response.setHeader("Set-Cookie", [cookie(issued.token, deps.config.publicUrl), clearedLoginCookie(deps.config.publicUrl)]);
    noStore(response);
    return redirect(response, state.returnTo ?? (isP0(deps.config) ? "/home" : "/"), deps.config);
  }

  const token = cookieValue(request.headers.cookie, COOKIE);
  const webSession = await deps.webSessions.resolve(token);
  // Nothing rendered for a signed-in participant may be kept by a shared
  // browser or an intermediary; the header is set before any route so error
  // pages carry it too.
  if (webSession !== null) noStore(response);
  if (method === "GET" && url.pathname === "/signin" && isP0(deps.config) && deps.config.readerEnabled) {
    noStore(response);
    const destination = returnPath(url.searchParams.get("return"), true) ?? "/home";
    if (webSession) return redirect(response, destination, deps.config);
    return html(response, 200, page(deps.config, null, "Sign in to Phlogiston", `${productIntro(false)}${signInForm(deps.config, destination)}${accountAvailability()}<p><a href="/community">Explore The Cabinet without signing in</a></p>`), deps.config);
  }
  if (method === "GET" && url.pathname === "/help" && isP0(deps.config)) return html(response, 200, page(deps.config, webSession, "Getting started", READER_HELP), deps.config);
  if (url.pathname === "/display") {
    if (method === "POST") {
      const form = webSession ? await checkedForm(deps, request, webSession) : await readForm(request);
      const choice = required(form, "display");
      if (!["light", "dark", "system"].includes(choice)) throw new HttpError(400, "Choose Light, Dark, or System.");
      response.setHeader("Set-Cookie", displayPreferenceCookie(displayPreference(choice), deps.config.publicUrl));
      noStore(response);
      return redirect(response, form.get("return") === "/settings" && webSession ? "/settings" : "/display", deps.config);
    }
    if (method === "GET") return html(response, 200, page(deps.config, webSession, "Display", displayForm(webSession)), deps.config);
    throw new HttpError(404, "Not found.");
  }
  if (method === "GET" && url.pathname === "/" && webSession && deps.config.readerEnabled && !url.search) return redirect(response, "/home", deps.config);
  if (method === "GET" && ["/", "/community"].includes(url.pathname)) {
    let reader: Reader | undefined;
    if (webSession && deps.config.readerEnabled) {
      try { const oauthSession = await restoredSession(deps, response, token, webSession); const scope = await requireBlueskySession(oauthSession, webSession.did, deps.config); if (hasReaderScope(scope, deps.config)) reader = deps.reader?.(oauthSession) ?? new Reader(oauthSession); } catch { /* Public collection remains available independently. */ }
    }
    return home(deps, response, webSession, url.searchParams, reader);
  }
  if (method === "GET" && url.pathname.startsWith("/d/")) {
    const rkey = validRkey(url.pathname.slice("/d/".length));
    let reader: Reader | undefined;
    if (webSession && isP0(deps.config) && deps.config.readerEnabled) {
      try { const oauthSession = await restoredSession(deps, response, token, webSession); const scope = await requireBlueskySession(oauthSession, webSession.did, deps.config); if (hasReaderScope(scope, deps.config)) reader = deps.reader?.(oauthSession) ?? new Reader(oauthSession); } catch { /* The admitted post remains available independently. */ }
    }
    return discussion(deps, response, webSession, rkey, reader);
  }
  if (method === "GET" && url.pathname === "/discussion") {
    return redirect(response, discussionHref(validRkey(required(url.searchParams, "rkey"))), deps.config);
  }
  if (method === "GET" && isP0(deps.config) && PUBLIC_PAGE_PATHS.has(url.pathname)) {
    const { title, body } = publicPage(url.pathname);
    return html(response, 200, page(deps.config, webSession, title, body), deps.config);
  }
  if (webSession === null) {
    if (method === "GET" && isP0(deps.config) && deps.config.readerEnabled && SIGNIN_DOCUMENT_PATHS.has(url.pathname)) {
      noStore(response);
      const destination = returnPath(url.pathname + url.search, true) ?? returnPath(url.pathname, true) ?? "/home";
      return redirect(response, signinHref(destination), deps.config);
    }
    throw new HttpError(401, "Sign in is required to view this page.");
  }

  if (isP0(deps.config) && deps.config.readerEnabled && ["/home", "/feed", "/feeds", "/thread", "/context", "/sources", "/local-quiet", "/attention", "/quiet"].includes(url.pathname)) {
    if (method !== "GET" && !(method === "POST" && ["/quiet", "/local-quiet", "/feeds"].includes(url.pathname))) throw new HttpError(404, "Not found.");
    const oauthSession = await restoredSession(deps, response, token, webSession);
    const scope = await requireBlueskySession(oauthSession, webSession.did, deps.config);
    if (!hasReaderScope(scope, deps.config)) return html(response, 200, page(deps.config, webSession, "Your Following feed", `<p>Connect your Bluesky feed to read the people you follow here. Your existing community access still works.</p>${readerConnect(webSession, "/home", false)}`), deps.config);
    const reader = deps.reader?.(oauthSession) ?? new Reader(oauthSession);
    try {
    if (url.pathname === "/feeds") {
      if (!deps.personalFeeds || !deps.publicBlocks) throw new HttpError(503, "Personal feeds are unavailable.");
      if (!hasCurationScope(scope, deps.config)) return html(response, 200, page(deps.config, webSession, "Create a personal feed", curationConnect(webSession, hasQuietScope(scope, deps.config))), deps.config);
      let id = url.searchParams.get("edit") ?? undefined;
      let value: PersonalFeedInput | undefined;
      let preview = "";
      if (method === "POST") {
        const form = await checkedForm(deps, request, webSession);
        id = form.get("id") || undefined;
        if (id && !deps.personalFeeds.get(webSession.did, id)) throw new HttpError(404, "Personal feed not found.");
        const action = required(form, "action");
        if (action === "delete") {
          if (!id) throw new HttpError(400, "Choose a saved feed.");
          await requireSiteWrites(deps.config);
          deps.localQuiet?.clearFeed(webSession.did, `personal:${id}`);
          deps.personalFeeds.remove(webSession.did, id);
          return redirect(response, "/feeds", deps.config);
        }
        if (!["preview", "save"].includes(action)) throw new HttpError(400, "Choose Preview or Save.");
        const name = required(form, "name").trim();
        if (!name || [...name].length > 80 || /[\u0000-\u001f\u007f]/.test(name)) throw new HttpError(400, "Use a feed name of 1–80 characters.");
        const curator = await reader.curatorProfile(required(form, "curator").trim().replace(/^@/, ""));
        const blocks = await readCuratorBlocks(deps,curator.did);
        value = {name, sources:[{kind:"following"}], policies:{publicBlocks:{curatorDid:curator.did,curatorHandle:curator.handle}}, transformations:{includeReplies:form.get("replies")==="yes",includeReposts:form.get("reposts")==="yes"},ordering:"upstream",publishing:null};
        if (action === "save") {
          await requireSiteWrites(deps.config);
          const saved = id ? deps.personalFeeds.update(webSession.did, id, value) : deps.personalFeeds.create(webSession.did, value);
          if (!saved) throw new HttpError(404, "Personal feed not found.");
          return redirect(response, `/feeds?edit=${saved.id}&saved=1`, deps.config);
        }
        const previewReader = deps.reader?.(oauthSession) ?? new Reader(oauthSession);
        const feed = await previewReader.following(undefined, {...value.transformations,excludedDids:new Set(blocks.excludedDids)});
        preview = `<section class="personal-preview"><h2>Preview</h2>${feed.items.length ? renderFeed(previewReader, feed.items) : "<p>No posts remain in this sample. This does not mean your wider Following feed is empty.</p>"}${curationDetails(value.policies.publicBlocks,blocks.checkedAt,blocks.recordCount,feed.omitted["curator-blocks"] ?? 0)}</section>`;
      } else if (id) {
        value = deps.personalFeeds.get(webSession.did, id);
        if (!value) throw new HttpError(404, "Personal feed not found.");
      }
      return html(response, 200, page(deps.config, webSession, id ? "Edit personal feed" : "Create a personal feed", `<p>Borrow another account's perspective without becoming that account.</p><p>Start with your Following timeline, then add exclusions from a public account's direct blocks. Your own Bluesky viewing settings still apply.</p>${url.searchParams.get("saved") === "1" ? '<p role="status">Feed saved. Open it below in either view.</p>' : ""}${personalFeedForm(webSession.csrf,value,id)}${preview}${personalFeedList(deps.personalFeeds.list(webSession.did),webSession.csrf)}<p><a href="/help">Feeds, communities, and what works today</a></p>`), deps.config);
    }
    if (url.pathname === "/sources") {
      const sources = [{uri: "following", name: "Following", href: "/home"}, {uri: "community", name: "The Cabinet", href: "/community"}];
      let available = hasFeedScope(scope, deps.config);
      if (available) {
        try { for (const feed of await reader.savedFeeds()) sources.push({...feed, href: `/home?feed=${encodeURIComponent(feed.uri)}`}); }
        catch { available = false; }
      }
      for (const feed of deps.personalFeeds?.list(webSession.did) ?? []) sources.push({uri:`personal:${feed.id}`,name:feed.name,href:`/home?personal=${feed.id}`});
      return json(response, 200, {sources, feedsConnected: hasFeedScope(scope, deps.config), feedsAvailable: available}, deps.config);
    }
    if (url.pathname === "/local-quiet") {
      if (!deps.localQuiet) throw new HttpError(503, "Local conversation controls are unavailable.");
      if (method === "GET") { const key = url.searchParams.get("feed") ?? "following"; requirePersonalFeed(deps,webSession.did,key); return json(response, 200, {roots: deps.localQuiet.list(webSession.did, key)}, deps.config); }
      const form = await checkedForm(deps, request, webSession);
      await requireSiteWrites(deps.config);
      const feed = required(form, "feed");
      requirePersonalFeed(deps,webSession.did,feed);
      // Store validates exact feed keys before a read or mutation.
      deps.localQuiet.list(webSession.did, feed);
      const action = required(form, "action");
      if (!["quiet", "restore"].includes(action)) throw new HttpError(400, "Choose quiet or restore.");
      const uri = required(form, "uri");
      const root = action === "restore" ? required(form, "root") : await reader.resolveRoot(uri);
      // Undo removes only an existing local preference; an unavailable upstream
      // post must not trap the participant in a preference they cannot undo.
      await requireSiteWrites(deps.config);
      if (action === "restore") deps.localQuiet.remove(webSession.did, feed, root);
      else deps.localQuiet.set(webSession.did, feed, root);
      return json(response, 200, {root, feed, quiet: action === "quiet", providerChanged: false}, deps.config);
    }
    if (url.pathname === "/context") {
      const uri = required(url.searchParams, "uri");
      if (!isValidPostUri(uri)) throw new HttpError(400, "A valid post link is required.");
      const thread = await reader.thread(uri);
      const post = "post" in thread ? thread.post : null;
      if (!post || post.uri !== uri) throw new HttpError(404, "Post context is unavailable.");
      const decision = reader.decision(post, "contentView");
      if (decision.filter || decision.noOverride || decision.blur) throw new HttpError(403, "This post is hidden by your viewing settings.");
      const context = await deps.labels?.lookup(post.author.did).catch(() => null) ?? null;
      const relevant = context ? {...context, rows: context.rows.filter(row => row.uri === uri || row.uri === post.author.did)} : null;
      const labels = [...(post.labels ?? []), ...(post.author.labels ?? [])].slice(0, 30);
      const rows = labels.map(label => `<li>${escapeHtml(label.val)} <small>From ${escapeHtml(label.src)} · ${label.neg ? "removal" : "application"}</small></li>`).join("");
      return html(response, 200, page(deps.config, webSession, "Post context", `<h2>Labels supplied with this post</h2>${rows ? `<ul>${rows}</ul>` : "<p>No labels were supplied with this post.</p>"}<h2>Independent observations</h2><p>Labelwatch observations below concern this account and this exact post. They do not establish current label state or community admission.</p>${renderLabels(relevant, post.author.did, "post")}<p><a href="${escapeHtml(threadHref(uri))}">Open conversation</a></p>`), deps.config);
    }
    if (method === "POST") {
      const form = await checkedForm(deps, request, webSession);
      if (!hasQuietScope(scope, deps.config)) throw new HttpError(403, "Connect conversation controls before taking this action.");
      if (!deps.quiet) throw new HttpError(503, "Conversation controls are unavailable.");
      await requireSiteWrites(deps.config);
      const uri = required(form, "uri");
      const root = await reader.resolveRoot(uri);
      if (root !== required(form, "root")) throw new HttpError(409, "The conversation root could not be confirmed. No action was sent.");
      const action = required(form, "action");
      if (!["quiet", "restore"].includes(action)) throw new HttpError(400, "Choose a conversation action.");
      const current = await reader.readQuiet(root);
      deps.quiet.reconcile(webSession.did, root, current);
      const desired = action === "quiet";
      const matched = await deps.quiet.apply(webSession.did, root, desired, () => reader.setQuiet(root, desired, () => requireSiteWrites(deps.config)), () => reader.readQuiet(root));
      if (!matched) throw new HttpError(409, "The provider still reports the previous conversation setting. The requested change is not confirmed.");
      return redirect(response, threadHref(root), deps.config);
    }
    if (url.pathname === "/attention") {
      const records = deps.quiet?.list(webSession.did) ?? [];
      return html(response, 200, page(deps.config, webSession, "Conversation controls", `<p>Bluesky thread notification mutes are listed here. These also affect Following. Local “Quiet here” choices are separate and can be reviewed within each feed. Open a conversation to check its current setting or undo it.</p><ul>${records.map(item => `<li><a href="${escapeHtml(threadHref(item.root))}">Open conversation</a> · Last check: ${item.status === "unknown" ? "outcome unknown—check before acting again" : item.status === "muted" ? "quieted" : "restored"}</li>`).join("") || "<li>No conversation actions yet.</li>"}</ul><p>Settings are checked with your account provider when you open a conversation. This list records actions taken here; it is not a complete inventory of your Bluesky mutes.</p>`), deps.config);
    }
    if (url.pathname === "/thread") {
      const uri = required(url.searchParams, "uri");
      if (!isValidPostUri(uri)) throw new HttpError(400, "A valid post link is required.");
      const thread = await reader.thread(uri);
      const declaredRoot = AppBskyFeedDefs.isThreadViewPost(thread) ? (thread.post.record as {reply?: {root?: {uri?: unknown}}}).reply?.root?.uri : undefined;
      const placement = await admittedDiscussion(deps, [uri, ...(typeof declaredRoot === "string" ? [declaredRoot] : [])]);
      const community = placement ? `<p class="community-context">${placement.uri === uri ? "This post is" : "This conversation starts from a post"} in ${escapeHtml(deps.config.communityName)}. <a href="${escapeHtml(discussionHref(placement.rkey))}">Open it there</a></p>` : "";
      let controls = "<p>Conversation controls are unavailable for this thread.</p>";
      try {
        const root = await reader.resolveRoot(uri);
        const quiet = await reader.readQuiet(root);
        deps.quiet?.reconcile(webSession.did, root, quiet);
        const unresolved = deps.quiet?.list(webSession.did).some(item => item.root === root && item.status === "unknown") === true;
        controls = unresolved ? '<p class="notice">An earlier request did not confirm completion. Further conversation changes are paused for this thread while its outcome is checked. A current setting alone cannot settle an interrupted request.</p>' : hasQuietScope(scope, deps.config) ? `<form method="post" action="/quiet" class="quiet-control"><input type="hidden" name="csrf" value="${escapeHtml(webSession.csrf)}"><input type="hidden" name="uri" value="${escapeHtml(uri)}"><input type="hidden" name="root" value="${escapeHtml(root)}"><input type="hidden" name="action" value="${quiet ? "restore" : "quiet"}"><p>${quiet ? "This conversation is quieted in Following." : "Had enough of this conversation?"}</p><button>${quiet ? "Unmute Bluesky notifications" : "Mute Bluesky notifications"}</button><p class="muted">${quiet ? "Restoring also unmutes" : "Quieting also mutes"} this thread’s notifications in Bluesky. It does not mute the person or change community decisions.</p></form>` : `<details class="quiet-control"><summary>Bluesky notification controls</summary><p>Hide this conversation from Following here. This also mutes its thread notifications in Bluesky. You can undo it here.</p>${readerConnect(webSession, threadHref(uri), true)}</details>`;
      } catch { /* Unknown lineage or readback never becomes a guessed action. */ }
      return html(response, 200, page(deps.config, webSession, "Conversation", `<p class="reader-back"><a href="/home">Back to Following</a></p>${community}${renderThread(reader, thread, controls)}<p><a href="/attention">Manage conversation controls</a></p>`), deps.config);
    }
    const feedUri = url.searchParams.get("feed");
    const personalId = url.searchParams.get("personal");
    if (feedUri && personalId) throw new HttpError(400, "Choose one content source.");
    if (personalId && !hasCurationScope(scope, deps.config)) return html(response, 200, page(deps.config, webSession, "Connect personal feeds", curationConnect(webSession,hasQuietScope(scope,deps.config))), deps.config);
    if (feedUri && !hasFeedScope(scope, deps.config)) return html(response, 200, page(deps.config, webSession, "Connect saved feeds", `<p>Allow access to your saved custom feeds. Following and your community access remain available.</p>${readerConnect(webSession, "/home", false, true)}`), deps.config);
    if (feedUri && !(await reader.savedFeeds()).some(feed => feed.uri === feedUri)) throw new HttpError(400, "Choose one of your saved feeds.");
    const personal = personalId ? deps.personalFeeds?.get(webSession.did,personalId) : undefined;
    if (personalId && !personal) throw new HttpError(404, "Personal feed not found.");
    const revision = personal ? createHash("sha256").update(JSON.stringify(personal)).digest("hex") : undefined;
    if (personal && url.searchParams.has("cursor") && url.searchParams.get("revision") !== revision) throw new HttpError(409, "This feed definition changed. Refresh before continuing.");
    const blocks = personal ? await readCuratorBlocks(deps,personal.policies.publicBlocks.curatorDid) : undefined;
    if (personal && !blocks) throw new HttpError(503, "The curator's public blocks could not be checked. This feed has not been shown without them.");
    const activeReader = personal ? (deps.reader?.(oauthSession) ?? new Reader(oauthSession)) : reader;
    const cursor = url.searchParams.get("cursor") ?? undefined;
    const feed = personal && blocks ? await activeReader.following(cursor,{...personal.transformations,excludedDids:new Set(blocks.excludedDids)}) : feedUri ? await reader.feed(feedUri, cursor) : await reader.following(cursor);
    const feedKey = personal ? `personal:${personal.id}` : feedUri ?? "following";
    const roots = new Set(deps.localQuiet?.list(webSession.did, feedKey) ?? []);
    const items = feed.items.filter(item => {
      const record = item.post.record as {reply?: {root?: {uri?: unknown}}};
      const root = record.reply ? record.reply.root?.uri : item.post.uri;
      return typeof root !== "string" || !roots.has(root);
    });
    const omitted: Omissions = {...feed.omitted, ...(items.length < feed.items.length ? {"local-quiet": feed.items.length - items.length} : {})};
    const attention = renderOmissions(items.length, omitted, {labelers: feed.labelers, ...(personal ? {curatorHandle: personal.policies.publicBlocks.curatorHandle, editHref: `/feeds?edit=${personal.id}`} : {})});
    const order = feedUri ? "Posts stay in the order this feed’s publisher returned them. Phlogiston does not rank these posts and cannot say why the feed ordered them this way."
      : "Posts stay in the order Bluesky returned them. Phlogiston does not rank these posts and cannot say why Bluesky ordered them this way.";
    const next = new URLSearchParams(); if(personal){next.set("personal",personal.id);next.set("revision",revision!);} if (feedUri) next.set("feed", feedUri); if (feed.cursor) next.set("cursor", feed.cursor);
    const title = personal?.name ?? (feedUri ? "Custom feed" : "Following");
    const personalInfo = personal && blocks ? `<p class="personal-feed-summary">Your Following, with exclusions from @${escapeHtml(personal.policies.publicBlocks.curatorHandle)} · <a href="/feeds?edit=${personal.id}">Edit feed</a></p>${curationDetails(personal.policies.publicBlocks,blocks.checkedAt,blocks.recordCount,feed.omitted["curator-blocks"] ?? 0)}` : "";
    return html(response, 200, page(deps.config, webSession, title, `<div class="feed-surface" data-feed-key="${escapeHtml(feedKey)}">${personalInfo}${attention}${renderFeed(activeReader, items)}${items.length === 0 ? '<p class="feed-empty">No posts to show on this page.</p>' : ""}${feed.cursor ? `<p class="feed-next"><a href="/home?${escapeHtml(next.toString())}">Continue reading</a></p>` : ""}<details class="reader-details"><summary>About this feed</summary><p>${order} Viewing preferences apply. Up to 90 posts are checked per page. Local quiet applies only to this selected feed; it does not change Bluesky notifications.</p><p><a href="/attention">Conversation controls</a> · <a href="/labels">Labels observed on your account</a></p></details></div>`), deps.config);
    } catch (error) {
      if (error instanceof HttpError) throw error;
      throw new HttpError(503, "Your feed or conversation could not be checked right now. No unverified content or conversation setting is being shown. Try again, or visit Community.");
    }
  }

  if (isP0(deps.config) && method === "GET" && ["/home", "/labels", "/settings"].includes(url.pathname)) {
    await restoredSession(deps, response, token, webSession);
    if (url.pathname === "/home") return participantHome(deps, response, webSession);
    if (url.pathname === "/labels") return participantLabels(deps, response, webSession);
    return participantSettings(deps, response, webSession);
  }

  if (method === "POST" && url.pathname === "/signout") {
    await checkedForm(deps, request, webSession);
    await endAccountAccess(deps, webSession.did);
    response.setHeader("Set-Cookie", clearedCookie(deps.config.publicUrl));
    return redirect(response, "/", deps.config);
  }
  if (method === "POST" && url.pathname === "/disconnect") {
    await checkedForm(deps, request, webSession);
    await endAccountAccess(deps, webSession.did);
    response.setHeader("Set-Cookie", clearedCookie(deps.config.publicUrl));
    return html(response, 200, page(deps.config, null, "Disconnected", [
      "<p>Disconnect revoked this app’s access to your account and ended its sessions in every browser.</p>",
      "<ul>",
      "<li>Your public posts remain public on your PDS.</li>",
      "<li>Community admission history is unchanged.</li>",
      "<li>Settings kept here are not deleted; use Delete my Phlogiston data in Settings for that.</li>",
      "<li>You can sign back in at any time.</li>",
      "</ul>",
      '<p><a href="/">Return to the community</a></p>',
    ].join("")), deps.config);
  }
  if (method === "POST" && url.pathname === "/erase") {
    await checkedForm(deps, request, webSession);
    const erased = await eraseAccount(deps, webSession.did);
    response.setHeader("Set-Cookie", clearedCookie(deps.config.publicUrl));
    return html(response, 200, page(deps.config, null, "Your Phlogiston data was deleted", [
      `<p>Deleted for <span class="identity">${escapeHtml(webSession.did)}</span>:</p><ul>`,
      `<li>${erased.feeds} personal feed${erased.feeds === 1 ? "" : "s"}, ${erased.localQuiet} hidden conversation${erased.localQuiet === 1 ? "" : "s"} and ${erased.quietHistory} conversation-control record${erased.quietHistory === 1 ? "" : "s"}</li>`,
      `<li>${erased.seen} read position${erased.seen === 1 ? "" : "s"}, ${erased.plans} submission draft${erased.plans === 1 ? "" : "s"} and ${erased.journals} write journal${erased.journals === 1 ? "" : "s"}</li>`,
      "<li>Your sign-in tokens, in every browser, after asking your provider to revoke them</li>",
      "<li>This browser’s saved layout</li>",
      "</ul><p>Not deleted, because Phlogiston does not control them or keeps them as moderation records:</p><ul>",
      "<li>Your posts and records on your own PDS, including community submission requests you made. Delete them there.</li>",
      "<li>Thread mutes already applied in Bluesky. Unmute them in Bluesky.</li>",
      "<li>The Cabinet’s submission and moderation records (see <a href=\"/privacy\">Privacy</a> to ask about them).</li>",
      "</ul><p>Phlogiston keeps no backup of this data, so nothing is restored later.</p>",
      '<p><a href="/">Return to the community</a></p><script type="module" src="/static/forget.js"></script>',
    ].join("")), deps.config);
  }
  if (method === "GET" && url.pathname === "/mine") { if (isP0(deps.config)) await restoredSession(deps, response, token, webSession); return mine(deps, response, webSession, url.searchParams); }
  if (method === "GET" && url.pathname === "/moderation") { if (isP0(deps.config)) await restoredSession(deps, response, token, webSession); return moderationQueue(deps, response, webSession, url.searchParams); }
  if (method === "GET" && url.pathname === "/operation") {
    return operationPage(deps, response, webSession, required(url.searchParams, "id"), undefined);
  }
  if (method === "POST" && url.pathname === "/seen") {
    const form = await checkedForm(deps, request, webSession);
    await deps.activities.acknowledge(webSession.did, required(form, "snapshot"));
    return redirect(response, "/mine", deps.config);
  }
  if (isP0(deps.config) && method === "POST" && url.pathname === "/contribute") throw new HttpError(403, "This collection accepts existing posts only; composition and replies are unavailable.");
  if (method === "POST" && url.pathname === "/contribute") {
    const form = await checkedForm(deps, request, webSession);
    const oauthSession = await restoredSession(deps, response, token, webSession);
    const operationId = randomUUID();
    const service = contributionService(deps, oauthSession, webSession.did);
    const reply = replyInput(form);
    if (reply !== undefined) await requireOpenDiscussion(deps, reply.discussion.uri);
    const plan = await service.prepare({
      operationId,
      authorDid: webSession.did,
      sourceRkey: deterministicTid(operationId),
      text: required(form, "text"),
      communityDid: deps.config.communityDid,
      createdAt: new Date().toISOString(),
      ...(reply === undefined ? {} : { reply }),
    });
    await deps.plans.save(plan);
    const result = await service.advance(plan);
    return operationPage(deps, response, webSession, operationId, result.status);
  }
  if (method === "POST" && url.pathname === "/submit-existing") {
    const form = await checkedForm(deps, request, webSession);
    const rkey = await ownPostRkey(deps, webSession, postReference(required(form, "post")));
    const oauthSession = await restoredSession(deps, response, token, webSession);
    const service = contributionService(deps, oauthSession, webSession.did);
    const subject = await service.readOwnPost(webSession.did, rkey);
    if (subject === null) {
      throw new HttpError(404, "That post is not in your Bluesky account; it may have been deleted.");
    }
    const planned = service.planExisting({
      authorDid: webSession.did,
      subject,
      communityDid: deps.config.communityDid,
      createdAt: new Date().toISOString(),
    });
    if (isP0(deps.config)) {
      await requireSiteWrites(deps.config);
      if (!await intakeOpen(deps.config)) throw new HttpError(503,"New intake and admissions are suspended. Nothing new was queued.");
      const reservation = await reservations(deps).reserve(webSession.did, deps.config.communityDid, subject, planned.operationId);
      if (!reservation.active) throw new HttpError(409, "This exact version already has a terminal site decision. Check My submissions.");
    }
    const plan = await deps.plans.saveNew(planned);
    const result = await advancePlan(deps, service, plan);
    // The same exact post asked for again resumes the earlier operation; the
    // page must not restate "now waiting" for something that already happened.
    return operationPage(deps, response, webSession, plan.operationId, result.status, plan !== planned);
  }
  if (method === "POST" && url.pathname === "/operation/resume") {
    const form = await checkedForm(deps, request, webSession);
    const operationId = required(form, "operationId");
    const plan = await ownedPlan(deps, operationId, webSession.did);
    const oauthSession = await restoredSession(deps, response, token, webSession);
    if (isP0(deps.config) && (plan.existingPostCid === undefined || plan.discussion !== undefined)) throw new HttpError(403, "Legacy composition and replies cannot resume in this profile.");
    const result = await advancePlan(deps, contributionService(deps, oauthSession, webSession.did), plan);
    return operationPage(deps, response, webSession, operationId, result.status);
  }
  if (method === "POST" && url.pathname === "/moderate") {
    const form = await checkedForm(deps, request, webSession);
    if (webSession.did !== deps.config.moderatorDid) throw new HttpError(403, "Moderator permission is required.");
    const command = moderatorCommand(form);
    if (isP0(deps.config)) await restoredSession(deps,response,token,webSession);
    if (isP0(deps.config) && command.kind === "admit-root") {
      const target={uri:command.submissionUri,cid:command.submissionCid};
      const current=await privateStatus(deps,webSession.did,target);
      if(current.decision === "submission_unavailable") throw new HttpError(409,"The exact submission is no longer current or available; no admission attempted.");
      if(current.decision === "declined") throw new HttpError(409,"This exact subject version was declined for this site.");
      const subject=strongRef(current.subject),author=target.uri.split("/")[2]!;
      const bound=await reservations(deps).find(deps.config.communityDid,author,subject);
      if(bound?.submission && (bound.submission.uri !== target.uri || bound.submission.cid !== target.cid)) throw new HttpError(409,"This intent is bound to a different exact submission reference; no admission attempted.");
      if(current.decision !== "admitted") {
        if(!await intakeOpen(deps.config)) throw new HttpError(503,"New intake and admissions are suspended.");
        const intake = await reservations(deps).reserve(author,deps.config.communityDid,subject,existingPostOperationIdForIntake(deps,author,subject),false);
        if(!intake.active) throw new HttpError(409,"This exact intent has ended local intake; it cannot be admitted from an inactive reservation.");
        await reservations(deps).update(intake.operationId,{submission:target});
      }
    }
    if (isP0(deps.config) && command.kind === "decline-root") {
      const target={uri:command.submissionUri,cid:command.submissionCid};
      const status=await privateStatus(deps,webSession.did,target);
      if(status.decision === "submission_unavailable") throw new HttpError(409,"The exact submission is no longer available; no new decision attempted.");
      const subject=strongRef(status.subject),author=target.uri.split("/")[2]!;
      const intake=await reservations(deps).find(deps.config.communityDid,author,subject);
      if(intake) await reservations(deps).update(intake.operationId,{submission:target});
    }
    if (isP0(deps.config) && (command.kind === "remove-reply" || command.kind === "restore-reply")) throw new HttpError(403, "Reply moderation is unavailable in this root-only profile.");
    const broker = new TrustedModeratorBroker(
      {
        restore: async () => {
          const restored = await restoredSession(deps, response, token, webSession);
          return { did: restored.did, sessionRef: webSession.did };
        },
      },
      deps.authority,
      new Set([deps.config.moderatorDid]),
    );
    const result = await broker.moderate({
      cookieHeader: request.headers.cookie ?? "",
      sameOrigin: true,
      csrfValid: true,
      command,
    });
    if (isP0(deps.config) && result.ok && (command.kind === "admit-root" || command.kind === "decline-root")) {
      try {
        const current=await privateStatus(deps, webSession.did,{uri:command.submissionUri,cid:command.submissionCid});
        if(current.decision === "admitted" || current.decision === "declined") {
          const subject=strongRef(current.subject), author=command.submissionUri.split("/")[2]!;
          const entry=await reservations(deps).reserve(author,deps.config.communityDid,subject,existingPostOperationIdForIntake(deps,author,subject),false);
          await reservations(deps).update(entry.operationId,{active:false,decision:stringOf(current.decision)});
        }
      } catch { /* an unknown result never releases capacity */ }
    }
    return html(response, result.ok ? 200 : 409, page(deps.config, webSession, "Moderation result", `<p>${result.ok ? (command.kind === "decline-root" ? "Declined privately for this site. No public moderation record was created; the author’s post is unchanged." : "Recorded. The observer may take a moment to catch up.") : "Not recorded; retry is safe after checking the current view."}</p><p><a href="/moderation">Back to moderation</a></p>`), deps.config);
  }
  throw new HttpError(404, "That page does not exist.");
}

async function home(deps: Dependencies, response: ServerResponse, session: WebSession | null, params: URLSearchParams, reader?: Reader): Promise<void> {
  let document: Record<string, unknown>;
  try {
    document = await deps.projection.getCapped(
      `/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/discussions`,
      "discussions",
      deps.config.discussionsMaxItems,
    );
  } catch (error) {
    if (isP0(deps.config) && !(error instanceof ProjectionTooLargeError)) {
      const notice = '<p class="notice">Independent observation is unavailable right now. Discussion coverage and submission outcomes are unknown. Sign-in remains available.</p>';
      return html(response, 503, page(deps.config, session, isFrontDoor(deps.config, session) ? "Phlogiston" : deps.config.communityName, homeContent(deps, session, params, notice)), deps.config);
    }
    if (!(error instanceof ProjectionTooLargeError)) communityUnavailable(error);
    const notice = '<p class="notice">This community has more discussions than this page can show yet.</p>';
    return html(response, 200, page(deps.config, session, isFrontDoor(deps.config, session) ? "Phlogiston" : deps.config.communityName, homeContent(deps, session, params, notice)), deps.config);
  }
  const all = array(document.discussions);
  const totalPages = Math.max(1, Math.ceil(all.length / DISCUSSIONS_PAGE_SIZE));
  const pageNumber = requestedPage(params, totalPages);
  const items = all.slice((pageNumber - 1) * DISCUSSIONS_PAGE_SIZE, pageNumber * DISCUSSIONS_PAGE_SIZE);
  const profiles = await deps.profiles.lookup(items.map((item) => stringOf(record(item).authorDid)));
  const identity = (did: string): string => renderIdentity(did, profiles, { avatars: deps.config.avatarsEnabled });
  const hydrated = new Map<string, string>();
  if (reader) await Promise.all(items.slice(0, 10).map(async item => {
    const root = record(item), ref = strongRef(root.root);
    let body = '<p class="feed-notice">This admitted version cannot be shown right now.</p>';
    try {
      if (root.status !== "removed") {
        const thread = await reader.thread(ref.uri);
        if ("post" in thread && thread.post.uri === ref.uri && thread.post.cid === ref.cid) body = renderPost(reader, thread.post);
      }
    } catch { /* A newer version or unavailable viewing preferences never substitutes for admission. */ }
    hydrated.set(`${ref.uri}\n${ref.cid}`, body);
  }));
  const discussions = items.map((item) => {
    const root = record(item);
    const ref = strongRef(root.discussion);
    const rootRef = strongRef(root.root);
    const post = record(root.post);
    const authorDid = stringOf(root.authorDid);
    const fallbackTitle = isP0(deps.config) ? "Post" : "Discussion";
    const text = String(post.text ?? fallbackTitle);
    const seedPrefix = "Operator/project seed for The Cabinet: ";
    const operatorSeed = isP0(deps.config) && authorDid === deps.config.communityDid && text.startsWith(seedPrefix);
    const title = escapeHtml(snippet(operatorSeed ? text.slice(seedPrefix.length) : text) || fallbackTitle);
    const meta = [
      authorDid === "" ? "" : identity(authorDid),
      postedAt(stringOf(post.createdAt)),
    ].filter((part) => part !== "").join(" · ");
    const rkey = ref.uri.split("/").at(-1) ?? "";
    const heading = rkey === ""
      ? title
      : `<a href="${escapeHtml(discussionHref(rkey))}">${title}</a>`;
    if (reader) return `<li class="community-post">${hydrated.get(`${rootRef.uri}\n${rootRef.cid}`) ?? '<p>Open this item to view its admitted version.</p>'}${whyHere(stringOf(root.admittedAt), rootRef.uri)}<a href="${escapeHtml(discussionHref(rkey))}">Open in ${escapeHtml(deps.config.communityName)}</a></li>`;
    return `<li>${operatorSeed ? '<span class="seed-label">Collection starter</span>' : ""}<div class="item-heading">${heading} ${isP0(deps.config) ? "" : COMMUNITY_VIEW_BADGE}</div>${meta === "" ? "" : `<div class="meta">${meta}</div>`}${whyHere(stringOf(root.admittedAt), rootRef.uri)}</li>`;
  }).join("");
  const first = all.length === 0 ? 0 : (pageNumber - 1) * DISCUSSIONS_PAGE_SIZE + 1;
  const last = Math.min(all.length, pageNumber * DISCUSSIONS_PAGE_SIZE);
  const summary = all.length === 0 ? "" : `<p class="pages-summary">${first}–${last} of ${all.length} ${isP0(deps.config) ? "posts" : "discussions"}</p>`;
  const previous = pageNumber > 1 ? `<a href="${pageHref(pageNumber - 1)}">Previous page</a>` : "";
  const next = pageNumber < totalPages ? `<a href="${pageHref(pageNumber + 1)}">Next page</a>` : "";
  const pages = totalPages > 1 ? `<nav class="pages" aria-label="Pages">${previous}<span>Page ${pageNumber} of ${totalPages}</span>${next}</nav>` : "";
  const empty = isP0(deps.config) ? "No posts in the collection yet." : "No discussions yet.";
  return html(response, 200, page(deps.config, session, isFrontDoor(deps.config, session) ? "Phlogiston" : deps.config.communityName, homeContent(deps, session, params, `${summary}<ul class="collection-posts">${discussions || `<li>${empty}</li>`}</ul>${pages}`)), deps.config);
}

function homeContent(deps: Dependencies, session: WebSession | null, params: URLSearchParams, collection: string): string {
  const p0 = isP0(deps.config);
  return `${isFrontDoor(deps.config, session) ? `${productIntro(true)}${accountAvailability()}<h2 class="cabinet-heading">${escapeHtml(deps.config.communityName)}</h2>` : ""}${homeBody(deps, session, params)}<section id="collection" aria-labelledby="collection-heading"><h2 id="collection-heading">${p0 ? "Collection" : "Discussions"}</h2>${collection}</section>${p0 ? p0Participation(deps, session, params) : ""}`;
}

function p0Participation(deps: Dependencies, session: WebSession | null, params: URLSearchParams): string {
  const provider = deps.config.p0HostedPdsOrigin ? (deps.config.p0AllowBluesky ? "Bluesky or Phlogiston" : "Phlogiston") : "Bluesky";
  const form = session === null ? (deps.config.readerEnabled ? '<p><a href="/signin?return=%2Fcommunity%23submit">Sign in to submit a post</a></p>' : signInForm(deps.config, returnPath(params.get("return"))))
    : `<form method="post" action="/submit-existing"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><label>Link to your public post<input name="post" required maxlength="1024" placeholder="https://bsky.app/profile/…/post/…"></label><button>Submit for review</button></form><p><a href="/mine">Check your submissions</a> for the outcome.</p>`;
  return `<section id="submit" class="participation" aria-labelledby="submit-heading"><h2 id="submit-heading">Submit one of your posts</h2><p>Submit a link to a public post you wrote. Your submission is public; a moderator decides whether it appears here. Your original post stays in your account.</p>${form}<details class="about"><summary>What happens after I submit?</summary><p>Post from your usual ${provider} account first, then submit the link here. A moderator reviews it before it can appear in the collection. Sign in and visit <a href="/mine">My submissions</a> to check its status.</p><p>The submission request is a public record in your account, even if the moderator declines it. A decline is a private decision for this site; it does not make your submission private or delete it from the network.</p><p>Approval includes the reviewed version of your post. Editing or deleting it can stop it appearing here. Removing it from this collection does not edit or delete your original.</p></details></section>`;
}

function homeBody(deps: Dependencies, session: WebSession | null, params: URLSearchParams): string {
  if (isP0(deps.config)) {
    const cabinet = deps.config.communityName === "The Cabinet";
    const tagline = cabinet ? "Internet curiosities worth another look." : deps.config.communityPurpose;
    const description = cabinet ? "A small, human-curated collection of public posts about odd discoveries and forgotten corners of the web." : "A human-curated collection of public posts.";
    return `<div class="collection-intro"><p class="exhibition">An exhibition on Phlogiston</p><p class="collection-tagline">${escapeHtml(tagline)}</p><p>${description}</p><p>Browse without signing in. <a href="/help">Using Phlogiston and creating communities</a></p><nav class="collection-actions" aria-label="Explore the collection"><a href="#collection">Browse the collection</a><a href="#submit">Submit one of your posts</a></nav></div>`;
  }
  const purpose = `<p class="purpose">${escapeHtml(deps.config.communityPurpose)}</p>`;
  const about = `<details class="about"><summary>What is this?</summary><p>This is a moderated collection of public Bluesky posts. Each post stays in its author's own account; the community only records which exact versions are shown here and can stop showing them. Showing or no longer showing a post never changes or deletes it.</p><p class="legend">${COMMUNITY_VIEW_BADGE} marks posts the community has added to this page. Links named “Public post on Bluesky” and author names open the author’s public record on Bluesky.</p></details>`;
  const auth = session === null
    ? signInForm(deps.config, returnPath(params.get("return")))
    : `<form method="post" action="/contribute" class="contribute"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><label for="new-discussion">Start a discussion</label><p id="new-discussion-note">This publishes a new post on your own Bluesky account, then asks the moderator to add it here.</p><textarea id="new-discussion" name="text" aria-describedby="new-discussion-note" required></textarea><button>Post to Bluesky and submit</button></form><form method="post" action="/submit-existing" class="contribute"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><label>Add a post you already made<input name="post" required maxlength="1024" placeholder="https://bsky.app/profile/…/post/…"></label><p>Paste the link to one of your own Bluesky posts. The post is not changed; this asks the moderator to add it here.</p><button>Ask to add this post</button></form>`;
  return `${purpose}${about}${auth}`;
}

async function readCuratorBlocks(deps: Dependencies, did: string) {
  try {
    if (!deps.publicBlocks) throw new Error("unavailable");
    return await deps.publicBlocks.read(did);
  } catch {
    throw new HttpError(503, "The curator's complete public block list could not be read. This feature currently supports Bluesky-hosted and Phlogiston accounts with up to 5,000 direct blocks. Try again later; the feed has not been shown without its exclusions.");
  }
}
function requirePersonalFeed(deps: Dependencies, did: string, key: string): void {
  if (key.startsWith("personal:") && !deps.personalFeeds?.get(did,key.slice(9))) throw new HttpError(404,"Personal feed not found.");
}
function curationConnect(session: WebSession, retainQuiet: boolean): string {
  return `<p>Connect public account context to build private views of your Following feed. This adds read access to account profiles and saved custom feeds; public block records need no curator login. It does not allow copying blocks or publishing feeds. Your existing community-submission permission remains${retainQuiet ? ", along with your existing Bluesky notification controls" : ""}.</p><form method="post" action="/oauth/login"><input type="hidden" name="handle" value="${escapeHtml(session.did)}"><input type="hidden" name="return" value="/feeds"><input type="hidden" name="access" value="${retainQuiet ? "curation-quiet" : "curation"}"><button>Connect personal feeds</button></form>`;
}
function readerConnect(session: WebSession, returnTo: string, quiet: boolean, feeds = false): string {
  return `<form method="post" action="/oauth/login"><input type="hidden" name="handle" value="${escapeHtml(session.did)}"><input type="hidden" name="return" value="${escapeHtml(returnTo)}"><input type="hidden" name="access" value="${quiet ? "quiet" : feeds ? "feeds" : "reader"}"><p>${quiet ? "Allow Bluesky thread notification mute and unmute, in addition to feed reading and community submissions. Local quiet does not need this permission." : "Allow Phlogiston to read feeds, conversations and viewing preferences, alongside community submissions."}</p><button>${quiet ? "Connect Bluesky notification controls" : feeds ? "Connect saved feeds" : "Connect my feed"}</button></form>`;
}

function signInForm(config: AppConfig, returnTo?: string): string {
  const p0 = isP0(config);
  const hidden = returnTo === undefined ? "" : `<input type="hidden" name="return" value="${escapeHtml(returnTo)}">`;
  if (p0 && config.readerEnabled) return `<form method="post" action="/oauth/login" class="signin"><p>Use your existing Bluesky account. Enter your handle to continue to Bluesky’s sign-in. Phlogiston never sees your password. <a href="/about">What signing in allows</a></p>${hidden}<label>Account handle<input name="handle" required placeholder="you.bsky.social" autocapitalize="none" spellcheck="false"></label><button>Sign in</button><details class="permissions"><summary>What you allow</summary><p>Read your Following feed, conversations, labeler settings and viewing preferences; create a community submission only when you choose. No permission to create, edit or delete posts. Conversation controls ask for a separate grant.</p><code>${escapeHtml(READER_SCOPE)}</code></details></form>`;
  if (p0) {
    const provider = config.p0AllowBluesky ? "your existing Bluesky account" : config.p0HostedPdsOrigin ? "your existing Phlogiston account" : "your existing Bluesky account";
    const label = config.p0AllowBluesky ? "Account handle" : config.p0HostedPdsOrigin ? "Phlogiston handle" : "Bluesky handle";
    const example = config.p0HostedPdsOrigin && !config.p0AllowBluesky ? "you.phlogiston.social" : "you.bsky.social";
    return `<form method="post" action="/oauth/login" class="signin"><p>Sign in with ${provider} for your activity and account label context. Signing in alone does not submit anything.</p><p>You will be asked to allow public submission requests from your account. This permission cannot edit or delete your posts.</p>${hidden}<label>${label}<input name="handle" required placeholder="${example}" autocapitalize="none" spellcheck="false"></label><button>Sign in to Phlogiston</button><details class="about permissions"><summary>Permission details</summary><p>Requested scope: <code>${escapeHtml(P0_SCOPE)}</code></p><p>This lets Phlogiston create public submission records only. It does not grant permission to create posts, or make you a moderator. You still choose which of your posts to submit.</p></details></form>`;
  }
  return `<form method="post" action="/oauth/login" class="signin"><p>Sign in with your Bluesky (ATProto) account. Nothing is created here; you will be asked to allow this site to post and submit on your behalf.</p>${hidden}<label>ATProto handle <input name="handle" required></label><button>Sign in</button></form>`;
}

const SIGNIN_DOCUMENT_PATHS = new Set(["/home", "/feed", "/feeds", "/thread", "/context", "/attention", "/labels", "/settings", "/mine", "/moderation", "/operation"]);
function signinHref(destination = "/home"): string {
  return `/signin?${new URLSearchParams({return: destination})}`;
}
function isFrontDoor(config: AppConfig, session: WebSession | null): boolean {
  return isP0(config) && config.readerEnabled === true && session === null && displayContext.getStore()?.path === "/";
}
function productIntro(link: boolean): string {
  return `<section class="product-intro" aria-label="About Phlogiston"><p class="product-tagline">A different way to experience Bluesky.</p><p>Read Following and custom feeds side by side. Build personal feeds using another account’s public blocklist. Follow conversations without losing your place, and quiet them in a view when you’ve had enough.</p>${link ? '<p class="frontdoor-actions"><a class="signin-link" href="/signin">Sign in with Bluesky / ATProto</a><a href="/community">Explore The Cabinet</a></p>' : ""}</section>`;
}
function accountAvailability(): string {
  return '<p class="account-availability">Sign in with an existing Bluesky account; Phlogiston doesn’t offer accounts. You can create private personal feeds. Community creation is currently operator-managed. <a href="/help">Getting started</a></p>';
}

/** Explicit local read destinations only; no arbitrary URLs or mutation replay. */
function returnPath(value: string | null | undefined, reader = false): string | undefined {
  if (typeof value !== "string") return undefined;
  if (reader) {
    if (value.length > 800 || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u0020\u007f]/.test(value)) return undefined;
    const parsed = new URL(value, "https://local.invalid");
    if (parsed.origin !== "https://local.invalid" || parsed.pathname !== value.split(/[?#]/)[0]) return undefined;
    const path = parsed.pathname, params = parsed.searchParams;
    if (parsed.hash && !(path === "/community" && parsed.hash === "#submit")) return undefined;
    if ([...params.keys()].some((key, i, keys) => keys.indexOf(key) !== i)) return undefined;
    const uuid = (v: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v);
    let allowed: Record<string, (v: string) => boolean> = {};
    if (["/home", "/feed"].includes(path)) allowed = {feed: v => /^at:\/\/did:[a-z0-9]+:[A-Za-z0-9._:%-]+\/app\.bsky\.feed\.generator\/[A-Za-z0-9._~:-]+$/.test(v), personal: uuid, alongside: uuid};
    else if (path === "/feeds") allowed = {edit: uuid};
    else if (["/thread", "/context"].includes(path)) { if (!params.has("uri")) return undefined; allowed = {uri: isValidPostUri}; }
    else if (path === "/operation") { if (!params.has("id")) return undefined; allowed = {id: uuid}; }
    else if (!["/attention", "/labels", "/settings", "/mine", "/moderation", "/community"].includes(path) && !/^\/d\/[A-Za-z0-9._~:-]+$/.test(path)) return undefined;
    if (path === "/d/." || path === "/d/..") return undefined;
    if ([...params].some(([key, val]) => !Object.hasOwn(allowed, key) || !allowed[key]!(val))) return undefined;
    if (params.has("personal") && params.has("feed")) return undefined;
    return path + (params.size ? `?${params}` : "") + parsed.hash;
  }
  if (["/home", "/feed", "/feeds", "/attention"].includes(value)) return value;
  if (value.startsWith("/thread?")) {
    const params = new URLSearchParams(value.slice(8));
    const uri = params.get("uri");
    return uri && isValidPostUri(uri) && [...params.keys()].length === 1 ? threadHref(uri) : undefined;
  }
  if (!value.startsWith("/d/")) return undefined;
  const rkey = value.slice("/d/".length);
  if (!RKEY_PATTERN.test(rkey) || rkey === "." || rkey === "..") return undefined;
  return value;
}

function loginState(nonce: string, returnTo: string | undefined): string {
  const state = new URLSearchParams({ nonce });
  if (returnTo !== undefined) state.set("return", returnTo);
  return state.toString();
}

function parseLoginState(value: string | null | undefined, reader = false): { nonce: string; returnTo: string | undefined } | undefined {
  if (typeof value !== "string" || value.length > 1024) return undefined;
  const state = new URLSearchParams(value);
  const nonce = state.get("nonce");
  if (nonce === null || !/^[A-Za-z0-9_-]{16,64}$/.test(nonce)) return undefined;
  return { nonce, returnTo: returnPath(state.get("return"), reader) };
}

function sameToken(expected: string, actual: string): boolean {
  const a = Buffer.from(expected);
  const b = Buffer.from(actual);
  return a.length === b.length && timingSafeEqual(a, b);
}

function pageHref(pageNumber: number): string {
  return pageNumber <= 1 ? "/" : `/?page=${pageNumber}`;
}

function requestedPage(params: URLSearchParams, totalPages: number): number {
  const raw = params.get("page");
  if (raw === null) return 1;
  if (!/^\d{1,6}$/.test(raw)) throw new HttpError(400, "The page number is malformed.");
  const value = Number(raw);
  if (value < 1) return 1;
  return Math.min(value, totalPages);
}

function validRkey(value: string): string {
  if (!RKEY_PATTERN.test(value) || value === "." || value === "..") {
    throw new HttpError(400, "That discussion link is malformed.");
  }
  return value;
}

function discussionHref(rkey: string): string {
  return `/d/${encodeURIComponent(rkey)}`;
}

async function discussion(deps: Dependencies, response: ServerResponse, session: WebSession | null, rkey: string, reader?: Reader): Promise<void> {
  const notHere = "That discussion isn't in this community.";
  let doc: Record<string, unknown>;
  try {
    doc = await deps.projection.get(`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/discussions/${encodeURIComponent(rkey)}`);
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) throw new HttpError(404, notHere);
    communityUnavailable(error);
  }
  const root = record(doc.discussion);
  const discussionRef = strongRef(root.discussion);
  if (discussionRef.uri === "") throw new HttpError(404, notHere);
  const post = record(root.post);
  const rootRef = strongRef(root.root);
  const replyRecords = (isP0(deps.config) ? [] : array(doc.replies)).map((value) => record(value));
  const profiles = await deps.profiles.lookup([
    stringOf(root.authorDid),
    ...replyRecords.map((reply) => stringOf(reply.authorDid)),
  ]);
  const view: ReplyView = { moderatorDid: deps.config.moderatorDid, profiles, avatars: deps.config.avatarsEnabled };
  const replies = replyRecords.map((value) => renderReply(value, session, view)).join("");
  const authorDid = stringOf(root.authorDid);
  // The moderator sees the DID beside every hydrated name here, as on the
  // moderation queue, so a display name never stands in for identity.
  const showDid = session !== null && session.did === deps.config.moderatorDid;
  const identity = (did: string): string => renderIdentity(did, profiles, { avatars: deps.config.avatarsEnabled, showDid });
  const bylineParts = [
    authorDid === "" ? "" : `Started by ${identity(authorDid)}`,
    postedAt(stringOf(post.createdAt)),
  ].filter((part) => part !== "");
  const byline = bylineParts.length === 0
    ? COMMUNITY_VIEW_BADGE
    : `${COMMUNITY_VIEW_BADGE} ${bylineParts.join(" · ")}`;
  const removedBanner = root.status === "removed"
    ? `<p class="tombstone-banner">This discussion was removed from this community’s view; the author’s public post is not deleted or changed. ${publicPostLink(rootRef.uri)} ${observerPermalink(deps.config, rkey)}</p>`
    : "";
  const replyForm = isP0(deps.config) ? "" : root.closed
    ? "<p>This discussion is closed to new community replies.</p>"
    : session === null
    ? `<p class="signin-prompt"><a href="/?return=${encodeURIComponent(discussionHref(rkey))}">Sign in to reply</a></p>`
    : `<form method="post" action="/contribute"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><input type="hidden" name="discussionUri" value="${escapeHtml(discussionRef.uri)}"><input type="hidden" name="discussionCid" value="${escapeHtml(discussionRef.cid)}"><input type="hidden" name="rootUri" value="${escapeHtml(rootRef.uri)}"><input type="hidden" name="rootCid" value="${escapeHtml(rootRef.cid)}"><input type="hidden" name="parentUri" value="${escapeHtml(rootRef.uri)}"><input type="hidden" name="parentCid" value="${escapeHtml(rootRef.cid)}"><label for="reply-text">Reply</label><p id="reply-note">Your reply is posted publicly on your Bluesky account.</p><textarea id="reply-text" name="text" aria-describedby="reply-note" required></textarea><button>Post reply and add to this discussion</button></form>`;
  const rootModeration = session !== null && session.did === deps.config.moderatorDid && !root.closed
    ? `<form method="post" action="/moderate"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><input type="hidden" name="kind" value="remove-root"><input type="hidden" name="uri" value="${escapeHtml(discussionRef.uri)}"><input type="hidden" name="cid" value="${escapeHtml(discussionRef.cid)}"><label>Reason <input name="reason" required></label><button>Remove from community</button></form>`
    : "";
  // A removed root keeps only its tombstone banner, as reply tombstones do,
  // and brings no public conversation into the community's view.
  const conversation = root.status !== "removed" && isP0(deps.config) && deps.config.readerEnabled
    ? await publicConversation(deps, session, reader, rootRef, rkey) : undefined;
  const rootBody = root.status === "removed"
    ? ""
    : `${conversation?.root ?? `<article>${linkedText(String(post.text ?? "[unavailable]"))}</article>`}${whyHere(stringOf(root.admittedAt), rootRef.uri)}`;
  const title = isP0(deps.config) ? `In ${deps.config.communityName}` : "Discussion";
  // In P0 the moderator's form follows the conversation, folded, so reading is not interrupted.
  const p0Moderation = isP0(deps.config) && rootModeration !== "" ? `<details class="moderator-actions"><summary>Moderator actions</summary>${rootModeration}</details>` : "";
  const inlineModeration = isP0(deps.config) ? "" : rootModeration;
  return html(response, 200, page(deps.config, session, title, `${removedBanner}<p class="byline">${byline}</p>${rootBody}${inlineModeration}<ol>${replies}</ol>${replyForm}${conversation?.section ?? ""}${p0Moderation}<p class="projection-note">Community view: admission and removal change only this view, never the author’s public post.</p>`), deps.config);
}

function linkedText(text: string): string {
  return text.split(/(https:\/\/[^\s<>"]+)/).map((part, i) => {
    if (i % 2 === 0) return escapeHtml(part);
    try { const href = externalHttpsUrl(part); return `<a href="${escapeHtml(href)}" rel="noreferrer noopener">${escapeHtml(part)}</a>`; } catch { return escapeHtml(part); }
  }).join("");
}

/**
 * Public replies under an admitted post, read through the viewer's own grant.
 * They are Bluesky testimony shown beside the community's decision, never
 * admitted material, and only for the exact admitted version.
 */
async function publicConversation(deps: Dependencies, session: WebSession | null, reader: Reader | undefined,
  rootRef: {uri: string; cid: string}, rkey: string): Promise<{root?: string; section: string}> {
  const name = escapeHtml(deps.config.communityName);
  const open = publicPostLink(rootRef.uri, "open it on Bluesky");
  const signin = escapeHtml(signinHref(discussionHref(rkey)));
  const note = session === null
    ? `Replies posted publicly on Bluesky. ${name} has not reviewed or admitted them. Bluesky’s default moderation applies; <a href="${signin}">sign in</a> to use your own settings.`
    : `Replies posted publicly on Bluesky. ${name} has not reviewed or admitted them; your viewing settings apply.`;
  const wrap = (body: string) => `<section class="community-conversation" aria-labelledby="public-conversation"><h2 id="public-conversation">Public conversation</h2><p class="conversation-note">${note}</p>${body}</section>`;
  const viewer = session === null ? new SignedOutViewer() : reader;
  const read = session === null ? deps.publicThreads?.read.bind(deps.publicThreads) : reader?.thread.bind(reader);
  if (session === null && !read) return {section: wrap(`<p><a href="${signin}">Sign in to read the public conversation here</a>${open ? `, or ${open}` : ""}.</p>`)};
  if (!viewer || !read) return {section: wrap(readerConnect(session!, discussionHref(rkey), false))};
  const links = session === null ? "public" : "reader";
  let thread: ThreadResult;
  try { thread = await read(rootRef.uri); }
  catch { return {section: wrap(marker({established: false}, "Phlogiston could not read the public conversation right now. Nothing here says it was removed."))}; }
  if (!AppBskyFeedDefs.isThreadViewPost(thread)) return {section: wrap(renderThread(viewer, thread))};
  if (thread.post.uri !== rootRef.uri || thread.post.cid !== rootRef.cid) {
    const current = session === null ? publicPostLink(rootRef.uri, "Read the current conversation on Bluesky") : `<a href="${escapeHtml(threadHref(rootRef.uri))}">Read the current conversation</a>`;
    return {section: wrap(`${marker({established: true, decidedBy: "source"}, `This post has changed since ${deps.config.communityName} admitted it, so its newer public conversation is not shown here.`)}<p class="feed-notice">${current}</p>`)};
  }
  const replies = renderReplies(viewer, thread, links);
  // Signed-out readers keep the community's own rendering of the admitted post.
  return {...(session === null ? {} : {root: `<div class="thread-focus">${renderPost(viewer, thread.post, "contentView", true)}</div>`}),
    section: wrap(replies || '<p class="feed-notice">Bluesky returned no public replies.</p>')};
}

/** The community page for a conversation's admitted post or its root, when the observer can say so. */
async function admittedDiscussion(deps: Dependencies, uris: readonly string[]): Promise<{rkey: string; uri: string} | undefined> {
  try {
    const document = await deps.projection.getCapped(`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/discussions`, "discussions", deps.config.discussionsMaxItems);
    for (const uri of uris) {
      const item = array(document.discussions).map(record).find(entry => entry.status !== "removed" && strongRef(entry.root).uri === uri);
      const rkey = item ? strongRef(item.discussion).uri.split("/").at(-1) : undefined;
      if (rkey && RKEY_PATTERN.test(rkey)) return {rkey, uri};
    }
  } catch { /* Unknown placement adds no community context; the conversation still renders. */ }
  return undefined;
}

function observerPermalink(config: AppConfig, rkey: string): string {
  if (config.observerPublicUrl === undefined) return "";
  const href = `${config.observerPublicUrl}/i/${encodeURIComponent(rkey)}`;
  return `<a class="external" href="${escapeHtml(href)}" rel="noopener noreferrer">Observer record for this admission</a>`;
}

export interface ReplyView {
  moderatorDid: string;
  profiles: ReadonlyMap<string, HydratedProfile>;
  avatars: boolean;
}

export function renderReply(
  reply: Record<string, unknown>,
  session: WebSession | null,
  view: ReplyView,
): string {
  const moderator = session !== null && session.did === view.moderatorDid ? session : null;
  const replyPost = record(reply.post);
  const admission = strongRef(reply.admission);
  const controllingAction = reply.controllingAction === null || reply.controllingAction === undefined
    ? null
    : strongRef(reply.controllingAction);
  const remove = moderator !== null && reply.status !== "removed"
    ? `<form method="post" action="/moderate"><input type="hidden" name="csrf" value="${escapeHtml(moderator.csrf)}"><input type="hidden" name="kind" value="remove-reply"><input type="hidden" name="uri" value="${escapeHtml(admission.uri)}"><input type="hidden" name="cid" value="${escapeHtml(admission.cid)}"><label>Reason <input name="reason" required></label><button>Remove from community</button></form>`
    : "";
  const restore = moderator !== null && reply.status === "removed" && controllingAction !== null
    ? `<form method="post" action="/moderate"><input type="hidden" name="csrf" value="${escapeHtml(moderator.csrf)}"><input type="hidden" name="kind" value="restore-reply"><input type="hidden" name="uri" value="${escapeHtml(admission.uri)}"><input type="hidden" name="cid" value="${escapeHtml(admission.cid)}"><input type="hidden" name="controllingActionUri" value="${escapeHtml(controllingAction.uri)}"><input type="hidden" name="controllingActionCid" value="${escapeHtml(controllingAction.cid)}"><label>Reason <input name="reason" required></label><button>Restore to community</button></form>`
    : "";
  const author = renderIdentity(stringOf(reply.authorDid), view.profiles, { avatars: view.avatars, showDid: moderator !== null });
  const subject = strongRef(reply.subject);
  if (reply.status === "removed") {
    const link = publicPostLink(subject.uri);
    const unchanged = link === ""
      ? "The author’s public post is not deleted or changed."
      : `The author’s public post is not deleted or changed: ${link}.`;
    return `<li class="tombstone">Removed from this community’s view: ${escapeHtml(String(reply.reason ?? "moderation action"))}. ${unchanged}${restore}</li>`;
  }
  const meta = [postedAt(stringOf(replyPost.createdAt))].filter((part) => part !== "").join("");
  return `<li><div>${COMMUNITY_VIEW_BADGE} ${author}: ${escapeHtml(String(replyPost.text ?? "[unavailable]"))}</div>${meta === "" ? "" : `<div class="meta">${meta}</div>`}${whyHere(stringOf(reply.admittedAt), subject.uri)}${remove}</li>`;
}


async function participantLabels(deps: Dependencies, response: ServerResponse, session: WebSession): Promise<void> {
  const context = await deps.labels?.lookup(session.did).catch(() => null) ?? null;
  return html(response, 200, page(deps.config, session, "My Labels", renderLabels(context, session.did)), deps.config);
}

async function participantHome(deps: Dependencies, response: ServerResponse, session: WebSession): Promise<void> {
  const profiles = await deps.profiles.lookup([session.did]).catch(() => new Map<string, HydratedProfile>());
  let recent = "<p>Your community activity is unavailable right now. You can still browse the collection or look at your labels.</p>";
  try {
    const doc = await deps.projection.get(`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/participants/${encodeURIComponent(session.did)}`);
    const rows = array(doc.discussions).slice(0, 5).map(value => {
      const root = record(value), ref = strongRef(root.discussion), rkey = ref.uri.split("/").at(-1) ?? "";
      if (!RKEY_PATTERN.test(rkey)) return "";
      const title = root.status === "removed" ? REMOVED_ROOT_TITLE : snippet(stringOf(record(root.post).text)) || "View post";
      return `<li><a href="${escapeHtml(discussionHref(rkey))}">${escapeHtml(title)}</a></li>`;
    }).join("");
    recent = rows ? `<ul>${rows}</ul>` : "<p>No admitted posts to show here yet. Check your submissions below for pending or declined requests, or submit one of your public posts.</p>";
  } catch { /* Each read surface remains independently available. */ }
  return html(response, 200, page(deps.config, session, "Your Phlogiston", `
    <p class="lede">Your collections, contributions, and account context in one place.</p>
    <p>Signed in as ${renderIdentity(session.did, profiles, { avatars: deps.config.avatarsEnabled, showDid: true })}.</p>
    <div class="participant-grid"><section class="participant-card"><h2>Your community activity</h2>${recent}<p><a href="/mine">All submissions and review status</a></p><p><a href="/#submit">Submit one of your posts</a></p></section>
    <section class="participant-card"><h2>My Labels</h2><p>Explore what Labelwatch has observed about labels on your account and records, and where those observations came from.</p><p><a href="/labels">See your label context</a></p></section>
    <section class="participant-card"><h2>${escapeHtml(deps.config.communityName)}</h2><p>${escapeHtml(deps.config.communityPurpose)}</p><p><a href="/">Browse the collection</a></p></section></div>`), deps.config);
}

function displayForm(session: WebSession | null, returnTo = "/display"): string {
  const choice = displayContext.getStore()?.theme ?? "system";
  return `<form method="post" action="/display" class="display-form">${session ? `<input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}">` : ""}<input type="hidden" name="return" value="${returnTo}"><fieldset><legend>Appearance</legend><div class="display-options">${(["system", "light", "dark"] as const).map(value => `<label><input type="radio" name="display" value="${value}"${choice === value ? " checked" : ""}>${value === "system" ? "System" : value === "light" ? "Light" : "Dark"}</label>`).join("")}</div></fieldset><p class="muted">System follows your device’s appearance. Your choice is saved in this browser and also applies when signed out.</p><button>Save display preference</button></form>`;
}

function participantSettings(deps: Dependencies, response: ServerResponse, session: WebSession): void {
  return html(response, 200, page(deps.config, session, "Settings", `${displayForm(session, "/settings")}<h2>Your identity</h2><p class="identity">${escapeHtml(session.did)}</p><p>Your account and original posts stay with your account provider. Phlogiston stores your application session and submission progress.</p><h2>Permissions</h2>${deps.config.readerEnabled ? '<p>Connected feeds read your Following timeline, conversations, viewing preferences and labeler settings. Optional conversation controls mute or unmute thread notifications in Bluesky and filter quieted conversations from Following here.</p>' : ""}<p>Phlogiston can create public community submission requests when you choose to submit. It cannot edit or delete your original posts, and sign-in does not grant moderator access.</p><details><summary>Granted permissions</summary><code>${escapeHtml(session.grantedScopes ?? P0_SCOPE)}</code></details><h2>Leaving</h2><p>Sign out and Disconnect both revoke Phlogiston’s access to your account and end its sessions in every browser. Neither deletes your posts or public submission records.</p>${sessionActions(session)}<h2>Delete my Phlogiston data</h2><p>Deletes everything Phlogiston keeps for your account (personal feeds, hidden conversations, conversation-control history, read positions, submission drafts and sign-in tokens) and signs you out. It cannot be undone. See <a href="/privacy">Privacy</a> for what remains.</p><form method="post" action="/erase"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><button>Delete my Phlogiston data</button></form>`), deps.config);
}

async function mine(deps: Dependencies, response: ServerResponse, session: WebSession, params = new URLSearchParams()): Promise<void> {
  const doc = await deps.projection.get(`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/participants/${encodeURIComponent(session.did)}`);
  const details = new Map<string, { authorDid: string; title: string; createdAt: string }>();
  const activities: DiscussionActivity[] = array(doc.discussions).map((value) => {
    const root = record(value);
    const ref = strongRef(root.discussion);
    // A removed root keeps only a fixed title here, as its permalink keeps
    // only its tombstone banner; the projection still carries the text.
    details.set(ref.uri, {
      authorDid: stringOf(root.authorDid),
      title: root.status === "removed"
        ? REMOVED_ROOT_TITLE
        : snippet(String(record(root.post).text ?? "Discussion")) || "Discussion",
      createdAt: stringOf(record(root.post).createdAt),
    });
    const events = array(doc.activity).filter((item) => {
      const event = record(item);
      const discussion = strongRef(event.discussion);
      return discussion.uri === ref.uri && discussion.cid === ref.cid;
    });
    return {
      discussionUri: ref.uri,
      version: Number(root.lastActivitySequence ?? 0),
      newReplies: events.filter((item) => record(item).type === "reply_admitted").length,
      moderationChanges: events.filter((item) => /remove|restore/.test(String(record(item).type))).length,
    };
  });
  const profiles = await deps.profiles.lookup([...details.values()].map((detail) => detail.authorDid));
  const snapshot = await deps.activities.issue(session.did, activities);
  const rows = snapshot.discussions.map((item) => {
    const badge = item.unread ? '<span class="badge">Unread</span> ' : "";
    const detail = details.get(item.discussionUri) ?? { authorDid: "", title: "Discussion", createdAt: "" };
    const rkey = item.discussionUri.split("/").at(-1) ?? "";
    const title = rkey === ""
      ? escapeHtml(detail.title)
      : `<a href="${escapeHtml(discussionHref(rkey))}">${escapeHtml(detail.title)}</a>`;
    const author = detail.authorDid === "" ? "" : ` · ${renderIdentity(detail.authorDid, profiles, { avatars: deps.config.avatarsEnabled })}`;
    const posted = detail.createdAt === "" ? "" : ` · ${postedAt(detail.createdAt)}`;
    return `<li>${badge}${title} ${COMMUNITY_VIEW_BADGE}${author}${posted} — ${isP0(deps.config) ? `${item.moderationChanges} moderation changes` : `${item.newReplies} replies, ${item.moderationChanges} moderation changes`}</li>`;
  }).join("");
  const unfinished = await unfinishedSection(deps, session.did);
  const waiting = isP0(deps.config) ? await p0StatusSection(deps, session, params) : await waitingSection(deps, session.did);
  const listHeading = unfinished === "" && waiting === "" ? "" : "<h2>Discussions you are in</h2>";
  return html(response, 200, page(deps.config, session, isP0(deps.config) ? "My submissions" : "My discussions", `${unfinished}${waiting}${listHeading}<ul>${rows || "<li>None yet.</li>"}</ul><form method="post" action="/seen"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><input type="hidden" name="snapshot" value="${escapeHtml(snapshot.token)}"><button>Mark as read</button></form>`), deps.config);
}

// The signed-in author's contribution plans whose community submission the
// durable journal has not recorded as committed: an interrupted action is
// found again here instead of only through the link the browser lost.
// Derived from the plan store and the journal; nothing new is recorded.
async function unfinishedSection(deps: Dependencies, did: string): Promise<string> {
  const journal = new DurableWriteJournal(join(deps.config.runtimeDirectory, "operations", `${encodeURIComponent(did)}.json`));
  const unfinished: ContributionPlan[] = [];
  for (const plan of await deps.plans.byAuthor(did)) {
    const context = await journal.find(plan.contextOperationId);
    if (context?.phase !== "committed") unfinished.push(plan);
  }
  if (unfinished.length === 0) return "";
  unfinished.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  const items = unfinished.slice(0, UNFINISHED_ACTIONS_LIMIT).map((plan) => {
    const what = plan.existingPostCid !== undefined
      ? "Adding a post you already made"
      : plan.discussion !== undefined
        ? "A reply"
        : "A new discussion";
    const started = plan.createdAt === "" ? "" : ` · started <time datetime="${escapeHtml(plan.createdAt)}">${escapeHtml(humanDate(plan.createdAt))}</time>`;
    return `<li><a href="/operation?id=${encodeURIComponent(plan.operationId)}">${what}</a>${started}</li>`;
  }).join("");
  return `<h2>Unfinished actions</h2><p>These actions were interrupted before they finished. Nothing was duplicated; open one to check the exact records and continue.</p><ul class="unfinished">${items}</ul>`;
}

// The signed-in author's own root submissions that the projection lists as
// not yet admitted. The full queue is read server-side and filtered to the
// session DID here; no other author's entry is rendered.
async function waitingSection(deps: Dependencies, did: string): Promise<string> {
  const heading = "<h2>Waiting for the moderator</h2>";
  let entries: Record<string, unknown>[];
  try {
    const doc = await deps.projection.get(`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/moderation-queue`);
    entries = array(doc.submissions).map((value) => record(value)).filter((entry) => {
      const submission = strongRef(entry.submission);
      return entry.authorDid === did && submission.uri.startsWith(`at://${did}/`) && submission.cid !== "";
    });
  } catch {
    return `${heading}<p class="notice">Whether any of your submissions are still waiting for the moderator cannot be checked right now. Try again later.</p>`;
  }
  if (entries.length === 0) return "";
  const posts = await hydratePosts(deps, entries.map((entry) => strongRef(entry.subject).uri));
  const items = entries.map((entry) => {
    const subject = strongRef(entry.subject);
    const text = submittedText(posts, subject);
    const link = publicPostLink(subject.uri);
    return `<li>${text}${link === "" ? "Your submitted post" : link}</li>`;
  }).join("");
  return `${heading}<p>You submitted these posts to the community. The moderator has not admitted them yet, so they are not in the community view. Your public posts are unaffected.</p><ul class="waiting">${items}</ul>`;
}

async function moderationQueue(deps: Dependencies, response: ServerResponse, session: WebSession, params = new URLSearchParams()): Promise<void> {
  if (isP0(deps.config)) return p0ModerationQueue(deps, response, session, params);
  if (session.did !== deps.config.moderatorDid) throw new HttpError(403, "Moderator permission is required.");
  const doc = await deps.projection.get(`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/moderation-queue`);
  const entries = array(doc.submissions).map((value) => record(value));
  const profiles = await deps.profiles.lookup(entries.map((entry) => stringOf(entry.authorDid)));
  const posts = await hydratePosts(deps, entries.map((entry) => strongRef(entry.subject).uri));
  const rows = entries.map((entry) => {
    const submission = strongRef(entry.submission);
    const subject = strongRef(entry.subject);
    const authorDid = stringOf(entry.authorDid);
    const author = authorDid === "" ? "" : `${renderIdentity(authorDid, profiles, { avatars: deps.config.avatarsEnabled, showDid: true })} · `;
    const link = publicPostLink(subject.uri);
    const text = submittedText(posts, subject);
    return `<li>${author}${escapeHtml(submission.uri)}${link === "" ? "" : ` · ${link}`}${text}<form method="post" action="/moderate"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><input type="hidden" name="kind" value="admit-root"><input type="hidden" name="uri" value="${escapeHtml(submission.uri)}"><input type="hidden" name="cid" value="${escapeHtml(submission.cid)}"><button>Admit</button></form></li>`;
  }).join("");
  return html(response, 200, page(deps.config, session, "Moderation", `<ul>${rows || "<li>No pending roots.</li>"}</ul>`), deps.config);
}

async function hydratePosts(deps: Dependencies, uris: readonly string[]): Promise<ReadonlyMap<string, HydratedPost>> {
  if (deps.posts === undefined) return new Map();
  try {
    return await deps.posts.lookup(uris.filter((uri) => uri !== ""));
  } catch {
    return new Map();
  }
}

// AppView text is shown only for the exact submitted version: when the
// AppView's current CID differs from the subject CID, nothing is shown.
function submittedText(posts: ReadonlyMap<string, HydratedPost>, subject: StrongRef): string {
  const post = posts.get(subject.uri);
  if (post === undefined || subject.cid === "" || post.cid !== subject.cid) return "";
  return `<article class="submitted-text">${escapeHtml(post.text)}</article><p class="meta hydration-note">(text from Bluesky, unverified)</p>`;
}

async function operationPage(deps: Dependencies, response: ServerResponse, session: WebSession, operationId: string, status: string | undefined, repeated = false): Promise<void> {
  const plan = await ownedPlan(deps, operationId, session.did);
  const message = status === undefined
    ? "Your last action was interrupted. Nothing was duplicated; you can safely pick up where you left off."
    : repeated && status === "complete"
    ? `You already asked to add this exact post; nothing new was created. ${isP0(deps.config) ? "My submissions" : "My discussions"} shows whether the moderator has added it.`
    : isP0(deps.config) && status === "complete" ? "The public submission record was written. Awaiting independent observation; this does not mean admitted or queued." : userMessage(status as Parameters<typeof userMessage>[0], plan);
  const done = status === "complete";
  return html(response, 200, page(deps.config, session, "Contribution", `<p>${escapeHtml(message)}</p>${done ? `<p><a href="/mine">${isP0(deps.config) ? "View my submissions" : "View my discussions"}</a></p>` : `<form method="post" action="/operation/resume"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><input type="hidden" name="operationId" value="${escapeHtml(operationId)}"><button>Continue</button></form>`}`), deps.config);
}

/**
 * The participant's OAuth session behind the web session. When it cannot be
 * restored (revoked at the PDS, refresh refused, store lost), the web session
 * is ended too, so the participant is asked to sign in again rather than
 * shown a failure that repeats on every attempt.
 */
/** Revoke the account's provider tokens (best effort) and end every web session of the account. */
async function endAccountAccess(deps: Dependencies, did: string): Promise<void> {
  await deps.oauth?.revoke?.(did).catch(() => undefined);
  await deps.webSessions.revokeAccount(did);
}

/** Delete everything Phlogiston keeps for one account; the community's moderation records are out of scope. */
async function eraseAccount(deps: Dependencies, did: string): Promise<{feeds: number; localQuiet: number; quietHistory: number; seen: number; plans: number; journals: number}> {
  const journal = join(deps.config.runtimeDirectory, "operations", `${encodeURIComponent(did)}.json`);
  const journals = await rm(journal).then(() => 1, (error: NodeJS.ErrnoException) => { if (error.code === "ENOENT") return 0; throw error; });
  const erased = {
    feeds: deps.personalFeeds?.eraseAccount(did) ?? 0,
    localQuiet: deps.localQuiet?.eraseAccount(did) ?? 0,
    quietHistory: deps.quiet?.eraseAccount(did) ?? 0,
    seen: await deps.activities.eraseMember(did),
    plans: await deps.plans.deleteByAuthor(did),
    journals,
  };
  await endAccountAccess(deps, did);
  return erased;
}

async function restoredSession(deps: Dependencies, response: ServerResponse, token: string | undefined, session: WebSession): Promise<OAuthSession> {
  try {
    const restored = await deps.oauth.restore(session.did);
    if (isP0(deps.config)) await requireBlueskySession(restored, session.did, deps.config);
    return restored;
  } catch {
    await deps.webSessions.revoke(token);
    response.setHeader("Set-Cookie", clearedCookie(deps.config.publicUrl));
    throw new HttpError(401, "Your sign-in has expired. Sign in again.");
  }
}

function contributionService(deps: Dependencies, session: OAuthSession, did: string): ContributionService {
  const original = deps.repoWriter === undefined ? new OAuthPublicRepoWriter(session, did) : deps.repoWriter(session, did);
  const writer: PublicRepoWriter = isP0(deps.config) ? { get: address => original.get(address), create: async (address, record) => {
    if (address.collection !== "app.phlogiston.community.submit") throw new HttpError(403, "Only submission records may be written in this profile.");
    await requireBlueskySession(session, did, deps.config);
    await requireActiveMutation(deps, did, address, record);
    await requireSiteWrites(deps.config);
    return original.create(address, record);
  }} : original;
  return new ContributionService(
    new DurableWriteJournal(join(deps.config.runtimeDirectory, "operations", `${encodeURIComponent(did)}.json`), isP0(deps.config) ? async operation => {
      await requireActiveMutation(deps, did, operation, operation.record, operation.operationId);
      await requireSiteWrites(deps.config);
    } : undefined),
    deps.config.integrationFaultDirectory === undefined
      ? writer
      : new PostCommitFaultWriter(writer, deps.config.integrationFaultDirectory),
  );
}

async function ownedPlan(deps: Dependencies, id: string, did: string): Promise<ContributionPlan> {
  const plan = await deps.plans.get(id);
  if (plan.authorDid !== did) throw new HttpError(403, "That action belongs to a different account.");
  return plan;
}

function postReference(value: string): PostReference {
  try {
    return parsePostReference(value);
  } catch (error) {
    if (error instanceof PostReferenceError) throw new HttpError(400, error.message);
    throw error;
  }
}

/**
 * Self-submission only: the post's repository must be the session DID. A handle
 * counts as the session's own only when the existing profile hydration reports
 * that exact handle for the session DID; no other handle resolution happens,
 * and an unresolved handle (the AppView's `handle.invalid`) is unknown, not
 * someone else's. Either way the post is read from, and the submission
 * written to, the session DID's own repository.
 */
async function ownPostRkey(deps: Dependencies, session: WebSession, reference: PostReference): Promise<string> {
  const refusal = "You can only add your own posts here.";
  const hint = `paste the link that shows your account as ${session.did}`;
  if (reference.kind === "did") {
    if (reference.did !== session.did) throw new HttpError(403, refusal);
    return reference.rkey;
  }
  const own = (await deps.profiles.lookup([session.did])).get(session.did)?.handle;
  if (own === undefined) {
    throw new HttpError(503, `We couldn't confirm that link is yours right now. Try again in a moment, or ${hint}.`);
  }
  if (own.toLowerCase() !== reference.handle) {
    throw new HttpError(403, `${refusal} That link names a different account; to add one of yours, ${hint}.`);
  }
  return reference.rkey;
}

// A reply form can be replayed after the moderator removed or closed the
// discussion; the projection, not the form, decides whether replies are open.
async function requireOpenDiscussion(deps: Dependencies, discussionUri: string): Promise<void> {
  const rkey = validRkey(discussionUri.split("/").at(-1) ?? "");
  let doc: Record<string, unknown>;
  try {
    doc = await deps.projection.get(`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/discussions/${encodeURIComponent(rkey)}`);
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) {
      throw new HttpError(409, "That discussion is no longer in the community, so replies can't be added.");
    }
    throw error;
  }
  const root = record(doc.discussion);
  if (root.status !== "visible" || root.closed === true) {
    throw new HttpError(409, "That discussion is closed or no longer in the community, so replies can't be added.");
  }
}

function replyInput(form: URLSearchParams): { root: StrongRef; parent: StrongRef; discussion: StrongRef } | undefined {
  if (!form.has("discussionUri")) return undefined;
  return {
    root: { uri: required(form, "rootUri"), cid: required(form, "rootCid") },
    parent: { uri: required(form, "parentUri"), cid: required(form, "parentCid") },
    discussion: { uri: required(form, "discussionUri"), cid: required(form, "discussionCid") },
  };
}

function moderatorCommand(form: URLSearchParams): ModeratorCommand {
  if (form.get("kind") === "decline-root") return {kind:"decline-root",submissionUri:required(form,"uri"),submissionCid:required(form,"cid"),reason:required(form,"reason")};
  const kind = required(form, "kind");
  const uri = required(form, "uri");
  const cid = required(form, "cid");
  if (kind === "admit-root") return { kind, submissionUri: uri, submissionCid: cid };
  const reason = required(form, "reason");
  if (kind === "remove-root") return { kind, admissionUri: uri, admissionCid: cid, reason };
  if (kind === "remove-reply") return { kind, admissionUri: uri, admissionCid: cid, reason };
  if (kind === "restore-reply") return {
    kind,
    admissionUri: uri,
    admissionCid: cid,
    controllingActionUri: required(form, "controllingActionUri"),
    controllingActionCid: required(form, "controllingActionCid"),
    reason,
  };
  throw new HttpError(400, "Unknown moderation action.");
}

async function checkedForm(deps: Dependencies, request: IncomingMessage, session: WebSession): Promise<URLSearchParams> {
  requireOrigin(request, deps.config.publicUrl);
  const form = await readForm(request);
  if (required(form, "csrf", "This form has expired. Go back and try again.") !== session.csrf) throw new HttpError(403, "The form token did not match; submit the form again.");
  return form;
}

async function readForm(request: IncomingMessage): Promise<URLSearchParams> {
  if (request.headers["content-type"]?.split(";", 1)[0] !== "application/x-www-form-urlencoded") throw new HttpError(400, "The form encoding is not accepted.");
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of request) {
    const bytes = Buffer.from(chunk);
    total += bytes.length;
    if (total > MAX_FORM_BYTES) throw new HttpError(400, "The form is too large.");
    chunks.push(bytes);
  }
  return new URLSearchParams(Buffer.concat(chunks).toString("utf8"));
}

function required(values: URLSearchParams, key: string, message = `${key} is required.`): string {
  const value = values.get(key)?.trim();
  if (!value || value.includes("\0")) throw new HttpError(400, message);
  return value;
}
function requireOrigin(request: IncomingMessage, origin: string): void {
  if (request.headers.origin !== origin) throw new HttpError(403, "The request origin is not accepted.");
}
function cookieValue(header: string | undefined, name: string): string | undefined {
  for (const item of header?.split(";") ?? []) {
    const [key, ...value] = item.trim().split("=");
    if (key === name) return value.join("=");
  }
  return undefined;
}
function cookie(value: string, publicUrl: string): string {
  return `${COOKIE}=${value}; Path=/; HttpOnly; SameSite=Lax; Max-Age=28800${new URL(publicUrl).protocol === "https:" ? "; Secure" : ""}`;
}
function clearedCookie(publicUrl: string): string {
  return `${COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${new URL(publicUrl).protocol === "https:" ? "; Secure" : ""}`;
}
function loginCookie(nonce: string, publicUrl: string): string {
  return `${LOGIN_COOKIE}=${nonce}; Path=/oauth; HttpOnly; SameSite=Lax; Max-Age=${LOGIN_COOKIE_MAX_AGE}${new URL(publicUrl).protocol === "https:" ? "; Secure" : ""}`;
}
function clearedLoginCookie(publicUrl: string): string {
  return `${LOGIN_COOKIE}=; Path=/oauth; HttpOnly; SameSite=Lax; Max-Age=0${new URL(publicUrl).protocol === "https:" ? "; Secure" : ""}`;
}
function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function strongRef(value: unknown): StrongRef {
  const target = record(value);
  return { uri: typeof target.uri === "string" ? target.uri : "", cid: typeof target.cid === "string" ? target.cid : "" };
}
function stringOf(value: unknown): string {
  return typeof value === "string" ? value : "";
}
function redirect(response: ServerResponse, location: string, config: AppConfig): void {
  secure(response, config); response.statusCode = 303; response.setHeader("Location", location); response.end();
}
function text(response: ServerResponse, status: number, body: string, config: AppConfig): void {
  secure(response, config); response.statusCode = status; response.setHeader("Content-Type", "text/plain; charset=utf-8"); response.end(body);
}
function json(response: ServerResponse, status: number, body: unknown, config: AppConfig): void {
  secure(response, config); response.statusCode = status; response.setHeader("Content-Type", "application/json"); response.end(JSON.stringify(body));
}
function html(response: ServerResponse, status: number, body: string, config: AppConfig): void {
  response.setHeader("Vary", "Cookie");
  if (!response.hasHeader("Cache-Control")) response.setHeader("Cache-Control", "private, no-cache");
  secure(response, config); response.statusCode = status; response.setHeader("Content-Type", "text/html; charset=utf-8"); response.end(body);
}
let stylesheetBody: Promise<Buffer> | undefined;
async function stylesheet(response: ServerResponse, config: AppConfig): Promise<void> {
  stylesheetBody ??= readFile(new URL("../static/app.css", import.meta.url));
  const body = await stylesheetBody;
  secure(response, config);
  response.statusCode = 200;
  response.setHeader("Content-Type", "text/css; charset=utf-8");
  response.setHeader("Cache-Control", "no-cache");
  response.end(body);
}
function noStore(response: ServerResponse): void {
  response.setHeader("Cache-Control", "no-store");
}
function secure(response: ServerResponse, config: AppConfig): void {
  const images = config.avatarsEnabled || config.readerEnabled ? " img-src 'self' https://cdn.bsky.app https://video.bsky.app; media-src https://video.bsky.app;" : "";
  response.setHeader("Content-Security-Policy", `default-src 'self';${images} base-uri 'none'; frame-ancestors 'none'`);
  response.setHeader("Referrer-Policy", "same-origin");
  response.setHeader("X-Content-Type-Options", "nosniff");
}
function sessionActions(session: WebSession): string {
  return `<form method="post" action="/signout"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><button>Sign out</button></form><form method="post" action="/disconnect"><input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><button>Disconnect</button></form>`;
}

function page(config: AppConfig, session: WebSession | null, title: string, body: string): string {
  const display = displayContext.getStore();
  const path = display?.path ?? "/";
  const siteHome = isP0(config) && path === "/";
  const documentTitle = siteHome ? "Phlogiston" : `${title}${isP0(config) ? " · Phlogiston" : ""}`;
  const description = path === "/community"
    ? `${config.communityName}: a human-curated collection of public posts on Phlogiston.`
    : "Your Bluesky feeds, conversations, and curated collections, side by side. More control over your attention, with context when you want it.";
  const socialMetadata = isP0(config)
    ? `<meta name="description" content="${escapeHtml(description)}"><meta property="og:type" content="website"><meta property="og:site_name" content="Phlogiston"><meta property="og:title" content="${escapeHtml(documentTitle)}"><meta property="og:description" content="${escapeHtml(description)}"><meta name="twitter:card" content="summary"><meta name="twitter:title" content="${escapeHtml(documentTitle)}"><meta name="twitter:description" content="${escapeHtml(description)}">`
    : "";
  const feedActive = ["/home", "/feed", "/thread", "/attention"].includes(path);
  const communityActive = path === "/community" || path === "/" || path.startsWith("/d/");
  const nav = session !== null && isP0(config) && config.readerEnabled
    ? `<nav aria-label="Main"><a href="/home"${feedActive ? ' aria-current="page"' : ""}>Following</a><a href="/community"${communityActive ? ' aria-current="page"' : ""}>Community</a><details class="account-menu"><summary>Account</summary><div class="account-menu-items"><a href="/labels">My labels</a><a href="/attention">Conversation controls</a><a href="/mine">My submissions</a><a href="/display">Display</a><a href="/settings">Settings</a><a href="/feeds">Personal feeds</a><a href="/help">Getting started</a>${session.did === config.moderatorDid ? '<a href="/moderation">Moderate</a>' : ""}</div></details></nav>`
    : session === null
    ? (isP0(config) && config.readerEnabled ? '<nav aria-label="Main"><a href="/community">The Cabinet</a><a href="/display">Display</a><a class="header-signin" href="/signin">Sign in</a></nav>' : '<nav aria-label="Display"><a href="/help">Getting started</a><a href="/display">Display</a></nav>')
    : `<nav aria-label="Account"><span class="identity">${escapeHtml(session.did)}</span>${isP0(config) ? '<a href="/home">Home</a><a href="/">Collection</a><a href="/labels">My Labels</a><a href="/settings">Settings</a>' : ""}<a href="/mine">${isP0(config) ? "My submissions" : "My discussions"}</a>${session.did === config.moderatorDid ? '<a href="/moderation">Moderate</a>' : ""}${isP0(config) ? "" : sessionActions(session)}</nav>`;
  return `<!doctype html><html lang="en" data-theme="${display?.theme ?? "system"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/static/app.css"><title>${escapeHtml(documentTitle)}</title>${socialMetadata}</head><body${isP0(config) ? ` class="p0${config.readerEnabled && ["/home", "/feed", "/thread"].includes(path) ? " reader-page" : ""}"` : ""}><a class="skip" href="#content">Skip to content</a><header><div class="header-inner"><a class="brand" href="${isP0(config) && session !== null ? "/home" : "/"}">${isP0(config) ? "Phlogiston" : escapeHtml(config.communityName)}</a>${nav}</div></header><main id="content"${session && config.readerEnabled ? ` data-workspace-did="${escapeHtml(session.did)}" data-csrf="${escapeHtml(session.csrf)}"` : ""}>${config.p0TestPdsOrigin ? `<p class="notice">Isolated integration qualification: this loopback instance explicitly uses ${escapeHtml(config.p0TestPdsOrigin)} test accounts. It is not the public Bluesky lifecycle or launch readiness.</p>` : ""}<div class="page-heading"><h1>${escapeHtml(title)}</h1>${session && config.readerEnabled && ["/home", "/feed"].includes(path) ? '<a class="feed-refresh" href="/home" aria-label="Refresh Following">Refresh</a>' : ""}</div>${body}</main>${isP0(config) ? publicFooter() : ""}${session && config.readerEnabled && ["/home", "/feed"].includes(path) ? '<script type="module" src="/static/workspace.js"></script>' : ""}</body></html>`;
}

export async function main(): Promise<void> {
  const config = loadConfig();
  const oauth = createOAuthClient(config);
  const deps: Dependencies = {
    config,
    labels: new LabelwatchDirectory(),
    ...(config.readerEnabled ? { publicThreads: new PublicThreadReader(config.appViewOrigin, {maxEntries: config.discussionsMaxItems}), quiet: new QuietStore(join(config.runtimeDirectory, "quiet", "history.sqlite")), localQuiet: new LocalQuietStore(join(config.runtimeDirectory, "local-quiet", "preferences.sqlite")), personalFeeds: new PersonalFeedStore(join(config.runtimeDirectory,"personal-feeds","definitions.sqlite")), publicBlocks: new PublicBlockDirectory({supportsPds: origin => supportedPds(config,origin),resolvePds: async (did,signal) => { if(!did.startsWith("did:plc:")) throw new Error("Curator identity hosting is not supported yet"); const identity = await oauth.oauthResolver.resolveIdentity(did,{noCache:true,signal}); const service = identity.didDoc.service?.find(s=>s.id === "#atproto_pds" || s.id === `${did}#atproto_pds`); if(identity.did !== did || service?.type !== "AtprotoPersonalDataServer" || typeof service.serviceEndpoint !== "string") throw new Error("Curator PDS could not be resolved"); return {did:identity.did,pds:service.serviceEndpoint}; }}) } : {}),
    oauth,
    p0Identity: async did => {
      const identity=await oauth.oauthResolver.resolveIdentity(did,{noCache:true});
      const service=identity.didDoc.service?.find(s=>s.id === "#atproto_pds" || s.id === `${did}#atproto_pds`);
      return did.startsWith("did:plc:") && identity.did === did && service?.type === "AtprotoPersonalDataServer" && typeof service.serviceEndpoint === "string" && supportedPds(config,service.serviceEndpoint);
    },
    webSessions: new WebSessionStore(join(config.runtimeDirectory, "web-sessions")),
    plans: new ContributionPlanStore(join(config.runtimeDirectory, "contribution-plans")),
    activities: new ActivitySnapshots(
      Buffer.from(process.env.COMMUNITY_SNAPSHOT_SECRET ?? "", "base64url"),
      new FileSeenStore(join(config.runtimeDirectory, "last-seen.json")),
    ),
    authority: new UnixAuthorityRequester(config.authoritySocket),
    projection: new ObserverClient(config.observerUrl, config.observerMaxResponseBytes),
    profiles: new AppViewProfileDirectory(
      config.appViewOrigin,
      new ProfileCache(1_000, 10 * 60 * 1_000, 60 * 1_000, () => Date.now()),
    ),
    posts: new AppViewPostDirectory(
      config.appViewOrigin,
      new PostCache(1_000, 10 * 60 * 1_000, 60 * 1_000, () => Date.now()),
    ),
  };
  createServer(createHandler(deps)).listen(config.port, "127.0.0.1");
  const sweep = () => retentionSweep(config.runtimeDirectory, deps, (did) => oauth.revoke(did))
    .catch((error: unknown) => { console.error(`retention sweep failed: ${error instanceof Error ? error.message : String(error)}`); });
  void sweep();
  setInterval(() => void sweep(), HOUR_MS).unref();
}

if (process.argv[1] === import.meta.filename) {
  await main();
}

function reservations(deps: Dependencies): P0Reservations { return new P0Reservations(join(deps.config.runtimeDirectory,"p0-intake"), () => Date.now(), JSON.stringify([deps.config.communityDid,deps.config.publicUrl,deps.config.p0HostedPdsOrigin ? `hosted:${deps.config.p0HostedPdsOrigin}${deps.config.p0AllowBluesky ? "+bluesky" : ""}` : deps.config.p0TestPdsOrigin ?? "bluesky"])); }
function p0PlanSubject(deps: Dependencies, plan: ContributionPlan): StrongRef {
  if (plan.communityDid !== deps.config.communityDid || !plan.existingPostCid || plan.discussion !== undefined ||
      plan.source.repo !== plan.authorDid || plan.source.collection !== POST_COLLECTION ||
      !RKEY_PATTERN.test(plan.source.rkey) || !Number.isFinite(Date.parse(plan.createdAt))) {
    throw new HttpError(403, "This plan is not an existing-post intent for this community.");
  }
  const subject = { uri: `at://${plan.authorDid}/${POST_COLLECTION}/${plan.source.rkey}`, cid: plan.existingPostCid };
  const identity = existingPostOperationId(deps.config.communityDid, subject);
  if (plan.operationId !== identity || plan.sourceOperationId !== `${identity}:source` ||
      plan.contextOperationId !== `${identity}:context` || plan.context.repo !== plan.authorDid ||
      plan.context.collection !== SUBMIT_COLLECTION || plan.context.rkey !== submissionRkey(deps.config.communityDid, subject)) {
    throw new HttpError(403, "This plan does not match its exact source and submission identity.");
  }
  return subject;
}

async function requireActiveMutation(
  deps: Dependencies, did: string, address: RecordAddress, raw: unknown, operationId?: string,
): Promise<void> {
  const value = record(raw), subject = strongRef(value.subject);
  const identity = existingPostOperationId(deps.config.communityDid, subject);
  if (address.repo !== did || address.collection !== SUBMIT_COLLECTION || value.$type !== SUBMIT_COLLECTION ||
      value.community !== deps.config.communityDid || value.discussion !== undefined || !subject.cid ||
      !subject.uri.startsWith(`at://${did}/${POST_COLLECTION}/`) ||
      address.rkey !== submissionRkey(deps.config.communityDid, subject) ||
      (operationId !== undefined && operationId !== `${identity}:context`)) {
    throw new HttpError(403, "Fresh submission does not match this community's exact intent.");
  }
  const reservation = await reservations(deps).find(deps.config.communityDid, did, subject);
  if (!reservation || !reservation.active || reservation.operationId !== identity) {
    throw new HttpError(409, "Fresh submission requires its matching active intake reservation. No new write was attempted.");
  }
}

async function advancePlan(deps: Dependencies, service: ContributionService, plan: ContributionPlan) {
  if (!isP0(deps.config)) return service.advance(plan);
  const subject = p0PlanSubject(deps, plan);
  return reservations(deps).execute(plan.authorDid, async () => {
    const reservation = await reservations(deps).find(deps.config.communityDid, plan.authorDid, subject);
    const active = reservation?.active === true && reservation.operationId === plan.operationId;
    const journal = new DurableWriteJournal(join(deps.config.runtimeDirectory, "operations", `${encodeURIComponent(plan.authorDid)}.json`));
    const previous = await journal.find(plan.contextOperationId);
    if (!active && previous?.phase !== "attempted_unknown" && previous?.phase !== "committed") {
      throw new HttpError(409, "This action has no matching active intake reservation. No fresh write can resume from this plan.");
    }
    const result = await service.advance(plan, !active);
    // Reload after the service updates its separate journal instance.
    const refreshed = new DurableWriteJournal(join(deps.config.runtimeDirectory, "operations", `${encodeURIComponent(plan.authorDid)}.json`));
    const current = await refreshed.find(plan.contextOperationId);
    if (result.status === "complete" && current?.committedCid && reservation) {
      await reservations(deps).update(plan.operationId, { submission: {
        uri: `at://${plan.authorDid}/${plan.context.collection}/${plan.context.rkey}`, cid: current.committedCid,
      } });
    }
    if (result.status === "community_submission_conflict" && active) {
      // A digest conflict alone cannot establish publication or nonpublication.
      // Qualify the current record separately; missing or uncertain reads retain capacity.
      const observed = await service.readContext(plan).catch(() => null);
      const value = record(observed?.record);
      const candidate = record(value.subject);
      const keys = Object.keys(value);
      const qualified = observed?.cid && value.$type === SUBMIT_COLLECTION &&
        typeof value.community === "string" && /^did:[a-z]+:[A-Za-z0-9._:%-]+$/.test(value.community) &&
        typeof value.createdAt === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value.createdAt) && Number.isFinite(Date.parse(value.createdAt)) &&
        keys.every(key => ["$type", "community", "subject", "createdAt"].includes(key)) &&
        Object.keys(candidate).every(key => ["uri", "cid"].includes(key)) &&
        typeof candidate.uri === "string" && candidate.uri.split("/").length === 5 && candidate.uri.startsWith(`at://${plan.authorDid}/${POST_COLLECTION}/`) &&
        /^[A-Za-z0-9._~:-]+$/.test(candidate.uri.split("/").at(-1) ?? "") &&
        typeof candidate.cid === "string" && candidate.cid.length > 0;
      if (qualified) {
        if (value.community === deps.config.communityDid && candidate.uri === subject.uri && candidate.cid === subject.cid) {
          await reservations(deps).update(plan.operationId, { submission: {
            uri: `at://${plan.authorDid}/${SUBMIT_COLLECTION}/${plan.context.rkey}`, cid: observed!.cid,
          } });
        } else {
          await reservations(deps).update(plan.operationId, { active: false, decision: "submission_conflict" });
        }
      }
    }
    if (!active && result.status === "community_submission_pending") {
      throw new HttpError(409, "Readback did not establish this submission. A fresh mutation requires new admitted intake; this plan grants none.");
    }
    return result;
  });
}
async function privateStatus(deps:Dependencies,did:string,target:StrongRef):Promise<Record<string,unknown>> {
  const result=await deps.authority.request({operationId:`status:${randomUUID()}`,action:"root_status",authenticatedDid:did,target});
  if(!result.ok || !result.result) throw new HttpError(503,"Private submission status cannot be checked right now.");
  const submission=strongRef(result.result.submission);
  if (result.result.decision === "submission_unavailable") {
    if(submission.uri !== target.uri || submission.cid !== target.cid || result.result.subject !== null || result.result.admission !== null) throw new HttpError(503,"Unavailable status did not match the exact submission.");
    return result.result;
  }
  const subject=strongRef(result.result.subject);
  if (submission.uri !== target.uri || submission.cid !== target.cid || !subject.uri || !subject.cid ||
      !["none","admit_pending","admitted","declined"].includes(stringOf(result.result.decision))) throw new HttpError(503,"Private exact-submission status could not be qualified.");
  return result.result;
}
async function p0StatusSection(deps:Dependencies,session:WebSession,params:URLSearchParams):Promise<string> {
  const observed = new Set<string>();
  let coverage = "Observer coverage unavailable; absence is unknown.", next = "", deferred = "";
  const query = new URLSearchParams({limit:"25",authorDid:session.did});
  const cursor=params.get("cursor"); if(cursor) { if(cursor.length>2048) throw new HttpError(400,"Queue cursor is too long."); query.set("cursor",cursor); }
  try {
    const queue=await deps.projection.get(`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/moderation-queue?${query}`);
    coverage=record(queue.coverage).overflow || record(queue.coverage).incomplete ? "More candidates or incomplete observation remain. This page is not a complete history." : "This is a bounded candidate page, not a complete repository history.";
    if(typeof queue.nextCursor === "string") next=`<a href="/mine?cursor=${encodeURIComponent(queue.nextCursor)}">Next observed submission page</a>`;
    for(const raw of array(queue.submissions).slice(0,25)) {
      const entry=record(raw); if(entry.authorDid !== session.did) continue;
      const submission=strongRef(entry.submission),subject=strongRef(entry.subject);
      const current=await privateStatus(deps,session.did,submission);
      if(current.decision === "submission_unavailable") {
        const old=await reservations(deps).find(deps.config.communityDid,session.did,subject);
        if(old?.submission?.uri === submission.uri && old.submission.cid === submission.cid) await reservations(deps).update(old.operationId,{active:false,decision:"submission_unavailable"});
        continue;
      }
      const qualified=strongRef(current.subject); if(qualified.uri !== subject.uri || qualified.cid !== subject.cid) continue;
      const decision=stringOf(current.decision);
      try {
        if(decision === "admitted" || decision === "declined") {
          const old=(await reservations(deps).byAuthor(session.did)).find(e=>e.subject.uri === subject.uri && e.subject.cid === subject.cid);
          if(old) await reservations(deps).update(old.operationId,{active:false,decision});
          continue;
        }
        if(!await intakeOpen(deps.config)) {deferred+="<li>Observed candidate deferred: active intake is suspended; no decline or admission.</li>"; continue;}
        const intake=await reservations(deps).reserve(session.did,deps.config.communityDid,subject,existingPostOperationIdForIntake(deps,session.did,subject),false);
        if(!intake.active) {deferred+="<li>Observed candidate deferred: this exact intent has ended local intake.</li>";continue;}
        await reservations(deps).update(intake.operationId,{submission});
        observed.add(`${subject.uri}\n${subject.cid}`);
      } catch {deferred+="<li>Observed candidate deferred: active intake capacity is full or unavailable; no decision inferred.</li>";}
    }
  } catch { /* private decision status still remains useful when observation is unavailable */ }
  const entries=await reservations(deps).byAuthor(session.did);
  const rows=[];
  for(const entry of entries.slice(-25)) {
    let message="Awaiting independently verified observation. A completed repository write is not admission.";
    if (entry.decision === "submission_unavailable") message="The exact submission is no longer current or available. Local intake ended; this is not a decline and makes no claim about earlier admission.";
    if (entry.decision === "submission_conflict") message="This local submission attempt ended because the current repository record has a different qualified intent. It is not a decline or admission, and earlier publication is not inferred.";
    if(entry.submission && (entry.active || entry.decision === "admitted" || entry.decision === "declined")) {
      try {
        const status=await privateStatus(deps,session.did,entry.submission);
        const decision=stringOf(status.decision);
        if(decision === "declined" || decision === "admitted" || decision === "submission_unavailable") await reservations(deps).update(entry.operationId,{active:false,decision});
        message=decision === "submission_unavailable" ? "The exact submission is no longer current or available. Local intake ended; this is not a decline and makes no claim about earlier admission." : decision === "declined" ? `Declined for this site (private decision): ${stringOf(status.reason)}. Your public post is unchanged.` : decision === "admitted" ? "Admitted by the operator; the public view depends on independent observation." : decision === "admit_pending" ? "Admission outcome is unknown; the reservation remains active." : observed.has(`${entry.subject.uri}\n${entry.subject.cid}`) ? "Waiting for moderator review of this independently observed exact submission." : "Awaiting independently verified observation; no decision has been inferred.";
      } catch { message="Status is unknown right now; the reservation is retained."; }
    }
    rows.push(`<li>${publicPostLink(entry.subject.uri)} <code>${escapeHtml(entry.subject.cid)}</code><p>${escapeHtml(message)}</p></li>`);
  }
  return `<details><summary>Application permissions</summary><p>Requested scopes: ${escapeHtml(P0_SCOPE)}. Granted scopes: ${escapeHtml(session.grantedScopes ?? "Confirmed on sign-in.")}</p></details><h2>Your submissions</h2><ul>${rows.join("") || "<li>None yet.</li>"}</ul><p>Shows all active subjects plus recent completed subjects, up to 25 in total. A submission stays pending until a moderator’s decision is confirmed.</p><ul>${deferred}</ul>${next}<p>${escapeHtml(coverage)}</p>`;
}
async function p0ModerationQueue(deps:Dependencies,response:ServerResponse,session:WebSession,params:URLSearchParams):Promise<void> {
  if(session.did !== deps.config.moderatorDid) throw new HttpError(403,"Moderator permission is required.");
  // Navigation cursor is carried in a same-origin GET, never trusted as authority.
  const query = new URLSearchParams({limit:"25"});
  for (const field of ["cursor","authorDid"]) { const v=params.get(field); if(v) { if(v.length>2048) throw new HttpError(400,"Queue cursor is too long."); query.set(field,v); }}
  const path=`/api/v0/communities/${encodeURIComponent(deps.config.communityDid)}/moderation-queue?${query}`;
  const doc=await deps.projection.get(path);
  // Reconcile at most the 100 active exact submissions, including admissions no longer in candidate pages.
  const activeEntries = await reservations(deps).active();
  const offset = Number(params.get("reconcileOffset") ?? "0");
  const reconciliationOffset = Number.isSafeInteger(offset) && offset >= 0 && offset < 100 ? offset : 0;
  for (const active of activeEntries.slice(reconciliationOffset,reconciliationOffset+10)) {
    if (!active.submission) continue;
    try { const status=await privateStatus(deps,session.did,active.submission);
      if(status.decision === "declined" || status.decision === "admitted" || status.decision === "submission_unavailable") await reservations(deps).update(active.operationId,{active:false,decision:stringOf(status.decision)});
    } catch { /* unknown decisions retain active capacity */ }
  }
  const rows=[];
  for(const raw of array(doc.submissions).slice(0,25)) {
    const entry=record(raw), submission=strongRef(entry.submission), subject=strongRef(entry.subject), did=stringOf(entry.authorDid);
    if (!deps.p0Identity || !await deps.p0Identity(did).catch(()=>false)) { rows.push("<li>Unsupported or unknown account custody; not selected for intake.</li>"); continue; }
    let status:Record<string,unknown>;
    try { status=await privateStatus(deps,session.did,submission); } catch { rows.push("<li>Candidate status unavailable; no intake or decision inferred.</li>"); continue; }
    if(status.decision === "submission_unavailable") { rows.push("<li>Exact candidate submission is no longer current; no new intake or public decision inferred.</li>"); continue; }
    const confirmedSubject=strongRef(status.subject);
    if(confirmedSubject.uri !== subject.uri || confirmedSubject.cid !== subject.cid) { rows.push("<li>Exact candidate subject disagrees with authority readback; no intake selected.</li>"); continue; }
    const decision=stringOf(status.decision);
    if(decision === "declined" || decision === "admitted") {
      const keyPlan=existingPostOperationIdForIntake(deps,did,subject);
      await reservations(deps).reserve(did,deps.config.communityDid,subject,keyPlan,false).then(e=>reservations(deps).update(e.operationId,{active:false,decision})).catch(()=>undefined);
      continue;
    }
    if (!await intakeOpen(deps.config)) { rows.push("<li>New active intake is suspended; this candidate is deferred, not declined.</li>"); continue; }
    try { const e=await reservations(deps).reserve(did,deps.config.communityDid,subject,existingPostOperationIdForIntake(deps,did,subject),false);
      if(!e.active) {rows.push("<li>Candidate deferred: this exact intent has ended local intake; no new admission offered.</li>");continue;}
      if(e.submission && (e.submission.uri !== submission.uri || e.submission.cid !== submission.cid)) {rows.push("<li>Candidate alias deferred: this exact intent remains bound to its first qualified submission reference.</li>");continue;}
      await reservations(deps).update(e.operationId,{submission}); }
    catch { rows.push(`<li>${escapeHtml(did)}: deferred because active intake is full; no decline or admission.</li>`); continue; }
    const base=`<input type="hidden" name="csrf" value="${escapeHtml(session.csrf)}"><input type="hidden" name="uri" value="${escapeHtml(submission.uri)}"><input type="hidden" name="cid" value="${escapeHtml(submission.cid)}">`;
    rows.push(`<li>${escapeHtml(did)} ${publicPostLink(subject.uri)} <code>${escapeHtml(subject.cid)}</code><form method="post" action="/moderate">${base}<input type="hidden" name="kind" value="admit-root"><button>Admit exact version</button></form><form method="post" action="/moderate">${base}<input type="hidden" name="kind" value="decline-root"><label>Private reason<input name="reason" required maxlength="2000"></label><button>Decline for this site</button></form></li>`);
  }
  const nextQuery = new URLSearchParams();
  if(typeof doc.nextCursor === "string")nextQuery.set("cursor",doc.nextCursor);
  if(params.get("authorDid"))nextQuery.set("authorDid",params.get("authorDid")!);
  const next = typeof doc.nextCursor === "string" ? `<a href="/moderation?${escapeHtml(nextQuery.toString())}">Next candidate page</a>` : "";
  const reconcileNext = activeEntries.length > reconciliationOffset+10 ? `<a href="/moderation?reconcileOffset=${reconciliationOffset+10}">Check more active intake statuses</a>` : "";
  const continuations = Object.entries(record(record(doc.coverage).authorCursors)).slice(0,25).map(([did,cursor]) => typeof cursor === "string" ? `<a href="/moderation?authorDid=${encodeURIComponent(did)}&cursor=${encodeURIComponent(cursor)}">More candidates for ${escapeHtml(did)}</a>` : "").join(" ");
  return html(response,200,page(deps.config,session,"Review candidates",`<p>Only reserved items are active review work. Other publications are candidates, not automatically queued. This request checks at most 10 existing active statuses and 25 candidates.</p><ul>${rows.join("") || "<li>No active candidates on this page.</li>"}</ul>${next} ${continuations} ${reconcileNext}<p>${record(doc.coverage).overflow || record(doc.coverage).incomplete ? "More candidates or incomplete observation remain; use the continuation links." : "This bounded page does not claim complete stream history."}</p>`),deps.config);
}
function existingPostOperationIdForIntake(deps:Dependencies,did:string,subject:StrongRef):string {
 return new ContributionService(new DurableWriteJournal("unused"),{get:async()=>null,create:async()=>{throw new Error("inert");}}).planExisting({authorDid:did,subject,communityDid:deps.config.communityDid,createdAt:new Date().toISOString()}).operationId;
}
