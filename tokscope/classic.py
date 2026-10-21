"""The Classic design (the look before the ink redesign), kept as a second skin next to Ink.

Pages carry both stylesheets: <style id="skin-ink"> and <style id="skin-classic" media="not all">. The Classic/Ink button
(key `s`) flips their media attributes; SKIN_APPLY restores the saved choice (localStorage `tokscope-skin`) before paint.
Every part of the switch is named "skin" (`grep -rn -i skin tokscope tests`). The skin block in report.py's JS_CORE needs
the #skin button: without it the page script throws."""
from . import fonts

CLASSIC_CSS = """
:root{--page:#f6f6f3;--surface:#ffffff;--ink:#1d1d1b;--ink2:#3e3e3a;--muted:#62625c;--grid:#e3e3dc;--edge:#c6c6bc;--mark:#0086b9;--agent:#e49921;--mark-ink:#00749f;--agent-ink:#9a5f00;
--tint:#e2f5ff;--track:#ecece6;--c1:var(--mark);--c2:var(--agent);--c3:#1baf7a;--c4:#6250d6;--c5:#e87ba4;--c0:#c4c4bc;--chip:#efefea;--hl:#ffe9a8;--pass:#1f7a3d;--fail:#b3261e;
--sans:SANS;--mono:MONO;--ease:cubic-bezier(0.22,1,0.36,1);--ease-expo:cubic-bezier(0.16,1,0.3,1);interpolate-size:allow-keywords;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){DARK}}
:root[data-theme=dark]{DARK}
b,strong{font-weight:600}.kpi b,.hero .big em,.delta{font-family:var(--mono)}.kpi b{font-weight:600}*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 var(--sans);accent-color:var(--mark)}
main{max-width:1180px;margin:0 auto;padding:28px 16px 72px}h1{font-size:22px;margin:0 0 2px;text-wrap:balance}h2{font-size:17px;margin:0 0 4px}h3{font-size:14px;margin:14px 0 6px}
.sub{color:var(--ink2);margin:0 0 16px}pre.diff{white-space:pre-wrap;font:12px/1.5 var(--mono);background:var(--page);padding:10px;border-radius:8px;max-height:420px;overflow:auto;margin:6px 0 10px}
pre.diff .add{color:var(--pass)}pre.diff .del{color:var(--fail)}pre.diff .hunk{color:var(--muted)}
#skill-versions .versions h3{margin:14px 0 8px}#skill-versions .card{margin:0 0 12px}
details.vdiff>summary{cursor:pointer;font-size:13px;margin:6px 0}.few{font-size:10px;font-weight:600;text-transform:uppercase;color:var(--muted);border:1px solid var(--edge);border-radius:4px;padding:0 4px;margin-left:4px}
code.ver{font-size:11px;color:var(--muted);background:var(--chip);border-radius:4px;padding:0 4px;margin-left:2px}
.privacy{border:1px solid var(--edge);border-left:3px solid var(--mark);border-radius:8px;padding:8px 12px;margin:0 0 12px;font-size:13px;color:var(--ink2);background:var(--surface)}.privacy b{color:var(--mark-ink);text-transform:uppercase;font-size:11px;letter-spacing:.04em;margin-right:6px}.note{color:var(--muted);font-size:12px;margin:0 0 10px}.usd{color:var(--muted);font-size:12px}
:focus-visible{outline:2px solid var(--mark);outline-offset:2px;border-radius:4px}
.hero{position:relative;overflow:hidden;border:1px solid color-mix(in oklch,var(--mark) 30%,var(--edge));border-radius:14px;padding:20px 22px;margin:12px 0 16px;
background:radial-gradient(120% 160% at 0% 0%,color-mix(in oklch,var(--mark) 16%,transparent),transparent 55%),
radial-gradient(70% 140% at 100% 100%,color-mix(in oklch,var(--agent) 12%,transparent),transparent 60%),var(--surface)}
.hero .big{font-size:28px;font-weight:700;letter-spacing:-0.01em;margin:0 0 6px;font-variant-numeric:tabular-nums}.hero p{margin:2px 0;color:var(--ink2)}
.hero .big em{font-style:normal;font-weight:600;color:var(--mark-ink)}.hero a{color:var(--mark-ink);text-underline-offset:2px}
.trend{display:inline-block;padding:1px 8px;border-radius:999px;font-weight:600}
.up{color:var(--fail);background:color-mix(in oklch,var(--fail) 13%,transparent)}.down{color:var(--pass);background:color-mix(in oklch,var(--pass) 13%,transparent)}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
.kpi{background:var(--surface);border:1px solid var(--edge);border-radius:10px;padding:10px 14px;min-width:120px;transition:border-color .2s var(--ease),transform .2s var(--ease)}
.kpi:hover{border-color:color-mix(in oklch,var(--mark) 45%,var(--edge));transform:translateY(-1px)}
.kpi span{display:block;color:var(--ink2);font-size:12px}.kpi b{font-size:19px;font-variant-numeric:tabular-nums}
.card{background:var(--surface);border:1px solid var(--edge);border-radius:12px;padding:14px 16px;margin-bottom:14px;overflow-x:auto}
details.more{background:var(--surface);border:1px solid var(--edge);border-radius:12px;padding:10px 16px;margin-bottom:10px;transition:border-color .2s var(--ease)}
details.more:hover,details.more[open]{border-color:color-mix(in oklch,var(--mark) 35%,var(--edge))}
details.more>summary{cursor:pointer;font-weight:600;list-style:none;display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 6px}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::before{content:"›";display:inline-block;color:var(--mark-ink);font-weight:600;transition:transform .2s var(--ease)}
details.more[open]>summary::before{transform:rotate(90deg)}details.more>summary .ttl{flex:none;white-space:nowrap}details.more>summary .note{flex:1 1 18em;min-width:0;overflow-wrap:anywhere;font-weight:400;margin:0}
@media (max-width:640px){details.more>summary .note{flex-basis:100%}}
details::details-content{block-size:0;overflow:hidden;transition:block-size .3s var(--ease),content-visibility .3s allow-discrete}
details[open]::details-content{block-size:auto}
details[open]>:not(summary){animation:reveal .28s var(--ease) both}
@keyframes reveal{from{opacity:.4;transform:translateY(-4px)}}
/* the number is always the real value; only its focus animates, so a paused frame never shows wrong data */
.kpi b,.hero .big em{display:inline-block;animation:focus .7s var(--ease-expo) both}
@keyframes focus{from{filter:blur(2px);opacity:.6}}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{padding:5px 8px;text-align:right;white-space:nowrap;vertical-align:top}
th{color:var(--muted);font-weight:500;font-size:12px;border-bottom:1px solid var(--grid)}td:first-child,th:first-child{text-align:left}
tr+tr td{border-top:1px solid var(--grid)}td.l{text-align:left;white-space:normal;color:var(--ink2);min-width:220px}td.u{color:var(--muted);font-size:12px}
td.lm{text-align:left;white-space:normal;color:var(--ink2);font-size:12px}
.bar{display:flex;align-items:center;gap:8px;justify-content:flex-end}.bar i{display:flex;gap:2px;width:90px;height:8px;background:var(--track);border-radius:4px;overflow:hidden}
.bar i u{display:block;height:100%;background:var(--mark);border-radius:0 4px 4px 0;transform-origin:left;animation:grow .5s var(--ease-expo) both;animation-delay:calc(var(--i,0)*25ms)}
.bar i u.a{background:var(--agent);border-radius:0 4px 4px 0}.bar i u:has(+u.a){border-radius:0}
@keyframes grow{from{transform:scaleX(0)}}
.key{display:inline-flex;align-items:center;gap:4px;margin-right:10px}.key i{width:10px;height:10px;border-radius:3px;background:var(--mark)}.key i.a{background:var(--agent)}
svg text{fill:var(--muted);font-size:11px}svg .g{stroke:var(--grid)}svg rect.m{fill:var(--mark);transform-box:fill-box;transform-origin:bottom;transition:opacity .15s}
#trend[open] svg rect.m{animation:rise .55s var(--ease-expo) both;animation-delay:calc(var(--i,0)*12ms)}
@keyframes rise{from{transform:scaleY(0)}}
svg rect.hit{fill:transparent}svg .chg{stroke:var(--agent);stroke-width:1.5;stroke-dasharray:3 3}svg text.chg-l{fill:var(--agent-ink);font-weight:600}
svg:hover rect.m{opacity:.45}svg g.d:hover rect.m{opacity:1}
#tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--edge);border-radius:8px;padding:6px 9px;font-size:12px;
box-shadow:0 6px 20px #0003;max-width:320px;opacity:0;transform:translateY(4px);transition:opacity .15s var(--ease),transform .15s var(--ease);z-index:30}
#tip.on{opacity:1;transform:none}
.pass,.fail{font-weight:600;padding:0 7px;border-radius:999px}
.pass{color:var(--pass);background:color-mix(in oklch,var(--pass) 13%,transparent)}.fail{color:var(--fail);background:color-mix(in oklch,var(--fail) 13%,transparent)}
.changes{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}.delta{font-size:22px;font-weight:600;color:var(--mark-ink)}
pre.answer{white-space:pre-wrap;font:12px/1.5 var(--mono);background:var(--page);padding:10px;border-radius:8px;max-height:480px;overflow:auto}
mark{background:var(--hl);color:inherit;border-radius:2px}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px}
.tools input[type=search],.tools select{font:inherit;padding:6px 10px;border:1px solid var(--edge);border-radius:8px;background:var(--page);color:var(--ink);transition:border-color .15s var(--ease),box-shadow .15s var(--ease)}
.tools input[type=search]:focus,.tools select:focus{outline:none;border-color:var(--mark);box-shadow:0 0 0 3px color-mix(in oklch,var(--mark) 22%,transparent)}
.tools input[type=search]{flex:1;min-width:180px}
.srow{border:1px solid var(--edge);border-radius:10px;background:var(--surface);margin-bottom:8px;
transition:border-color .2s var(--ease),box-shadow .2s var(--ease),transform .2s var(--ease),background .2s var(--ease)}
#session-list{position:relative}.srow.ghost{position:absolute;left:0;right:0;margin:0;pointer-events:none;z-index:0}
.bar [data-count],.note [data-count]{font-variant-numeric:tabular-nums}
.srow:hover{border-color:color-mix(in oklch,var(--mark) 40%,var(--edge));transform:translateY(-1px);
box-shadow:0 6px 18px -10px color-mix(in oklch,var(--mark) 55%,transparent)}
.srow[open]{border-color:color-mix(in oklch,var(--mark) 55%,var(--edge));background:color-mix(in oklch,var(--mark) 4%,var(--surface));
box-shadow:0 8px 26px -14px color-mix(in oklch,var(--mark) 60%,transparent)}
.srow[open]:hover{transform:none}
.srow.picked{border-color:var(--mark);box-shadow:0 0 0 2px color-mix(in oklch,var(--mark) 22%,transparent)}
.srow>summary{display:grid;grid-template-columns:22px 92px 1fr 90px 74px 92px 150px 14px;gap:8px;align-items:center;padding:9px 10px;cursor:pointer;list-style:none;border-radius:10px}
.srow>summary:focus-visible{outline:2px solid var(--mark);outline-offset:2px}
.srow>summary input{accent-color:var(--mark);cursor:pointer}
.srow>summary .t{transition:color .15s var(--ease)}.srow:hover>summary .t{color:var(--mark-ink)}
.srow>summary .split{transition:transform .2s var(--ease);transform-origin:left}.srow:hover>summary .split{transform:scaleY(1.35)}
.cv{color:var(--muted);font-weight:600;text-align:center;transition:transform .2s var(--ease),color .15s var(--ease)}
.srow:hover .cv{color:var(--mark-ink);transform:translateX(2px)}.srow[open] .cv{transform:rotate(90deg);color:var(--mark-ink)}
.srow .body tr td{transition:background .15s var(--ease)}.srow .body tr:hover td{background:color-mix(in oklch,var(--mark) 7%,transparent)}
/* left sidebar: every section one click away; the link of the section in view is highlighted */
.layout>main{min-width:0}
.layout{display:grid;grid-template-columns:224px minmax(0,1fr);max-width:1460px;margin:0 auto}
.side{position:sticky;top:0;align-self:start;height:100vh;overflow-y:auto;padding:28px 12px 20px 16px;border-right:1px solid var(--edge);background:var(--page);z-index:10}
.brand{font-weight:600;font-size:13px;color:var(--mark-ink);margin:0 0 14px 10px;display:flex;align-items:center;gap:7px;--tok-accent:var(--agent)}
.brand .logo{width:24px;height:15px;flex:none;position:relative;top:-1px}
.toc{display:flex;flex-direction:column;gap:2px}
.toc a{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 10px;border-radius:8px;color:var(--ink2);text-decoration:none;
font-size:14px;transition:background .15s var(--ease),color .15s var(--ease),transform .15s var(--ease)}
.toc a:hover{background:color-mix(in oklch,var(--mark) 10%,transparent);color:var(--ink);transform:translateX(2px)}
.toc a.on{background:color-mix(in oklch,var(--mark) 15%,transparent);color:var(--mark-ink);font-weight:600}
.toc a:focus-visible{outline:2px solid var(--mark);outline-offset:1px}
.sub-toc{display:flex;flex-direction:column;gap:1px;margin:2px 0 4px 14px;padding-left:6px;border-left:1px solid var(--grid)}
.sub-toc a{font-size:13px;padding:4px 10px}
.cnt{font-size:11px;font-weight:400;color:var(--muted);font-variant-numeric:tabular-nums;background:var(--chip);padding:1px 7px;border-radius:999px}
[id]{scroll-margin-top:16px}
.totop{position:fixed;right:22px;bottom:22px;z-index:25;width:44px;height:44px;border-radius:50%;font:700 18px/1 inherit;
border:1px solid color-mix(in oklch,var(--mark) 40%,var(--edge));background:var(--surface);color:var(--mark-ink);box-shadow:0 8px 22px -10px #0006;
opacity:0;visibility:hidden;transform:translateY(10px);
transition:opacity .2s var(--ease),transform .2s var(--ease),visibility .2s,bottom .2s var(--ease),background .15s var(--ease),color .15s var(--ease)}
.totop.show{opacity:1;visibility:visible;transform:none}
.totop.show:hover{background:var(--mark);color:#fff;transform:translateY(-2px)}
.totop:focus-visible{outline:2px solid var(--mark);outline-offset:2px}
body.picking .totop{bottom:92px}  /* clear the sticky Compare bar */
@media (max-width:900px){.layout{display:block}
.side{height:auto;padding:8px 16px;border-right:0;border-bottom:1px solid var(--edge);overflow-x:auto;overflow-y:hidden;scrollbar-width:none}.side::-webkit-scrollbar{display:none}
.brand,.sub-toc,.cnt{display:none}.toc{flex-direction:row;white-space:nowrap}.toc a:hover{transform:none}}
/* everything that reacts to a click shows the hand cursor */
a,summary,label,select,button:not(:disabled),input[type=checkbox],svg [data-change],[data-copy]{cursor:pointer}
#sessions{overflow:visible}  /* a scrolling card would stop the pick bar from sticking */
.pickbar{position:sticky;bottom:12px;z-index:20;display:flex;gap:10px;align-items:center;justify-content:space-between;margin:4px 0 8px;
padding:10px 14px;border:1px solid color-mix(in oklch,var(--mark) 45%,var(--edge));border-radius:12px;background:var(--surface);
box-shadow:0 10px 30px -12px #0005;animation:pop .25s var(--ease) both}
.pickbar[hidden]{display:none}.pickbar .acts{display:flex;gap:8px;align-items:center}
.primary{all:unset;cursor:pointer;font-weight:600;font-size:13px;padding:6px 14px;border-radius:8px;background:var(--mark);color:#fff;
transition:transform .15s var(--ease),box-shadow .15s var(--ease),opacity .15s var(--ease)}
.primary:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 6px 16px -6px var(--mark)}.primary:active:not(:disabled){transform:none}
.primary:focus-visible{outline:2px solid var(--mark);outline-offset:2px}.primary:disabled{opacity:.45;cursor:not-allowed}
.srow>summary::-webkit-details-marker{display:none}
.srow>summary .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.srow>summary .r{text-align:right;font-variant-numeric:tabular-nums}
.srow>summary .n{white-space:nowrap;color:var(--ink2);font-size:13px}
.srow>summary .sk{color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.split{display:flex;gap:2px;height:8px;border-radius:4px;overflow:hidden;background:var(--track)}
.split u{display:block;height:100%;background:var(--mark)}.split u.a{background:var(--agent)}
.srow .body{padding:4px 4px 12px 30px}
.srow .body td.l{overflow-wrap:anywhere}.srow .body td.calls{min-width:300px}.scroll{overflow-x:auto}.run{display:grid;grid-template-columns:minmax(0,max-content) minmax(0,1fr) auto auto;column-gap:10px;align-items:baseline;
padding:3px 8px 3px calc(8px + var(--d,0)*16px);border-radius:6px;line-height:1.5;transition:background .15s var(--ease)}
.run:hover{background:color-mix(in oklch,var(--agent) 9%,transparent)}
.run .rt{color:var(--agent-ink);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px}
tr.runs-row td{border-top:0;padding-top:0}.runs{border:1px solid color-mix(in oklch,var(--agent) 30%,var(--edge));border-radius:8px;padding:4px;
background:color-mix(in oklch,var(--agent) 4%,var(--surface));text-align:left;white-space:normal}
.run .rd{color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.run .est{text-align:right}.run .usd{white-space:nowrap}.runs-more>summary{padding:2px 8px;color:var(--mark-ink);font-size:12px}.cl{line-height:1.6}.cl+.cl{margin-top:2px}.est{color:var(--ink);font-variant-numeric:tabular-nums}
.ck{display:inline-block;min-width:46px;margin-right:6px;font-size:11px;color:var(--muted)}.ck.agents{color:var(--agent-ink)}.ck.mcp{color:var(--mark-ink)}
.ids{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;align-items:center;margin:4px 0 10px;padding:10px 12px;
background:var(--surface);border:1px solid var(--edge);border-radius:10px}
.ids dt{color:var(--muted);font-size:12px}.ids dd{margin:0;display:flex;gap:6px;align-items:center;min-width:0}
.ids dd .code{overflow-wrap:anywhere}.ids dt:first-child,.ids dt:first-child+dd .code{font-weight:600;color:var(--ink)}.code{font:12px var(--mono);background:var(--chip);padding:2px 6px;border-radius:4px;user-select:all}
#compare{display:none;border:1px solid color-mix(in oklch,var(--mark) 45%,var(--edge));background:linear-gradient(var(--tint),transparent 120px),var(--surface)}
#compare.on{display:block;animation:pop .25s var(--ease) both}
@keyframes pop{from{opacity:.4;transform:translateY(-6px)}}
.btn{all:unset;cursor:pointer;font-size:12px;color:var(--mark-ink);padding:2px 6px;border-radius:6px;transition:background .15s var(--ease)}
.btn:hover{background:color-mix(in oklch,var(--mark) 14%,transparent)}
@media (max-width:640px){.srow>summary{grid-template-columns:22px 1fr 80px 14px}.srow>summary .d,.srow>summary .sk,.srow>summary .n,.srow>summary .split{display:none}}
/* motion layer: entrance, spotlight, aurora, scroll reveal; all of it off under reduced motion */
html{scroll-behavior:smooth}body{transition:background-color .35s var(--ease),color .35s var(--ease)}
#progress{position:fixed;inset:0 0 auto 0;height:3px;z-index:40;transform-origin:0 50%;transform:scaleX(0);
background:linear-gradient(90deg,var(--mark),var(--agent));box-shadow:0 0 12px color-mix(in oklch,var(--mark) 60%,transparent)}
.hero::before{content:"";position:absolute;inset:-40%;pointer-events:none;opacity:.55;
background:radial-gradient(30% 40% at 30% 40%,color-mix(in oklch,var(--mark) 22%,transparent),transparent 70%),
radial-gradient(25% 35% at 70% 60%,color-mix(in oklch,var(--agent) 20%,transparent),transparent 70%);animation:drift 18s ease-in-out infinite alternate}
@keyframes drift{to{transform:translate(6%,-4%) rotate(8deg) scale(1.08)}}
.hero>*{position:relative}.hero{animation:rise-in .7s var(--ease-expo) backwards}
.hero .big em{background:linear-gradient(90deg,var(--mark),color-mix(in oklch,var(--mark) 45%,var(--agent)));-webkit-background-clip:text;background-clip:text;color:transparent}
.kpi{position:relative;overflow:hidden;animation:rise-in .6s var(--ease-expo) backwards;animation-delay:calc(120ms + var(--i,0)*70ms)}
@keyframes rise-in{from{opacity:0;transform:translateY(12px) scale(.98)}}
.kpi::after,.hero::after,.changes .card::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity .3s var(--ease);
background:radial-gradient(220px circle at var(--mx,50%) var(--my,50%),color-mix(in oklch,var(--mark) 16%,transparent),transparent 70%)}
.kpi:hover::after,.hero:hover::after,.changes .card:hover::after{opacity:1}.changes .card{position:relative}
.kpi:hover{box-shadow:0 10px 24px -16px color-mix(in oklch,var(--mark) 70%,transparent)}
.js .reveal{opacity:0;transform:translateY(16px);transition:opacity .6s var(--ease-expo),transform .6s var(--ease-expo)}
.js .reveal.in{opacity:1;transform:none}
/* sidebar: one pill slides to the section in view */
.toc{position:relative}.toc a{position:relative;z-index:1}.toc-pill{position:absolute;left:0;top:0;border-radius:8px;pointer-events:none;
background:color-mix(in oklch,var(--mark) 15%,transparent);box-shadow:inset 3px 0 0 var(--mark);
transition:transform .35s var(--ease-expo),width .35s var(--ease-expo),height .35s var(--ease-expo),opacity .2s}
.has-pill .toc a.on{background:transparent}
.side-foot{display:flex;gap:6px;margin:18px 0 0 4px}
.chip{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2);padding:5px 10px;border:1px solid var(--edge);border-radius:999px;
transition:border-color .15s var(--ease),color .15s var(--ease),background .15s var(--ease)}
.chip:hover{border-color:var(--mark);color:var(--mark-ink)}.chip:focus-visible{outline:2px solid var(--mark);outline-offset:2px}
.chip kbd,.keys kbd{font:600 11px var(--mono);padding:1px 6px;border-radius:5px;border:1px solid var(--edge);border-bottom-width:2px;background:var(--surface);color:var(--ink)}
::view-transition-old(root),::view-transition-new(root){animation:none;mix-blend-mode:normal}
/* chart: 7-day average draws itself in; a guide follows the pointer */
svg .ma{fill:none;stroke:var(--agent);stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:0}
#trend[open] svg .ma{animation:draw 1.4s var(--ease-expo) .25s backwards}@keyframes draw{from{stroke-dashoffset:1}}
svg .guide{stroke:var(--ink2);stroke-width:1;stroke-dasharray:2 3;opacity:0;transition:opacity .15s}svg:hover .guide{opacity:.6}
.key i.ln{height:3px;border-radius:2px;background:var(--agent)}
/* copy feedback, empty state, shortcuts dialog */
.btn.ok{color:var(--pass);background:color-mix(in oklch,var(--pass) 14%,transparent);animation:pop .25s var(--ease) both}
#toast{position:fixed;left:50%;bottom:26px;z-index:50;transform:translate(-50%,16px);opacity:0;pointer-events:none;padding:9px 16px;border-radius:999px;
background:var(--ink);color:var(--page);font-size:13px;font-weight:600;box-shadow:0 12px 30px -12px #0008;transition:opacity .2s var(--ease),transform .3s var(--ease-expo)}
#toast.on{opacity:1;transform:translate(-50%,0)}
.empty{text-align:center;padding:34px 12px;color:var(--muted);border:1px dashed var(--grid);border-radius:12px;animation:reveal .3s var(--ease) both}
.empty b{display:block;color:var(--ink);font-size:15px;margin-bottom:4px}
#s-more{border:1px solid var(--edge);padding:6px 14px;border-radius:8px}
dialog.keys{border:1px solid var(--edge);border-radius:14px;background:var(--surface);color:var(--ink);padding:18px 22px;min-width:300px;box-shadow:0 30px 60px -20px #0009}
dialog.keys[open]{animation:pop-in .3s var(--ease-expo) both}@keyframes pop-in{from{opacity:0;transform:translateY(8px) scale(.97)}}
dialog.keys::backdrop{background:#0005;backdrop-filter:blur(3px)}
dialog.keys dl{display:grid;grid-template-columns:auto 1fr;gap:8px 14px;margin:10px 0 0}dialog.keys dd{margin:0;color:var(--ink2)}
/* breakdown charts: categorical slots validated in both modes (blue, amber, aqua, violet, magenta); --c0 is "Other" */
.viz{margin:4px 0 16px}.viz svg{display:block;overflow:visible}.viz svg text.ax,.viz svg text.name{fill:var(--ink2)}
.viz svg text.val{fill:var(--ink2);font-weight:600;font-variant-numeric:tabular-nums}.viz svg text.lbl{fill:var(--ink);font-size:11.5px;paint-order:stroke;stroke:var(--surface);stroke-width:3px}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--ink2);margin:8px 0 10px}.legend .key{margin:0}
.legend .key i.was,.viz .dot.was{background:color-mix(in oklch,var(--c1) 40%,var(--muted));fill:color-mix(in oklch,var(--c1) 40%,var(--muted))}
.legend b{color:var(--ink);font-weight:600}
.share{display:flex;gap:2px;height:16px;border-radius:4px;overflow:hidden;margin-top:6px}.share i{display:block;min-width:3px;transform-origin:left;transition:filter .15s}
.share:hover i{filter:saturate(.35) opacity(.55)}.share i:hover{filter:none}
.viz .dot{fill:var(--c1);stroke:var(--surface);stroke-width:2px;transition:r .15s var(--ease)}.viz .dot:not(.hi){fill:color-mix(in oklch,var(--c1) 55%,var(--surface))}
.viz circle.hit,.viz rect.hit{fill:transparent}.viz g[data-tip]:hover .dot{r:7px}
.viz .span{stroke:color-mix(in oklch,var(--c1) 45%,var(--surface));stroke-width:2px;stroke-linecap:round}
.viz g.rg:hover rect.hit,.viz g.db:hover rect.hit{fill:color-mix(in oklch,var(--mark) 6%,transparent)}
.viz g.seg:hover path,.viz g.seg:hover rect:not(.hit){filter:brightness(1.12)}
#breakdowns details[open] .share i{animation:grow .7s var(--ease-expo) both;animation-delay:calc(var(--i,0)*60ms)}
#breakdowns details[open] .viz g.seg{transform-box:fill-box;transform-origin:bottom;animation:rise .6s var(--ease-expo) both;animation-delay:calc(var(--i,0)*70ms)}
#breakdowns details[open] .viz g.pt,#breakdowns details[open] .viz g.rg,#breakdowns details[open] .viz g.db{animation:rise-in .5s var(--ease-expo) both;animation-delay:calc(min(var(--i,0),20)*25ms)}
#breakdowns details[open] .viz .span{stroke-dasharray:1;stroke-dashoffset:0}
#breakdowns details[open] .viz g.rg .span,#breakdowns details[open] .viz g.db .span{animation:draw .8s var(--ease-expo) both;animation-delay:calc(var(--i,0)*30ms + .1s)}
/* narrow cards shrink, then drop, the bars and let headers and the calls column wrap, so a table fits its card
   instead of scrolling sideways; the numbers always stay */
th{white-space:normal}td:first-child{white-space:normal;overflow-wrap:anywhere;min-width:8ch}
.card,.srow .body,details.more{container-type:inline-size}
@container (max-width:1000px){.bar i{width:56px}td.l{min-width:160px}.srow .body td.calls{min-width:200px}}
@container (max-width:860px){.bar i{display:none}.srow .body td.calls{min-width:0}td.lm,td.calls{white-space:normal}td.l{min-width:120px}}
/* phone width: a table of five or more columns becomes one block per row, each cell a "column: value" line;
   narrower tables stay tables */
@container (max-width:520px){table:has(td[data-label]:nth-child(5)),table:has(td[data-label]:nth-child(5)) tbody,table:has(td[data-label]:nth-child(5)) tr{display:block}
table:has(td[data-label]:nth-child(5)) tr:first-child:has(th){display:none}table:has(td[data-label]:nth-child(5)) tr{padding:6px 0;border-top:1px solid var(--grid)}
table:has(td[data-label]:nth-child(5)) td{display:flex;justify-content:space-between;gap:12px;border:0;padding:2px 4px;max-width:none;white-space:normal;text-align:right}
table:has(td[data-label]:nth-child(5)) td::before{content:attr(data-label);color:var(--muted);font-size:12px;text-align:left;flex:none}
table:has(td[data-label]:nth-child(5)) td:first-child{font-weight:600}table:has(td[data-label]:nth-child(5)) td:first-child::before{content:none}
table:has(td[data-label]:nth-child(5)) td:empty{display:none}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after,::details-content{animation:none!important;transition:none!important}
.js .reveal{opacity:1;transform:none}html{scroll-behavior:auto}}
""".replace("SANS", fonts.SANS).replace("MONO", fonts.MONO).replace("DARK", "--page:#151514;--surface:#1f1f1d;--ink:#ecece8;--ink2:#c9c9c3;--muted:#a5a59e;--grid:#34342f;--edge:#34342f;--mark:#0398cd;--agent:#c68206;--mark-ink:#0398cd;--agent-ink:#e0a030;--tint:#102635;--track:#2b2b28;--chip:#2b2b28;--hl:#5a4b00;--pass:#5cc183;--fail:#f08a80;--c3:#199e70;--c4:#9085e9;--c5:#d55181;--c0:#55554f;color-scheme:dark")

CLASSIC_DASH_CSS = """
main{width:100%;min-width:0}main a{color:var(--mark-ink);text-underline-offset:2px}
.dash-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;margin:0 0 14px}.dash-head h1{margin:0}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-left:auto}
.filters select{font:inherit;font-size:13px;padding:5px 8px;border:1px solid var(--edge);border-radius:8px;background:var(--surface);color:var(--ink);max-width:220px}
.filters a{font-size:12px;color:var(--muted)}
.fresh{font-size:12px;color:var(--muted);display:inline-flex;align-items:center;gap:6px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--pass);margin-right:8px;box-shadow:0 0 0 0 color-mix(in oklch,var(--pass) 60%,transparent);animation:pulse 2s infinite}
.fresh .dot{margin:0}.fresh.stale .dot{background:var(--muted);animation:none}
@keyframes pulse{70%{box-shadow:0 0 0 8px transparent}100%{box-shadow:0 0 0 0 transparent}}
/* the report's .kpis is a content-sized flex row; here the six tiles fill the width, edge to edge with .cols2 below */
[data-region=kpis]>.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px}[data-region=kpis] .kpi{min-width:0}
@media (max-width:1200px){[data-region=kpis]>.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:560px){[data-region=kpis]>.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
.kpi{position:relative}.kpi .dl{display:block;font-size:11px;color:var(--muted);margin-top:2px}.kpi .dl .trend{display:inline-block;font-size:11px;padding:0 6px}
.spark{display:block;margin-top:4px}.spark polyline{fill:none;stroke:var(--mark);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
.cols2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:14px}
/* spender cards share one width: two to a row on a desktop (the third starts the next row), one on a phone;
   wide enough that a long name (compound-engineering:ce-simplify-code) fits on one line, and it wraps whole if not */
.cols3{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,400px),1fr));gap:14px}
.cols3 table{width:100%;table-layout:fixed}.cols3 th:nth-child(2),.cols3 td:nth-child(2){width:130px}
.cols3 th:nth-child(3),.cols3 td:nth-child(3){width:48px}.cols3 .bar i{width:48px}
.cols3 td:first-child{white-space:normal;overflow-wrap:anywhere}.cols3 td{vertical-align:baseline}
/* the "What changed" tables share fixed number columns so they line up one under the other */
[data-region=changed] table{table-layout:fixed}[data-region=changed] td{vertical-align:baseline}[data-region=changed] td:not(:first-child){text-align:right;white-space:nowrap}
[data-region=changed] :is(th,td):nth-child(2){width:76px}[data-region=changed] :is(th,td):nth-child(3){width:80px}[data-region=changed] :is(th,td):nth-child(4){width:80px}[data-region=changed] .bar i{display:none}
[data-region=changed] td:first-child{overflow-wrap:break-word}@container (max-width:520px){[data-region=changed] :is(th,td):nth-child(2){width:62px}[data-region=changed] :is(th,td):is(:nth-child(3),:nth-child(4)){width:70px}}
@media (max-width:900px){.cols2,.cols3{grid-template-columns:1fr}}
h2.sec{font-size:15px;margin:6px 0 10px}.card h2{display:flex;align-items:center}
.today-nums{display:flex;gap:22px;flex-wrap:wrap;margin:6px 0 12px}.today-nums span{display:block;font-size:12px;color:var(--ink2)}
.today-nums b{font-size:22px;font-variant-numeric:tabular-nums}
.latest{display:flex;flex-direction:column;gap:3px;border-top:1px solid var(--grid);padding-top:10px}.latest a{color:var(--ink);text-decoration:none}
.latest a:hover b{color:var(--mark-ink)}
ul.plain{list-style:none;margin:0;padding:0}ul.plain li{padding:4px 0;border-bottom:1px solid var(--grid)}
.flash{animation:flash 1.2s var(--ease)}@keyframes flash{from{background:color-mix(in oklch,var(--pass) 18%,transparent)}}
#newdata{position:fixed;right:20px;bottom:20px;z-index:40}
@media (prefers-reduced-motion:reduce){.dot,.flash{animation:none}}
.libtools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 14px}.libtools input[type=search]{min-width:min(100%,280px)}
.libtools .chip input{margin:0}
.libgroup{margin:0 0 18px}.libgroup h2 .note{margin:0 0 0 8px;font-weight:400}
.libgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:12px}
a.sk{display:flex;flex-direction:column;gap:6px;background:var(--surface);border:1px solid var(--edge);border-radius:12px;padding:12px 14px;
color:var(--ink);text-decoration:none;transition:border-color .15s var(--ease),transform .15s var(--ease)}
a.sk:hover{border-color:var(--mark);transform:translateY(-1px)}a.sk b{font-size:14px;overflow-wrap:anywhere}
a.sk p{margin:0;color:var(--ink2);font-size:12.5px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
a.sk .meta{margin-top:auto;font-size:11.5px;color:var(--muted)}
.badge{font-size:11px;font-weight:500;padding:1px 7px;border-radius:999px;background:var(--chip);color:var(--ink2);margin-left:8px;vertical-align:1px}
.badge.inst{color:var(--agent-ink)}
.libview{display:grid;grid-template-columns:minmax(150px,230px) minmax(0,1fr);gap:14px;align-items:start}
@media (max-width:860px){.libview{grid-template-columns:minmax(0,1fr)}.files{position:static;max-height:190px}}
.files{position:sticky;top:12px;padding:8px;max-height:calc(100vh - 24px);overflow:auto}
.files a{display:block;padding:4px 8px;border-radius:6px;font:12px/1.4 var(--mono);color:var(--ink2);overflow-wrap:anywhere;text-decoration:none}
.files a:hover{color:var(--mark-ink)}.files a.on{background:var(--tint);color:var(--mark-ink)}
.viewer{overflow:visible}.viewer .path{font:600 13px var(--mono);margin:0 0 8px;overflow-wrap:anywhere}
.viewbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;margin:0 0 10px}.viewbar .note{margin:0}
.seg{display:inline-flex;gap:4px}.seg .chip.on{border-color:var(--mark);color:var(--mark-ink)}
.md{font-size:14px;line-height:1.6;max-width:84ch;overflow-wrap:anywhere}.md>:first-child{margin-top:0}
.md h1{font-size:20px}.md h2{font-size:17px;border-bottom:1px solid var(--grid);padding-bottom:4px}.md h3{font-size:15px}.md h4{font-size:14px}
.md h1,.md h2,.md h3,.md h4{margin:20px 0 8px}.md p,.md ul,.md ol{margin:0 0 10px}.md ul,.md ol{padding-left:22px}.md li{margin:2px 0}
.md code{font:.88em var(--mono);background:var(--chip);border-radius:4px;padding:1px 4px}
.md pre,pre.src{font:12.5px/1.55 var(--mono);background:var(--page);border:1px solid var(--edge);border-radius:8px;padding:10px 12px;
margin:0 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}
.md pre code{background:none;padding:0;font-size:inherit}
.md blockquote{margin:0 0 10px;padding:2px 12px;border-left:3px solid var(--grid);color:var(--ink2)}
.md table{margin:0 0 12px}.md td,.md th{white-space:normal;overflow-wrap:anywhere;vertical-align:top;text-align:left}
.md hr{border:0;border-top:1px solid var(--grid);margin:16px 0}
.libhead .ids dd{display:block;min-width:0;overflow-wrap:anywhere}.libhead .ids dt:first-child{font-weight:400;color:var(--muted)}
pre.src{counter-reset:ln}pre.src .ln{display:block;padding-left:5.5ch;text-indent:-5.5ch}
pre.src .ln::before{counter-increment:ln;content:counter(ln);display:inline-block;width:4ch;margin-right:1.5ch;text-indent:0;
text-align:right;color:var(--muted);user-select:none}pre.src .ln.hit{background:var(--hl);border-radius:3px}
.ste-n{white-space:nowrap}.libtools select{font:inherit;font-size:13px;padding:5px 8px;border:1px solid var(--edge);border-radius:8px;
background:var(--surface);color:var(--ink)}.seg .chip b{color:var(--fail);font-weight:600}
ol.ste{list-style:none;margin:10px 0 0;padding:0}ol.ste li{display:grid;grid-template-columns:auto auto 1fr;gap:2px 10px;align-items:baseline;
padding:8px 0;border-bottom:1px solid var(--grid)}ol.ste .lnk{font:12px var(--mono);text-decoration:none}
ol.ste .rule{font:600 12px var(--mono)}ol.ste .lvl{font-size:11px;color:var(--muted);justify-self:start}
ol.ste li.hard .lvl{color:var(--fail)}ol.ste .line,ol.ste .msg{grid-column:1/-1}
ol.ste .line{font:12.5px/1.5 var(--mono);background:var(--page);border-radius:6px;padding:4px 8px;white-space:pre-wrap;overflow-wrap:anywhere}
ol.ste mark{background:var(--hl);color:inherit;border-radius:2px}ol.ste .msg{font-size:12.5px;color:var(--ink2)}
.pnums{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--ink2)}.pnums b{color:var(--ink);font-size:14px}
details.folders{margin-top:8px;font-size:13px}details.folders summary{cursor:pointer;color:var(--mark-ink)}details.folders li{overflow-wrap:anywhere}
table.mcp td{vertical-align:baseline}table.mcp :is(th,td):is(:nth-child(2),:nth-child(3),:nth-child(7)){text-align:left}table.mcp td:nth-child(3){white-space:normal;overflow-wrap:anywhere}table.mcp td:nth-child(3) .note{display:block;margin:2px 0 0}
table.mcp .st{white-space:normal;text-align:left}
/* the status is what a reader looks for: a filled pill in the state's color, the text in ink for contrast */
.st .pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;line-height:1.5;
background:var(--chip);color:var(--ink2);border:1px solid transparent}
.st.ok .pill{background:color-mix(in oklch,var(--pass) 16%,transparent);border-color:color-mix(in oklch,var(--pass) 45%,transparent);color:var(--ink)}
.st.warn .pill{background:color-mix(in oklch,var(--agent) 18%,transparent);border-color:color-mix(in oklch,var(--agent) 50%,transparent);color:var(--ink)}
.st.bad .pill{background:color-mix(in oklch,var(--fail) 18%,transparent);border-color:color-mix(in oklch,var(--fail) 50%,transparent);color:var(--ink)}
.st.off .pill{font-weight:500}
table.mcp tbody tr{transition:background .15s var(--ease)}
table.mcp tbody tr:hover{background:color-mix(in oklch,var(--mark) 8%,transparent)}
table.mcp tbody tr:hover td:first-child{color:var(--mark-ink)}
.badge.flag{color:var(--agent-ink)}.badge{white-space:nowrap}code.login{display:block;margin-top:2px;font-size:11.5px;color:var(--ink2);overflow-wrap:anywhere}
#mcp-add{margin-top:14px}#mcp-find{margin-top:14px}#reg-form{margin:6px 0}#reg-form input{flex:1 1 20em;font:inherit;font-size:13px;
padding:6px 10px;border:1px solid var(--edge);border-radius:8px;background:var(--page);color:var(--ink)}
.sk.reg{cursor:default}.sk.reg:hover{transform:none}.sk.reg .acts{display:flex;flex-wrap:wrap;gap:4px}.sk.reg .meta a{margin-right:8px}#mcp-form label.wide{display:flex;flex-direction:column;gap:4px;font-size:13px;margin:0 0 8px}
#mcp-form input,#mcp-form textarea,#mcp-form select{font:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--edge);border-radius:8px;
background:var(--surface);color:var(--ink);min-width:0}#mcp-form textarea{font-family:var(--mono)}
.pair{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 6px}
#mcp-form .namefield{flex:1 1 20em;display:flex;align-items:center;gap:8px;font-size:13px}#mcp-form .namefield input{flex:1;min-width:12em}.pair input{flex:1 1 12em}
.ask{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:10px 0;padding:10px 12px;border:1px solid var(--mark);border-radius:10px;
background:color-mix(in oklch,var(--mark) 9%,var(--surface));animation:reveal .2s var(--ease) both}.ask p{margin:0;flex:1 1 20em}.ask .acts{display:flex;gap:8px}
.busy{position:relative;padding-left:30px!important;opacity:.9;cursor:progress}
.busy::before{content:"";position:absolute;left:11px;top:50%;width:11px;height:11px;margin-top:-7px;border:2px solid currentColor;border-right-color:transparent;
border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.spin{display:inline-block;width:12px;height:12px;margin-right:7px;vertical-align:-1px;border:2px solid var(--mark);border-right-color:transparent;
border-radius:50%;animation:spin .8s linear infinite}
.runbar{height:4px;border-radius:2px;background:var(--track);overflow:hidden;margin:14px 0 10px}
.runbar i{display:block;width:35%;height:100%;border-radius:2px;background:var(--mark);animation:slide 1.6s var(--ease) infinite}
@keyframes slide{from{transform:translateX(-100%)}to{transform:translateX(290%)}}.runline{margin:0 0 8px}.runline b{font-variant-numeric:tabular-nums}
p.warn{color:var(--agent-ink);font-size:13px}
ol.steps{list-style:none;margin:6px 0 0;padding:0;max-height:360px;overflow-y:auto;font-size:12.5px}
ol.steps li{display:flex;gap:10px;padding:4px 0;border-bottom:1px solid var(--grid)}ol.steps span{min-width:0;overflow-wrap:anywhere}
ol.steps time{flex:none;width:5.5em;color:var(--muted);font:12px var(--mono)}ol.steps li.sub span{padding-left:16px;color:var(--ink2)}
ol.steps li.say span{color:var(--ink2);font-style:italic}ol.steps li:is(.error,.denied) span{color:var(--fail)}ol.steps li.retry span{color:var(--agent-ink)}
ol.steps li.start span,ol.steps li.end span{font-weight:600}
.outcome{display:flex;flex-direction:column;gap:4px;margin:12px 0 6px;padding:12px 14px;border:1px solid var(--edge);border-radius:10px;
animation:reveal .3s var(--ease) both}.outcome b{font-size:15px}.outcome span{overflow-wrap:anywhere}
.outcome.ok{background:color-mix(in oklch,var(--pass) 12%,transparent);border-color:color-mix(in oklch,var(--pass) 45%,transparent)}
.outcome.bad{background:color-mix(in oklch,var(--fail) 12%,transparent);border-color:color-mix(in oklch,var(--fail) 45%,transparent)}
.outcome.off{background:var(--chip)}
a.outcome.run{color:var(--ink);text-decoration:none;background:color-mix(in oklch,var(--mark) 9%,var(--surface));border-color:var(--mark);margin:-4px 0 14px}
a.outcome.run:hover{background:color-mix(in oklch,var(--mark) 15%,var(--surface))}
@media (prefers-reduced-motion:reduce){.runbar i,.spin,.busy::before{animation:none}}
.cmp .viewbar{margin-bottom:8px}.cmp .path{margin:0}
table.sbs{width:100%;table-layout:fixed;border-collapse:collapse;font:12.5px/1.5 var(--mono)}table.sbs col.n{width:3.2em}
table.sbs th{text-align:left;font:600 12px var(--sans)}table.sbs td{vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere;
padding:1px 6px;border-bottom:0;text-align:left}table.sbs td.n{color:var(--muted);text-align:right;user-select:none;padding-right:8px}
table.sbs td.del{background:color-mix(in oklch,var(--fail) 12%,transparent)}table.sbs td.add{background:color-mix(in oklch,var(--pass) 12%,transparent)}
table.sbs td.gap{background:repeating-linear-gradient(135deg,transparent 0 6px,var(--chip) 6px 8px)}
table.sbs td.del mark{background:color-mix(in oklch,var(--fail) 32%,transparent);color:inherit;border-radius:2px}
table.sbs td.add mark{background:color-mix(in oklch,var(--pass) 34%,transparent);color:inherit;border-radius:2px}
table.sbs tr.fold td{color:var(--muted);text-align:center;font-family:var(--sans);background:var(--page);padding:3px}
@media (max-width:700px){table.sbs col.n{width:2.4em}table.sbs{font-size:11.5px}}
/* the decision stays in sight while you read the comparison */
.decide{position:sticky;bottom:12px;z-index:6;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between;
margin:14px 0 0;padding:10px 14px;border:1px solid var(--mark);border-radius:12px;background:var(--surface);
box-shadow:0 10px 30px -12px color-mix(in oklch,var(--ink) 45%,transparent);animation:reveal .3s var(--ease) both}
.decide .note{margin-left:6px}.decide .acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.btn.danger{color:var(--fail)}.btn.danger:hover{background:color-mix(in oklch,var(--fail) 14%,transparent)}
#bench .verdict{font-size:14px;margin:6px 0 10px}#bench-form{margin:10px 0}#bench-form select{font:inherit;font-size:13px;padding:5px 8px;
border:1px solid var(--edge);border-radius:8px;background:var(--surface);color:var(--ink);max-width:100%}
#task-form label.wide{display:flex;flex-direction:column;gap:4px;font-size:13px;margin:0 0 8px}
#task-form input,#task-form textarea{font:inherit;font-size:13px;padding:6px 8px;border:1px solid var(--edge);border-radius:8px;background:var(--surface);color:var(--ink)}
#task-form textarea{font-family:var(--mono)}#task-new{margin-top:10px}
table.bres td:not(:first-child),table.bres th:not(:first-child){text-align:right}table.bres td:last-child,table.bres th:last-child{text-align:left}
details.more#optimize-panel{margin:-4px 0 14px}.optform{display:flex;flex-direction:column;gap:8px}.opt{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.opt .note{margin:0}.optrow{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.optrow select,.optrow input{font:inherit;font-size:13px;padding:5px 8px;border:1px solid var(--edge);border-radius:8px;background:var(--surface);color:var(--ink)}
.optrow input{width:6em}select option{background:var(--surface);color:var(--ink)}.err{color:var(--fail);font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere}.sub3{font-size:13px;margin:14px 0 6px}
.state{font-size:12px;padding:1px 8px;border-radius:999px;background:var(--chip);color:var(--ink2)}.state.done,.state.applied{color:var(--pass)}
.state.failed,.state.interrupted{color:var(--fail)}.state.running{color:var(--mark-ink)}#job table{margin:10px 0}
.fm{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 14px;font-size:12.5px;background:var(--page);border:1px solid var(--edge);
border-radius:8px;padding:10px 12px;margin:0 0 16px}.fm dt{color:var(--muted)}.fm dd{margin:0}
"""

SKIN_APPLY = ("<script>try{if(localStorage.getItem('tokscope-skin')==='classic'){"
              "document.getElementById('skin-ink').media='not all';document.getElementById('skin-classic').media='all';"
              "document.documentElement.dataset.skin='classic'}}catch(_){}</script>")
SKIN_BUTTON = ('<button type="button" class="chip" id="skin" aria-pressed="false" '
               'title="Switch between the Classic and Ink designs">Classic</button>')
