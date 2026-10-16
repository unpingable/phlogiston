import assert from "node:assert/strict";
import { mkdtempSync, statSync, rmSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import { PersonalFeedStore, type PersonalFeedInput } from "./personal-feeds.js";
const A="did:plc:alice",B="did:plc:bob";
const definition=():PersonalFeedInput=>({name:"Alice",sources:[{kind:"following"}],policies:{publicBlocks:{curatorDid:B,curatorHandle:"bob.test"}},transformations:{includeReplies:false,includeReposts:true},ordering:"upstream",publishing:null});
function fixture(){const dir=mkdtempSync(join(tmpdir(),"personal-feed-"));const path=join(dir,"private","feeds.sqlite");return {dir,path,store:new PersonalFeedStore(path)};}
test("account scoped CRUD, immutable identity and restart continuity",()=>{const f=fixture();try{const feed=f.store.create(A,definition());assert.equal(feed.version,1);assert.equal(f.store.get(B,feed.id),undefined);assert.equal(f.store.update(B,feed.id,definition()),undefined);assert.equal(f.store.remove(B,feed.id),false);assert.deepEqual(f.store.list(B),[]);assert.equal(f.store.update(A,feed.id,{...definition(),name:"Changed"})?.name,"Changed");f.store.close();const reopened=new PersonalFeedStore(f.path);assert.equal(reopened.get(A,feed.id)?.name,"Changed");assert.equal(reopened.remove(A,feed.id),true);assert.deepEqual(reopened.list(A),[]);reopened.close();}finally{rmSync(f.dir,{recursive:true,force:true});}});
test("strict version1 schema rejects unsupported definitions and supplied owner",()=>{const f=fixture();try{for(const patch of [{version:2},{ownerDid:B},{id:"injected"},{sources:[]},{sources:[definition().sources[0],definition().sources[0]]},{ordering:"random"},{publishing:{did:A}},{name:" "},{name:"a".repeat(81)},{transformations:{includeReplies:1,includeReposts:true}},{sources:[{kind:"author",did:A,handle:"alice.test"}]},{policies:null},{policies:{publicBlocks:{curatorDid:"bob.test",curatorHandle:"bob.test"}}},{policies:{publicBlocks:{curatorDid:B,curatorHandle:"https://bob.test"}}},{policies:{publicBlocks:{curatorDid:B,curatorHandle:"bob.test",publisherDid:A}}}])assert.throws(()=>f.store.create(A,{...definition(),...patch}));assert.deepEqual(f.store.list(A),[]);}finally{f.store.close();rmSync(f.dir,{recursive:true,force:true});}});
test("cap remains atomic across independent SQLite connections and accounts",()=>{const f=fixture();const second=new PersonalFeedStore(f.path);try{for(let i=0;i<19;i++)f.store.create(A,definition());second.create(A,definition());assert.throws(()=>f.store.create(A,definition()),/full/);assert.equal(second.list(A).length,20);second.create(B,definition());assert.equal(f.store.list(B).length,1);assert.equal(second.remove(A,second.list(A)[0]!.id),true);f.store.create(A,definition());assert.equal(f.store.list(A).length,20);}finally{second.close();f.store.close();rmSync(f.dir,{recursive:true,force:true});}});
test("protected modes and separate database boundary",()=>{const f=fixture();try{assert.equal(statSync(f.path).mode&0o777,0o600);assert.equal(statSync(join(f.dir,"private")).mode&0o777,0o700);f.store.close();chmodSync(f.path,0o644);assert.throws(()=>new PersonalFeedStore(f.path),/private/);chmodSync(f.path,0o600);const db=new DatabaseSync(f.path);db.exec("CREATE TABLE other_state(value TEXT)");db.close();assert.throws(()=>new PersonalFeedStore(f.path),/separate database/);}finally{rmSync(f.dir,{recursive:true,force:true});}});
test("concurrent processes admit exactly one final account slot",async()=>{
  const {spawn}=await import("node:child_process");const f=fixture();
  try {
    for(let i=0;i<19;i++)f.store.create(A,definition());
    const moduleUrl=new URL("./personal-feeds.ts",import.meta.url).href;
    const code=`import {PersonalFeedStore} from ${JSON.stringify(moduleUrl)};const store=new PersonalFeedStore(process.argv[1]);try{store.create(${JSON.stringify(A)},${JSON.stringify(definition())});process.exitCode=0;}catch(e){process.exitCode=e.status===409?9:10;}finally{store.close();}`;
    const run=()=>new Promise<number|null>((resolve,reject)=>{const child=spawn(process.execPath,["--import","tsx","--input-type=module","-e",code,f.path],{stdio:["ignore","ignore","pipe"]});let errors="";child.stderr.on("data",value=>{errors+=String(value);});child.once("error",reject);child.once("exit",exit=>{if(exit!==0&&exit!==9)reject(new Error(errors));else resolve(exit);});});
    const exits=await Promise.all([run(),run()]);assert.deepEqual(exits.sort(),[0,9]);assert.equal(f.store.list(A).length,20);
  } finally {f.store.close();rmSync(f.dir,{recursive:true,force:true});}
});
