import assert from "node:assert/strict";
import { mkdtempSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { QuietStore } from "./quiet.js";
import { HttpError } from "./http-error.js";
const did="did:plc:fixtureaccount", other="did:plc:otheraccount";
const root="at://did:plc:postowner/app.bsky.feed.post/3test";
function fixture() {
  const dir=mkdtempSync(join(tmpdir(),"phlo-quiet-")), path=join(dir,"quiet.sqlite");
  return {dir,path,store:new QuietStore(path)};
}
const status=(code:number)=>(e:unknown)=>e instanceof HttpError && e.status===code;
test("journal before effect; unconfirmed response stays unknown despite immediate readback",async()=>{
  const f=fixture();try {
    let calls=0;
    await assert.rejects(f.store.apply(did,root,true,async()=>{calls++;assert.equal(f.store.list(did)[0]?.status,"unknown");throw Error();},async()=>true),status(503));
    assert.equal(calls,1);assert.equal(f.store.list(did)[0]?.status,"unknown");
    await assert.rejects(f.store.apply(did,root,true,async()=>{calls++;},async()=>true),status(409));
    assert.equal(calls,1);
    assert.equal(await f.store.apply(did,root+"known",true,async()=>{},async()=>false),false);
    assert.equal(f.store.list(did).find(item=>item.root===root+"known")?.status,"unmuted");
  }finally{f.store.close();rmSync(f.dir,{recursive:true});}
});
test("delayed provider effect cannot turn unknown into a new dispatch across restart",async()=>{
  const f=fixture();
  let providerMuted=false;let writes=0;
  await assert.rejects(f.store.apply(did,root,true,async()=>{writes++;throw Error("response lost");},async()=>providerMuted),status(503));
  f.store.close();const reopened=new QuietStore(f.path);
  try {
    assert.equal(reopened.list(did)[0]?.status,"unknown");
    providerMuted=true; // the original request takes effect after the first readback
    await assert.rejects(reopened.apply(did,root,true,async()=>{writes++;},async()=>providerMuted),status(409));
    reopened.reconcile(other,root,true);assert.deepEqual(reopened.list(other),[]);
    reopened.reconcile(did,root,providerMuted);assert.equal(reopened.list(did)[0]?.status,"unknown");
    assert.equal(writes,1);
    assert.equal(statSync(f.path).mode&0o777,0o600);assert.equal(statSync(f.dir).mode&0o777,0o700);
  }finally{reopened.close();rmSync(f.dir,{recursive:true});}
});
test("same account concurrent apply and reconcile refuse while other account proceeds",async()=>{
  const f=fixture();let release!:()=>void;const held=new Promise<void>(r=>{release=r;});
  try {
    const action=f.store.apply(did,root,true,()=>held,async()=>true);
    const second=new QuietStore(f.path);
    try {
      await assert.rejects(second.apply(did,root+"3",true,async()=>{assert.fail();},async()=>true),status(409));
    } finally { second.close(); }
    await assert.rejects(f.store.apply(did,root+"2",false,async()=>{},async()=>false),status(409));
    assert.throws(()=>f.store.reconcile(did,root,false),status(409));
    assert.equal(await f.store.apply(other,root,false,async()=>{},async()=>false),true);
    release();await action;assert.equal(f.store.list(did)[0]?.status,"muted");assert.equal(f.store.list(other)[0]?.status,"unmuted");
  }finally{release();f.store.close();rmSync(f.dir,{recursive:true});}
});
test("100 per account limit refuses before effect; existing entries can change",async()=>{
  const f=fixture();try {
    for(let i=0;i<100;i++)await f.store.apply(did,root+i,true,async()=>{},async()=>true);
    let sent=false;await assert.rejects(f.store.apply(did,root+"overflow",true,async()=>{sent=true;},async()=>true),status(409));
    assert.equal(sent,false);assert.equal(f.store.list(did).length,100);
    assert.equal(await f.store.apply(did,root+"0",false,async()=>{},async()=>false),true);
    assert.equal(await f.store.apply(other,root,true,async()=>{},async()=>true),true);
  }finally{f.store.close();rmSync(f.dir,{recursive:true});}
});
test("invalid DID and handle-authority post refuse",async()=>{
  const f=fixture();try {
    assert.throws(()=>f.store.list("account.example"),status(400));
    await assert.rejects(f.store.apply(did,"at://account.example/app.bsky.feed.post/3test",true,async()=>{assert.fail();},async()=>true),status(400));
  }finally{f.store.close();rmSync(f.dir,{recursive:true});}
});
