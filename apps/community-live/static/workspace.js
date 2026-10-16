import {initialState, transition, markAttentionStale} from './workspace-state.js';
const main = document.querySelector('main[data-workspace-did]');
if (main) start(main);
async function start(main) {
  const did = main.dataset.workspaceDid, csrf = main.dataset.csrf;
  const key = `phlogiston.workspace.v1:${did}`;
  const helpKey = `phlogiston.help.v1:${did}`;
  let help = {};
  try { help=JSON.parse(localStorage.getItem(helpKey)||'{}')||{}; } catch {}
  function rememberHelp(){try{localStorage.setItem(helpKey,JSON.stringify(help));}catch{}}
  let sources = [{href:'/home',name:'Following',uri:'following'},{href:'/community',name:'The Cabinet',uri:'community'}];
  let connected = false, unavailable = false;
  try { const r = await fetch('/sources',{cache:'no-store'}); if(r.ok){const d=await r.json(); sources=d.sources;connected=d.feedsConnected;unavailable=!d.feedsAvailable;} } catch {}
  const valid = new Set(sources.map(s=>s.href));
  const params=new URLSearchParams(location.search);
  const canonical = location.pathname + (params.has('personal') ? `?personal=${encodeURIComponent(params.get('personal'))}` : params.has('feed') ? `?feed=${encodeURIComponent(params.get('feed'))}` : '');
  if (!valid.has(canonical)) sources.push({href:canonical,name:'Selected feed',uri:new URLSearchParams(location.search).get('feed')||'following'});
  valid.add(canonical);
  let state = {...initialState(),primary:canonical};
  try {
    const saved=JSON.parse(localStorage.getItem(key)||'null');
    if(saved && ['pinned','paired'].includes(saved.mode)) {
      state.mode=saved.mode;state.secondary=valid.has(saved.secondary)?saved.secondary:null;
      for(const [p,s] of Object.entries(saved.pairs||{}).slice(-24)) if(valid.has(p)&&(s===null||valid.has(s)))state.pairs[p]=s;
    }
  } catch {}
  const requestedCompanion=params.get('alongside');
  if(requestedCompanion && valid.has(`/home?personal=${requestedCompanion}`)){state.secondary=`/home?personal=${requestedCompanion}`;state.mode='pinned';}
  const initial=document.createElement('div');initial.className='workspace-view';while(main.firstChild)initial.append(main.firstChild);
  main.classList.add('workspace');document.body.classList.add('workspace-active');
  main.innerHTML='<aside class="workspace-nav" aria-label="Sources"><h2>Read</h2><p class="workspace-create"><a href="/feeds">Create a personal feed</a> · <a href="/help">Help</a></p><label>Primary view<select id="primary-source"></select></label><label>Add another view<select id="secondary-source"></select></label><label>Companion behavior<select id="companion-mode"><option value="pinned">Pinned</option><option value="paired">Remember per feed</option></select></label><p class="muted workspace-hint">Pinned stays put when you switch feeds. Open a conversation to inspect it temporarily.</p></aside><section class="workspace-primary" aria-label="Primary reading view" tabindex="-1"></section><aside class="workspace-secondary" aria-label="Companion view" hidden><div class="companion-heading"><strong id="companion-title">Alongside</strong><button type="button" id="dismiss-context">Back to companion</button><button type="button" id="close-companion">Close</button></div><section class="companion-content" tabindex="-1"></section></aside><div class="workspace-status" role="status" aria-live="polite"></div>';
  const primary=main.querySelector('.workspace-primary'),secondary=main.querySelector('.companion-content'),aside=main.querySelector('.workspace-secondary'),status=main.querySelector('.workspace-status');
  const primarySelect=main.querySelector('#primary-source'),secondarySelect=main.querySelector('#secondary-source'),mode=main.querySelector('#companion-mode');
  secondarySelect.add(new Option('Closed',''));
  for(const source of sources){primarySelect.add(new Option(source.name,source.href));secondarySelect.add(new Option(source.name,source.href));}
  if(!connected){const form=document.createElement('form');form.method='post';form.action='/oauth/login';for(const [name,value] of Object.entries({handle:did,return:'/home',access:'feeds'})){const i=document.createElement('input');i.type='hidden';i.name=name;i.value=value;form.append(i);}const button=document.createElement('button');button.textContent='Connect saved feeds';form.append(button);main.querySelector('.workspace-nav').append(form);}
  else if(unavailable){const p=document.createElement('p');p.textContent='Saved feeds could not be loaded. Refresh to try again.';main.querySelector('.workspace-nav').append(p);}
  function layout() {
    const height=document.querySelector('body > header')?.getBoundingClientRect().height || 45;
    document.documentElement.style.setProperty('--workspace-header',`${height}px`);
    const overlay=matchMedia('(max-width:760px)').matches && !aside.hidden;
    primary.inert=overlay;main.querySelector('.workspace-nav').inert=overlay;
  }
  new ResizeObserver(layout).observe(document.querySelector('body > header'));
  window.addEventListener('resize',layout);layout();
  const panes=new Map([[primary,{cache:new Map([[state.primary,{node:initial,scroll:0,pages:1}]]),key:null,serial:0}],[secondary,{cache:new Map(),key:null,serial:0}]]);
  function save(){try{localStorage.setItem(key,JSON.stringify({mode:state.mode,secondary:state.secondary,pairs:state.pairs}));}catch{}}
  function announce(text){status.replaceChildren();status.textContent=text;}
  function hideLocal(node,roots){node.querySelectorAll('.following-feed > article[data-post-uri]').forEach(post=>{post.hidden=roots.includes(post.dataset.threadRoot||post.dataset.postUri);});}
  function decorate(node,source){
    const surface=node.querySelector('.feed-surface');if(!surface)return;
    node.querySelectorAll('.following-feed > article[data-post-uri]').forEach(post=>{
      const actions=post.querySelector('.feed-actions');if(!actions||actions.querySelector('[data-local-quiet]'))return;
      const button=document.createElement('button');button.type='button';button.dataset.localQuiet=post.dataset.postUri;button.textContent='Quiet here';button.title='Hide this conversation in this feed only. Bluesky notifications stay unchanged.';actions.append(button);
    });
    if(!node.querySelector('.local-quiet-review')){
      const details=document.createElement('details');details.className='local-quiet-review';const summary=document.createElement('summary');summary.textContent='Quieted in this feed';details.append(summary);
      details.addEventListener('toggle',async()=>{if(!details.open)return;details.querySelectorAll('p,button').forEach(e=>e.remove());try{const r=await fetch(`/local-quiet?feed=${encodeURIComponent(surface.dataset.feedKey)}`,{cache:'no-store'});if(!r.ok)throw Error();const {roots}=await r.json();if(!roots.length){const p=document.createElement('p');p.textContent='No conversations quieted here.';details.append(p);}for(const root of roots){const b=document.createElement('button');b.type='button';b.textContent='Restore conversation';b.dataset.restoreRoot=root;details.append(b);}}catch{const p=document.createElement('p');p.textContent='Local preferences are unavailable.';details.append(p);}});node.append(details);
    }
  }
  async function fragment(href){
    const target=new URL(href,location.origin);if(target.origin!==location.origin||!['/home','/feed','/thread','/context','/community'].includes(target.pathname)&&!target.pathname.startsWith('/d/'))throw Error('Unsupported view');
    const r=await fetch(target,{cache:'no-store',headers:{Accept:'text/html'}});if(r.status===401){location.assign('/');throw Error('Please sign in again.');}if(!r.ok)throw Error('This view is unavailable. Your other view is still here.');
    const text=await r.text();if(text.length>3000000)throw Error('View is too large.');const doc=new DOMParser().parseFromString(text,'text/html');const content=doc.querySelector('main');if(!content||content.dataset.workspaceDid!==did)throw Error('Session changed. Reload to continue.');const node=document.createElement('div');node.className='workspace-view';node.append(...content.childNodes);node.querySelectorAll('script').forEach(s=>s.remove());return node;
  }
  async function show(pane,href,refresh=false){
    const p=panes.get(pane),serial=++p.serial;
    if(p.key&&p.cache.has(p.key))p.cache.get(p.key).scroll=pane.scrollTop;
    if(!href){pane.replaceChildren();p.key=null;return;}
    try {
      let view=refresh?null:p.cache.get(href);
      if(!view){pane.setAttribute('aria-busy','true');const node=await fragment(href);if(serial!==p.serial)return;decorate(node,href);view={node,scroll:0,pages:1};p.cache.set(href,view);}
      if(serial!==p.serial)return;
      p.key=href;pane.replaceChildren(view.node);pane.scrollTop=view.scroll;
      const name=sources.find(s=>s.href===href)?.name;const heading=view.node.querySelector('.page-heading h1');if(name&&heading)heading.textContent=name;
      while(p.cache.size>8){const oldest=[...p.cache.keys()].find(k=>k!==href&&k!==state.secondary);if(!oldest)break;p.cache.delete(oldest);}
    }catch(error){if(serial===p.serial)announce(error.message);}finally{if(serial===p.serial)pane.removeAttribute('aria-busy');}
  }
  async function render(){save();primarySelect.value=state.primary;secondarySelect.value=state.secondary||'';mode.value=state.mode;aside.hidden=!(state.secondary||state.context);main.classList.toggle('has-companion',!aside.hidden);main.querySelector('#dismiss-context').hidden=!state.context;main.querySelector('#close-companion').hidden=Boolean(state.context);layout();main.querySelector('#companion-title').textContent=state.context?'Inspecting':sources.find(s=>s.href===state.secondary)?.name||'Alongside';await Promise.all([show(primary,state.primary),show(secondary,state.context||state.secondary)]);}
  if(!help.welcomeDismissed){
    const intro=document.createElement('section');intro.className='reader-welcome';intro.setAttribute('aria-label','Getting started');
    intro.innerHTML='<h2>Bluesky, with a little more room to work.</h2><p>Read feeds side by side and explore conversations without losing your place. Create a private view of Following using another account’s public blocks as extra exclusions.</p><p>This is a reader: posting, likes, reposts and notifications are not available yet.</p><button type="button" data-try-companion>Try a second view</button> <a href="/feeds">Create a personal feed</a> · <a href="/help">What can I do here?</a> <button type="button" data-dismiss-intro>Got it</button>';
    intro.querySelector('[data-dismiss-intro]').onclick=()=>{help.welcomeDismissed=true;rememberHelp();intro.remove();};
    intro.querySelector('[data-try-companion]').onclick=()=>{state=transition(state,{type:'secondary',source:'/community'});render();};
    initial.prepend(intro);
  }
  decorate(initial,state.primary);
  primarySelect.addEventListener('change',()=>{state=transition(state,{type:'primary',source:primarySelect.value});history.replaceState(null,'',state.primary);render();});
  secondarySelect.addEventListener('change',()=>{state=transition(state,{type:'secondary',source:secondarySelect.value||null});render();});
  mode.addEventListener('change',()=>{state=transition(state,{type:'mode',mode:mode.value});render();});
  main.querySelector('#dismiss-context').addEventListener('click',()=>{state=transition(state,{type:'dismiss'});render().then(()=>{if(!state.secondary)primary.focus({preventScroll:true});});});
  main.querySelector('#close-companion').addEventListener('click',()=>{state=transition(state,state.context?{type:'dismiss'}:{type:'secondary',source:null});render().then(()=>{if(!state.secondary)primary.focus({preventScroll:true});});});
  document.addEventListener('submit',e=>{if(['/signout','/disconnect'].includes(new URL(e.target.action).pathname)){for(const p of panes.values())p.cache.clear();}});
  async function quiet(node,uri,action,root){
    const feed=node.querySelector('.feed-surface')?.dataset.feedKey;if(!feed)return;
    const form=new URLSearchParams({csrf,feed,uri,action,...(root?{root}:{})});
    const r=await fetch('/local-quiet',{method:'POST',body:form,headers:{Accept:'application/json'}});if(!r.ok)throw Error('Could not change this conversation. No result has been assumed.');const result=await r.json();
    for(const p of panes.values())for(const v of p.cache.values()){const surface=v.node.querySelector('.feed-surface');if(surface?.dataset.feedKey===feed){surface.querySelectorAll('.following-feed > article[data-post-uri]').forEach(post=>{if((post.dataset.threadRoot||post.dataset.postUri)===result.root)post.hidden=result.quiet;});markAttentionStale(surface);}}
    announce(action==='quiet'?'Conversation quieted in this feed. Bluesky notifications unchanged.':'Conversation restored in this feed.');
    if(action==='quiet'){const undo=document.createElement('button');undo.type='button';undo.textContent='Undo';undo.onclick=()=>quiet(node,uri,'restore',result.root).catch(e=>announce(e.message));status.append(undo);}
    else { // Refresh only when this view did not retain the hidden row (e.g. after reload).
      const p=[...panes.entries()].find(([,p])=>p.cache.get(p.key)?.node===node);
      if(p&&!node.querySelector(`[data-post-uri="${CSS.escape(result.root)}"]`))await show(p[0],p[1].key,true);
    }
  }
  main.addEventListener('click',async e=>{
    const button=e.target.closest('button[data-local-quiet],button[data-restore-root]');
    if(button){button.disabled=true;try{await quiet(button.closest('.workspace-view'),button.dataset.localQuiet||button.dataset.restoreRoot,button.dataset.restoreRoot?'restore':'quiet',button.dataset.restoreRoot);}catch(error){announce(error.message);}finally{button.disabled=false;}return;}
    const link=e.target.closest('a');if(!link||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0)return;const url=new URL(link.href);if(url.origin!==location.origin)return;
    const pane=link.closest('.workspace-primary,.companion-content');if(!pane)return;
    if(['/thread','/context'].includes(url.pathname)||url.pathname.startsWith('/d/')){e.preventDefault();state=transition(state,{type:'inspect',source:url.pathname+url.search});await render();secondary.focus({preventScroll:true});if(!help.threadTipSeen){announce('Back to companion returns to the view you were reading.');help.threadTipSeen=true;rememberHelp();}return;}
    if(link.closest('.feed-next')){e.preventDefault();const p=panes.get(pane),view=p.cache.get(p.key);if(view.loadingMore)return;if(view.pages>=4){announce('This view has reached its reading limit. Refresh to start a new page set.');return;}view.loadingMore=true;link.setAttribute('aria-disabled','true');try{const next=await fragment(url.pathname+url.search);const feed=next.querySelector('.following-feed');if(!feed)throw Error('Next page unavailable.');const current=view.node.querySelector('.following-feed');const seen=new Set([...current.querySelectorAll(':scope > article')].map(x=>x.dataset.postUri));let context=null;for(const child of [...feed.children]){if(child.matches('.feed-context')){context=child;continue;}if(child.dataset.postUri&&seen.has(child.dataset.postUri)){context=null;continue;}if(context){current.append(context);context=null;}current.append(child);if(child.dataset.postUri)seen.add(child.dataset.postUri);}link.closest('.feed-next').replaceWith(next.querySelector('.feed-next')||document.createTextNode(''));view.pages++;decorate(view.node,p.key);}catch(error){announce(error.message);link.removeAttribute('aria-disabled');}finally{view.loadingMore=false;}return;}
    if(link.closest('.pages')) { e.preventDefault();const p=panes.get(pane),key=p.key,serial=++p.serial;try {const node=await fragment('/community'+url.search);if(p.serial!==serial)return;p.cache.set(key,{node,scroll:0,pages:1});p.key=null;await show(pane,key);}catch(error){announce(error.message);}return; }
    if(link.classList.contains('feed-refresh')){e.preventDefault();await show(pane,panes.get(pane).key,true);}
  });
  document.querySelector('header nav[aria-label="Main"]')?.addEventListener('click', e => {
    const a=e.target.closest('a'); if(!a||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0)return;
    const target=new URL(a.href);const href=target.pathname+target.search;
    if(target.origin===location.origin&&valid.has(href)) {e.preventDefault();state=transition(state,{type:'primary',source:href});history.replaceState(null,'',href);render();}
  });
  await render();
}
