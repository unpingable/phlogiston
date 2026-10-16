// Controlled negative/recovery cases for an already installed P0 app and PDS.
// Public repository reads are used only to check exact record cardinality.
import { constants } from "node:fs";
import { open, lstat, readFile, rename, stat, writeFile } from "node:fs/promises";
import { isAbsolute } from "node:path";
import { chromium } from "playwright-core";

const required = name => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};
const app = required("PDS_NEGATIVE_APP_ORIGIN");
const provider = "https://phlogiston.social";
const authorA = {handle:required("PDS_NEGATIVE_AUTHOR_A_HANDLE"),did:required("PDS_NEGATIVE_AUTHOR_A_DID"),passwordFile:required("PDS_NEGATIVE_AUTHOR_A_PASSWORD_FILE")};
const authorB = {handle:required("PDS_NEGATIVE_AUTHOR_B_HANDLE"),did:required("PDS_NEGATIVE_AUTHOR_B_DID"),passwordFile:required("PDS_NEGATIVE_AUTHOR_B_PASSWORD_FILE")};
const otherPost = required("PDS_NEGATIVE_OTHER_AUTHOR_POST_URI");
const duplicatePost = required("PDS_NEGATIVE_DUPLICATE_POST_URI");
const pausePath = process.env.PDS_NEGATIVE_SITE_PAUSE_PATH;
const pausePost = process.env.PDS_NEGATIVE_PAUSE_POST_URI;
const receiptPath = required("PDS_NEGATIVE_RECEIPT");
const progressPath = required("PDS_NEGATIVE_PROGRESS");
const executablePath = required("COMMUNITY_BROWSER_EXECUTABLE");
const sourceRevision = required("PDS_NEGATIVE_SOURCE_REVISION");
const run = required("PDS_NEGATIVE_RUN");
const appUrl = new URL(app);
if (appUrl.origin !== app || (appUrl.protocol !== "https:" && !(appUrl.protocol === "http:" && ["127.0.0.1","localhost","[::1]"].includes(appUrl.hostname)))) throw new Error("app must be an exact HTTPS or loopback origin");
if (authorA.did === authorB.did || authorA.handle === authorB.handle) throw new Error("two distinct authors are required");
for (const value of [otherPost,duplicatePost,pausePost].filter(Boolean)) {
  if (!/^at:\/\/did:plc:[^/]+\/app\.bsky\.feed\.post\/[A-Za-z0-9._:-]+$/.test(value)) throw new Error("post must be an exact post AT URI");
}
if (otherPost.split("/")[2] !== authorA.did || duplicatePost.split("/")[2] !== authorA.did || duplicatePost === otherPost) throw new Error("other-author and fresh duplicate posts must belong to author A and differ");
if (Boolean(pausePath) !== Boolean(pausePost)) throw new Error("pause path and fresh pause post must be supplied together");
if (pausePost && (pausePost.split("/")[2] !== authorA.did || [otherPost,duplicatePost].includes(pausePost))) throw new Error("pause post must be a different author A post");
for (const path of [receiptPath,progressPath,authorA.passwordFile,authorB.passwordFile,...(pausePath ? [pausePath] : [])]) if (!isAbsolute(path)) throw new Error("paths must be absolute");
if (receiptPath === progressPath) throw new Error("receipt and progress paths must differ");

async function password(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = await file.stat();
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o077) !== 0 || info.size > 4096) throw new Error("credential file owner, mode, type or size is invalid");
    const value = (await file.readFile("utf8")).trimEnd();
    if (!value || value.includes("\n")) throw new Error("credential file is not one password line");
    return value;
  } finally { await file.close(); }
}

const stages = [];
let phase = "configuration";
let browser;
let control;
let controlIdentity;
let pauseRestored = true;
let progressStarted = false;
async function progress(stage, detail = {}) {
  phase = stage;
  stages.push({stage,time:new Date().toISOString(),...detail});
  const data = JSON.stringify({schema:"phlogiston.pds-browser-negative-progress.v1",run,phase,pausePath:pausePath ?? null,pauseRestored,stages},null,2)+"\n";
  if (!progressStarted) {
    await writeFile(progressPath,data,{flag:"wx",mode:0o600});
    progressStarted = true;
  } else {
    const temporary = `${progressPath}.${process.pid}.tmp`;
    await writeFile(temporary,data,{flag:"wx",mode:0o600});
    await rename(temporary,progressPath);
  }
  process.stdout.write(`${stage}\n`);
}

async function signIn(context, account) {
  const page = await context.newPage();
  await page.goto(app,{waitUntil:"domcontentloaded"});
  await page.locator('form.signin input[name="handle"]').fill(account.handle);
  await Promise.all([page.waitForURL(url => url.origin === provider && url.pathname.startsWith("/oauth/authorize")),page.locator('form.signin button').click()]);
  if (new URL(page.url()).origin !== provider) throw new Error("authorization did not use configured PDS");
  await page.locator('input[name="password"]').fill(await password(account.passwordFile));
  await page.getByRole("button",{name:"Sign in"}).click();
  await page.getByRole("button",{name:"Authorize"}).waitFor();
  if (new URL(page.url()).origin !== provider) throw new Error("consent did not use configured PDS");
  await Promise.all([page.waitForURL(url => url.origin === app && !url.pathname.startsWith("/oauth/")),page.getByRole("button",{name:"Authorize"}).click()]);
  await page.getByRole("button",{name:"Sign out"}).waitFor();
  if (!await page.locator("nav .identity").getByText(account.did).count()) throw new Error("signed-in DID did not match account input");
  return page;
}

async function formPost(page,path,fields) {
  const csrf = await page.locator('form[action="/submit-existing"] input[name="csrf"]').inputValue();
  return page.evaluate(async ({path,fields,csrf}) => {
    const response = await fetch(path,{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams({csrf,...fields})});
    return {status:response.status,text:(await response.text()).replace(/<[^>]*>/g," ").replace(/\s+/g," ").slice(0,2000)};
  },{path,fields,csrf});
}

async function records(did) {
  const all=[];
  let cursor;
  for (let page=0;page<10;page++) {
    const url = new URL("/xrpc/com.atproto.repo.listRecords",provider);
    url.searchParams.set("repo",did);
    url.searchParams.set("collection","app.phlogiston.community.submit");
    url.searchParams.set("limit","100");
    if (cursor) url.searchParams.set("cursor",cursor);
    const response=await fetch(url);
    if (!response.ok) throw new Error("public PDS listRecords failed");
    const body=await response.json();
    if (!Array.isArray(body.records)) throw new Error("public PDS listRecords was malformed");
    for (const row of body.records) {
      if (typeof row.uri !== "string" || typeof row.cid !== "string") throw new Error("public PDS record identity was malformed");
      all.push({uri:row.uri,cid:row.cid,subject:row.value?.subject});
    }
    if (!body.cursor) return all;
    if (typeof body.cursor !== "string") throw new Error("public PDS cursor was malformed");
    cursor=body.cursor;
  }
  throw new Error("public PDS record list exceeded the bounded scan");
}

async function sourceCid(uri) {
  const parts=uri.split("/");
  const url=new URL("/xrpc/com.atproto.repo.getRecord",provider);
  url.searchParams.set("repo",parts[2]);url.searchParams.set("collection","app.bsky.feed.post");url.searchParams.set("rkey",parts.at(-1));
  const response=await fetch(url);
  if (!response.ok) throw new Error("source post is not currently readable on PDS");
  const body=await response.json();
  if (body.uri !== uri || typeof body.cid !== "string") throw new Error("source post exact identity differs");
  return body.cid;
}

function exactSubmissions(rows,uri,cid) {return rows.filter(row => row.subject?.uri === uri && row.subject?.cid === cid);}

async function openPause() {
  const file=await open(pausePath,constants.O_RDWR | constants.O_NOFOLLOW);
  try {
    const info=await file.stat();
    if (!info.isFile() || info.uid !== process.getuid() || (info.mode & 0o022) !== 0 || info.size > 16 || (await file.readFile("utf8")) !== "open\n") throw new Error("pause control is not runner-owned, regular, closed to group writes and open");
    controlIdentity={dev:info.dev,ino:info.ino};
    control=file;
  } catch(error) {
    await file.close();
    throw error;
  }
}
async function writePause(text) {
  await control.truncate(0);
  await control.write(Buffer.from(text),0,Buffer.byteLength(text),0);
  await control.sync();
  const current=await lstat(pausePath);
  if (!current.isFile() || current.dev !== controlIdentity.dev || current.ino !== controlIdentity.ino || await readFile(pausePath,"utf8") !== text) throw new Error("pause control pathname or contents changed");
}

try {
  const executable=await stat(executablePath);
  if (!executable.isFile()) throw new Error("browser executable is not a regular file");
  await progress("browser_start");
  browser=await chromium.launch({executablePath,headless:true});
  await progress("author_a_oauth");
  let pageA=await signIn(await browser.newContext(),authorA);
  await progress("author_b_oauth");
  const pageB=await signIn(await browser.newContext(),authorB);
  const bBefore=await records(authorB.did);
  const refusedGet=await pageB.goto(`${app}/moderation`,{waitUntil:"domcontentloaded"});
  if (refusedGet?.status() !== 403) throw new Error("non-moderator queue GET was not refused");
  await pageB.goto(app,{waitUntil:"domcontentloaded"});
  const refusedPost=await formPost(pageB,"/moderate",{kind:"admit-root"});
  if (refusedPost.status !== 403) throw new Error("non-moderator action POST was not refused");
  await progress("non_moderator_refused");
  const other=await formPost(pageB,"/submit-existing",{post:otherPost});
  if (other.status !== 403 || exactSubmissions(await records(authorB.did),otherPost,await sourceCid(otherPost)).length !== 0 || (await records(authorB.did)).length !== bBefore.length) throw new Error("another author's post was not refused without a submission");
  await progress("other_author_post_refused");
  const cid=await sourceCid(duplicatePost);
  const before=await records(authorA.did);
  if (exactSubmissions(before,duplicatePost,cid).length !== 0) throw new Error("duplicate qualification requires a fresh unsubmitted post");
  const first=await formPost(pageA,"/submit-existing",{post:duplicatePost});
  if (first.status !== 200 || !/Awaiting independent observation/.test(first.text)) throw new Error("first exact submission did not complete");
  const one=exactSubmissions(await records(authorA.did),duplicatePost,cid);
  if (one.length !== 1) throw new Error("first submission did not create exactly one exact PDS record");
  await progress("first_submission",{submission:one[0]});
  const second=await formPost(pageA,"/submit-existing",{post:duplicatePost});
  if (second.status !== 200 || !/already asked to add this exact post/.test(second.text)) throw new Error("duplicate did not return the existing operation");
  const after=await records(authorA.did);
  const same=exactSubmissions(after,duplicatePost,cid);
  if (after.length !== before.length+1 || same.length !== 1 || same[0].uri !== one[0].uri || same[0].cid !== one[0].cid) throw new Error("duplicate changed PDS submission identity or count");
  await progress("duplicate_same_operation_no_extra_record",{submission:one[0]});
  await browser.close();browser=undefined;
  await progress("browser_closed");
  browser=await chromium.launch({executablePath,headless:true});
  pageA=await signIn(await browser.newContext(),authorA);
  const mine=await pageA.goto(`${app}/mine`,{waitUntil:"domcontentloaded"});
  if (mine?.status() !== 200) throw new Error("fresh OAuth sign-in could not read own status");
  await progress("fresh_browser_oauth_recovered");
  if (pausePath) {
    const pauseCid=await sourceCid(pausePost);
    const pauseBefore=await records(authorA.did);
    if (exactSubmissions(pauseBefore,pausePost,pauseCid).length !== 0) throw new Error("pause qualification requires a fresh unsubmitted post");
    await openPause();
    await progress("pause_control_acquired");
    pauseRestored=false;
    await progress("pause_restore_required");
    await writePause("paused\n");
    await progress("site_paused");
    await pageA.goto(app,{waitUntil:"domcontentloaded"});
    const paused=await formPost(pageA,"/submit-existing",{post:pausePost});
    const pauseAfter=await records(authorA.did);
    if (paused.status !== 503 || pauseAfter.length !== pauseBefore.length || exactSubmissions(pauseAfter,pausePost,pauseCid).length !== 0) throw new Error("paused site emitted a new submission");
    await progress("paused_submission_refused_no_write");
  }
} catch {
  process.exitCode=1;
  await progress("failed",{at:phase});
} finally {
  if (control) {
    try {
      await writePause("open\n");
      pauseRestored=true;
      await progress("pause_restored");
    } catch {
      process.exitCode=1;
      await progress("pause_restore_failed_operator_action_required");
    } finally { await control.close(); }
  }
  try { await browser?.close(); }
  catch { process.exitCode=1; await progress("browser_close_failed"); }
  if (!process.exitCode) await progress("complete");
  await writeFile(receiptPath,JSON.stringify({schema:"phlogiston.pds-browser-negative.v1",run,sourceRevision,appOrigin:app,pdsOrigin:provider,authorADid:authorA.did,authorBDid:authorB.did,otherPost,duplicatePost,pausePost:pausePost ?? null,pausePath:pausePath ?? null,pauseRestored,stages,result:process.exitCode ? "failed" : "complete",caveat:"Browser observations and bounded public PDS record reads only. No provider credential, token, callback URL or screenshot is retained. This does not qualify app restart, backup restore or complete stream history."},null,2)+"\n",{flag:"wx",mode:0o600});
}
