"""The dashboard's own stylesheet and page scripts (the report's shared CSS and JS live in web/report/styles.py and web/report/scripts.py)."""




DASH_CSS = """
.cols2{gap:22px}
.libtools input[type=search]{padding:6px 14px;border:var(--line-w) solid var(--ink);border-radius:999px}
a.sk{transition:transform var(--t-fast) var(--ease),box-shadow var(--t-fast) var(--ease)}
a.sk:hover{transform:translate(-2px,-2px);box-shadow:5px 6px 0 var(--shadow)}
.seg .chip:is(:hover,.on) b{color:inherit}
.sk.reg:hover{box-shadow:none}
.ask{border:var(--line-w) solid var(--ink)}
table.sbs th{font:600 12px var(--sans)}
table.sbs td.gap{background:var(--chip)}
.decide{border:var(--line-w) solid var(--ink)}
.btn.danger:hover{background:var(--ink);color:var(--page)}
table.sbs th{font:500 11px/1.45 var(--mono)}
/* overview: look only (the layout is in layout.py, between "overview" and "end overview") */
.answer{box-shadow:10px 12px 0 var(--shadow);margin:0 10px 14px 0}
.tband{fill:color-mix(in oklch,var(--mark) 24%,transparent)}
.privacy b{font:600 11px var(--mono);letter-spacing:.08em}
.segctl{border-radius:var(--r-btn)}
/* end overview */
.state{font-size:11px}
.st .pill,.state{font-weight:500}
.movers th{font-weight:500}
.libtools input[type=search]{font-family:var(--mono);font-size:12px;font-weight:400}
/* optimize page: tables scroll in their own wrapper, long evidence wraps, a failed check reads as one */
ul.plain li.bad{color:var(--fail)}
.badge.ver.ok{color:var(--pass)}
.badge.ver.warn{color:var(--agent-ink)}
a.badge.ver{text-decoration:none}
.card pre.src{max-height:240px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
.card li,.card dd{overflow-wrap:anywhere}
.card textarea{width:100%;max-width:100%;box-sizing:border-box}
#opt-est{margin:8px 0}
"""

LIB_JS = """
// library: find by name or description, show installed skills on request, rendered or source view
const libFind=document.getElementById('lib-find'),libInst=document.getElementById('lib-inst'),libDead=document.getElementById('lib-dead');
function libFilter(){const q=(libFind?.value||'').trim().toLowerCase(),all=libInst?.checked;let shown=0;
  document.querySelectorAll('a.sk').forEach(a=>{const ok=(all||a.dataset.origin==='mine')&&(!libDead?.checked||a.dataset.unused==='1')&&(!q||a.dataset.find.includes(q));a.hidden=!ok;shown+=ok});
  document.querySelectorAll('.libgroup').forEach(g=>g.hidden=!g.querySelector('a.sk:not([hidden])'));
  const none=document.getElementById('lib-none');if(none)none.hidden=shown>0}
let vHash=null;try{vHash=location.hash.startsWith('#v-')&&document.querySelector(`a.sk[data-dir="${CSS.escape(decodeURIComponent(location.hash.slice(3)))}"]`)}catch(_){}  // a malformed hash: stay on the list
if(vHash)location.replace(vHash.href+location.hash);
libFind?.addEventListener('input',libFilter);libInst?.addEventListener('change',libFilter);libDead?.addEventListener('change',libFilter);if(libFind)libFilter();
document.getElementById('lib-sort')?.addEventListener('change',e=>{const by=e.target.value;
  document.querySelectorAll('.libgrid').forEach(g=>[...g.children].sort((a,b)=>by?(+b.dataset[by])-(+a.dataset[by])||a.dataset.find.localeCompare(b.dataset.find)
    :a.dataset.find.localeCompare(b.dataset.find)).forEach(a=>g.append(a)))});
document.getElementById('ste-adv')?.addEventListener('change',e=>document.querySelectorAll('ol.ste li.adv').forEach(li=>li.hidden=!e.target.checked));
document.querySelectorAll('[data-goto]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();
  document.querySelector('[data-view=src]')?.click();const ln=document.getElementById(a.dataset.goto);if(!ln)return;
  document.querySelectorAll('.ln.hit').forEach(x=>x.classList.remove('hit'));ln.classList.add('hit');ln.scrollIntoView({block:'center'})}));
// optimize: start a run, follow it, apply or discard it; every write carries the token of this page
const token=document.querySelector('meta[name=tokscope-token]')?.content||'';
async function send(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Tokscope-Token':token},
  body:JSON.stringify(body||{})});const j=await r.json().catch(()=>({error:'no answer'}));if(!r.ok)throw new Error(j.error||r.status);return j}
function showErr(e){const el=document.getElementById('opt-err');if(el){el.textContent=e.message;el.hidden=false}}
// a question on the page, not confirm(): some browsers (an editor's built-in one) block dialogs, and confirm() then says no at once
function ask(anchor,text,ok='OK'){return new Promise(res=>{document.querySelector('.ask')?.remove();const box=el('div','ask');
  box.setAttribute('role','alertdialog');const y=el('button','primary',ok),n=el('button','btn','Cancel'),acts=el('span','acts');y.type=n.type='button';
  const esc=e=>{if(e.key==='Escape')done(false)},done=v=>{box.remove();document.removeEventListener('keydown',esc);res(v)};
  y.addEventListener('click',()=>done(true));n.addEventListener('click',()=>done(false));document.addEventListener('keydown',esc);
  acts.append(y,n);box.append(el('p','',text),acts);anchor.after(box);box.scrollIntoView({block:'nearest'});y.focus()})}
function busy(b,text){b.dataset.label=b.textContent;b.disabled=true;b.classList.add('busy');b.textContent=text}
function idle(b){b.disabled=false;b.classList.remove('busy');b.textContent=b.dataset.label||b.textContent}
document.getElementById('mcp-check')?.addEventListener('click',async e=>{const b=e.target,when=document.getElementById('mcp-when');
  b.disabled=true;when.textContent='Checking… this can take a minute.';
  try{await send(`/api/projects/${document.getElementById('mcp').dataset.project}/health`);location.reload()}
  catch(err){showErr(err);b.disabled=false;when.textContent='The check failed.'}});
const mcpCard=document.getElementById('mcp'),mf=document.getElementById('mcp-form');
function mcpKind(){const k=mf.transport.value==='stdio'?'stdio':'http';mf.querySelectorAll('[data-for]').forEach(d=>d.hidden=d.dataset.for!==k);
  document.getElementById('mcp-pair').textContent=k==='stdio'?'+ Environment variable':'+ Header'}
function addPair(key='',value='',hint='',title='',secret=true){const d=document.createElement('div');d.className='pair';d.innerHTML='<input placeholder="NAME" aria-label="Name">'+
  '<input type="password" placeholder="value or ${VAR}" aria-label="Value" autocomplete="off"><button type="button" class="btn">Remove</button>';
  const [k,v]=d.querySelectorAll('input');k.value=key;v.value=value;if(!secret)v.type='text';if(hint)v.placeholder=hint;if(title)d.title=title;
  d.querySelector('button').addEventListener('click',()=>d.remove());document.getElementById('mcp-pairs').append(d)}
// registry: results are drawn with textContent only, since every field comes from a public catalog
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e}
function useOption(s,o){const add=document.getElementById('mcp-add');add.open=true;mf.elements['name'].value=s.name;
  mf.transport.value=o.transport==='stdio'?'stdio':o.transport;mcpKind();mf.command.value=o.command||'';mf.args.value=(o.args||[]).join('\\n');
  mf.url.value=o.url||'';document.getElementById('mcp-pairs').replaceChildren();
  (o.pairs||[]).forEach(p=>addPair(p.key,p.value,p.secret?'${'+p.key+'}':(p.required?'required':'optional'),p.description,p.secret));
  add.scrollIntoView({block:'start',behavior:smoothOk()?'smooth':'auto'});mf.elements['name'].focus()}
document.getElementById('reg-form')?.addEventListener('submit',async e=>{e.preventDefault();const out=document.getElementById('reg-results'),
  err=document.getElementById('reg-err'),b=e.target.querySelector('button');err.hidden=true;b.disabled=true;out.replaceChildren(el('p','note','Searching… the registry can take up to 30 seconds.'));
  try{const r=await fetch('/api/registry?q='+encodeURIComponent(e.target.q.value));const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);
    out.replaceChildren();if(!j.length)out.append(el('p','note','No server this form can install matches. Try another word.'));
    j.forEach(s=>{const c=el('div','sk reg');const h=el('b','',s.title);c.append(h,el('span','note',s.id+(s.version?' · '+s.version:'')),el('p','',s.description));
      const links=el('span','meta');[['repository',s.repository],['website',s.website]].forEach(([t,u])=>{if(u&&u.startsWith('https://')){
        const a=el('a','',t);a.href=u;a.target='_blank';a.rel='noopener noreferrer';links.append(a,' ')}});c.append(links);
      const acts=el('span','acts');s.options.forEach(o=>{const u=el('button','btn','Use '+o.label);u.type='button';
        u.addEventListener('click',()=>useOption(s,o));acts.append(u)});c.append(acts);out.append(c)})}
  catch(x){out.replaceChildren();err.textContent=x.message;err.hidden=false}finally{b.disabled=false}});
if(mf){mf.transport.addEventListener('change',mcpKind);mcpKind();document.getElementById('mcp-pair').addEventListener('click',()=>addPair());
  mf.addEventListener('submit',async e=>{e.preventDefault();const err=document.getElementById('mcp-err');err.hidden=true;
    const pairs=[...mf.querySelectorAll('.pair')].map(d=>({key:d.children[0].value.trim(),value:d.children[1].value})).filter(x=>x.key);
    const hole=mf.args.value.split('\\n').find(a=>/^<[^>]+>$/.test(a.trim()));
    if(hole){err.textContent=`Replace ${hole.trim()} in the arguments with a real value.`;err.hidden=false;return}
    const sub=mf.querySelector('button[type=submit]');
    if(mf.scope.value==='project'&&pairs.some(x=>x.value&&!x.value.includes('${'))&&
      !await ask(sub.parentElement,'A value is not a ${VAR} reference. It will be written into .mcp.json, which is usually committed. Continue?','Write it'))return;
    busy(sub,'Adding…');
    const body={name:mf.elements['name'].value,scope:mf.scope.value,transport:mf.transport.value,command:mf.command.value,
      args:mf.args.value.split('\\n'),url:mf.url.value,pairs};
    try{await send(`/api/projects/${mcpCard.dataset.project}/mcp`,body);location.reload()}
    catch(x){err.textContent=x.message;err.hidden=false;idle(sub)}})}
document.querySelectorAll('[data-mcp-remove]').forEach(b=>b.addEventListener('click',async()=>{
  if(!await ask(document.querySelector('#mcp .acts'),`Remove ${b.dataset.mcpRemove} from the ${b.dataset.scope} scope?`,'Remove'))return;
  busy(b,'Removing…');
  try{await send(`/api/projects/${mcpCard.dataset.project}/mcp/remove`,{name:b.dataset.mcpRemove,scope:b.dataset.scope});location.reload()}
  catch(x){showErr(x);idle(b)}}));
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('[data-pane]').forEach(p=>p.hidden=p.dataset.pane!==b.dataset.view)}));
"""

OPT_JS = """
// optimize page: approve or reject a run (LIB_JS's send, ask, busy and idle carry this page's token)
const decideEl=document.getElementById('decide');
if(decideEl){const reason=document.getElementById('opt-reason'),ok=decideEl.querySelector('[data-opt-act=approve]'),
    syncOk=()=>{if(ok&&!ok.dataset.block)ok.disabled=decideEl.dataset.need==='1'&&!reason.value.trim()};
  reason.addEventListener('input',syncOk);
  decideEl.querySelectorAll('[data-opt-act]').forEach(b=>b.addEventListener('click',async()=>{const act=b.dataset.optAct,all=decideEl.querySelectorAll('[data-opt-act]');
    if(act==='approve'&&!await ask(b.parentElement,'Write the draft into the skill folder? tokscope keeps the old version and commits only the skill\\'s files when it is in git.','Approve'))return;
    busy(b,act==='approve'?'Approving…':'Rejecting…');all.forEach(x=>x.disabled=true);
    try{await send(`/optimize/${decideEl.dataset.run}/${act}`,{reason:reason.value});location.reload()}
    catch(err){showErr(err);all.forEach(x=>{x.disabled=!!x.dataset.block});idle(b);syncOk()}}))}
// library: ask for the estimate of an optimize run, then for a confirm; the server starts the worker only after the confirm
const startEl=document.getElementById('optstart');
if(startEl){const est=document.getElementById('opt-est'),err=document.getElementById('optstart-err'),go=startEl.querySelector('button[type=submit]'),
    fail=e=>{err.textContent=e.message;err.hidden=false};
  const body=()=>({skill:startEl.dataset.skill,budget:+startEl.budget.value,runs:+startEl.runs.value,model:startEl.model.value.trim()});
  startEl.addEventListener('input',()=>{est.hidden=true;est.replaceChildren();go.hidden=false});
  startEl.addEventListener('submit',async e=>{e.preventDefault();err.hidden=true;busy(go,'Counting…');
    try{const j=await send('/optimize/start',body());est.replaceChildren(...j.estimate.lines.map(t=>el('p','note',t)));
      const ok=el('button','primary','Start the run');ok.type='button';est.append(ok);est.hidden=false;go.hidden=true;
      ok.addEventListener('click',async()=>{busy(ok,'Starting…');
        try{const r=await send('/optimize/start',{...body(),confirm:true});location.href=r.url}catch(x){fail(x);idle(ok)}})}
    catch(x){fail(x)}finally{idle(go)}})}
"""

SETTINGS_JS = """
// settings: the Background service card; LIB_JS's send() carries this page's token. Stop may end this very page (when the
// service serves it), so a stop that gets no answer counts as done.
(()=>{const err=document.getElementById('svc-err');
  const fail=m=>{if(err){err.textContent=m;err.hidden=false}};
  const act=async(path,body,b)=>{if(err)err.hidden=true;if(b)busy(b,'Working…');
    try{await send(path,body);location.reload()}
    catch(e){if(b)idle(b);
      if(path.endsWith('/stop')&&e instanceof TypeError){document.getElementById('svc-state').textContent='Stopped';
        fail('The service stopped, and this page was served by it. Start it again with: tokscope service install');return}
      fail(e.message);const box=document.getElementById('svc-auto-box');if(box&&path.endsWith('/autostart'))box.checked=!body.on}};
  document.querySelectorAll('[data-svc]').forEach(b=>b.addEventListener('click',async()=>{const a=b.dataset.svc;
    if(a==='stop'&&!await ask(b.closest('.setrow'),'Stop the background service? If this dashboard is served by it, this page stops answering until you start it again.','Stop'))return;
    act('/api/service/'+a,{},b)}));
  document.getElementById('svc-auto-box')?.addEventListener('change',e=>act('/api/service/autostart',{on:e.target.checked}))})();
"""

MANAGED_JS = """
// managed: pause or unpause a deployment after a question on the page; LIB_JS's send() carries this page's token
document.querySelectorAll('[data-dep-act]').forEach(b=>b.addEventListener('click',async()=>{const act=b.dataset.depAct,pause=act==='pause';
  const err=document.getElementById('dep-err');if(err)err.hidden=true;
  if(!await ask(b.closest('table'),pause?`Pause ${b.dataset.name}? Scheduled runs stop until you unpause it; sessions already running go on.`
    :`Unpause ${b.dataset.name}? It runs again from its next scheduled time; runs missed while paused are not made up.`,pause?'Pause':'Unpause'))return;
  busy(b,pause?'Pausing…':'Unpausing…');
  try{await send(`/api/managed/deployments/${act}`,{id:b.dataset.dep});location.reload()}
  catch(e){idle(b);if(err){err.textContent=e.message;err.hidden=false}}}));
"""

DASH_JS = """
// A page takes a moment to render (the Overview reads the whole range): from a click on a link or Apply until the next
// page arrives, a bar runs along the top and the page dims. Quick pages (under 150 ms) show nothing.
(()=>{const bar=document.createElement('div');bar.id='navload';bar.setAttribute('aria-hidden','true');bar.innerHTML='<i></i>';document.body.appendChild(bar);
  let t,off;const on=()=>{clearTimeout(t);clearTimeout(off);t=setTimeout(()=>root.classList.add('loading'),150);
    off=setTimeout(()=>root.classList.remove('loading'),15000)};  // a cancelled navigation (Esc, Stop) never says so: give up after 15 s
  addEventListener('pageshow',()=>{clearTimeout(t);clearTimeout(off);root.classList.remove('loading')});
  document.addEventListener('click',e=>{const a=e.target.closest&&e.target.closest('a[href]');
    if(!a||typeof a.href!=='string'||e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||(a.target&&a.target!=='_self')||a.hasAttribute('download'))return;
    const u=new URL(a.href,location.href);
    if(u.origin===location.origin&&u.pathname+u.search!==location.pathname+location.search&&!u.pathname.startsWith('/api/'))on()});
  document.addEventListener('submit',e=>{if(e.target.matches('form.filters'))on()});
  window.tokscopeNavLoad=on})();
// Apply keeps only the filters set, so the URL reads like the view (range=30 is the default)
document.querySelectorAll('form.filters').forEach(fm=>fm.addEventListener('submit',e=>{e.preventDefault();const q=new URLSearchParams();
  fm.querySelectorAll('select').forEach(x=>{if(x.value&&!(x.name==='range'&&x.value==='30'))q.set(x.name,x.value)});
  location.href=fm.getAttribute('action')+(q.toString()?'?'+q:'')}));
// a changed select applies at once, so the Apply button is hidden when scripts run
document.querySelectorAll('form.filters select').forEach(x=>x.addEventListener('change',()=>x.form.requestSubmit()));
// phone menu: the Menu button and the filter pill open one sheet. While it is open the page behind is inert, focus moves
// into the sheet and wraps there, Escape closes it, and focus goes back to the control that opened it
(()=>{const sheet=document.getElementById('sheet'),bar=document.getElementById('menu-btn'),main=document.querySelector('main'),
  ctl=[...document.querySelectorAll('[aria-controls=sheet]')],phone=matchMedia('(max-width:639px)');let back=null,selOpen=false;
  if(!sheet||!bar)return;
  const focusable=()=>[bar,...sheet.querySelectorAll('a[href],button,select,input,[tabindex]:not([tabindex="-1"])')].filter(e=>!e.disabled&&e.getClientRects().length);
  const set=on=>{sheet.classList.toggle('open',on);document.documentElement.classList.toggle('menu-open',on);ctl.forEach(b=>b.setAttribute('aria-expanded',on));
    main.inert=on;if(on){sheet.setAttribute('role','dialog');sheet.setAttribute('aria-modal','true');sheet.setAttribute('aria-label','Menu')}
    else['role','aria-modal','aria-label'].forEach(a=>sheet.removeAttribute(a))};
  const open=from=>{back=from;set(true);requestAnimationFrame(()=>(sheet.querySelector('.toc a.on')||sheet.querySelector('a,button')).focus())};
  const close=(restore=true)=>{if(!sheet.classList.contains('open'))return;set(false);if(restore&&back)back.focus();back=null};
  ctl.forEach(b=>b.addEventListener('click',()=>sheet.classList.contains('open')?close():open(b)));
  // a native select popup and the shortcuts dialog handle Escape and Tab themselves; the sheet leaves them alone
  sheet.querySelectorAll('select').forEach(x=>{x.addEventListener('mousedown',()=>{selOpen=!selOpen});x.addEventListener('blur',()=>{selOpen=false});
    x.addEventListener('change',()=>{selOpen=false});
    x.addEventListener('keydown',e=>{if(e.key===' '||e.key==='Enter'||(e.altKey&&e.key.startsWith('Arrow')))selOpen=true})});
  document.addEventListener('keydown',e=>{if(!sheet.classList.contains('open'))return;
    if(e.target.closest&&e.target.closest('dialog')||document.querySelector('dialog[open]'))return;
    if(e.key==='Escape'){if(selOpen&&e.target.tagName==='SELECT'){selOpen=false;return}e.preventDefault();close()}
    else if(e.key==='Tab'){const f=focusable(),i=f.indexOf(document.activeElement);
      if(e.shiftKey&&i<=0){e.preventDefault();f[f.length-1].focus()}else if(!e.shiftKey&&(i<0||i===f.length-1)){e.preventDefault();f[0].focus()}}});
  // 639px is the phone block's max-width in layout.py; a window widened past it closes the sheet and leaves focus alone
  phone.addEventListener('change',e=>{if(!e.matches)close(false)})})();
const freshEl=document.getElementById('fresh'),page=document.body.dataset.page;let stamp=document.body.dataset.stamp,seenAt=Date.now();
const ago=t=>{const s=Math.round((Date.now()-t)/1000);return s<60?'just now':s<3600?Math.round(s/60)+' min ago':Math.round(s/3600)+' h ago'};
let ingestErr=null;
function fresh(ok){freshEl.classList.toggle('stale',!ok||!!ingestErr);document.body.classList.toggle('offline',!ok);freshEl.title=ingestErr?'last ingest failed: '+ingestErr:'';freshEl.lastChild.textContent=!ok?' offline · '+ago(seenAt):ingestErr?' live · last ingest failed: '+ingestErr.slice(0,80):' live · updated '+ago(seenAt)}
// a live value changes at once; a chip beside it says by how much for 2 s (in --t-state, out 0.7 times that), in every motion setting
const CHIP_MS=2000,CHIP_OUT_MS=140;
function deltaChip(el,from){const to=+el.dataset.count,d=to-from;if(!d)return;
  const f={int:v=>Math.round(v).toLocaleString('en-US'),tok:fmt,pct:v=>Math.round(v)+'%',
    usd:v=>'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}[el.dataset.kind]||fmt;
  const host=el.closest('.kpi,.today-nums>div');if(!host)return;host.querySelectorAll('.dchip').forEach(c=>c.remove());
  const c=document.createElement('small');c.className='dchip';c.textContent=(d>0?'+':'\u2212')+f(Math.abs(d));
  c.setAttribute('aria-hidden','true');(el.closest('.today-nums')?el.after(c):host.append(c));
  setTimeout(()=>c.classList.add('out'),CHIP_MS-CHIP_OUT_MS);setTimeout(()=>c.remove(),CHIP_MS)}
// the live dot gives one ring when a poll finds new data (never a loop)
function ring(){document.querySelectorAll('.fresh .dot,h2>.dot').forEach(d=>{d.classList.remove('ring');void d.offsetWidth;d.classList.add('ring');
  setTimeout(()=>d.classList.remove('ring'),700)})}
// overview: swap each region for its new render and show a delta chip on the numbers; other pages offer a reload
async function refresh(){document.documentElement.classList.add('settled');const url=location.pathname+location.search+(location.search?'&':'?')+'partial=1';
  const doc=new DOMParser().parseFromString(await (await fetch(url)).text(),'text/html');
  tzSync(doc);  // the fetched page has UTC text; format it the way the live one is, so an unchanged region compares equal
  document.querySelectorAll('[data-region]').forEach(r=>{const next=doc.querySelector(`[data-region="${r.dataset.region}"]`);if(!next||next.innerHTML===r.innerHTML)return;
    const old={};r.querySelectorAll('[data-key]').forEach(el=>old[el.dataset.key]=+el.dataset.count);
    r.innerHTML=next.innerHTML;bindTips(r);r.querySelectorAll('[data-key]').forEach(el=>{if(el.dataset.key in old)deltaChip(el,old[el.dataset.key])})})}
function offerReload(){if(document.getElementById('newdata'))return;const b=document.createElement('button');b.id='newdata';b.className='primary';
  b.textContent='New data · reload';b.addEventListener('click',()=>{window.tokscopeNavLoad&&tokscopeNavLoad();location.reload()});document.body.append(b)}
// sessions page: tag the rows of sessions that are open (running = working, open = waiting for you), every poll
async function syncLive(){if(page!=='sessions')return;window.LIVE=await (await fetch('/api/live')).json();window.paintLive()}
let liveSig=null;syncLive().catch(()=>{});
async function poll(){if(document.hidden)return;
  try{const j=await (await fetch('/api/version')).json();seenAt=Date.now();ingestErr=j.error||null;
    const changed=j.stamp!==stamp,moved=liveSig!==null&&j.live!==liveSig;liveSig=j.live;
    if(changed||(moved&&page==='overview')){stamp=j.stamp;page==='overview'?await refresh():offerReload();ring()}
    if(moved||changed)syncLive();fresh(true)}catch(_){fresh(false)}}
setInterval(poll,2000);setInterval(()=>fresh(!freshEl.classList.contains('stale')),30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
"""
