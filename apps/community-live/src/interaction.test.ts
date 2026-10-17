import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { InteractionService, postText } from "./interaction.js";
import { DurableWriteJournal, RecordConflictError, ProviderRefusalError, type ObservedRecord, type PublicRepoWriter, type RecordAddress } from "./operations.js";

const DID="did:plc:alice", SUBJECT={uri:"at://did:plc:bob/app.bsky.feed.post/post1",cid:"bafy-post"};
const key=(a:RecordAddress)=>`${a.repo}/${a.collection}/${a.rkey}`;
class MemoryWriter implements PublicRepoWriter {
  records=new Map<string,ObservedRecord>(); creates=0; deletes=0; deleteSwap:string|undefined; loseCreate=false; loseDelete=false; conflictDelete=false;
  async create(address:RecordAddress,record:unknown) { this.creates++;const cid=`cid-${this.creates}`;this.records.set(key(address),{cid,record});if(this.loseCreate)throw new Error("lost response");return {cid}; }
  async get(address:RecordAddress) { return this.records.get(key(address)) ?? null; }
  async delete(address:RecordAddress,swapRecord?:string) { this.deletes++;this.deleteSwap=swapRecord;if(this.conflictDelete)throw new RecordConflictError("changed");this.records.delete(key(address));if(this.loseDelete)throw new Error("lost response"); }
}
async function fixture(fn:(service:InteractionService,writer:MemoryWriter,path:string)=>Promise<void>) { const root=await mkdtemp(join(tmpdir(),"interaction-"));const path=join(root,"journal.json");const writer=new MemoryWriter();try{await fn(new InteractionService(new DurableWriteJournal(path),writer,DID),writer,path);}finally{await rm(root,{recursive:true,force:true});} }

test("text-first composition is bounded by graphemes and bytes",()=>{
 assert.equal(postText(" hello "),"hello");assert.throws(()=>postText("   "),/required/);assert.throws(()=>postText("x".repeat(301)),/300/);assert.throws(()=>postText("💥".repeat(301)),/300/);
});

test("like uses one immutable exact-address operation across lost response and restart",()=>fixture(async(service,writer,path)=>{
 writer.loseCreate=true;const first=await service.create("like","operation-like-0001",{subject:SUBJECT});assert.equal(first.result.phase,"attempted_unknown");assert.equal(writer.creates,1);
 writer.loseCreate=false;const restarted=new InteractionService(new DurableWriteJournal(path),writer,DID);const result=await restarted.create("like","operation-like-0001",{subject:SUBJECT});assert.equal(result.result.phase,"committed");assert.equal(writer.creates,1);assert.equal(result.result.operation.record && (result.result.operation.record as {$type:string}).$type,"app.bsky.feed.like");
}));

test("undo resolves the viewer record, checks subject and owner, and reconciles a lost delete",()=>fixture(async(service,writer,path)=>{
 const liked=await service.create("like","operation-like-0002",{subject:SUBJECT});assert.equal(liked.result.phase,"committed");
 writer.loseDelete=true;const first=await service.remove("unlike","operation-unlike-01",liked.uri,undefined,SUBJECT);assert.equal(first.result.phase,"attempted_unknown");assert.equal(writer.deletes,1);
 writer.loseDelete=false;const restarted=new InteractionService(new DurableWriteJournal(path),writer,DID);const done=await restarted.resume("operation-unlike-01");assert.equal(done.result.phase,"committed");assert.equal(writer.deletes,1);
 const replay=await restarted.remove("unlike","operation-unlike-01",liked.uri,undefined,SUBJECT);assert.equal(replay.result.phase,"committed");assert.equal(writer.deletes,1);
 await assert.rejects(restarted.remove("unlike","operation-unlike-01",liked.uri,undefined,{...SUBJECT,cid:"changed"}),/different intent/);
 await assert.rejects(service.remove("unlike","operation-foreign-01",liked.uri.replace(DID,"did:plc:mallory"),undefined,SUBJECT),/signed-in account/);
}));

test("undo refuses a viewer record for a different subject and deletion of an unjournaled post",()=>fixture(async(service,writer)=>{
 const liked=await service.create("like","operation-like-0003",{subject:SUBJECT});
 await assert.rejects(service.remove("unlike","operation-unlike-02",liked.uri,undefined,{...SUBJECT,cid:"other"}),/does not match/);
 const postAddress={repo:DID,collection:"app.bsky.feed.post",rkey:"outside"};writer.records.set(key(postAddress),{cid:"outside-cid",record:{$type:"app.bsky.feed.post",text:"elsewhere",createdAt:new Date().toISOString()}});
 await assert.rejects(service.remove("delete-post","operation-delete-01",`at://${key(postAddress)}`,"outside-cid"),/created by this app/);
}));

test("app-created posts can be deleted but a changed CID fails closed",()=>fixture(async(service,writer)=>{
 const post=await service.create("post","operation-post-0001",{text:"public text"});assert.equal(post.result.phase,"committed");
 const address=post.result.operation;const saved=writer.records.get(key(address))!;writer.records.set(key(address),{...saved,cid:"changed"});
 await assert.rejects(service.remove("delete-post","operation-delete-02",post.uri,post.result.cid),/exact record/);
 writer.records.set(key(address),saved);const removed=await service.remove("delete-post","operation-delete-03",post.uri,post.result.cid);assert.equal(removed.result.phase,"committed");assert.equal(writer.records.has(key(address)),false);assert.equal(writer.deleteSwap,post.result.cid);
}));

test("operation identity binds kind, exact subject, reply lineage and text",()=>fixture(async(service)=>{
 await service.create("like","operation-intent-001",{subject:SUBJECT});
 await assert.rejects(service.create("repost","operation-intent-001",{subject:SUBJECT}),/different intent/);
 await service.create("reply","operation-intent-002",{text:"first",root:SUBJECT,parent:SUBJECT});
 await assert.rejects(service.create("reply","operation-intent-002",{text:"second",root:SUBJECT,parent:SUBJECT}),/different intent/);
}));

test("duplicate like with a different operation identity is refused",()=>fixture(async(service,writer)=>{
 await service.create("like","operation-duplicate-1",{subject:SUBJECT});
 await assert.rejects(service.create("like","operation-duplicate-2",{subject:SUBJECT}),/already committed/);
 assert.equal(writer.creates,1);
}));

test("like can be created again after this app commits its unlike",()=>fixture(async(service,writer)=>{
 const liked=await service.create("like","operation-relike-first",{subject:SUBJECT});
 await service.remove("unlike","operation-relike-undo",liked.uri,liked.result.cid,SUBJECT);
 const reliked=await service.create("like","operation-relike-second",{subject:SUBJECT});
 assert.equal(reliked.result.phase,"committed");assert.equal(writer.creates,2);
}));

test("like can be created again after the provider record was removed elsewhere",()=>fixture(async(service,writer)=>{
 const liked=await service.create("like","operation-external-first",{subject:SUBJECT});
 writer.records.delete(key(liked.result.operation));
 const reliked=await service.create("like","operation-external-second",{subject:SUBJECT});
 assert.equal(reliked.result.phase,"committed");assert.equal(writer.creates,2);
}));

test("undo action maps to exactly one collection",()=>fixture(async(service)=>{
 const liked=await service.create("like","operation-map-like",{subject:SUBJECT});
 await assert.rejects(service.remove("unrepost","operation-map-wrong",liked.uri,undefined,SUBJECT),/does not match/);
}));

test("provider InvalidSwap mapping terminalizes delete as a conflict",()=>fixture(async(service,writer)=>{
 const liked=await service.create("like","operation-swap-like",{subject:SUBJECT});writer.conflictDelete=true;
 const result=await service.remove("unlike","operation-swap-delete",liked.uri,liked.result.cid,SUBJECT);assert.equal(result.result.phase,"conflict");assert.equal(result.result.reason,"delete_target_mismatch");assert.equal(writer.deleteSwap,liked.result.cid);
}));

test("delete preparation persists only the complete delete-shaped operation",async()=>{
 const journal=new DurableWriteJournal("unused"),internal=journal as unknown as {loaded:boolean;flush:()=>Promise<void>};let flushes=0;
 internal.loaded=true;internal.flush=async()=>{flushes++;};
 const planned=await journal.prepareDelete({repo:DID,collection:"app.bsky.feed.like",rkey:"one"},{cid:"exact",record:{$type:"app.bsky.feed.like",subject:SUBJECT}},"operation-delete-once");
 assert.equal(flushes,1);assert.equal(planned.action,"delete");assert.equal(planned.committedCid,"exact");
});


test("complete provider refusal remains refused while transport errors stay unknown",()=>fixture(async(service,writer)=>{
 writer.create=async()=>{throw new ProviderRefusalError("Forbidden")};
 const denied=await service.create("post","operation-provider-denied",{text:"refused"});assert.equal(denied.result.phase,"refused");assert.equal(denied.result.reason,"provider_refused:Forbidden");
 writer.create=async()=>{throw new Error("connection lost")};
 const uncertain=await service.create("post","operation-provider-unknown",{text:"unknown"});assert.equal(uncertain.result.phase,"attempted_unknown");
 await assert.rejects(service.create("post","operation-duplicate-unknown",{text:"unknown"}),/unresolved/);
}));

test("Check outcome is read-only after confirmed absence and new identities cannot duplicate it",()=>fixture(async(service,writer)=>{
 let attempts=0;writer.create=async()=>{attempts++;throw new Error("connection lost")};
 const unknown=await service.create("post","operation-read-only-001",{text:"one publication"});assert.equal(unknown.result.phase,"attempted_unknown");
 assert.equal((await service.resume("operation-read-only-001")).result.phase,"refused");
 assert.equal((await service.resume("operation-read-only-001")).result.phase,"refused");assert.equal(attempts,1);
 await assert.rejects(service.create("post","operation-read-only-002",{text:"one publication"}),/unresolved/);
}));

test("a lost like response with absent readback blocks a new identity until exact retry",()=>fixture(async(service,writer)=>{
 writer.create=async()=>{throw new Error("connection lost")};
 await service.create("like","operation-late-like-001",{subject:SUBJECT});
 await assert.rejects(service.create("like","operation-late-like-002",{subject:SUBJECT}),/awaiting confirmation/);
 await assert.rejects(service.create("like","operation-late-like-003",{subject:SUBJECT}),/awaiting confirmation/);
}));

test("the outstanding bound also fences unknown deletes while reconciliation remains usable",()=>fixture(async(service,writer)=>{
 const likes=[];
 for(let index=0;index<26;index++) likes.push(await service.create("like",`operation-bound-like-${index}`,{subject:{...SUBJECT,uri:SUBJECT.uri+index}}));
 writer.loseDelete=true;
 for(let index=0;index<25;index++) await service.remove("unlike",`operation-bound-undo-${index}`,likes[index]!.uri,undefined,{...SUBJECT,uri:SUBJECT.uri+index});
 await assert.rejects(service.remove("unlike","operation-bound-undo-25",likes[25]!.uri,undefined,{...SUBJECT,uri:SUBJECT.uri+25}),/unfinished.*limit/);
 assert.equal(writer.deletes,25);
 assert.equal((await service.resume("operation-bound-undo-0")).result.phase,"committed");
 assert.equal((await service.remove("unlike","operation-bound-undo-25",likes[25]!.uri,undefined,{...SUBJECT,uri:SUBJECT.uri+25})).result.phase,"attempted_unknown");
}));

test("a refused same-address retry recognizes a late matching provider commit",()=>fixture(async(service,writer)=>{
 let original:ObservedRecord|undefined;
 writer.create=async(address,record)=>{original={cid:"late-cid",record};throw new Error("lost response")};
 const first=await service.create("post","operation-late-post-001",{text:"one public post"});
 assert.equal((await service.resume(first.operationId)).result.reason,"confirmed_absent");
 writer.create=async(address)=>{writer.records.set(key(address),original!);throw new ProviderRefusalError("InvalidRequest")};
 const retried=await service.retry(first.operationId);assert.equal(retried.result.phase,"committed");assert.equal(retried.result.cid,"late-cid");
}));
