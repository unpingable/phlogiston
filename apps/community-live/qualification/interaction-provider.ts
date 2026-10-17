// Explicit operator-owned disposable identity only. Never use a personal account.
// node --import tsx qualification/interaction-provider.ts <private-account.json> <receipt.json>
import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,rm,mkdir} from 'node:fs/promises';
import {createServer} from 'node:http';
import {join} from 'node:path';
import {tmpdir,homedir} from 'node:os';
import {randomUUID} from 'node:crypto';
import {chromium} from 'playwright-core';
import {loadConfig} from '../src/config.js';
import {createOAuthClient} from '../src/oauth.js';
import {createHandler, type Dependencies} from '../src/server.js';
import {WebSessionStore,ContributionPlanStore,SecretJsonFileStore} from '../src/storage.js';
import {ActivitySnapshots} from '../src/activity.js';
import {OAuthPublicRepoWriter} from '../src/repo-writer.js';
import {READER_SCOPE,READER_INTERACTION_SCOPE} from '../src/p0.js';
import {DurableWriteJournal} from '../src/operations.js';
import type {AddressInfo} from 'node:net';

const [accountPath,receiptPath]=process.argv.slice(2);
if(!accountPath||!receiptPath)throw new Error('private account path and receipt path required');
const account=JSON.parse(await readFile(accountPath,'utf8'));
assert.ok(['http://127.0.0.1:3002','https://phlogiston.social'].includes(account.origin));
const provider='https://phlogiston.social';
assert.match(account.handle,/^rc-[a-z0-9]+\.phlogiston\.social$/);
const runtime=await mkdtemp(join(tmpdir(),'phlo-interaction-provider-'));
const stages:unknown[]=[];let phase='initialization',status='failed';
let handler: ReturnType<typeof createHandler>;
const server=createServer((req,res)=>handler(req,res));
await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${(server.address() as AddressInfo).port}`;
const config=loadConfig({COMMUNITY_PROFILE:'p0',COMMUNITY_READER_ENABLED:'true',COMMUNITY_PUBLIC_URL:origin,COMMUNITY_DID:'did:plc:qualification',COMMUNITY_MODERATOR_DID:'did:plc:moderator',COMMUNITY_NAME:'Provider qualification',COMMUNITY_PURPOSE:'Disposable fixture',COMMUNITY_RUNTIME_DIR:runtime,COMMUNITY_OBSERVER_URL:'http://127.0.0.1:1',COMMUNITY_AUTHORITY_SOCKET:join(runtime,'no-authority'),COMMUNITY_SITE_PAUSE_PATH:join(runtime,'site'),COMMUNITY_ADMISSION_PAUSE_PATH:join(runtime,'admission'),COMMUNITY_P0_HOSTED_PDS_ORIGIN:'https://phlogiston.social'});
await writeFile(config.sitePausePath!,'open\n',{mode:0o600});
const oauth=createOAuthClient(config),webSessions=new WebSessionStore(join(runtime,'web-sessions'));
let loseCreateResponse=false;
const deps:Dependencies={config,oauth,webSessions,repoWriter:(session,did)=>{const writer=new OAuthPublicRepoWriter(session,did);return {get:address=>writer.get(address),delete:(address,cid)=>writer.delete(address,cid),create:async(address,record)=>{const result=await writer.create(address,record);if(loseCreateResponse){loseCreateResponse=false;throw new Error('deterministically lost provider response')}return result;}};},plans:new ContributionPlanStore(join(runtime,'plans')),activities:new ActivitySnapshots(Buffer.alloc(32,1),{get:async()=>0,advance:async()=>{}}),authority:{request:async()=>{throw new Error('No community authority in this qualification')}},projection:{get:async()=>({discussions:[]}),getCapped:async()=>({discussions:[]})},profiles:{lookup:async()=>new Map()}};
handler=createHandler(deps);
const browser=await chromium.launch({executablePath:join(homedir(),'.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')});
const context=await browser.newContext({viewport:{width:390,height:844}}),page=await context.newPage();page.setDefaultTimeout(30000);
const stage=(name:string,detail:object={})=>{phase=name;stages.push({name,...detail,time:new Date().toISOString()});console.log(name)};
async function consent(){
 await page.waitForURL(url=>url.origin===provider);
 const password=page.locator('input[name=password]');
 if(await password.count()){await password.fill(account.password);await page.getByRole('button',{name:'Sign in',exact:true}).click();}
 await page.getByRole('button',{name:'Authorize',exact:true}).click();
 await page.waitForURL(url=>url.origin===origin);
}
async function session(){const token=(await context.cookies(origin)).find(c=>c.name==='community_session')?.value;assert.ok(token);const session=await webSessions.resolve(token);assert.ok(session);return session;}
async function action(fields:Record<string,string>){const current=await session();const response=await context.request.post(origin+'/interact',{headers:{Origin:origin},form:{csrf:current.csrf,operationId:randomUUID(),...fields}});return {status:response.status(),body:await response.text()};}
const journal=()=>new DurableWriteJournal(join(runtime,'interactions',`${encodeURIComponent(account.did)}.json`));
const publicRead=async(uri:string)=>{const [,repo,collection,rkey]=/^at:\/\/([^/]+)\/([^/]+)\/(.+)$/.exec(uri)!;const response=await fetch(`${provider}/xrpc/com.atproto.repo.getRecord?`+new URLSearchParams({repo:repo!,collection:collection!,rkey:rkey!}));if(response.status===400){const body=await response.json() as {error:string};if(body.error==='RecordNotFound')return null;throw new Error('provider read refused');}assert.equal(response.status,200);const value=await response.json() as {uri:string;cid:string;value:unknown};assert.equal(value.uri,uri);return value;};
try{
 stage('reader-consent-start');await page.goto(origin+'/signin');await page.locator('input[name=handle]').fill(account.did);await page.locator('form.signin button').click();await consent();
 const readerSession=await oauth.restore(account.did);assert.equal((await readerSession.getTokenInfo()).scope,READER_SCOPE);await page.goto(origin+'/settings');assert.match(await page.locator('main').innerText(),/Off\./);stage('fresh-reader-grant',{scope:(await readerSession.getTokenInfo()).scope});
 const denied=await action({action:'post',text:'MUST NOT PUBLISH: reader refusal'});assert.equal(denied.status,403);stage('reader-direct-route-refusal');
 await page.getByText('Enable content interaction',{exact:true}).click();await page.getByRole('button',{name:'Continue to provider consent'}).click();await consent();
 const writerSession=await oauth.restore(account.did);const info=await writerSession.getTokenInfo();assert.equal(info.scope,READER_INTERACTION_SCOPE);stage('interaction-provider-consent',{scope:info.scope,issuer:info.iss,audience:info.aud,did:info.sub});
 const saved=await new SecretJsonFileStore<{tokenSet:{refresh_token:string}}>(join(runtime,'oauth','session')).get(account.did);assert.ok(saved?.tokenSet.refresh_token);
 const lostId=randomUUID();loseCreateResponse=true;const interrupted=await action({action:'post',text:'Disposable interrupted publication; same operation will be reconciled.',operationId:lostId});assert.equal(interrupted.status,200);assert.match(interrupted.body,/outcome is unknown/);
 handler=createHandler({...deps,webSessions:new WebSessionStore(join(runtime,'web-sessions'))});
 const reconciled=await action({action:'resume',operationId:lostId});assert.match(reconciled.body,/provider confirmed/);const lost=(await journal().entries(account.did)).find(o=>o.operationId===lostId)!;const lostUri=`at://${lost.repo}/${lost.collection}/${lost.rkey}`;assert.equal((await publicRead(lostUri))?.cid,lost.committedCid);assert.equal((await action({action:'delete-post',record:lostUri,recordCid:lost.committedCid!})).status,200);assert.equal(await publicRead(lostUri),null);stage('lost-response-and-handler-restart-reconciled',{uri:lostUri,cid:lost.committedCid});
 const posted=await action({action:'post',text:'Disposable Phlogiston interaction qualification. This record will be removed.'});assert.equal(posted.status,200);assert.match(posted.body,/provider confirmed/);const post=(await journal().entries(account.did)).find(o=>o.collection==='app.bsky.feed.post' && o.action !== 'delete' && o.operationId !== lostId)!;const postUri=`at://${post.repo}/${post.collection}/${post.rkey}`,observed=await publicRead(postUri);assert.equal(observed?.cid,post.committedCid);stage('post-exact-public-readback',{uri:postUri,cid:post.committedCid});
 // Reader eligibility uses the ordinary AppView path, including moderation.
 stage('wait-for-appview');
 let threadReady=false;
 for(let attempt=0;attempt<20;attempt++){const result=await action({action:'like',uri:postUri,cid:post.committedCid!});if(result.status===200){assert.match(result.body,/provider confirmed/);threadReady=true;break;}await new Promise(resolve=>setTimeout(resolve,1500));}
 assert.ok(threadReady,'AppView must resolve exact post before interaction');
 const like=(await journal().entries(account.did)).find(o=>o.collection==='app.bsky.feed.like')!;const likeUri=`at://${like.repo}/${like.collection}/${like.rkey}`;assert.equal((await publicRead(likeUri))?.cid,like.committedCid);stage('like-exact-public-readback',{uri:likeUri,cid:like.committedCid});
 assert.equal((await action({action:'repost',uri:postUri,cid:post.committedCid!})).status,200);const repost=(await journal().entries(account.did)).find(o=>o.collection==='app.bsky.feed.repost')!,repostUri=`at://${repost.repo}/${repost.collection}/${repost.rkey}`;assert.equal((await publicRead(repostUri))?.cid,repost.committedCid);stage('repost-exact-public-readback',{uri:repostUri,cid:repost.committedCid});
 const replied=await action({action:'reply',uri:postUri,cid:post.committedCid!,text:'Disposable reply; exact root and parent qualification.'});assert.equal(replied.status,200);assert.match(replied.body,/provider confirmed/);const reply=(await journal().entries(account.did)).find(o=>(o.record as {reply?:unknown}).reply)!;const replyUri=`at://${reply.repo}/${reply.collection}/${reply.rkey}`;const replyValue=await publicRead(replyUri);assert.deepEqual((replyValue?.value as {reply:unknown}).reply,{root:{uri:postUri,cid:post.committedCid},parent:{uri:postUri,cid:post.committedCid}});stage('reply-lineage-public-readback',{uri:replyUri,cid:reply.committedCid});
 for(const [kind,uri]of [['unlike',likeUri],['unrepost',repostUri]]){const removed=await action({action:kind!,uri:postUri,cid:post.committedCid!,record:uri!});assert.equal(removed.status,200);assert.match(removed.body,/record was removed/);assert.equal(await publicRead(uri!),null);}stage('undo-owned-likes-and-reposts');
 for(const item of [reply,post]){const uri=`at://${item.repo}/${item.collection}/${item.rkey}`;assert.equal((await action({action:'delete-post',record:uri,recordCid:item.committedCid!})).status,200);assert.equal(await publicRead(uri),null);}stage('public-fixture-records-retired');
 await page.goto(origin+'/settings');await page.getByText('Disable content interaction',{exact:true}).click();await page.getByRole('button',{name:'Disable interaction and disconnect'}).click();assert.match(await page.locator('main').innerText(),/provider accepted/);await assert.rejects(oauth.restore(account.did));await assert.rejects(new OAuthPublicRepoWriter(writerSession,account.did).create({repo:account.did,collection:'app.bsky.feed.post',rkey:'retained-session-must-refuse'},{$type:'app.bsky.feed.post',text:'MUST NOT PUBLISH',createdAt:new Date().toISOString()}));await assert.rejects(writerSession.server.request('token',{grant_type:'refresh_token',refresh_token:saved.tokenSet.refresh_token}));stage('disable-removed-effective-authority-and-provider-refresh-refused');
 await page.goto(origin+'/signin');await page.locator('input[name=handle]').fill(account.did);await page.locator('form.signin button').click();await consent();assert.equal((await (await oauth.restore(account.did)).getTokenInfo()).scope,READER_SCOPE);assert.equal((await action({action:'post',text:'reader must still refuse'})).status,403);stage('reader-reconnect-has-no-social-write-authority');
 await page.goto(origin+'/settings');await page.getByRole('button',{name:'Sign out',exact:true}).click();await assert.rejects(oauth.restore(account.did));stage('reader-logout-retired-grant');
 status='passed';
}catch(error){stage('failed',{failedPhase:phase,errorType:error instanceof Error?error.name:'unknown'});process.exitCode=1;}
finally{
 await browser.close();await new Promise<void>(resolve=>server.close(()=>resolve()));
 await writeFile(receiptPath,JSON.stringify({schema_version:1,status,time:new Date().toISOString(),did:account.did,handle:account.handle,provider:provider,client:origin,stages,runtime_custody:runtime,retirement:'On success provider records and grant retired; remove local runtime after receipt custody. On failure reconcile journal then delete only fixture records and grant.'},null,2)+'\n',{mode:0o600});
 if(status==='passed')await rm(runtime,{recursive:true,force:true});
}
