import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import type { BskyPreferences } from "@atproto/api";
import { Reader, type ReaderTransport } from "./reader.js";
import { LocalQuietStore } from "./local-quiet.js";
import { FEED_SCOPE, READER_INTERACTION_SCOPE } from "./p0.js";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { chromium, type Browser, type BrowserContext, type Page } from "playwright-core";
import type { OAuthSession } from "@atproto/oauth-client-node";

import type { LabelDirectory } from "./labels.js";
import { ActivitySnapshots, type SeenStore } from "./activity.js";
import { loadConfig, type AppConfig } from "./config.js";
import { ObserverClient } from "./observer.js";
import { AppViewProfileDirectory, ProfileCache } from "./profiles.js";
import { createHandler, type Dependencies } from "./server.js";
import { ContributionPlanStore, WebSessionStore } from "./storage.js";

// Automated browser qualification for PCV1-M6. Runs against a real browser
// executable resolved in order: COMMUNITY_BROWSER_EXECUTABLE, the cached
// Playwright headless shell, then the system Chrome. Absence is a failure,
// not a skip: the suite must never silently drop out of `pnpm check`.
const BROWSER_CANDIDATES = [
  process.env.COMMUNITY_BROWSER_EXECUTABLE,
  `${homedir()}/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell`,
  "/usr/bin/google-chrome",
].filter((value): value is string => typeof value === "string" && value !== "");
const browserExecutable = BROWSER_CANDIDATES.find((candidate) => existsSync(candidate));
if (browserExecutable === undefined) {
  throw new Error("no browser executable found; set COMMUNITY_BROWSER_EXECUTABLE");
}

const SHOTS = process.env.COMMUNITY_BROWSER_SHOTS ?? new URL("../.browser-shots/", import.meta.url).pathname;

const MODERATOR = "did:plc:moderator";
const MEMBER = "did:plc:alice";
const COMMUNITY = "did:plc:community";
const ADMISSION = "app.phlogiston.community.admission";

interface StubReply {
  status?: number;
  body?: unknown;
  raw?: string;
}

interface Harness {
  origin: string;
  sessions: WebSessionStore;
  signOutCalls: string[];
  close(): Promise<void>;
}

async function startApp(
  reply: (path: string) => StubReply,
  overrides: Partial<AppConfig> = {},
  appViewReply: (path: string) => StubReply = () => ({ status: 500, body: {} }),
  labels?: LabelDirectory,
  oauthScope?: string,
): Promise<Harness> {
  const root = await mkdtemp(join(tmpdir(), "community-browser-"));
  const observer = createServer((request, response) => {
    const stub = reply(request.url ?? "/");
    response.statusCode = stub.status ?? 200;
    response.setHeader("Content-Type", "application/json");
    response.end(stub.raw ?? JSON.stringify(stub.body ?? {}));
  });
  await new Promise<void>((resolve) => observer.listen(0, "127.0.0.1", resolve));
  const observerUrl = `http://127.0.0.1:${(observer.address() as AddressInfo).port}`;
  const appView = createServer((request, response) => {
    const stub = appViewReply(request.url ?? "/");
    response.statusCode = stub.status ?? 200;
    response.setHeader("Content-Type", "application/json");
    response.end(stub.raw ?? JSON.stringify(stub.body ?? {}));
  });
  await new Promise<void>((resolve) => appView.listen(0, "127.0.0.1", resolve));
  const appViewOrigin = `http://127.0.0.1:${(appView.address() as AddressInfo).port}`;

  // The browser sends its own Origin header on form posts, so the app's
  // public URL must be the actual ephemeral origin, not a placeholder.
  const app = createServer();
  await new Promise<void>((resolve) => app.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(app.address() as AddressInfo).port}`;
  const config: AppConfig = {
    publicUrl: origin,
    communityDid: COMMUNITY,
    communityName: "Test Community",
    communityPurpose: "A bounded test community",
    moderatorDid: MODERATOR,
    runtimeDirectory: root,
    observerUrl,
    observerMaxResponseBytes: 64 * 1024,
    discussionsMaxItems: 500,
    appViewOrigin,
    avatarsEnabled: false,
    authoritySocket: join(root, "authority.sock"),
    port: 3210,
    ...overrides,
  };
  const sessions = new WebSessionStore(join(root, "web-sessions"));
  const signOutCalls: string[] = [];
  const deps: Dependencies = {
    config,
    ...(labels ? { labels } : {}),
    oauth: {
      authorize: async () => new URL("https://auth.invalid.test/authorize"),
      callback: async () => ({ session: { did: MEMBER } as unknown as OAuthSession }),
      restore: async (did: string) => ({
        did,
        getTokenInfo: async () => ({ sub: did, iss: "https://bsky.social", aud: "https://fixture.host.bsky.network", scope: oauthScope ?? "atproto repo:app.phlogiston.community.submit?action=create" }),
        signOut: async () => {
          signOutCalls.push(did);
        },
      } as unknown as OAuthSession),
      revoke: async (did: string) => {
        signOutCalls.push(did);
      },
    },
    webSessions: sessions,
    plans: new ContributionPlanStore(join(root, "contribution-plans")),
    activities: new ActivitySnapshots(Buffer.alloc(32, 3), new MemorySeenStore()),
    authority: { request: async () => ({ ok: true }) },
    projection: new ObserverClient(config.observerUrl, config.observerMaxResponseBytes),
    profiles: new AppViewProfileDirectory(
      config.appViewOrigin,
      new ProfileCache(1_000, 10 * 60 * 1_000, 60 * 1_000, () => Date.now()),
    ),
  };
  app.on("request", (request, response) => void createHandler(deps)(request, response));
  return {
    origin,
    sessions,
    signOutCalls,
    close: async () => {
      await closeServer(app);
      await closeServer(observer);
      await closeServer(appView);
    },
  };
}

function closeServer(server: Server): Promise<void> {
  return new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}

class MemorySeenStore implements SeenStore {
  private readonly versions = new Map<string, number>();

  public async get(memberDid: string, discussionUri: string): Promise<number> {
    return this.versions.get(`${memberDid} ${discussionUri}`) ?? 0;
  }

  public async advance(memberDid: string, discussionUri: string, displayedVersion: number): Promise<void> {
    const item = `${memberDid} ${discussionUri}`;
    const current = this.versions.get(item) ?? 0;
    if (displayedVersion > current) this.versions.set(item, displayedVersion);
  }
}

function discussionItem(rkey: string, text: string): Record<string, unknown> {
  return {
    discussion: { uri: `at://${COMMUNITY}/${ADMISSION}/${rkey}`, cid: `cid-${rkey}` },
    root: { uri: `at://did:plc:bob/app.bsky.feed.post/${rkey}`, cid: `post-cid-${rkey}` },
    post: { text, createdAt: "2026-09-08T09:30:00.000Z" },
    authorDid: "did:plc:bob",
    admittedAt: "2026-09-09T10:00:00.000Z",
    status: "visible",
    closed: false,
  };
}

function discussionList(count: number): Record<string, unknown> {
  return {
    communityDid: COMMUNITY,
    discussions: Array.from({ length: count }, (_, index) => discussionItem(`rkey${index}`, `Topic number ${index}`)),
    cursor: null,
    snapshot: {},
  };
}

const DETAIL = {
  communityDid: COMMUNITY,
  discussion: discussionItem("root1", "Root post text"),
  replies: [
    {
      status: "visible",
      authorDid: "did:plc:carol",
      post: { text: "A visible reply", createdAt: "2026-09-08T10:00:00.000Z" },
      admission: { uri: `at://${COMMUNITY}/app.phlogiston.community.replyAdmission/reply1`, cid: "cid-reply1" },
      subject: { uri: "at://did:plc:carol/app.bsky.feed.post/reply1", cid: "post-cid-reply1" },
      admittedAt: "2026-09-08T11:00:00.000Z",
    },
    {
      status: "removed",
      reason: "Off topic",
      post: {},
      admission: { uri: `at://${COMMUNITY}/app.phlogiston.community.replyAdmission/reply2`, cid: "cid-reply2" },
      subject: { uri: "at://did:plc:carol/app.bsky.feed.post/reply2", cid: "post-cid-reply2" },
      authorDid: "did:plc:carol",
      admittedAt: "2026-09-08T11:05:00.000Z",
    },
  ],
  activity: [],
  snapshot: {},
};

async function signIn(context: BrowserContext, harness: Harness, did: string = MEMBER): Promise<void> {
  const { token } = await harness.sessions.issue(did);
  await context.addCookies([{ name: "community_session", value: token, url: harness.origin }]);
}

let browser: Browser | undefined;

test.before(async () => {
  await mkdir(SHOTS, { recursive: true });
  browser = await chromium.launch({ executablePath: browserExecutable });
});

test.after(async () => {
  await browser?.close();
});

function context(viewport: { width: number; height: number }): Promise<BrowserContext> {
  assert.ok(browser !== undefined);
  return browser.newContext({ viewport });
}

test("P0: collection is visible before authentication on desktop and narrow mobile", async () => {
  const posts = [
    { ...discussionItem("coffee", "Operator/project seed for The Cabinet: A networked camera watched a Cambridge coffee pot in 1991. A small everyday problem with a memorable solution."), authorDid: COMMUNITY },
    discussionItem("birds", "A protocol for delivering Internet packets by carrier pigeon."),
    discussionItem("web", "Visit the first website and follow its early links."),
  ];
  const harness = await startApp(() => ({ body: { discussions: posts, cursor: null } }), {
    profile: "p0", communityName: "The Cabinet", p0HostedPdsOrigin: "https://phlogiston.social", p0AllowBluesky: true,
  });
  try {
    for (const width of [320, 390, 1280]) {
      const session = await context({ width, height: 844 });
      try {
        const page = await session.newPage();
        await page.goto(harness.origin);
        await page.getByRole("heading", { name: "The Cabinet", exact: true }).waitFor();
        assert.equal(await page.locator("header .brand").innerText(), "Phlogiston");
        await page.getByText("An exhibition on Phlogiston", { exact: true }).waitFor();
        assert.equal(await page.locator(".collection-posts > li").count(), 3);
        assert.equal(await page.locator(".seed-label").count(), 1);
        assert.match(await page.locator(".item-heading").first().innerText(), /^A networked camera/);
        const first = await page.locator(".collection-posts > li").first().boundingBox();
        const form = await page.locator("form.signin").boundingBox();
        assert.ok(first && form && first.y < 700 && first.y < form.y, "first post must be in initial viewport and precede sign-in");
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        assert.equal(await page.locator(".permissions code").isVisible(), false);
        await page.getByRole("link", { name: "Submit one of your posts", exact: true }).click();
        assert.equal(new URL(page.url()).hash, "#submit");
        await page.getByText("Permission details", { exact: true }).click();
        assert.equal(await page.locator(".permissions code").innerText(), "atproto repo:app.phlogiston.community.submit?action=create");
        await page.getByText("What happens after I submit?", { exact: true }).click();
        await page.getByText(/does not make your submission private or delete it from the network/).waitFor();
        assert.equal(await page.locator("form.signin").getAttribute("action"), "/oauth/login");
        await page.goto(harness.origin);
        await page.screenshot({ path: join(SHOTS, `p0-frontdoor-${width}.png`), fullPage: true });
      } finally { await session.close(); }
    }
    const signedIn = await context({ width: 390, height: 844 });
    try {
      await signIn(signedIn, harness);
      const page = await signedIn.newPage();
      await page.goto(harness.origin);
      const form = page.locator('form[action="/submit-existing"]');
      assert.equal(await form.count(), 1);
      assert.ok(await form.locator('input[name="csrf"]').inputValue());
      await form.getByRole("button", { name: "Submit for review" }).waitFor();
      assert.equal(await page.locator('form[action="/contribute"]').count(), 0);
      await page.getByRole("link", { name: "My submissions", exact: true }).first().waitFor();
    } finally { await signedIn.close(); }
  } finally { await harness.close(); }
});

test("P0: another collection keeps its purpose and only advertises configured providers", async () => {
  const harness = await startApp(() => ({ body: { discussions: [], cursor: null } }), {
    profile: "p0", communityName: "Print room", communityPurpose: "Etchings & <woodcuts>", p0HostedPdsOrigin: "https://phlogiston.social", p0AllowBluesky: false,
  });
  const session = await context({ width: 390, height: 844 });
  try {
    const page = await session.newPage();
    await page.goto(harness.origin);
    assert.equal(await page.locator(".collection-tagline").innerText(), "Etchings & <woodcuts>");
    assert.equal(await page.locator("woodcuts").count(), 0);
    assert.doesNotMatch(await page.locator("body").innerText(), /Internet curiosities|Bluesky or Phlogiston/);
    await page.getByText("What happens after I submit?", { exact: true }).click();
    await page.getByText(/Post from your usual Phlogiston account first/).waitFor();
    assert.equal(await page.locator('input[name="handle"]').getAttribute("placeholder"), "you.phlogiston.social");
  } finally { await session.close(); await harness.close(); }
});

test("desktop: home renders, discussion navigation round-trips, sign-in form present", async () => {
  const harness = await startApp((path) => path.includes("/discussions/rkey0")
    ? { body: { ...DETAIL, discussion: discussionItem("rkey0", "Topic number 0") } }
    : { body: discussionList(2) });
  const session = await context({ width: 1280, height: 800 });
  try {
    const page = await session.newPage();
    const response = await page.goto(`${harness.origin}/`);
    assert.equal(response?.status(), 200);
    await assert.doesNotReject(page.getByRole("link", { name: "Topic number 0" }).waitFor());
    await assert.doesNotReject(page.getByRole("button", { name: "Sign in" }).waitFor());
    await page.screenshot({ path: join(SHOTS, "home-desktop.png") });

    // OAuth itself redirects to an external provider the browser cannot
    // follow here; the session is established exactly as the callback leaves
    // it: a community_session cookie issued by the app.
    await signIn(session, harness);
    await page.reload();
    await page.getByRole("link", { name: "Topic number 0" }).click();
    await page.waitForURL(/\/d\/rkey0$/);
    await assert.doesNotReject(page.getByRole("article").getByText("Topic number 0").waitFor());

    await page.getByRole("link", { name: "Test Community" }).click();
    await page.waitForURL(`${harness.origin}/`);
    await assert.doesNotReject(page.getByRole("link", { name: "Topic number 1" }).waitFor());
  } finally {
    await session.close();
    await harness.close();
  }
});

test("mobile 360px: no horizontal overflow and discussion tap targets are reachable", async () => {
  const harness = await startApp((path) => path.includes("/discussions/rkey0")
    ? { body: { ...DETAIL, discussion: discussionItem("rkey0", "Topic number 0") } }
    : { body: discussionList(2) });
  const session = await context({ width: 360, height: 800 });
  try {
    const page = await session.newPage();
    await signIn(session, harness);
    const response = await page.goto(`${harness.origin}/`);
    assert.equal(response?.status(), 200);
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(scrollWidth <= 360, `horizontal overflow: scrollWidth ${scrollWidth}`);
    const target = page.getByRole("link", { name: "Topic number 0" });
    const box = await target.boundingBox();
    assert.ok(box !== null && box.width > 0 && box.x >= 0 && box.x + box.width <= 360, `tap target outside viewport: ${JSON.stringify(box)}`);
    await page.screenshot({ path: join(SHOTS, "home-mobile.png") });
    await target.click();
    await page.waitForURL(/\/d\/rkey0$/);
    await assert.doesNotReject(page.getByRole("article").getByText("Topic number 0").waitFor());
    const detailWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(detailWidth <= 360, `discussion page overflow: scrollWidth ${detailWidth}`);
  } finally {
    await session.close();
    await harness.close();
  }
});

test("keyboard-only: tab order, skip link, Enter activation, and visible focus", async () => {
  const harness = await startApp((path) => path.includes("/discussions/rkey0")
    ? { body: { ...DETAIL, discussion: discussionItem("rkey0", "Topic number 0") } }
    : { body: discussionList(2) });
  const session = await context({ width: 1280, height: 800 });
  try {
    const page = await session.newPage();
    await signIn(session, harness);
    await page.goto(`${harness.origin}/`);

    const describeFocus = (): Promise<string> => page.evaluate(() => {
      const el = document.activeElement;
      if (el === null) return "";
      return [el.tagName.toLowerCase(), el.getAttribute("class") ?? "", el.getAttribute("href") ?? "", (el.textContent ?? "").trim().slice(0, 40)].join("|");
    });

    await page.keyboard.press("Tab");
    const first = await describeFocus();
    assert.match(first, /^a\|skip\|#content\|/, `first tab stop must be the skip link, got ${first}`);
    const outline = await page.evaluate(() => {
      const el = document.activeElement;
      if (el === null) return { style: "", width: "" };
      const computed = getComputedStyle(el);
      return { style: computed.outlineStyle, width: computed.outlineWidth };
    });
    assert.equal(outline.style, "solid", ":focus-visible outline must not be none");
    assert.equal(outline.width, "2px");

    await page.keyboard.press("Enter");
    assert.equal(new URL(page.url()).hash, "#content", "skip link must move to the content landmark");

    // Fresh load: tab straight through without activating the skip link, so
    // the full order — skip link, nav, form, discussion links — is observed.
    // Navigate rather than reload: a reload keeps #content, and once the page
    // is taller than the viewport the browser starts sequential focus there.
    await page.goto(`${harness.origin}/`);
    const seen: string[] = [];
    let discussionFocused = false;
    for (let index = 0; index < 25 && !discussionFocused; index += 1) {
      await page.keyboard.press("Tab");
      const descriptor = await describeFocus();
      seen.push(descriptor);
      discussionFocused = descriptor.includes("/d/rkey0");
    }
    assert.ok(seen.some((descriptor) => descriptor.startsWith("a|skip|")), `skip link not first: ${seen.join(" ; ")}`);
    assert.ok(seen.some((descriptor) => descriptor.includes("/mine")), `nav unreachable by keyboard: ${seen.join(" ; ")}`);
    assert.ok(seen.some((descriptor) => descriptor.startsWith("textarea|") || descriptor.startsWith("button|")), `form unreachable by keyboard: ${seen.join(" ; ")}`);
    assert.ok(discussionFocused, `discussion link unreachable by keyboard: ${seen.join(" ; ")}`);

    await Promise.all([
      page.waitForURL(/\/d\/rkey0$/),
      page.keyboard.press("Enter"),
    ]);
    await assert.doesNotReject(page.getByRole("article").getByText("Topic number 0").waitFor());
  } finally {
    await session.close();
    await harness.close();
  }
});

test("AppView outage: 200 with raw DIDs, no console errors, no off-origin browser requests", async () => {
  const harness = await startApp((path) => path.includes("/discussions/rkey0")
    ? { body: { ...DETAIL, discussion: discussionItem("rkey0", "Topic number 0") } }
    : { body: discussionList(1) });
  const session = await context({ width: 1280, height: 800 });
  try {
    const page = await session.newPage();
    const requestedUrls: string[] = [];
    const consoleErrors: string[] = [];
    page.on("request", (request) => requestedUrls.push(request.url()));
    page.on("pageerror", (error) => consoleErrors.push(String(error)));
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    await signIn(session, harness);
    const home = await page.goto(`${harness.origin}/`);
    assert.equal(home?.status(), 200);
    await assert.doesNotReject(page.getByText("did:plc:bob").first().waitFor());
    const discussion = await page.goto(`${harness.origin}/d/rkey0`);
    assert.equal(discussion?.status(), 200);
    await assert.doesNotReject(page.getByRole("article").getByText("Topic number 0").waitFor());
    for (const requested of requestedUrls) {
      assert.ok(requested.startsWith(harness.origin), `browser made an off-origin request: ${requested}`);
    }
    assert.deepEqual(consoleErrors, []);
  } finally {
    await session.close();
    await harness.close();
  }
});

test("long display names and missing profiles hold layout and fall back to DIDs", async () => {
  const list = discussionList(2);
  const items = list.discussions as Record<string, unknown>[];
  items[1] = { ...discussionItem("rkey1", "Topic number 1"), authorDid: "did:plc:nobody" };
  const longName = `X${"y".repeat(249)}`;
  const harness = await startApp(
    () => ({ body: list }),
    {},
    appViewWith({ "did:plc:bob": { handle: "bob.example.test", displayName: longName } }),
  );
  const session = await context({ width: 1280, height: 800 });
  try {
    const page = await session.newPage();
    const response = await page.goto(`${harness.origin}/`);
    assert.equal(response?.status(), 200);
    await assert.doesNotReject(page.getByText(longName).waitFor());
    await assert.doesNotReject(page.getByText("did:plc:nobody").first().waitFor());
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(scrollWidth <= 1280, `horizontal overflow: scrollWidth ${scrollWidth}`);
  } finally {
    await session.close();
    await harness.close();
  }
});

test("tombstones explain removal, link the public post, and omit the observer permalink", async () => {
  const removedRoot = { ...DETAIL, discussion: { ...discussionItem("root1", "Root post text"), status: "removed" } };
  const harness = await startApp((path) => path.includes("/discussions/root1") ? { body: removedRoot } : { body: DETAIL });
  const session = await context({ width: 1280, height: 800 });
  try {
    const page = await session.newPage();
    await signIn(session, harness);
    const response = await page.goto(`${harness.origin}/d/root1`);
    assert.equal(response?.status(), 200);
    const banner = page.locator(".tombstone-banner");
    await assert.doesNotReject(banner.waitFor());
    assert.match(await banner.textContent() ?? "", /removed from this community’s view; the author’s public post is not deleted or changed/);
    assert.equal(await banner.locator("a.external").getAttribute("href"), "https://bsky.app/profile/did:plc:bob/post/root1");
    const tombstone = page.locator("li.tombstone");
    assert.match(await tombstone.textContent() ?? "", /Removed from this community’s view: Off topic\. The author’s public post is not deleted or changed/);
    assert.equal(await tombstone.locator("a.external").getAttribute("href"), "https://bsky.app/profile/did:plc:carol/post/reply2");
    assert.equal(await page.getByText("Observer record for this admission").count(), 0);
    const externalLabels = await page.locator("a.external").evaluateAll((anchors) => anchors.map((anchor) => anchor.textContent));
    // Banner, visible reply's "Why is this here?", and reply tombstone; a removed root has no "Why is this here?".
    assert.equal(externalLabels.filter((label) => label === "Public post on Bluesky").length, 3);
    assert.equal(await page.locator("article").count(), 0);
  } finally {
    await session.close();
    await harness.close();
  }
});

const HOSTILE = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '" autofocus onfocus=alert(1) x="',
  "' onclick='alert(1)",
  '<form action="https://collect.invalid.test/c"><button>Sign in again</button></form>',
  '<style>body{background:url("https://collect.invalid.test/x")}</style>',
  '<a href="javascript:alert(1)">moderator announcement</a>',
  'paypal-security.invalid.test verify your account',
  '‮4mF‭ reversed text',
  'body { display: none } </style><script>alert(2)</script>',
  'A'.repeat(10_000),
];

async function assertInertDom(page: Page): Promise<void> {
  assert.equal(await page.locator("img").count(), 0, "injected or unexpected img element");
  assert.equal(await page.locator("script").count(), 0, "injected script element");
  assert.equal(await page.locator("style").count(), 0, "injected style element");
  for (const attribute of ["onfocus", "onerror", "onmouseover", "onclick", "autofocus"]) {
    assert.equal(await page.locator(`[${attribute}]`).count(), 0, `element with ${attribute} handler`);
  }
  const actions = await page.locator("form").evaluateAll((forms) => forms.map((form) => form.getAttribute("action") ?? ""));
  for (const action of actions) assert.match(action, /^\//, `off-origin form action ${action}`);
  const hrefs = await page.locator("a").evaluateAll((anchors) => anchors.map((anchor) => anchor.getAttribute("href") ?? ""));
  for (const href of hrefs) assert.match(href, /^(\/|#|https:\/\/bsky\.app\/)/, `unexpected anchor href ${href}`);
}

test("hostile payloads create no live elements, links, or navigation in the real DOM", async () => {
  const hostileTime = '"><time onmouseover=alert(1)>';
  const hostileList = {
    communityDid: COMMUNITY,
    discussions: HOSTILE.map((textValue, index) => discussionItem(`hostile${index}`, textValue)),
    cursor: null,
    snapshot: {},
  };
  const hostileDetail = {
    ...DETAIL,
    discussion: {
      ...discussionItem("hostile0", HOSTILE[0] as string),
      admittedAt: hostileTime,
      post: { text: HOSTILE[0] as string, createdAt: hostileTime },
      discussion: { uri: `at://${COMMUNITY}/${ADMISSION}/hostile0" autofocus onfocus=alert(1) x="`, cid: 'cid" onmouseover="alert(1)' },
    },
    replies: HOSTILE.map((textValue, index) => ({
      status: "visible",
      authorDid: textValue,
      post: { text: textValue, createdAt: hostileTime },
      admittedAt: hostileTime,
      admission: { uri: `at://${COMMUNITY}/app.phlogiston.community.replyAdmission/h${index}`, cid: `cid-h${index}` },
    })),
  };
  const harness = await startApp((path) => path.includes("/discussions/hostile0")
    ? { body: hostileDetail }
    : { body: hostileList });
  const session = await context({ width: 1280, height: 800 });
  try {
    const page = await session.newPage();
    const requestedUrls: string[] = [];
    page.on("request", (request) => requestedUrls.push(request.url()));
    await signIn(session, harness);
    await page.goto(`${harness.origin}/`);
    await assertInertDom(page);
    const homeText = await page.locator("main").textContent();
    assert.ok(homeText?.includes("<script>alert(1)</script>"), "payload must render as inert text");

    await page.locator('a[href="/d/hostile0"]').click();
    await page.waitForURL(/\/d\/hostile0$/);
    await assertInertDom(page);
    const detailText = await page.locator("main").textContent();
    assert.ok(detailText?.includes("<script>alert(1)</script>"));
    for (const requested of requestedUrls) {
      assert.ok(requested.startsWith(harness.origin), `off-origin request: ${requested}`);
    }
    assert.ok(page.url().startsWith(harness.origin), `unexpected navigation to ${page.url()}`);
  } finally {
    await session.close();
    await harness.close();
  }
});

test("sign out and Disconnect round trips clear the cookie and never say logout", async () => {
  const harness = await startApp((path) => path.includes("/discussions/rkey0")
    ? { body: { ...DETAIL, discussion: discussionItem("rkey0", "Topic number 0") } }
    : { body: discussionList(1) });
  const session = await context({ width: 1280, height: 800 });
  try {
    const page = await session.newPage();
    await signIn(session, harness);
    await page.goto(`${harness.origin}/`);
    await assert.doesNotReject(page.getByRole("button", { name: "Sign out" }).waitFor());
    await assert.doesNotReject(page.getByRole("button", { name: "Disconnect" }).waitFor());
    const homeText = await page.locator("body").textContent();
    assert.doesNotMatch(homeText ?? "", /logout/i);

    await Promise.all([
      page.waitForURL(`${harness.origin}/`),
      page.getByRole("button", { name: "Sign out" }).click(),
    ]);
    await assert.doesNotReject(page.getByRole("button", { name: "Sign in" }).waitFor());
    assert.deepEqual(await session.cookies(), [], "sign out must clear the session cookie");

    await signIn(session, harness);
    await page.goto(`${harness.origin}/`);
    await page.getByRole("button", { name: "Disconnect" }).click();
    await assert.doesNotReject(page.getByText(/provider accepted its revocation request/).waitFor());
    const disconnectText = await page.locator("body").textContent();
    assert.match(disconnectText ?? "", /public posts remain public on your PDS/);
    assert.match(disconnectText ?? "", /admission history is unchanged/);
    assert.doesNotMatch(disconnectText ?? "", /logout/i);
    assert.deepEqual(harness.signOutCalls, [MEMBER, MEMBER], "sign out and Disconnect each revoke the provider tokens");
    assert.deepEqual(await session.cookies(), [], "disconnect must clear the session cookie");
  } finally {
    await session.close();
    await harness.close();
  }
});

test("pagination: page 2 navigates and reports the truthful range", async () => {
  const harness = await startApp(() => ({ body: discussionList(30) }));
  const session = await context({ width: 1280, height: 800 });
  try {
    const page = await session.newPage();
    await page.goto(`${harness.origin}/`);
    await assert.doesNotReject(page.getByText("1–25 of 30 discussions").waitFor());
    await assert.doesNotReject(page.getByText("Page 1 of 2").waitFor());

    await page.getByRole("link", { name: "Next page" }).click();
    await page.waitForURL(/\/\?page=2/);
    await assert.doesNotReject(page.getByText("26–30 of 30 discussions").waitFor());
    await assert.doesNotReject(page.getByText("Page 2 of 2").waitFor());

    await page.getByRole("link", { name: "Previous page" }).click();
    await page.waitForURL(`${harness.origin}/`);
    await assert.doesNotReject(page.getByText("1–25 of 30 discussions").waitFor());
  } finally {
    await session.close();
    await harness.close();
  }
});

function appViewWith(profiles: Record<string, Record<string, unknown>>): (path: string) => StubReply {
  return (path) => {
    if (!path.includes("app.bsky.actor.getProfiles")) return { status: 404, body: {} };
    const actors = new URL(path, "http://stub.invalid").searchParams.getAll("actors");
    return {
      body: { profiles: actors.filter((did) => did in profiles).map((did) => ({ did, ...profiles[did] })) },
    };
  };
}


test("P1: one signed-in shell preserves collection and submission navigation", async () => {
  const harness = await startApp(() => ({ body: { discussions: [discussionItem("one", "A collected curiosity")] } }), {
    profile: "p0", communityName: "The Cabinet", p0HostedPdsOrigin: "https://phlogiston.social", p0AllowBluesky: true,
  });
  try {
    for (const width of [320, 1280]) {
      const session = await context({ width, height: 844 });
      try {
        await signIn(session, harness);
        const page = await session.newPage();
        await page.goto(`${harness.origin}/home`);
        await page.getByRole("heading", { name: "Your Phlogiston", exact: true }).waitFor();
        await page.getByRole("heading", { name: "Your community activity" }).waitFor();
        await page.getByRole("link", { name: "My Labels", exact: true }).waitFor();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({ path: join(SHOTS, `participant-home-${width}.png`), fullPage: true });
        await page.getByRole("link", { name: "Settings", exact: true }).click();
        await page.getByRole("heading", { name: "Settings", exact: true }).waitFor();
        assert.ok(await page.locator('form[action="/disconnect"] input[name="csrf"]').inputValue());
        await page.getByRole("link", { name: "Collection", exact: true }).click();
        await page.getByRole("heading", { name: "The Cabinet", exact: true }).waitFor();
        assert.equal(await page.locator('form[action="/submit-existing"]').count(), 1);
      } finally { await session.close(); }
    }
    for (const route of ["/home", "/labels", "/settings"]) {
      const response = await fetch(`${harness.origin}${route}`);
      assert.equal(response.status, 401);
    }
  } finally { await harness.close(); }
});


test("P1: My Labels uses only the session DID and preserves account context on source failure", async () => {
  const seen: string[] = [];
  const harness = await startApp(() => ({ body: { discussions: [] } }), { profile: "p0" }, undefined, {
    lookup: async did => { seen.push(did); return null; },
  });
  const session = await context({ width: 390, height: 844 });
  try {
    await signIn(session, harness);
    const page = await session.newPage();
    await page.goto(`${harness.origin}/labels?did=did:plc:someoneelse`);
    await page.getByRole("heading", { name: "Label context unavailable" }).waitFor();
    assert.deepEqual(seen, [MEMBER]);
    assert.match((await page.request.get(`${harness.origin}/labels`)).headers()["cache-control"] ?? "", /no-store/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.getByRole("link", { name: "Home", exact: true }).click();
    await page.getByRole("heading", { name: "Your Phlogiston" }).waitFor();
    await page.screenshot({ path: join(SHOTS, "participant-source-unavailable.png"), fullPage: true });
  } finally { await session.close(); await harness.close(); }
});

test("FD2: signed-out reader front door and centralized sign-in reflow at three widths", async () => {
  const harness = await startApp(() => ({ body: { discussions: [discussionItem("fd2", "A Cabinet curiosity before sign-in")], cursor: null } }), {
    profile: "p0", readerEnabled: true, communityName: "The Cabinet",
  });
  try {
    for (const width of [320, 390, 1280]) {
      const session = await context({ width, height: 844 });
      try {
        const page = await session.newPage();
        await page.goto(`${harness.origin}/`);
        await page.getByText("A different way to experience Bluesky.", { exact: true }).waitFor();
        await page.getByText("A Cabinet curiosity before sign-in", { exact: true }).waitFor();
        assert.equal(await page.locator('input[name="handle"]').count(), 0);
        const headerSignIn = page.locator('header a[href="/signin"]');
        assert.equal(await headerSignIn.count(), 1);
        assert.equal(await headerSignIn.isVisible(), true);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await headerSignIn.click();
        await page.waitForURL(`${harness.origin}/signin`);
        assert.equal(await page.locator('input[name="handle"]').count(), 1);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.goto(`${harness.origin}/community`);
        await page.getByText("A Cabinet curiosity before sign-in", { exact: true }).waitFor();
        assert.equal(await page.locator('input[name="handle"]').count(), 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      } finally { await session.close(); }
    }
  } finally { await harness.close(); }
});

test("interaction: Settings shows the effective provider grant and explicit disconnect",async()=>{
 const harness=await startApp(()=>({body:{discussions:[],cursor:null}}),{profile:"p0",readerEnabled:true,communityName:"The Cabinet"},undefined,undefined,READER_INTERACTION_SCOPE);
 const session=await context({width:390,height:844});
 try{
  await signIn(session,harness);const page=await session.newPage();await page.goto(`${harness.origin}/settings`);
  await page.getByRole("heading",{name:"Content interaction"}).waitFor();await page.getByText("Enabled.",{exact:true}).waitFor();
  await page.getByText("Disable content interaction",{exact:true}).click();
  const form=page.locator('form[action="/interaction/disable"]');
  assert.ok(await form.locator('input[name="csrf"]').getAttribute("value"));
  await form.getByRole("button",{name:"Disable interaction and disconnect"}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:join(SHOTS,"interaction-settings-enabled.png"),fullPage:true});
 }finally{await session.close();await harness.close();}
});

test("AG1: quieting in the page replaces the page counts instead of leaving them wrong", async () => {
  const source = await readFile(new URL("../static/workspace-state.js", import.meta.url), "utf8");
  const ctx = await context({ width: 800, height: 600 });
  try {
    const page = await ctx.newPage();
    await page.setContent(`<div class="feed-surface" id="counted"><div class="attention-summary"><p>Showing 8 of the 19 posts received for this page.</p></div><section class="following-feed"></section></div><div class="feed-surface" id="plain"><section class="following-feed"></section></div>`);
    await page.addScriptTag({ type: "module", content: `${source}\nfor (const s of document.querySelectorAll(".feed-surface")) markAttentionStale(s); document.body.dataset.done = "1";` });
    await page.waitForSelector("body[data-done]");
    for (const id of ["counted", "plain"]) {
      const text = await page.locator(`#${id} > .attention-summary[data-stale="true"]`).innerText();
      assert.match(text, /no longer match|Refresh to recount/);
      assert.doesNotMatch(text, /Showing 8/);
      assert.equal(await page.locator(`#${id} > .attention-summary + .following-feed`).count(), 1);
    }
  } finally { await ctx.close(); }
});

test("AG1: Quiet here, Undo and Restore keep the page's accounting truthful", async () => {
  const root = await mkdtemp(join(tmpdir(), "community-browser-reader-"));
  const app = createServer();
  await new Promise<void>((resolve) => app.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${(app.address() as AddressInfo).port}`;
  const config = loadConfig({ COMMUNITY_PROFILE: "p0", COMMUNITY_READER_ENABLED: "true", COMMUNITY_PUBLIC_URL: origin,
    COMMUNITY_DID: COMMUNITY, COMMUNITY_NAME: "The Cabinet", COMMUNITY_PURPOSE: "Fixture collection",
    COMMUNITY_MODERATOR_DID: MODERATOR, COMMUNITY_RUNTIME_DIR: root, COMMUNITY_OBSERVER_URL: "http://127.0.0.1:8080",
    COMMUNITY_AUTHORITY_SOCKET: join(root, "socket"), COMMUNITY_SITE_PAUSE_PATH: join(root, "site"),
    COMMUNITY_ADMISSION_PAUSE_PATH: join(root, "admission") });
  await writeFile(config.sitePausePath!, "open\n", { mode: 0o600 });
  const sessions = new WebSessionStore(join(root, "sessions"));
  const localQuiet = new LocalQuietStore(join(root, "local-quiet.sqlite"));
  const post = (name: string, text: string) => ({ post: { uri: `at://${MEMBER}/app.bsky.feed.post/${name}`,
    cid: "bafyreifkpymf7jb3jg5giimeyzab6lbokwi3ko5hdutcj7ift54i64zqxu", author: { did: MEMBER, handle: "alice.test" },
    record: { $type: "app.bsky.feed.post", text, createdAt: "2026-10-12T00:00:00Z" }, indexedAt: "2026-10-12T00:00:00Z" } });
  const transport: ReaderTransport = {
    preferences: async () => ({ feedViewPrefs: { home: { hideReplies: false, hideRepliesByUnfollowed: false, hideRepliesByLikeCount: 0,
      hideReposts: false, hideQuotePosts: false } }, moderationPrefs: { adultContentEnabled: false, labels: {}, labelers: [],
      mutedWords: [], hiddenPosts: [] } }) as unknown as BskyPreferences,
    savedFeedPreferences: async () => [], labelDefinitions: async () => ({}),
    timeline: async () => ({ feed: [post("first", "First fixture post"), post("second", "Second fixture post")] }),
    postThread: async (uri) => ({ $type: "app.bsky.feed.defs#threadViewPost", post: post("first", "First fixture post").post, uri }),
    muteThread: async () => {}, unmuteThread: async () => {},
  };
  const oauthSession = (did: string) => ({ did, getTokenInfo: async () => ({ sub: did, iss: "https://bsky.social",
    aud: "https://fixture.host.bsky.network", scope: FEED_SCOPE }), signOut: async () => {} }) as unknown as OAuthSession;
  const deps = { config, webSessions: sessions, localQuiet, reader: (s: OAuthSession) => new Reader(s, transport),
    oauth: { authorize: async () => new URL("https://auth.invalid.test/authorize"), restore: async (did: string) => oauthSession(did),
      callback: async () => ({ session: oauthSession(MEMBER) }) }, labels: { lookup: async () => null } } as unknown as Dependencies;
  app.on("request", (request, response) => void createHandler(deps)(request, response));
  const session = await context({ width: 1280, height: 900 });
  try {
    const { token } = await sessions.issue(MEMBER, new Date(), FEED_SCOPE);
    await session.addCookies([{ name: "community_session", value: token, url: origin }]);
    const page = await session.newPage();
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${origin}/home`);
    const first = page.locator('.workspace-primary article[data-post-uri$="/first"]');
    const summary = page.locator(".workspace-primary .feed-surface > .attention-summary");
    await first.getByRole("button", { name: "Quiet here" }).waitFor();
    assert.equal(await summary.count(), 0);

    await first.getByRole("button", { name: "Quiet here" }).click();
    await page.locator('.workspace-primary .attention-summary[data-stale="true"]').waitFor();
    assert.equal(await first.isHidden(), true);
    assert.match(await summary.innerText(), /no longer match\. Refresh to recount\./);
    assert.deepEqual(localQuiet.list(MEMBER, "following"), [`at://${MEMBER}/app.bsky.feed.post/first`]);

    await page.getByRole("button", { name: "Undo" }).click();
    await page.getByText("Conversation restored in this feed.").waitFor();
    assert.equal(await first.isVisible(), true);
    assert.match(await summary.innerText(), /Refresh to recount\./);
    assert.deepEqual(localQuiet.list(MEMBER, "following"), []);

    await first.getByRole("button", { name: "Quiet here" }).click();
    await page.getByText("Conversation quieted in this feed.").waitFor();
    await page.reload();
    await page.locator('.workspace-primary article[data-post-uri$="/second"]').waitFor();
    assert.equal(await first.count(), 0);
    assert.match(await summary.innerText(), /Showing 1 of the 2 posts received for this page\. 1 hidden by your settings\./);
    assert.equal(await page.locator('.workspace-primary .attention-summary[data-stale]').count(), 0);
    await page.screenshot({ path: join(SHOTS, "ag1-quiet-summary.png"), fullPage: true });

    await page.locator(".workspace-primary .local-quiet-review summary").click();
    await page.getByRole("button", { name: "Restore conversation" }).click();
    await first.waitFor();
    assert.equal(await summary.count(), 0);
    assert.deepEqual(localQuiet.list(MEMBER, "following"), []);
    assert.deepEqual(errors, []);
  } finally {
    await session.close();
    await closeServer(app);
    localQuiet.close();
  }
});
