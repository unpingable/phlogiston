import assert from "node:assert/strict";
import test from "node:test";

import { XrpcResponseError } from "@atproto/lex-client";
import { RecordConflictError, ProviderRefusalError } from "./operations.js";
import { OAuthPublicRepoWriter } from "./repo-writer.js";

const DID="did:plc:alice",address={repo:DID,collection:"app.bsky.feed.post",rkey:"one"};

function writer(deleteRecord:(collection:string,rkey:string,options:Record<string,unknown>)=>Promise<unknown>):OAuthPublicRepoWriter {
  const value=Object.create(OAuthPublicRepoWriter.prototype) as OAuthPublicRepoWriter;
  Object.assign(value,{expectedDid:DID,client:{deleteRecord}});
  return value;
}

test("delete sends the exact committed CID as swapRecord",async()=>{
 let options:Record<string,unknown>|undefined;
 await writer(async(_collection,_rkey,value)=>{options=value;return {};}).delete(address,"committed-cid");
 assert.equal(options?.swapRecord,"committed-cid");
});

test("delete maps provider InvalidSwap to a terminal record conflict",async()=>{
 await assert.rejects(writer(async()=>{throw {error:"InvalidSwap"};}).delete(address,"committed-cid"),RecordConflictError);
});


test("readback refuses another record URI even with a valid looking CID and content",async()=>{
 const value=Object.create(OAuthPublicRepoWriter.prototype) as OAuthPublicRepoWriter;
 Object.assign(value,{expectedDid:DID,client:{getRecord:async()=>({body:{uri:"at://did:plc:other/app.bsky.feed.post/one",cid:"some-cid",value:{$type:"app.bsky.feed.post",text:"same"}}})}});
 await assert.rejects(value.get(address),/unexpected record identity/);
});

test("typed complete 403 refusal is distinguished from an HTTP 503 or malformed refusal",async()=>{
 const method={} as never;
 for(const [status,body,expected] of [[403,{error:"Forbidden"},ProviderRefusalError],[503,{error:"UpstreamFailure"},XrpcResponseError],[400,undefined,XrpcResponseError]] as const){
  const error=new XrpcResponseError(method,new Response("",{status}),body?{encoding:"application/json",body}:undefined);
  const value=Object.create(OAuthPublicRepoWriter.prototype) as OAuthPublicRepoWriter;
  Object.assign(value,{expectedDid:DID,client:{createRecord:async()=>{throw error}}});
  await assert.rejects(value.create(address,{$type:address.collection,text:"refused"}),expected);
 }
});
