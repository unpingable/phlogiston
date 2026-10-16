import {test} from 'node:test';
import assert from 'node:assert/strict';
import {initialState,transition} from '../static/workspace-state.js';
test('pinned companion survives feed switching and temporary inspection',()=>{
 let s=transition(initialState(),{type:'secondary',source:'/community'});
 s=transition(s,{type:'inspect',source:'/thread?uri=x'});
 assert.equal(s.secondary,'/community');
 s=transition(s,{type:'dismiss'}); assert.equal(s.secondary,'/community');assert.equal(s.context,null);
 s=transition(s,{type:'primary',source:'/home?feed=science'});assert.equal(s.secondary,'/community');
});
test('paired source selection restores only explicit associations',()=>{
 let s=transition(initialState(),{type:'mode',mode:'paired'});
 s=transition(s,{type:'secondary',source:'/community'});
 s=transition(s,{type:'primary',source:'/home?feed=science'});assert.equal(s.secondary,'/community');
 s=transition(s,{type:'secondary',source:'/home?feed=tech'});
 s=transition(s,{type:'inspect',source:'/context?uri=x'});
 s=transition(s,{type:'primary',source:'/home'});assert.equal(s.secondary,'/community');assert.equal(s.context,null);
 s=transition(s,{type:'primary',source:'/home?feed=science'});assert.equal(s.secondary,'/home?feed=tech');
});
test('transition history cannot mutate an earlier state and pairing memory is bounded',()=>{
 const old=initialState();let s=transition(old,{type:'mode',mode:'paired'});
 for(let i=0;i<50;i++){s=transition(s,{type:'primary',source:String(i)});s=transition(s,{type:'secondary',source:'/community'});}
 assert.equal(Object.keys(s.pairs).length,24);assert.deepEqual(old,initialState());
});
test('bounded transition exploration preserves pin and contextual base invariants',()=>{
 const events=[{type:'primary',source:'/home'},{type:'primary',source:'/home?feed=a'},{type:'secondary',source:'/community'},{type:'secondary',source:null},{type:'mode',mode:'paired'},{type:'mode',mode:'pinned'},{type:'inspect',source:'/thread?uri=x'},{type:'dismiss'}] as const;
 let states=[initialState()];
 for(let depth=0;depth<5;depth++){
  const next=[];
  for(const state of states)for(const event of events){
   const before=structuredClone(state),result=transition(state,event);assert.deepEqual(state,before);
   if(event.type==='inspect'||event.type==='dismiss'){assert.equal(result.secondary,state.secondary);assert.deepEqual(result.pairs,state.pairs);assert.equal(result.primary,state.primary);}
   if(event.type==='primary'&&state.mode==='pinned')assert.equal(result.secondary,state.secondary);
   next.push(result);
  }
  states=next;
 }
});
