// Controlled P0 lifecycle against an already installed app and stock PDS.
// The operator supplies normal existing posts and protected password files.
// This script never calls PDS administrative or repository-write XRPCs.
import { constants } from "node:fs";
import { open, stat, writeFile } from "node:fs/promises";
import { isAbsolute } from "node:path";
import { chromium } from "playwright-core";

const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};

const app = required("PDS_BROWSER_APP_ORIGIN");
const provider = "https://phlogiston.social";
const participant = required("PDS_BROWSER_PARTICIPANT_HANDLE");
const moderator = required("PDS_BROWSER_MODERATOR_HANDLE");
const participantFile = required("PDS_BROWSER_PARTICIPANT_PASSWORD_FILE");
const moderatorFile = required("PDS_BROWSER_MODERATOR_PASSWORD_FILE");
const post = required("PDS_BROWSER_POST_URI");
const declinePost = process.env.PDS_BROWSER_DECLINE_POST_URI;
const receiptPath = required("PDS_BROWSER_RECEIPT");
const executablePath = required("COMMUNITY_BROWSER_EXECUTABLE");
const sourceRevision = required("PDS_BROWSER_SOURCE_REVISION");
const run = required("PDS_BROWSER_RUN");
const origin = new URL(app);
if (origin.origin !== app || (origin.protocol !== "https:" && !(origin.protocol === "http:" && ["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname)))) {
  throw new Error("app must be an exact HTTPS or loopback origin");
}
for (const value of [post, declinePost].filter(Boolean)) {
  if (!/^at:\/\/did:plc:[^/]+\/app\.bsky\.feed\.post\/[A-Za-z0-9._:-]+$/.test(value)) throw new Error("post must be an exact post AT URI");
}
if (!isAbsolute(receiptPath)) throw new Error("receipt path must be absolute");

async function password(path) {
  if (!isAbsolute(path)) throw new Error("credential file path must be absolute");
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = await file.stat();
    if (!info.isFile() || (info.mode & 0o077) !== 0 || info.uid !== process.getuid() || info.size > 4096) {
      throw new Error("credential file has an invalid owner, mode, type or size");
    }
    const value = (await file.readFile("utf8")).trimEnd();
    if (!value || value.includes("\n")) throw new Error("credential file is not one password line");
    return value;
  } finally {
    await file.close();
  }
}

const stages = [];
let phase = "configuration";
let browser;
async function checkpoint(stage, detail = {}) {
  phase = stage;
  stages.push({stage, time: new Date().toISOString(), ...detail});
  process.stdout.write(`${stage}\n`);
}
async function signIn(context, handle, passwordFile) {
  const page = await context.newPage();
  await page.goto(app, {waitUntil:"domcontentloaded"});
  await page.locator('form.signin input[name="handle"]').fill(handle);
  await Promise.all([
    page.waitForURL(url => url.origin === provider && url.pathname.startsWith("/oauth/authorize")),
    page.locator('form.signin button').click(),
  ]);
  if (new URL(page.url()).origin !== provider) throw new Error("OAuth authorization did not use configured PDS");
  await page.locator('input[name="password"]').fill(await password(passwordFile));
  await page.getByRole("button", {name:"Sign in"}).click();
  await page.getByRole("button", {name:"Authorize"}).waitFor();
  if (new URL(page.url()).origin !== provider) throw new Error("OAuth consent did not use configured PDS");
  await Promise.all([
    page.waitForURL(url => url.origin === app && !url.pathname.startsWith("/oauth/")),
    page.getByRole("button", {name:"Authorize"}).click(),
  ]);
  await page.getByRole("button", {name:"Sign out"}).waitFor();
  return page;
}

async function submit(page, subject) {
  await page.goto(app, {waitUntil:"domcontentloaded"});
  const form = page.locator('form[action="/submit-existing"]');
  await form.locator('input[name="post"]').fill(subject);
  await form.getByRole("button", {name:"Submit for review"}).click();
  await page.getByText(/Awaiting independent observation|already requested|waiting for review/i).waitFor();
}

async function candidate(page, subject, action) {
  const rkey = subject.split("/").at(-1);
  const author = subject.split("/")[2];
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    await page.goto(`${app}/moderation?authorDid=${encodeURIComponent(author)}`, {waitUntil:"domcontentloaded"});
    const row = page.locator("li").filter({has:page.locator(`a[href*="/post/${rkey}"]`)});
    const form = row.locator(`form[action="/moderate"]:has(input[name="kind"][value="${action}"])`);
    if (await form.count() === 1) return form;
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  throw new Error("exact candidate was not observed within bound");
}

try {
  const executable = await stat(executablePath);
  if (!executable.isFile()) throw new Error("browser executable is not a regular file");
  await checkpoint("browser_start");
  browser = await chromium.launch({executablePath, headless:true});
  const participantContext = await browser.newContext();
  const moderatorContext = await browser.newContext();
  const publicContext = await browser.newContext();
  await checkpoint("participant_oauth");
  const participantPage = await signIn(participantContext, participant, participantFile);
  await checkpoint("moderator_oauth");
  const moderatorPage = await signIn(moderatorContext, moderator, moderatorFile);
  await checkpoint("submission");
  await submit(participantPage, post);
  await checkpoint("candidate_observation");
  const admit = await candidate(moderatorPage, post, "admit-root");
  await admit.getByRole("button", {name:"Admit exact version"}).click();
  await moderatorPage.getByText(/Recorded\. The observer may take a moment/).waitFor();
  await checkpoint("admission_recorded");
  const publicPage = await publicContext.newPage();
  const expectedPostHref = `https://bsky.app/profile/${post.split("/")[2]}/post/${post.split("/").at(-1)}`;
  const deadline = Date.now() + 180_000;
  let detail;
  while (Date.now() < deadline) {
    await publicPage.goto(app, {waitUntil:"domcontentloaded"});
    const links = await publicPage.locator('main a[href^="/d/"]').evaluateAll(nodes => nodes.map(node => node.getAttribute("href")).filter(Boolean));
    for (const path of links.slice(0, 25)) {
      await publicPage.goto(`${app}${path}`, {waitUntil:"domcontentloaded"});
      if (await publicPage.locator(`details.why a[href="${expectedPostHref}"]`).count() === 1) {
        detail = path;
        break;
      }
    }
    if (detail) break;
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  if (!detail) throw new Error("anonymous admission rendering was not observed within bound");
  await publicPage.goto(`${app}${detail}`, {waitUntil:"domcontentloaded"});
  await publicPage.getByText("Why is this here?").waitFor();
  await checkpoint("anonymous_render", {detail});
  await moderatorPage.goto(`${app}${detail}`, {waitUntil:"domcontentloaded"});
  const remove = moderatorPage.locator('form[action="/moderate"]:has(input[name="kind"][value="remove-root"])');
  await remove.locator('input[name="reason"]').fill("Controlled lifecycle removal");
  await remove.getByRole("button", {name:"Remove from community"}).click();
  await moderatorPage.getByText(/Recorded\. The observer may take a moment/).waitFor();
  await checkpoint("removal_recorded");
  const removeDeadline = Date.now() + 180_000;
  let removed = false;
  while (Date.now() < removeDeadline) {
    await publicPage.goto(`${app}${detail}`, {waitUntil:"domcontentloaded"});
    if (await publicPage.getByText(/removed from this community’s view/).count() === 1) {
      removed = true;
      break;
    }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  if (!removed) throw new Error("anonymous removal rendering was not observed within bound");
  await checkpoint("anonymous_removal_render");
  if (declinePost) {
    await submit(participantPage, declinePost);
    await checkpoint("decline_candidate_observation");
    const decline = await candidate(moderatorPage, declinePost, "decline-root");
    await decline.locator('input[name="reason"]').fill("Controlled lifecycle private decline");
    await decline.getByRole("button", {name:"Decline for this site"}).click();
    await moderatorPage.getByText(/Declined privately/).waitFor();
    await checkpoint("private_decline_recorded");
  }
  await checkpoint("complete");
} catch {
  await checkpoint("failed", {at:phase});
  process.exitCode = 1;
} finally {
  await browser?.close();
  await writeFile(receiptPath, JSON.stringify({schema:"phlogiston.pds-browser-lifecycle.v1",run,sourceRevision,appOrigin:app,pdsOrigin:provider,post,declinePost:declinePost ?? null,stages,result:process.exitCode ? "failed" : "complete",caveat:"No provider credential, OAuth token, callback URL, screenshot, or admin XRPC is retained. Stage checks are browser observations; independent PDS/observer receipts are still required."},null,2)+"\n",{flag:"wx",mode:0o600});
}
