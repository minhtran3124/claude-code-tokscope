"""The page scripts the report and the dashboard share: core, sessions list, table of contents, trend, benchmarks."""


JS_CORE = """
const tip=document.getElementById('tip');
function bindTips(root){root.querySelectorAll('[data-tip]').forEach(el=>{
  el.addEventListener('mousemove',e=>{tip.innerHTML=el.dataset.tip;tip.classList.add('on');
    tip.style.left=Math.min(e.clientX+12,innerWidth-330)+'px';tip.style.top=(e.clientY+12)+'px'});
  el.addEventListener('mouseleave',()=>tip.classList.remove('on'))})}
bindTips(document);
const fmt=v=>{v=v||0;for(const[u,d]of[['B',1e9],['M',1e6],['K',1e3]])if(v>=d)return(v/d).toFixed(1)+u;return String(Math.round(v))};
const usd=v=>v==null?'–':'$'+v.toFixed(2);
const smoothOk=()=>!matchMedia('(prefers-reduced-motion: reduce)').matches;
const toastEl=document.getElementById('toast');let toastT;
function toast(msg){toastEl.textContent=msg;toastEl.classList.add('on');clearTimeout(toastT);toastT=setTimeout(()=>toastEl.classList.remove('on'),1600)}
// counts each KPI up from zero; the last frame writes back the exact server-rendered text
// a restart keeps the first exact text and stops the older run, so reopening a session mid-count is safe
function countUp(el,delay,dur=1200){const end=el.dataset.end??(el.dataset.end=el.textContent),raw=+el.dataset.count;if(!raw||!smoothOk())return;
  const f={int:v=>Math.round(v).toLocaleString('en-US'),tok:fmt,pct:v=>Math.round(v)+'%',
    usd:v=>v>=1e4?'$'+(v/1e3).toFixed(1)+'K':'$'+v.toLocaleString('en-US',v>=1e3?{maximumFractionDigits:0}:{minimumFractionDigits:2,maximumFractionDigits:2})}[el.dataset.kind]||fmt;
  const run=el._run=(el._run||0)+1;
  el.textContent=f(0);setTimeout(()=>{const t0=performance.now();const step=now=>{if(el._run!==run)return;const p=Math.min(1,Math.max(0,(now-t0)/dur));
    el.textContent=p<1?f(raw*(1-Math.pow(1-p,4))):end;if(p<1)requestAnimationFrame(step)};requestAnimationFrame(step)},delay)}
// a live value (data-key, on the dashboard) shows its real number at once; the count-up is for the static report and the rows you open
document.querySelectorAll('[data-count]:not([data-key])').forEach((el,k)=>countUp(el,150+k*70));
// the entrances belong to the first paint (CSS: `html.settled [data-region] ...` turns them off); a region that a poll swaps in must not replay them
setTimeout(()=>document.documentElement.classList.add('settled'),1500);
const root=document.documentElement;
const isDark=()=>root.dataset.theme?root.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
const themeBtn=document.getElementById('theme');
// the report has one Theme button; the dashboard has a segmented control (Light, Dark, Auto) with data-set-theme buttons
function syncTheme(){if(themeBtn)themeBtn.innerHTML=(isDark()?'☀ Light':'☾ Dark')+' <kbd>t</kbd>';
  document.querySelectorAll('[data-set-theme]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.setTheme===(root.dataset.theme||'auto')))}
function setTheme(mode){if(mode==='auto'){delete root.dataset.theme;try{localStorage.removeItem('tokscope-theme')}catch(_){}}
  else{root.dataset.theme=mode;try{localStorage.setItem('tokscope-theme',mode)}catch(_){}}syncTheme()}
// the new theme grows out of the button as a circle, where the browser has view transitions
function toggleTheme(x,y,mode){const apply=()=>setTheme(mode||(isDark()?'light':'dark'));
  if(!document.startViewTransition||!smoothOk())return apply();
  const r=Math.hypot(Math.max(x,innerWidth-x),Math.max(y,innerHeight-y));
  document.startViewTransition(apply).ready.then(()=>root.animate({clipPath:[`circle(0px at ${x}px ${y}px)`,`circle(${r}px at ${x}px ${y}px)`]},
    {duration:650,easing:'cubic-bezier(0.16,1,0.3,1)',pseudoElement:'::view-transition-new(root)'}))}
if(themeBtn)themeBtn.addEventListener('click',e=>{const b=themeBtn.getBoundingClientRect();toggleTheme(e.clientX||b.left+b.width/2,e.clientY||b.top+b.height/2)});
document.querySelectorAll('[data-set-theme]').forEach(btn=>btn.addEventListener('click',e=>{const b=btn.getBoundingClientRect();
  toggleTheme(e.clientX||b.left+b.width/2,e.clientY||b.top+b.height/2,btn.dataset.setTheme)}));syncTheme();
const io='IntersectionObserver' in window?new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{rootMargin:'0px 0px -6% 0px'}):null;
document.querySelectorAll('.reveal,main>details.more,#breakdowns>details').forEach(el=>{el.classList.add('reveal');io?io.observe(el):el.classList.add('in')});
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// Times: stored in UTC, shown in the browser's zone unless the Time zone setting is UTC (localStorage `tokscope-tz`).
// <time data-ts data-fmt="hm|dt|range" [data-end]> is rewritten by tzSync when the setting changes or a region is swapped in
let TZ='local';try{if(localStorage.getItem('tokscope-tz')==='utc')TZ='utc'}catch(_){}
const tzp=ts=>{const d=new Date(/(Z|[+-][0-9][0-9]:?[0-9][0-9])$/.test(ts)?ts:ts+'Z');
  if(TZ==='utc'||isNaN(d))return{day:ts.slice(0,10),hm:ts.slice(11,16)};
  const p=n=>String(n).padStart(2,'0');
  return{day:`${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`,hm:`${p(d.getHours())}:${p(d.getMinutes())}`}};
// the abbreviation depends on the date (PST or PDT), so it is taken at the timestamp shown
const tzName=ts=>TZ==='utc'?'UTC':((new Intl.DateTimeFormat('en',{timeZoneName:'short'}).formatToParts(ts?new Date(/(Z|[+-][0-9][0-9]:?[0-9][0-9])$/.test(ts)?ts:ts+'Z'):new Date()).find(x=>x.type==='timeZoneName')||{}).value||'local');
function tzText(ts,fmt,end){if(!ts)return'';const a=tzp(ts),z=tzName(ts);
  return fmt==='hm'?`${a.hm} ${z}`:fmt==='range'?`${a.day} ${a.hm} → ${end?tzp(end).hm:''} ${z}`:`${a.day} ${a.hm} ${z}`}
function tzSync(r){(r||document).querySelectorAll('time[data-ts]').forEach(el=>{el.textContent=tzText(el.dataset.ts,el.dataset.fmt,el.dataset.end)})}
function setTz(mode){TZ=mode==='utc'?'utc':'local';try{TZ==='utc'?localStorage.setItem('tokscope-tz','utc'):localStorage.removeItem('tokscope-tz')}catch(_){}
  document.querySelectorAll('[data-set-tz]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.setTz===TZ));
  tzSync();if(window.onTz)window.onTz()}
document.querySelectorAll('[data-set-tz]').forEach(b=>{b.addEventListener('click',()=>setTz(b.dataset.setTz));b.setAttribute('aria-pressed',b.dataset.setTz===TZ)});
tzSync();
// keyboard: t theme, g top, ? this list; pages add their own keys
const keysDlg=document.getElementById('keys');
addEventListener('keydown',e=>{const typing=/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
  if(typing||e.metaKey||e.ctrlKey||e.altKey)return;
  if(e.key==='t'){const el=themeBtn||document.querySelector('[data-set-theme]'),b=el?el.getBoundingClientRect():{left:innerWidth/2,top:innerHeight/2,width:0,height:0};toggleTheme(b.left+b.width/2,b.top+b.height/2)}
  else if(e.key==='g')scrollTo({top:0})
  else if(e.key==='?'){keysDlg.open?keysDlg.close():keysDlg.showModal()}});
const keysBtn=document.getElementById('keys-btn');if(keysBtn)keysBtn.addEventListener('click',()=>keysDlg.showModal());
keysDlg.addEventListener('click',e=>{if(e.target===keysDlg)keysDlg.close()});
"""
SORT_SEG = ('<span class="seg" id="s-sort" role="group" aria-label="Sort sessions">'
            '<button type="button" class="chip on" data-sort="recent" aria-pressed="true">Newest</button>'
            '<button type="button" class="chip" data-sort="tokens" aria-pressed="false">Most tokens</button>'
            '<button type="button" class="chip" data-sort="agents" aria-pressed="false">Most subagent</button></span>')
JS_SESSIONS = """
const S=JSON.parse(document.getElementById('sessions-data').textContent);
const list=document.getElementById('session-list'),q=document.getElementById('s-q'),projBox=document.getElementById('s-proj'),sortBox=document.getElementById('s-sort');
// sort is the segmented control SORT_SEG: Newest, Most tokens, Most subagent tokens
let sortKey='recent';
// durations come from the layout sheet's tokens, so the script and the stylesheet never disagree
const cssVar=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const T_LAYOUT=parseFloat(cssVar('--t-layout'))||320,T_EXIT=(parseFloat(cssVar('--t-state'))||200)*.7;
const picked=new Set();let limit=15;
// a headless session (claude -p) sits under the session whose Bash call started it, indented by depth
// only the dashboard serves /sessions; the static report keeps the parent's name as text
const DASH=!!document.body.dataset.page;
const byId=new Map(S.map(s=>[s.id,s])),kids=new Map(),openKids=new Set();
S.forEach(s=>{if(s.parent&&byId.has(s.parent)&&s.parent!==s.id){if(!kids.has(s.parent))kids.set(s.parent,[]);kids.get(s.parent).push(s)}});
kids.forEach(k=>k.sort((a,b)=>a.start.localeCompare(b.start)));
// a root has no parent in this range (a parent loop, which ingest never makes, counts as a root too)
const isRoot=s=>{const seen=new Set([s.id]);for(let p=byId.get(s.parent);p;p=byId.get(p.parent)){if(seen.has(p.id))return true;seen.add(p.id)}return !byId.has(s.parent)};
// wraps each match of the filter in <mark>, after escaping
const hl=(text,needle)=>{if(!needle)return esc(text);const lo=text.toLowerCase(),n=needle.toLowerCase();let out='',pos=0,at;
  while((at=lo.indexOf(n,pos))>-1){out+=esc(text.slice(pos,at))+'<mark>'+esc(text.slice(at,at+n.length))+'</mark>';pos=at+n.length}
  return out+esc(text.slice(pos))};
// the bar fills its cell and shows the share of the session's tokens in the main thread (indigo) and in subagents (teal);
// the size of the session is the number next to it, so a small session is as easy to read as a huge one
function split(main,ag){const t=Math.max(main+ag,1);
  return `<span class=track><span class=split title="main ${fmt(main)} · subagents ${fmt(ag)}"><u style="width:${(100*main/t).toFixed(1)}%"></u>${ag?`<u class=a style="width:${(100*ag/t).toFixed(1)}%"></u>`:''}</span></span>`}
// time of day when the list is by day; date and time when it is ranked
const when=s=>{if(!s.start)return'';const p=tzp(s.start);return sortKey==='recent'?p.hm:p.day.slice(5)+' '+p.hm};
// the dashboard fills LIVE from /api/live (open sessions: {id:{status,entry}}); the static report has none
const liveTag=id=>{const l=(window.LIVE||{})[id];return l?`<span class="live ${l.status==='busy'?'working':'open'}" title="${l.status==='busy'?'working now':'open, waiting for you'} · ${esc(l.entry)}"><i></i><span class=lbl>${l.status==='busy'?'running':'open'}</span><span class=where> · ${esc(l.entry)}</span></span>`:''};
window.paintLive=()=>document.querySelectorAll('#session-list .srow').forEach(d=>{const t=d.querySelector('.t'),old=t.querySelector('.live'),
  html=liveTag(d.dataset.id);if(!old&&!html)return;if(old)old.remove();if(html)t.querySelector('.tt').insertAdjacentHTML('afterend',html)});
// a skill name gets one of five tints, the same one everywhere (widgets.hue)
const hue=n=>{let h=0x811c9dc5;for(let i=0;i<n.length;i++)h=Math.imul(h^n.charCodeAt(i),0x01000193)>>>0;return h%5};
const chip=n=>n?`<span class="skc t${hue(n)}" title="${esc(n)}">${esc(n)}</span>`:'';
function row(s){
  const d=document.createElement('details');d.className='srow'+(picked.has(s.id)?' picked':'')+(s.parent&&!byId.has(s.parent)?' orphan':'');d.dataset.id=s.id;
  const by=s.parent_title||s.parent?.slice(0,8)||'',from=s.parent?`\nstarted by ${by}${byId.has(s.parent)?'':' (outside this range)'}`:'';
  // a parent outside the range has no row to sit under, so the child names it
  d.innerHTML=`<summary><input type=checkbox aria-label="compare" ${picked.has(s.id)?'checked':''}${s.only?' disabled':''}>
    <span class=d>${esc(when(s))}</span><span class="t${/^session [0-9a-f]{8}$/.test(s.title||'')?' sid':''}" title="${esc(s.title+from)}"><span class=tt>${s.title?hl(s.title,q.value.trim()):s.only?'':'(untitled)'}</span>${s.project?`<small class=pj>${esc(s.project)}</small>`:''}<small class=why hidden></small>${s.only?`<span class=tag title="${esc(s.tip)}">telemetry only</span>`:''}${liveTag(s.id)}${/^session [0-9a-f]{8}$/.test(s.title||'')?'':`<code class=sid8>${esc(s.id.slice(0,8))}</code>`}${s.parent&&!byId.has(s.parent)?`<small class=from>from ${DASH&&s.parent?`<a href="/sessions?range=all&amp;q=${encodeURIComponent(s.parent)}" title="show the session that started this one (all time)">${esc(by)}</a>`:esc(by)}</small>`:''}</span>
    <span class=sk>${chip(s.top_skill)}</span><span class="r n">${s.prompts}</span><span class="r n" title="${s.runs||0} subagent runs" aria-label="${s.runs||0} subagent runs">${s.runs||'–'}</span><span class=r><b>${fmt(s.tokens)}</b></span>${split(s.main,s.agents)}<span class=cv aria-hidden=true>›</span></summary><div class=body></div>`;
  const cb=d.querySelector('input');
  cb.addEventListener('click',e=>e.stopPropagation());
  cb.addEventListener('change',()=>{cb.checked?picked.add(s.id):picked.delete(s.id);if(picked.size>4){picked.delete(s.id);cb.checked=false}
    d.classList.toggle('picked',cb.checked);updatePick()});
  // every open replays the bars and the count-up, not only the first one that builds the body
  d.addEventListener('toggle',()=>{if(!d.open)return;const b=d.querySelector('.body');
    if(d.dataset.done)b.getAnimations({subtree:true}).forEach(a=>{a.cancel();a.play()});else{b.innerHTML=detail(s);d.dataset.done=1}
    b.querySelectorAll('[data-count]').forEach(el=>countUp(el,(+el.dataset.i||0)*25,700))});
  return d}
function bar(v,top,ag=0,i=0){const p=top?Math.max(1.5,100*v/top):0,a=v?p*ag/v:0;return `<span class=bar><span data-count="${v}" data-i="${i}">${fmt(v)}</span><i style="--i:${i}"><u style="width:${(p-a).toFixed(1)}%"></u>${a>0.5?`<u class=a style="width:${a.toFixed(1)}%"></u>`:''}</i></span>`}
// ids an agent can use to trace the session further
function ids(s){return `<dl class=ids>${[['Session ID',s.id],...(s.parent?[['Started by',s.parent]]:[]),['Trace',`tokscope session ${s.id} --json`],['Transcript',s.path],['Resume',`claude --resume ${s.id}`]]
  .map(([k,v])=>`<dt>${k}</dt><dd><span class=code>${esc(v)}</span><button type=button class="btn cp" data-copy="${esc(v)}">Copy</button></dd>`).join('')}</dl>`}
// one line per kind: agents (exact tokens + models), mcp servers and tools (~ estimated from result size)
// one line per subagent run (type, what it was asked, measured tokens, model, price); nested runs indented
function runLine(r){const d=r.desc||'(no description)';return `<div class=run style="--d:${Math.max(r.depth,1)-1}">
  <b class=rt>${r.depth>1?'↳ ':''}${esc(r.type)}</b><span class=rd title="${esc(d)}">${esc(d)}</span>
  <span class=est>${fmt(r.tokens)}</span><span class=usd>${esc(r.model)}${r.usd==null?'':' · '+usd(r.usd)}</span></div>`}
// the calls cell only sums the runs; each run gets a line in a full-width row under the turn
function runsSummary(runs){return runs.length?`<div class=cl><span class="ck agents">agents</span>${runs.length} run${runs.length>1?'s':''} <span class=est>${fmt(runs.reduce((a,r)=>a+r.tokens,0))}</span> <span class=usd>listed below</span></div>`:''}
function runsRow(runs){if(!runs.length)return'';const head=runs.slice(0,10).map(runLine).join(''),rest=runs.slice(10);
  return `<tr class=runs-row><td></td><td colspan=7><div class=runs>${head}${rest.length?`<details class=runs-more><summary>+${rest.length} more runs</summary>${rest.map(runLine).join('')}</details>`:''}</div></td></tr>`}
function callCell(t){
  const item=(k,[name,n,tk])=>esc(n>1?name+'×'+n:name)+(tk?` <span class=est>~${fmt(tk)}</span>`:'');
  const line=(k,items)=>items.length?`<div class=cl><span class="ck ${k}">${k}</span>${items.slice(0,6).map(c=>item(k,c)).join(' · ')}${items.length>6?` <span class=usd>+${items.length-6}</span>`:''}</div>`:'';
  return runsSummary(t.runs)+line('mcp',t.mcp)+line('tools',t.tools)||'<span class=usd>none</span>'}
function detail(s){
  if(s.only)return `<dl class=ids>${[['Session ID',s.id]].map(([k,v])=>`<dt>${k}</dt><dd><span class=code>${esc(v)}</span><button type=button class="btn cp" data-copy="${esc(v)}">Copy</button></dd>`).join('')}</dl>
    <p class=note><time data-ts="${esc(s.start)}" data-end="${esc(s.end)}" data-fmt=range>${esc(tzText(s.start,'range',s.end))}</time> · ${s.requests} request${s.requests===1?'':'s'}${s.models?' · '+esc(s.models):''} · output ${fmt(s.output)} · <span class=usd>${usd(s.usd)} by Claude Code</span></p>
    <p class=note><span class=tag>telemetry only</span> ${esc(s.tip)}.${s.unpriced?` ${s.unpriced} request${s.unpriced===1?'':'s'} sent no cost and have no list price, so count as $0.`:''} It is in no skill, agent or phase breakdown.</p>`;
  const top=Math.max(...s.turns.map(t=>t.tokens),1);
  const turns=s.turns.map((t,k)=>`<tr><td data-label="#">${t.i??'–'}</td><td class=l data-label="prompt">${esc(t.text||(t.i===0?'(session start)':''))}</td>
    <td class=lm data-label="skill">${chip(t.skill)}${t.version?` <code class=ver title="${t.version[1]?'exact: hashed at the Skill call':'inferred from the kept text or the date'} · tokscope skills ${esc(t.skill)}">${esc(t.version[0].slice(0,6))}</code>`:''}</td><td data-label="tokens">${bar(t.tokens,top,t.agents_tokens,Math.min(k,12))}</td><td data-label="output">${fmt(t.output)}</td>
    <td data-label="req">${t.requests}</td><td class="lm calls" data-label="calls">${callCell(t)}</td><td class=u data-label="API-eq">${usd(t.usd)}</td></tr>${runsRow(t.runs)}`).join('');
  return `${ids(s)}<p class=note><time data-ts="${esc(s.start)}" data-end="${esc(s.end)}" data-fmt=range>${esc(tzText(s.start,'range',s.end))}</time> · ${esc(s.project)} ·
    main thread <span data-count="${s.main}">${fmt(s.main)}</span> · subagents <span data-count="${s.agents}">${fmt(s.agents)}</span> (${s.runs} runs) · output <span data-count="${s.output}">${fmt(s.output)}</span> · <span class=usd>${usd(s.usd)} API-eq</span></p>
    <div class=scroll><table><tr><th>#</th><th style="text-align:left">prompt</th><th style="text-align:left">skill</th><th>tokens</th><th>output</th><th title="model requests">req</th><th style="text-align:left">calls</th><th>API-eq</th></tr>${turns}</table></div>
    <p class=note>calls: subagent tokens are measured; MCP and tool tokens marked ~ are estimated from the size of the result each call put into the context.</p>`}
// rows are kept by id so a re-render moves them (FLIP): kept rows slide from where they were,
// new rows rise in one after another, and rows that leave fade out in place
const nodes=new Map(),EXPO='cubic-bezier(0.16,1,0.3,1)';
// one root and the sessions under it, depth first. A filter keeps a match, the sessions under it, and the sessions
// above it (dimmed when they do not match). A parent shows 3 children until its "+N more" is pressed.
function group(root,match){const out=[],seen=new Set();
  const walk=(s,d,up)=>{if(seen.has(s.id))return false;seen.add(s.id);const me=match(s),at=out.length,e={s,d,dim:false};out.push(e);
    let down=false;const spans=[];
    (kids.get(s.id)||[]).forEach(k=>{const from=out.length;down=walk(k,d+1,up||me)||down;if(out.length>from)spans.push(from)});
    if(!(me||up||down)){out.splice(at);return false}
    if(spans.length>3){const open=openKids.has(s.id);if(!open)out.splice(spans[3]);out.push({more:s,n:spans.length-3,d:d+1,open})}
    e.dim=!(me||up);return me||down};
  walk(root,0,false);return out}
function moreBtn(e){let el=nodes.get('more:'+e.more.id);
  if(!el){el=document.createElement('button');el.type='button';el.className='btn kids-more';el.dataset.id='more:'+e.more.id;
    el.addEventListener('click',()=>{const id=e.more.id;openKids.has(id)?openKids.delete(id):openKids.add(id);render();el.focus({preventScroll:true})});nodes.set('more:'+e.more.id,el)}
  el.textContent=e.open?'Show fewer':`+${e.n} more started by this session`;el.setAttribute('aria-expanded',e.open?'true':'false');el.style.setProperty('--depth',e.d);return el}
// a session and everything it started, for the day header (a collapsed "+N more" still counts)
function tally(s,seen=new Set()){if(seen.has(s.id))return[0,0];seen.add(s.id);let n=1,t=s.tokens;
  (kids.get(s.id)||[]).forEach(k=>{const[a,b]=tally(k,seen);n+=a;t+=b});return[n,t]}
// days follow the time column: the day of s.start in the chosen zone (d is 'YYYY-MM-DD'); the date is only a label, so it is formatted in UTC
const dayOf=s=>s.start?tzp(s.start).day:'';
const dayName=d=>!d?'No date':new Date(d+'T00:00:00Z').toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
// a group ranks by its root session's own numbers: a parent's totals do not include the sessions it started (DECISIONS.md, 'Headless child sessions keep their own totals')
const SORTS={recent:['Newest first',(a,b)=>b[0].s.start.localeCompare(a[0].s.start)],tokens:['Most tokens first',(a,b)=>b[0].s.tokens-a[0].s.tokens],
  agents:['Most subagent tokens first',(a,b)=>b[0].s.agents-a[0].s.agents]};
function headEl(){const h=document.createElement('div');h.className='shead';
  h.innerHTML=`<span></span><span class=d title="${esc(tzName())}">time</span><span class=t>session</span><span class=sk>top skill</span><span class="r n">prompts</span><span class="r n" title="subagent runs started in the session">subagents</span><span class=r>tokens</span><span class=track title="share of the session's tokens: main thread and subagents">split</span><span></span>`;return h}
window.onTz=()=>render();
function dayEl(label,n,tk){const h=document.createElement('div');h.className='dayhd';
  h.innerHTML=`<b>${esc(label)}</b><span>${n} session${n===1?'':'s'} · ${fmt(tk)} tokens</span>`;return h}
// why a session matches the filter when its title, id or top skill do not: it ran in a folder whose path has the text
// ('in'), it started `claude -p` in one ('ran'), or one of its prompts names it ('says'). Returns [kind, label] or null.
// A redacted report keeps no path or prompt text, so only its placeholders are here and these never match a real name.
// the folder name that holds the text (the last one that does), else the last folder
const base=(p,n)=>{const f=p.replace(/\\/+$/,'').split('/');return(n&&[...f].reverse().find(x=>x.toLowerCase().includes(n)))||f.pop()};
// lower-cased copies of the searchable text, built once per session on first use (a keystroke then only runs `includes`).
// Kept in a WeakMap, not on the data, and rebuilt when the cheap signature changes (title, folders, turn count, last prompt),
// so a session edited in place is never searched by its old text.
const PLACEHOLDER=/^\\[prompt · \\d+ chars\\]$/,LC=new WeakMap();
const lc=s=>{const t=s.turns||[],sig=[s.title,s.cwd,(s.hdirs||[]).join('|'),t.length,t.length?t[t.length-1].text:''].join('|');let c=LC.get(s);
  if(c&&c.sig===sig)return c;
  c={sig,title:(s.title||'').toLowerCase(),cwd:(s.cwd||'').toLowerCase(),hdirs:(s.hdirs||[]).map(x=>x.toLowerCase()),
    prompts:t.map(x=>x.text||'').filter(x=>x&&!PLACEHOLDER.test(x)).join('\\n').toLowerCase()};LC.set(s,c);return c};
// the filter for one needle (trimmed, lower case): match(s) keeps a session, whyOf(s) is the chip text when only a folder or
// a prompt matched. Each session is judged once per needle.
function finder(n){const memo=new Map();
  const ev=s=>{let e=memo.get(s);if(e)return e;const c=lc(s);
    if(c.title.includes(n)||s.id.startsWith(n)||(s.top_skill||'').includes(n))e={w:null,ok:true};
    else{let w=null;
      if(c.cwd.includes(n))w=['in',base(s.cwd,n)||s.project];
      else{const i=c.hdirs.findIndex(x=>x.includes(n));
        if(i>-1)w=['ran',base(s.hdirs[i],n)||s.hdirs[i]];else if(c.prompts.includes(n))w=['says',n]}
      e={w,ok:!!w}}
    memo.set(s,e);return e};
  const text=w=>!w?'':w[0]==='in'?'in '+w[1]:w[0]==='ran'?'ran claude -p in '+w[1]:'mentions '+w[1];
  return{match:s=>!n||ev(s).ok,whyOf:s=>n?text(ev(s).w):''}}
function render(){
  // one trimmed needle for the match, the chip and the <mark> (a pasted trailing space still finds the folder)
  const {match:textMatch,whyOf}=finder(q.value.trim().toLowerCase());
  const proj=projBox?projBox.value:'',match=s=>(!proj||s.project===proj)&&textMatch(s);
  let rows=S.filter(isRoot).map(s=>group(s,match)).filter(g=>g.length);
  rows.sort(SORTS[sortKey][1]);
  // sessions with no start go last under Newest, so "No date" never sits between two days
  if(sortKey==='recent')rows.sort((a,b)=>!a[0].s.start-!b[0].s.start);
  const page=rows.slice(0,limit),shown=page.flat(),keep=new Set(shown.map(e=>e.s?e.s.id:'more:'+e.more.id)),anim=smoothOk(),before=new Map();
  let top=list.getBoundingClientRect().top;
  if(anim)list.querySelectorAll(':scope>.srow:not(.ghost),:scope>.kids-more').forEach(el=>{before.set(el.dataset.id,el.getBoundingClientRect().top-top);el.getAnimations().forEach(a=>a.cancel())});
  const rowFor=e=>{if(e.more)return moreBtn(e);const s=e.s;let el=nodes.get(s.id);
    if(!el){el=row(s);nodes.set(s.id,el)}
    else{el.getAnimations().forEach(a=>a.cancel());el.classList.remove('ghost');el.style.top='';
      el.querySelector('.tt').innerHTML=s.title?hl(s.title,q.value.trim()):s.only?'':'(untitled)';el.querySelector('.d').textContent=when(s);
      el.classList.toggle('picked',picked.has(s.id));el.querySelector('input').checked=picked.has(s.id)}
    const why=whyOf(s),chip=el.querySelector('.why');chip.textContent=why;chip.title=why;chip.hidden=!why;el.classList.toggle('has-why',!!why);
    el.classList.toggle('child',e.d>0);el.classList.toggle('dim',e.dim);el.style.setProperty('--depth',e.d);
    return el};
  // by day: a header for each day (all its sessions and tokens, also those past "Show more"), newest first. Ranked: one header, and the date moves into the time column.
  const els=[];
  if(page.length){els.push(headEl());
    if(sortKey==='recent'){let cur=null;page.forEach(g=>{const day=dayOf(g[0].s);
      if(day!==cur){cur=day;let n=0,tk=0;rows.forEach(r=>{if(dayOf(r[0].s)===day){const[a,b]=tally(r[0].s);n+=a;tk+=b}});els.push(dayEl(dayName(day),n,tk))}
      g.forEach(e=>els.push(rowFor(e)))})}
    else{let n=0,tk=0;rows.forEach(r=>{const[a,b]=tally(r[0].s);n+=a;tk+=b});els.push(dayEl(SORTS[sortKey][0],n,tk));page.forEach(g=>g.forEach(e=>els.push(rowFor(e))))}}
  list.replaceChildren(...els);
  if(!rows.length){list.innerHTML=`<div class=empty><b>No sessions match “${esc(q.value)}”</b>Try part of a title, a skill name, a folder or the start of a session id.
    <p><button type=button class=btn id=s-clear>Clear the filter</button></p></div>`;
    document.getElementById('s-clear').addEventListener('click',()=>{q.value='';if(projBox)projBox.value='';render();q.focus()})}
  if(anim){top=list.getBoundingClientRect().top;const vh=innerHeight,seen=y=>y+top>-200&&y+top<vh+200;let k=0;
    // new rows wait for the leaving ones to clear so the two never show text over each other
    const wait=[...before.keys()].some(id=>!keep.has(id)&&seen(before.get(id)))?T_EXIT:0;
    els.filter(el=>el.dataset.id).forEach(el=>{const now=el.getBoundingClientRect().top-top,was=before.get(el.dataset.id);
      if(!seen(now)&&(was==null||!seen(was)))return;
      if(was==null)el.animate([{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}],
        {duration:T_LAYOUT,delay:wait+Math.min(k++,24)*22,easing:EXPO,fill:'backwards'});
      else if(Math.abs(was-now)>1)el.animate([{transform:`translateY(${was-now}px)`},{transform:'none'}],{duration:T_LAYOUT,easing:EXPO})});
    // a "+N more" button that leaves just goes; only rows fade out as ghosts
    before.forEach((y,id)=>{if(keep.has(id)||id.startsWith('more:')||!seen(y))return;const el=nodes.get(id);
      el.classList.add('ghost');el.style.top=y+'px';list.append(el);
      el.animate([{opacity:1},{opacity:0}],{duration:T_EXIT,easing:cssVar('--ease-exit'),fill:'forwards'})
        .finished.then(()=>{if(el.classList.contains('ghost'))el.remove()},()=>{})})}
  const more=document.getElementById('s-more');more.hidden=rows.length<=limit;more.textContent=`Show ${Math.min(rows.length-limit,50)} more`;
  document.getElementById('s-count').textContent=`showing ${Math.min(limit,rows.length)} of ${rows.length}`}
document.getElementById('s-more').addEventListener('click',()=>{limit+=50;render()});
q.addEventListener('input',()=>{limit=15;render()});
// the project list is built from the sessions in the range, most sessions first; picking one filters the list at once
if(projBox){const n=new Map();S.forEach(s=>{if(s.project)n.set(s.project,(n.get(s.project)||0)+1)});
  projBox.append(...[...n].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).map(([p,c])=>{const o=document.createElement('option');o.value=p;o.textContent=`${p} (${c})`;return o}));
  projBox.addEventListener('change',()=>{limit=15;render()})}
list.addEventListener('click',e=>{const b=e.target.closest('.cp');if(!b)return;
  navigator.clipboard.writeText(b.dataset.copy).then(()=>{b.textContent='Copied ✓';b.classList.add('ok');toast('Copied to the clipboard');
    setTimeout(()=>{b.textContent='Copy';b.classList.remove('ok')},1400)},
    ()=>getSelection().selectAllChildren(b.previousElementSibling))});render();
function renderCompare(){
  const box=document.getElementById('compare'),sel=S.filter(s=>picked.has(s.id));
  if(sel.length<2)return;
  const keys=(f,n)=>{const tot={};sel.forEach(s=>Object.entries(s[f]).forEach(([k,v])=>tot[k]=(tot[k]||0)+v));return Object.entries(tot).sort((a,b)=>b[1]-a[1]).slice(0,n).map(e=>e[0])};
  const line=(label,vals,low)=>{const nums=vals.map(v=>typeof v==='number'?v:null).filter(v=>v!=null),best=low&&nums.length?Math.min(...nums):null;
    return `<tr><td>${label}</td>${vals.map(v=>`<td>${typeof v==='number'?(v===best?'<b>'+fmt(v)+'</b>':fmt(v)):esc(v)}</td>`).join('')}</tr>`};
  let h=`<tr><th></th>${sel.map(s=>`<th title="${esc(s.title)}">${esc((s.title||'').slice(0,26))}<br><span class=usd>${esc(s.id.slice(0,8))}</span></th>`).join('')}</tr>`;
  h+=line('started',sel.map(dayOf));h+=line('prompts',sel.map(s=>s.prompts));
  h+=line('tokens',sel.map(s=>s.tokens),1);h+=line('tokens per prompt',sel.map(s=>s.tokens/Math.max(s.prompts,1)),1);
  h+=line('output tokens',sel.map(s=>s.output),1);h+=line('subagent runs',sel.map(s=>s.runs));
  h+=`<tr><td class=u>API-eq</td>${sel.map(s=>`<td class=u>${usd(s.usd)}</td>`).join('')}</tr>`;
  h+=`<tr><th colspan=${sel.length+1} style="text-align:left">tokens by owner</th></tr>`;
  keys('owners',8).forEach(k=>h+=line(k,sel.map(s=>s.owners[k]||0)));
  h+=`<tr><th colspan=${sel.length+1} style="text-align:left">tokens by skill</th></tr>`;
  keys('skills',8).forEach(k=>h+=line(k,sel.map(s=>s.skills[k]||0)));
  box.querySelector('table').innerHTML=h}
// selecting only builds the pick list; the comparison runs when Compare is pressed
sortBox.addEventListener('click',e=>{const b=e.target.closest('[data-sort]');if(!b||b.dataset.sort===sortKey)return;sortKey=b.dataset.sort;
  sortBox.querySelectorAll('[data-sort]').forEach(x=>{x.classList.toggle('on',x===b);x.setAttribute('aria-pressed',x===b)});render()});
const box=document.getElementById('compare'),pickBar=document.getElementById('pickbar'),go=document.getElementById('do-compare');
function updatePick(){
  // the tray rises when a second session is ticked and sinks again below two
  const n=picked.size,on=n>=2;pickBar.hidden=false;pickBar.classList.toggle('show',on);pickBar.inert=!on;document.body.classList.toggle('picking',on);go.disabled=!on;
  if(n)document.getElementById('pick-hint').textContent=`${n} of 4 picked${n>=4?' · the 5th is blocked':''}`;
  box.classList.remove('on')}  // a changed pick list makes a shown comparison stale
go.addEventListener('click',()=>{renderCompare();box.classList.add('on');box.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'})});
document.getElementById('clear-pick').addEventListener('click',()=>{picked.clear();render();updatePick()});
updatePick();
// keyboard: / filter, c compare, Esc leaves the filter
addEventListener('keydown',e=>{const typing=/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
  if(e.key==='Escape'&&document.activeElement===q){q.value?(q.value='',render()):q.blur();return}
  if(typing||e.metaKey||e.ctrlKey||e.altKey)return;
  if(e.key==='/'){e.preventDefault();q.scrollIntoView({block:'center'});q.focus()}
  else if(e.key==='c'&&!go.disabled)go.click()});
"""
JS_TOC = """
const tocLinks=[...document.querySelectorAll('.toc a')],tocTargets=tocLinks.map(a=>document.getElementById(a.hash.slice(1)));
let clicked=-1;
tocLinks.forEach((a,k)=>a.addEventListener('click',e=>{const t=tocTargets[k];if(!t)return;e.preventDefault();clicked=k;
  // a collapsed section opens when picked from the sidebar; scroll once its height has grown, or the target falls short
  const opening=t.tagName==='DETAILS'&&!t.open;if(opening)t.open=true;
  history.replaceState(null,'',a.hash);setTimeout(()=>{t.scrollIntoView({behavior:smoothOk()?'smooth':'auto',block:'start'});spy()},opening&&smoothOk()?320:0)}));
const topBtn=document.getElementById('totop');
topBtn.addEventListener('click',()=>{scrollTo({top:0,behavior:smoothOk()?'smooth':'auto'});spy()});
// 12 rect reads per scroll event is cheap enough without a frame throttle
const pill=document.createElement('span'),toc=document.querySelector('.toc'),progress=document.getElementById('progress');
pill.className='toc-pill';toc.prepend(pill);document.body.classList.add('has-pill');
function movePill(a){if(!a)return;const t=toc.getBoundingClientRect(),r=a.getBoundingClientRect();
  pill.style.transform=`translate(${r.left-t.left+toc.scrollLeft}px,${r.top-t.top+toc.scrollTop}px)`;pill.style.width=r.width+'px';pill.style.height=r.height+'px'}
function spy(){topBtn.classList.toggle('show',scrollY>500);
  const max=document.documentElement.scrollHeight-innerHeight;progress.style.transform=`scaleX(${max>0?Math.min(1,scrollY/max):0})`;
  let cur=0;tocTargets.forEach((t,k)=>{if(t&&t.getBoundingClientRect().top<=120)cur=k});
  // a section near the end can never reach the top; at the bottom the link that was clicked stays lit
  if(clicked>=0&&scrollY>=max-4&&tocTargets[clicked].getBoundingClientRect().top<innerHeight)cur=clicked;
  tocLinks.forEach((a,k)=>a.classList.toggle('on',k===cur));movePill(tocLinks[cur])}
addEventListener('scroll',spy,{passive:true});addEventListener('resize',spy);spy();
"""
JS_TREND = """
// the chart's guide line follows the day under the pointer
const chart=document.querySelector('#trend svg'),guide=chart&&chart.querySelector('.guide');
if(guide)chart.querySelectorAll('g.d').forEach(g=>g.addEventListener('mouseenter',()=>{const r=g.querySelector('rect.m');
  const x=(+r.getAttribute('x')+r.getAttribute('width')/2).toFixed(1);guide.setAttribute('x1',x);guide.setAttribute('x2',x)}));
document.querySelectorAll('svg [data-change]').forEach(el=>el.addEventListener('click',()=>{
  const c=document.getElementById('change-'+el.dataset.change);if(c){c.closest('details').open=true;c.scrollIntoView({behavior:'smooth',block:'center'})}}));"""
JS_BENCH = """
const leaky=document.getElementById('show-leaky');
if(leaky){const sync=()=>document.querySelectorAll('.leaky').forEach(el=>el.hidden=!leaky.checked);leaky.addEventListener('change',sync);sync()}
"""
JS_SUMMARY = """
// summary: group-by chips (the report shows one of four embedded tables; the dashboard chips are links), Copy and, in the report, the downloads
document.querySelectorAll('.sumview').forEach(v=>{
  const FIELDS=['key','requests','prompt_tokens','output_tokens','cost_usd','carried_cost_usd'],panes=[...v.querySelectorAll('.sum-pane')],
    cur=()=>panes.find(p=>!p.hidden),rowsOf=()=>JSON.parse(cur().dataset.rows);
  const safe=x=>/^[=+\\-@\\t\\r]/.test(x=String(x))?"'"+x:x;
  const cell=x=>/[",\\n\\r]/.test(x=safe(x))?'"'+x.replace(/"/g,'""')+'"':x;
  const asCsv=r=>[FIELDS.join(',')].concat(r.map(o=>FIELDS.map(k=>cell(o[k])).join(','))).join('\\n')+'\\n';
  v.querySelectorAll('[data-pick]').forEach(b=>b.addEventListener('click',()=>{
    panes.forEach(p=>p.hidden=p.dataset.by!==b.dataset.pick);
    v.querySelectorAll('[data-pick]').forEach(x=>{const on=x===b;x.classList.toggle('on',on);x.setAttribute('aria-pressed',on)})}));
  v.querySelectorAll('[data-dl]').forEach(a=>a.addEventListener('click',()=>{const f=a.dataset.dl,r=rowsOf();
    a.href=URL.createObjectURL(new Blob([f==='csv'?asCsv(r):JSON.stringify(r,null,2)],{type:f==='csv'?'text/csv':'application/json'}));
    a.download='tokscope-summary-'+cur().dataset.by+'.'+f;setTimeout(()=>URL.revokeObjectURL(a.href),1000)}));
  v.querySelector('[data-copy]').addEventListener('click',async()=>{
    const text=[FIELDS.join('\\t')].concat(rowsOf().map(o=>FIELDS.map(k=>safe(o[k])).join('\\t'))).join('\\n');
    try{await navigator.clipboard.writeText(text)}catch(_){const t=document.createElement('textarea');t.value=text;document.body.append(t);t.select();
      try{document.execCommand('copy')}finally{t.remove()}}
    toast('Copied')})});
"""
JS = JS_CORE + JS_SESSIONS + JS_TOC + JS_TREND + JS_BENCH + JS_SUMMARY
