const states = new WeakMap();
const active = new Set();
export function groupingLabKey(did) { return `phlogiston.labs.grouping.v1:${did}`; }
export function groupingLabEnabled(did) { try { return localStorage.getItem(groupingLabKey(did)) === 'on'; } catch { return false; } }
function setLab(key, enabled) { try { if(enabled)localStorage.setItem(key,'on');else localStorage.removeItem(key); } catch {} }
function settings() {
  const main=document.querySelector('main[data-workspace-did]'),input=document.querySelector('[data-lab-grouping]');if(!main||!input)return;
  const did=main.dataset.workspaceDid,status=document.querySelector('[data-labs-status]');
  input.checked=groupingLabEnabled(did);
  input.addEventListener('change',()=>{setLab(groupingLabKey(did),input.checked);status.textContent='Grouping choice saved for this account in this browser.';});
  document.querySelector('[data-labs-reset]')?.addEventListener('click',()=>{setLab(groupingLabKey(did),false);input.checked=false;status.textContent='Grouping reset for this account in this browser.';});
}

function anchor(feed) {
  const posts=[...feed.querySelectorAll('article[data-post-uri]:not([hidden])')];
  const post=posts.find(item=>item.getBoundingClientRect().bottom>0)||posts[0];return post?{uri:post.dataset.postUri,top:post.getBoundingClientRect().top}:null;
}
function keepAnchor(feed,before) { if(!before)return;const post=[...feed.querySelectorAll('article[data-post-uri]')].find(item=>item.dataset.postUri===before.uri);if(!post)return;const delta=post.getBoundingClientRect().top-before.top,scroller=feed.closest('.workspace-primary,.companion-content');if(scroller)scroller.scrollTop+=delta;else scrollBy(0,delta); }
function restore(state) { if(state.mode==='grouped')for(const details of state.feed.querySelectorAll('.labs-group-members'))state.expansion.set(details.dataset.groupKey,details.open);state.feed.replaceChildren(...state.nodes);state.mode='ordinary';state.panel.querySelector('[data-labs-ordinary]').setAttribute('aria-pressed','true');state.panel.querySelector('[data-labs-grouped]').setAttribute('aria-pressed','false'); }
function units(feed) {
  const result=[];let context=null;
  for(const node of [...feed.children]) { if(node.matches('.feed-context')){context=node;continue;}if(node.matches('article[data-post-uri]')){result.push({post:node,nodes:context?[context,node]:[node]});context=null;}else{if(context)result.push({post:null,nodes:[context]});context=null;result.push({post:null,nodes:[node]});} }
  if(context)result.push({post:null,nodes:[context]});return result;
}
function grouped(state) {
  const before=anchor(state.feed);restore(state);const rows=units(state.feed),buckets=new Map();
  for(const row of rows)if(row.post&&!row.post.hidden){const key=row.post.dataset.labsKey,kind=row.post.dataset.labsKind;if(key&&kind){const id=`${kind}\n${key}`,list=buckets.get(id)||[];list.push(row);buckets.set(id,list);}}
  const claimed=new Set(),output=[];
  for(const row of rows) {
    if(claimed.has(row)||!row.post||row.post.hidden){if(!claimed.has(row))output.push(...row.nodes);continue;}
    const members=buckets.get(`${row.post.dataset.labsKind}\n${row.post.dataset.labsKey}`)||[];
    if(members.length<2){output.push(...row.nodes);continue;}
    members.sort((a,b)=>{const first=Date.parse(a.post.dataset.labsCreatedAt),second=Date.parse(b.post.dataset.labsCreatedAt);return (Number.isFinite(second)?second:-Infinity)-(Number.isFinite(first)?first:-Infinity)||(a.post.dataset.postUri||'').localeCompare(b.post.dataset.postUri||'');});members.forEach(item=>claimed.add(item));
    const section=document.createElement('section');section.className='labs-group';const kind=row.post.dataset.labsKind==='source'?'source link':'conversation';
    const note=document.createElement('p');note.className='labs-group-note';note.textContent=`${members.length} contributions share this exact ${kind}. Grouping does not mean agreement or corroboration.`;section.append(note,...members[0].nodes);
    const details=document.createElement('details');details.className='labs-group-members';details.dataset.groupKey=`${row.post.dataset.labsKind}\n${row.post.dataset.labsKey}`;details.open=state.expansion.get(details.dataset.groupKey)||false;const summary=document.createElement('summary');summary.textContent=`Show ${members.length-1} more contribution${members.length===2?'':'s'}`;details.append(summary);const body=document.createElement('div');for(const member of members.slice(1))body.append(...member.nodes);details.append(body);section.append(details);output.push(section);
  }
  state.feed.replaceChildren(...output);state.mode='grouped';state.panel.querySelector('[data-labs-ordinary]').setAttribute('aria-pressed','false');state.panel.querySelector('[data-labs-grouped]').setAttribute('aria-pressed','true');keepAnchor(state.feed,before);
}
function choose(state,mode) { const before=anchor(state.feed);if(mode==='grouped')grouped(state);else{restore(state);keepAnchor(state.feed,before);} }

export function retireGroupingLab(node) { const state=states.get(node);if(!state)return;restore(state);state.panel.remove();states.delete(node);active.delete(state); }
window.addEventListener('storage',event=>{for(const state of active)if(event.key===null||event.key===groupingLabKey(state.did)){if(!groupingLabEnabled(state.did))retireGroupingLab(state.node);}});
window.addEventListener('pagehide',()=>{for(const state of active)retireGroupingLab(state.node);});
export function restoreGroupingLab(node) { const state=states.get(node);if(!state)return;const mode=state.mode;restore(state);state.resumeMode=mode; }
export function refreshGroupingLab(node,did,enabled=groupingLabEnabled(did)) {
  if(!enabled){retireGroupingLab(node);return;}
  const surface=node.querySelector('.feed-surface'),feed=surface?.querySelector('.following-feed');if(!feed||surface.dataset.feedKey!=='following')return;
  let state=states.get(node);
  if(state){const mode=state.resumeMode||state.mode;if(state.mode==='grouped')restore(state);state.nodes=[...feed.childNodes];state.resumeMode=null;if(mode==='grouped')grouped(state);return;}
  const panel=document.createElement('section');panel.className='labs-comparison';panel.setAttribute('aria-label','Grouping Labs comparison');panel.innerHTML='<strong>Labs: compare this Following snapshot</strong><p>Both presentations use these same received posts. The snapshot ends on reload or account change.</p><div><button type="button" data-labs-ordinary aria-pressed="true">Ordinary</button><button type="button" data-labs-grouped aria-pressed="false">Grouped</button><button type="button" data-labs-exit>Exit Labs</button></div>';
  feed.before(panel);state={node,did,feed,panel,nodes:[...feed.childNodes],mode:'ordinary',resumeMode:null,expansion:new Map()};states.set(node,state);active.add(state);
  panel.querySelector('[data-labs-ordinary]').onclick=()=>choose(state,'ordinary');panel.querySelector('[data-labs-grouped]').onclick=()=>choose(state,'grouped');panel.querySelector('[data-labs-exit]').onclick=()=>{setLab(groupingLabKey(did),false);for(const current of active)if(current.did===did){retireGroupingLab(current.node);}};
}
settings();
