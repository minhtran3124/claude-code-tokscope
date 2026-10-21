"""Static HTML report: the important numbers up front, everything else in expandable sections. Tokens first, USD second."""

import html
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from . import charts, fonts, paths, privacy, skills
from .brand import MARK, favicon_link
from .calls import est_tokens, mcp_server, turn_calls
from .changes import BENCH_PROJECT, impact, list_changes
from .ingest import CARRIED, connect
from .pricing import API_EQ_NOTE, COSTS_DOC

TOKENS = "(input + cache_read + cache_write_5m + cache_write_1h + output)"

CSS = """
:root{--page:#f2efe7;--surface:#fbf9f4;--ink:#231e16;--ink2:#4a4337;--muted:#665e51;--grid:#ddd6c8;--edge:#bfb6a6;--mark:#76a0e2;--agent:#f4b829;--mark-ink:#2f5aa8;--agent-ink:#8a5a00;
--tint:#e4ebf7;--track:#ebe6db;--c1:var(--mark);--c2:var(--agent);--c3:#d9708c;--c4:#4a4337;--c5:#8a8172;--c0:#bdb4a4;--chip:#ebe6db;--hl:#fbe6a6;--pass:#1a6934;--fail:#a33a23;
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
:focus-visible{outline:2px solid var(--ink);outline-offset:2px;border-radius:4px}
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
.tools input[type=search]:focus,.tools select:focus{outline:none;border-color:var(--ink);box-shadow:0 0 0 3px color-mix(in oklch,var(--ink) 22%,transparent)}
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
.srow>summary:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
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
.brand{font-weight:600;font-size:13px;color:var(--ink);margin:0 0 14px 10px;display:flex;align-items:center;gap:7px}
.brand .logo{width:24px;height:15px;flex:none;position:relative;top:-1px}
.toc{display:flex;flex-direction:column;gap:2px}
.toc a{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 10px;border-radius:8px;color:var(--ink2);text-decoration:none;
font-size:14px;transition:background .15s var(--ease),color .15s var(--ease),transform .15s var(--ease)}
.toc a:hover{background:color-mix(in oklch,var(--mark) 10%,transparent);color:var(--ink);transform:translateX(2px)}
.toc a.on{background:color-mix(in oklch,var(--mark) 15%,transparent);color:var(--mark-ink);font-weight:600}
.toc a:focus-visible{outline:2px solid var(--ink);outline-offset:1px}
.sub-toc{display:flex;flex-direction:column;gap:1px;margin:2px 0 4px 14px;padding-left:6px;border-left:1px solid var(--grid)}
.sub-toc a{font-size:13px;padding:4px 10px}
.cnt{font-size:11px;font-weight:400;color:var(--muted);font-variant-numeric:tabular-nums;background:var(--chip);padding:1px 7px;border-radius:999px}
[id]{scroll-margin-top:16px}
.totop{position:fixed;right:22px;bottom:22px;z-index:25;width:44px;height:44px;border-radius:50%;font:700 18px/1 inherit;
border:1px solid color-mix(in oklch,var(--mark) 40%,var(--edge));background:var(--surface);color:var(--mark-ink);box-shadow:0 8px 22px -10px #0006;
opacity:0;visibility:hidden;transform:translateY(10px);
transition:opacity .2s var(--ease),transform .2s var(--ease),visibility .2s,bottom .2s var(--ease),background .15s var(--ease),color .15s var(--ease)}
.totop.show{opacity:1;visibility:visible;transform:none}
.totop.show:hover{background:var(--ink);color:var(--page);transform:translateY(-2px)}
.totop:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
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
.primary{all:unset;cursor:pointer;font-weight:600;font-size:13px;padding:6px 14px;border-radius:8px;background:var(--ink);color:var(--page);
transition:transform .15s var(--ease),box-shadow .15s var(--ease),opacity .15s var(--ease)}
.primary:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 6px 16px -6px var(--mark)}.primary:active:not(:disabled){transform:none}
.primary:focus-visible{outline:2px solid var(--ink);outline-offset:2px}.primary:disabled{opacity:.45;cursor:not-allowed}
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
.chip:hover{border-color:var(--mark);color:var(--mark-ink)}.chip:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
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
/* breakdown charts: categorical slots in both modes (cobalt, mustard, blush, dark ink tint, mid ink tint); --c0 is "Other",
the palest tint; neighbours in the share bar differ by at least 1.5:1 in luminance */
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
""".replace("SANS", fonts.SANS).replace("MONO", fonts.MONO).replace("DARK", "--page:#1d1a15;--surface:#27231c;--ink:#f2efe7;--ink2:#d6cfc2;--muted:#b0a796;--grid:#3b3529;--edge:#4f4739;--mark:#76a0e2;--agent:#f4b829;--mark-ink:#8fb3ec;--agent-ink:#f4b829;--tint:#25304a;--track:#332e25;--chip:#332e25;--hl:#5a4500;--pass:#93d3b0;--fail:#f08a70;--c3:#c4607d;--c4:#d6cfc2;--c5:#8f8676;--c0:#5e5649;color-scheme:dark")

# the page script in parts: every page takes JS_CORE; the report takes them all, a dashboard page only its own
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
    usd:v=>'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}[el.dataset.kind]||fmt;
  const run=el._run=(el._run||0)+1;
  el.textContent=f(0);setTimeout(()=>{const t0=performance.now();const step=now=>{if(el._run!==run)return;const p=Math.min(1,Math.max(0,(now-t0)/dur));
    el.textContent=p<1?f(raw*(1-Math.pow(1-p,4))):end;if(p<1)requestAnimationFrame(step)};requestAnimationFrame(step)},delay)}
document.querySelectorAll('[data-count]').forEach((el,k)=>countUp(el,150+k*70));
document.querySelectorAll('.kpi,.hero,.changes .card').forEach(el=>el.addEventListener('pointermove',e=>{const r=el.getBoundingClientRect();
  el.style.setProperty('--mx',(e.clientX-r.left)+'px');el.style.setProperty('--my',(e.clientY-r.top)+'px')}));
const root=document.documentElement;
const isDark=()=>root.dataset.theme?root.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;
const themeBtn=document.getElementById('theme');
function syncTheme(){themeBtn.innerHTML=(isDark()?'☀ Light':'☾ Dark')+' <kbd>t</kbd>'}
// the new theme grows out of the button as a circle, where the browser has view transitions
function toggleTheme(x,y){const apply=()=>{root.dataset.theme=isDark()?'light':'dark';try{localStorage.setItem('tokscope-theme',root.dataset.theme)}catch(_){};syncTheme()};
  if(!document.startViewTransition||!smoothOk())return apply();
  const r=Math.hypot(Math.max(x,innerWidth-x),Math.max(y,innerHeight-y));
  document.startViewTransition(apply).ready.then(()=>root.animate({clipPath:[`circle(0px at ${x}px ${y}px)`,`circle(${r}px at ${x}px ${y}px)`]},
    {duration:650,easing:'cubic-bezier(0.16,1,0.3,1)',pseudoElement:'::view-transition-new(root)'}))}
themeBtn.addEventListener('click',e=>{const b=themeBtn.getBoundingClientRect();toggleTheme(e.clientX||b.left+b.width/2,e.clientY||b.top+b.height/2)});syncTheme();
const io='IntersectionObserver' in window?new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}}),{rootMargin:'0px 0px -6% 0px'}):null;
document.querySelectorAll('.reveal,main>details.more,#breakdowns>details').forEach(el=>{el.classList.add('reveal');io?io.observe(el):el.classList.add('in')});
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// keyboard: t theme, g top, ? this list; pages add their own keys
const keysDlg=document.getElementById('keys');
addEventListener('keydown',e=>{const typing=/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
  if(typing||e.metaKey||e.ctrlKey||e.altKey)return;
  if(e.key==='t'){const b=themeBtn.getBoundingClientRect();toggleTheme(b.left+b.width/2,b.top+b.height/2)}
  else if(e.key==='g')scrollTo({top:0})
  else if(e.key==='?'){keysDlg.open?keysDlg.close():keysDlg.showModal()}});
document.getElementById('keys-btn').addEventListener('click',()=>keysDlg.showModal());
keysDlg.addEventListener('click',e=>{if(e.target===keysDlg)keysDlg.close()});
"""
JS_SESSIONS = """
const S=JSON.parse(document.getElementById('sessions-data').textContent);
const list=document.getElementById('session-list'),q=document.getElementById('s-q'),sortSel=document.getElementById('s-sort');
const picked=new Set();let limit=15;
// wraps each match of the filter in <mark>, after escaping
const hl=(text,needle)=>{if(!needle)return esc(text);const lo=text.toLowerCase(),n=needle.toLowerCase();let out='',pos=0,at;
  while((at=lo.indexOf(n,pos))>-1){out+=esc(text.slice(pos,at))+'<mark>'+esc(text.slice(at,at+n.length))+'</mark>';pos=at+n.length}
  return out+esc(text.slice(pos))};
function split(main,ag){const t=Math.max(main+ag,1);return `<span class=split title="main ${fmt(main)} · subagents ${fmt(ag)}"><u style="width:${(100*main/t).toFixed(1)}%"></u>${ag?`<u class=a style="width:${(100*ag/t).toFixed(1)}%"></u>`:''}</span>`}
function row(s){
  const d=document.createElement('details');d.className='srow'+(picked.has(s.id)?' picked':'');d.dataset.id=s.id;
  d.innerHTML=`<summary><input type=checkbox aria-label="compare" ${picked.has(s.id)?'checked':''}>
    <span class=d>${s.start.slice(0,10)}</span><span class=t title="${esc(s.title)}">${s.title?hl(s.title,q.value.trim()):'(untitled)'}</span>
    <span class=r><b>${fmt(s.tokens)}</b></span>${split(s.main,s.agents)}<span class="r n">${s.prompts} prompts</span><span class=sk>${esc(s.top_skill||'')}</span><span class=cv aria-hidden=true>›</span></summary><div class=body></div>`;
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
function ids(s){return `<dl class=ids>${[['Session ID',s.id],['Trace',`tokscope session ${s.id} --json`],['Transcript',s.path],['Resume',`claude --resume ${s.id}`]]
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
  const top=Math.max(...s.turns.map(t=>t.tokens),1);
  const turns=s.turns.map((t,k)=>`<tr><td data-label="#">${t.i??'–'}</td><td class=l data-label="prompt">${esc(t.text||(t.i===0?'(session start)':''))}</td>
    <td class=lm data-label="skill">${esc(t.skill||'')}${t.version?` <code class=ver title="${t.version[1]?'exact: hashed at the Skill call':'inferred from the kept text or the date'} · tokscope skills ${esc(t.skill)}">${esc(t.version[0].slice(0,6))}</code>`:''}</td><td data-label="tokens">${bar(t.tokens,top,t.agents_tokens,Math.min(k,12))}</td><td data-label="output">${fmt(t.output)}</td>
    <td data-label="req">${t.requests}</td><td class="lm calls" data-label="calls">${callCell(t)}</td><td class=u data-label="API-eq">${usd(t.usd)}</td></tr>${runsRow(t.runs)}`).join('');
  return `${ids(s)}<p class=note>${s.start.replace('T',' ').slice(0,16)} → ${s.end.replace('T',' ').slice(11,16)} UTC · ${esc(s.project)} ·
    main thread <span data-count="${s.main}">${fmt(s.main)}</span> · subagents <span data-count="${s.agents}">${fmt(s.agents)}</span> (${s.runs} runs) · output <span data-count="${s.output}">${fmt(s.output)}</span> · <span class=usd>${usd(s.usd)} API-eq</span></p>
    <div class=scroll><table><tr><th>#</th><th style="text-align:left">prompt</th><th style="text-align:left">skill</th><th>tokens</th><th>output</th><th title="model requests">req</th><th style="text-align:left">calls</th><th>API-eq</th></tr>${turns}</table></div>
    <p class=note>calls: subagent tokens are measured; MCP and tool tokens marked ~ are estimated from the size of the result each call put into the context.</p>`}
// rows are kept by id so a re-render moves them (FLIP): kept rows slide from where they were,
// new rows rise in one after another, and rows that leave fade out in place
const nodes=new Map(),EXPO='cubic-bezier(0.16,1,0.3,1)';
function render(){
  const needle=q.value.toLowerCase();
  let rows=S.filter(s=>!needle||(s.title||'').toLowerCase().includes(needle)||s.id.startsWith(needle)||(s.top_skill||'').includes(needle));
  rows.sort(sortSel.value==='tokens'?(a,b)=>b.tokens-a.tokens:(a,b)=>b.start.localeCompare(a.start));
  const shown=rows.slice(0,limit),keep=new Set(shown.map(s=>s.id)),anim=smoothOk(),before=new Map();
  let top=list.getBoundingClientRect().top;
  if(anim)list.querySelectorAll(':scope>.srow:not(.ghost)').forEach(el=>{before.set(el.dataset.id,el.getBoundingClientRect().top-top);el.getAnimations().forEach(a=>a.cancel())});
  const els=shown.map(s=>{let el=nodes.get(s.id);
    if(!el){el=row(s);nodes.set(s.id,el)}
    else{el.getAnimations().forEach(a=>a.cancel());el.classList.remove('ghost');el.style.top='';
      el.querySelector('.t').innerHTML=s.title?hl(s.title,q.value.trim()):'(untitled)';
      el.classList.toggle('picked',picked.has(s.id));el.querySelector('input').checked=picked.has(s.id)}
    return el});
  list.replaceChildren(...els);
  if(!rows.length){list.innerHTML=`<div class=empty><b>No sessions match “${esc(q.value)}”</b>Try part of a title, a skill name or the start of a session id.
    <p><button type=button class=btn id=s-clear>Clear the filter</button></p></div>`;
    document.getElementById('s-clear').addEventListener('click',()=>{q.value='';render();q.focus()})}
  if(anim){top=list.getBoundingClientRect().top;const vh=innerHeight,seen=y=>y+top>-200&&y+top<vh+200;let k=0;
    // new rows wait for the leaving ones to clear so the two never show text over each other
    const wait=[...before.keys()].some(id=>!keep.has(id)&&seen(before.get(id)))?150:0;
    els.forEach(el=>{const now=el.getBoundingClientRect().top-top,was=before.get(el.dataset.id);
      if(!seen(now)&&(was==null||!seen(was)))return;
      if(was==null)el.animate([{opacity:0,transform:'translateY(10px) scale(.985)'},{opacity:1,transform:'none'}],
        {duration:420,delay:wait+Math.min(k++,24)*22,easing:EXPO,fill:'backwards'});
      else if(Math.abs(was-now)>1)el.animate([{transform:`translateY(${was-now}px)`},{transform:'none'}],{duration:480,easing:EXPO})});
    before.forEach((y,id)=>{if(keep.has(id)||!seen(y))return;const el=nodes.get(id);
      el.classList.add('ghost');el.style.top=y+'px';list.append(el);
      el.animate([{opacity:1},{opacity:0,transform:'scale(.97)'}],{duration:160,easing:'ease-out',fill:'forwards'})
        .finished.then(()=>{if(el.classList.contains('ghost'))el.remove()},()=>{})})}
  const more=document.getElementById('s-more');more.hidden=rows.length<=limit;more.textContent=`Show ${Math.min(rows.length-limit,50)} more`;
  document.getElementById('s-count').textContent=`showing ${Math.min(limit,rows.length)} of ${rows.length}`}
document.getElementById('s-more').addEventListener('click',()=>{limit+=50;render()});
q.addEventListener('input',()=>{limit=15;render()});
list.addEventListener('click',e=>{const b=e.target.closest('.cp');if(!b)return;
  navigator.clipboard.writeText(b.dataset.copy).then(()=>{b.textContent='Copied ✓';b.classList.add('ok');toast('Copied to the clipboard');
    setTimeout(()=>{b.textContent='Copy';b.classList.remove('ok')},1400)},
    ()=>getSelection().selectAllChildren(b.previousElementSibling))});sortSel.addEventListener('change',render);render();
function renderCompare(){
  const box=document.getElementById('compare'),sel=S.filter(s=>picked.has(s.id));
  if(sel.length<2)return;
  const keys=(f,n)=>{const tot={};sel.forEach(s=>Object.entries(s[f]).forEach(([k,v])=>tot[k]=(tot[k]||0)+v));return Object.entries(tot).sort((a,b)=>b[1]-a[1]).slice(0,n).map(e=>e[0])};
  const line=(label,vals,low)=>{const nums=vals.map(v=>typeof v==='number'?v:null).filter(v=>v!=null),best=low&&nums.length?Math.min(...nums):null;
    return `<tr><td>${label}</td>${vals.map(v=>`<td>${typeof v==='number'?(v===best?'<b>'+fmt(v)+'</b>':fmt(v)):esc(v)}</td>`).join('')}</tr>`};
  let h=`<tr><th></th>${sel.map(s=>`<th title="${esc(s.title)}">${esc((s.title||'').slice(0,26))}<br><span class=usd>${s.id.slice(0,8)}</span></th>`).join('')}</tr>`;
  h+=line('started',sel.map(s=>s.start.slice(0,10)));h+=line('prompts',sel.map(s=>s.prompts));
  h+=line('tokens',sel.map(s=>s.tokens),1);h+=line('tokens per prompt',sel.map(s=>s.tokens/Math.max(s.prompts,1)),1);
  h+=line('output tokens',sel.map(s=>s.output),1);h+=line('subagent runs',sel.map(s=>s.runs));
  h+=`<tr><td class=u>API-eq</td>${sel.map(s=>`<td class=u>${usd(s.usd)}</td>`).join('')}</tr>`;
  h+=`<tr><th colspan=${sel.length+1} style="text-align:left">tokens by owner</th></tr>`;
  keys('owners',8).forEach(k=>h+=line(k,sel.map(s=>s.owners[k]||0)));
  h+=`<tr><th colspan=${sel.length+1} style="text-align:left">tokens by skill</th></tr>`;
  keys('skills',8).forEach(k=>h+=line(k,sel.map(s=>s.skills[k]||0)));
  box.querySelector('table').innerHTML=h}
// selecting only builds the pick list; the comparison runs when Compare is pressed
const box=document.getElementById('compare'),pickBar=document.getElementById('pickbar'),go=document.getElementById('do-compare');
function updatePick(){
  const n=picked.size;pickBar.hidden=!n;document.body.classList.toggle('picking',n>0);go.disabled=n<2;go.textContent=n>=2?`Compare ${n} sessions`:'Compare';
  document.getElementById('pick-hint').textContent=n<2?`${n} selected · pick at least one more`:`${n} selected · max 4`;
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
JS = JS_CORE + JS_SESSIONS + JS_TOC + JS_TREND + JS_BENCH


_tok = charts.tok


def _usd(v):
    return "–" if v is None else f"${v:,.2f}"


def _bar(value, top):
    pct = 0 if not top else max(1.5, 100 * (value or 0) / top)
    return f'<span class="bar">{_tok(value)}<i><u style="width:{pct:.1f}%"></u></i></span>'


def _table(headers, rows, bar_col):
    """Cells: plain values, or (text, css class) tuples; class "raw" is pre-escaped HTML. The bar column holds tokens."""
    top = max((r[bar_col] or 0 for r in rows), default=0)
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = []
    for r in rows:
        cells = []
        for i, v in enumerate(r):
            # data-label names the column when a phone-width card stacks the table into one block per row
            label = f' data-label="{html.escape(headers[i])}"' if i < len(headers) else ""
            if i == bar_col:
                cells.append(f"<td{label}>{_bar(v, top)}</td>")
            elif isinstance(v, tuple):
                cells.append(f'<td class="{v[1]}"{label}>{v[0] if v[1] == "raw" else html.escape(str(v[0]))}</td>')
            else:
                # a long first-column name wraps on a narrow card; the title repeats it on hover
                title = f' title="{html.escape(str(v))}"' if i == 0 else ""
                cells.append(f"<td{title}{label}>{html.escape(str(v))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><tr>{head}</tr>{''.join(body)}</table>"


def _more(title, note, inner, anchor="", is_open=False):
    """A collapsed section: the summary line is all that shows until it is opened."""
    ident = f' id="{anchor}"' if anchor else ""
    return (f'<details class="more"{ident}{" open" if is_open else ""}><summary><span class="ttl">{title}</span>'
            f'<span class="note">{note}</span></summary>{inner}</details>')


def _daily_chart(days, changes):
    if not days:
        return "<p class='note'>No data.</p>"
    w, h, pad_l, pad_b, pad_t = 1100, 230, 56, 22, 18
    top = max(t for _, t, _ in days) or 1
    step = (w - pad_l) / len(days)
    bw = max(2, step - 2)
    index = {d: i for i, (d, _, _) in enumerate(days)}
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Tokens per day">'
           '<defs><linearGradient id="barfill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--mark)"/>'
           '<stop offset="1" style="stop-color:var(--mark);stop-opacity:.45"/></linearGradient></defs>'
           f'<line class="guide" x1="0" x2="0" y1="{pad_t}" y2="{h - pad_b}"/>']
    for frac in (0, 0.5, 1):
        y = pad_t + (h - pad_t - pad_b) * (1 - frac)
        out.append(f'<line class="g" x1="{pad_l}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end">{_tok(top * frac)}</text>')
    for i, (day, tokens, usd) in enumerate(days):
        x = pad_l + i * step
        bh = (h - pad_t - pad_b) * tokens / top
        tip = html.escape(f"<b>{day}</b><br>{_tok(tokens)} tokens<br><span class='usd'>{_usd(usd)} API-eq</span>")
        out.append(
            f'<g class="d" data-tip="{tip}"><rect class="hit" x="{x:.1f}" y="{pad_t}" width="{step:.1f}" height="{h - pad_t - pad_b}"/>'
            f'<rect class="m" fill="url(#barfill)" style="--i:{i}" x="{x:.1f}" y="{h - pad_b - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2"/></g>')
        if i % max(1, len(days) // 8) == 0:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{h - 6}" text-anchor="middle">{day[5:]}</text>')
    # 7-day trailing average, so a single heavy day does not read as a trend
    vals = [t for _, t, _ in days]
    pts = []
    for i in range(len(days)):
        window = vals[max(0, i - 6):i + 1]
        avg = sum(window) / len(window)
        pts.append(f"{pad_l + i * step + bw / 2:.1f},{h - pad_b - (h - pad_t - pad_b) * avg / top:.1f}")
    if len(pts) > 1:
        out.append(f'<polyline class="ma" pathLength="1" points="{" ".join(pts)}"/>')
    for cid, at, note, *_ in changes:
        i = index.get(at[:10])
        if i is None:
            continue
        x = pad_l + i * step + bw / 2
        tip = html.escape(f"<b>change #{cid}</b><br>{html.escape(note)}")
        out.append(f'<g data-change="{cid}" data-tip="{tip}" style="cursor:pointer"><line class="chg" x1="{x:.1f}" x2="{x:.1f}" '
                   f'y1="{pad_t - 6}" y2="{h - pad_b}"/><text class="chg-l" x="{x + 4:.1f}" y="{pad_t - 6}">#{cid}</text></g>')
    out.append("</svg>")
    return "".join(out)


FEW_LOADS = 5  # below this many loads a version's median says little
FEW_TAG = ' <span class="few" title="too few loads to judge">few</span>'


def _diff_html(lines):
    cls = lambda l: "add" if l.startswith("+") and not l.startswith("+++") else "del" if l.startswith("-") and not l.startswith("---") \
        else "hunk" if l.startswith(("@@", "+++", "---")) else ""  # noqa: E731
    return "<pre class='diff'>" + "\n".join(f"<span class='{cls(l)}'>{html.escape(l)}</span>" if cls(l) else html.escape(l)
                                            for l in lines) + "</pre>"


def _vs(before, after):
    if not before or after is None:
        return "–"
    pct = after / before - 1
    return f"{'▲' if pct > 0 else '▼'} {abs(pct):.0%}"


def _loads(n):
    return (f"{n}{FEW_TAG if n and n < FEW_LOADS else ''}", "raw")


def _skill_versions(conn, level="full"):
    """(skills with two or more tracked versions, HTML). A changed skill gets a card: each version's loads and median
    tokens per load, the change from the version before, and the diff between them. A skill with one tracked version
    and loads from before tracking goes in one table that compares the two. Diffs read kept files: full report only."""
    by_skill = {}
    for r in skills.versions(conn):
        if r["loads"] or r["version"]:
            by_skill.setdefault(r["skill"], []).append(r)
    if not by_skill:
        return 0, ("<p class='note'>No skill versions yet. They are recorded when the mod sees a Skill call and on each "
                   "<code>tokscope ingest</code>.</p>")
    tracked = lambda vs: [v for v in vs if v["version"]]  # noqa: E731
    weight = lambda vs: -sum((v["tokens_median"] or 0) * v["loads"] for v in vs)  # noqa: E731
    changed = {k: vs for k, vs in by_skill.items() if len(tracked(vs)) > 1}
    started = {k: vs for k, vs in by_skill.items() if len(tracked(vs)) == 1 and len(vs) == 2}
    rest = [k for k in by_skill if k not in changed and k not in started]
    single = sorted(k for k in rest if tracked(by_skill[k]))
    unknown = sorted(k for k in rest if not tracked(by_skill[k]))  # loaded, but no folder to hash
    cards = []
    for name, vs in sorted(changed.items(), key=lambda kv: weight(kv[1])):
        rows, prev = [], None
        for v in vs:
            label = f" v{v['label']}" if v["label"] else ""
            rows.append(((f"<code>{html.escape(v['version'] or 'before tracking')}</code>{html.escape(label)}", "raw"),
                         (v["first_seen"] or "")[:10] or "–", _loads(v["loads"]), v["exact"], v["tokens_median"] or 0,
                         _vs(prev, v["tokens_median"])))
            prev = v["tokens_median"] if v["tokens_median"] is not None else prev
        diffs = []
        versions = [v["version"] for v in tracked(vs)]
        for old, new in zip(versions, versions[1:]) if level == "full" else []:
            lines = skills.diff(name, old, new)
            if lines is None:
                continue
            added = sum(x.startswith("+") and not x.startswith("+++") for x in lines)
            removed = sum(x.startswith("-") and not x.startswith("---") for x in lines)
            diffs.append(f"<details class='vdiff'><summary>Diff <code>{old}</code> → <code>{new}</code> "
                         f"<span class='note'>{added} added, {removed} removed</span></summary>"
                         f"{_diff_html(lines) if lines else '<p class=note>Same text; only file names changed.</p>'}</details>")
        cards.append(f'<section class="card" id="v-{html.escape(name)}"><h3>{html.escape(name)}</h3>'
                     + _table(["version", "first seen", "loads", "exact", "median tokens / load", "vs before"], rows, 4)
                     + "".join(diffs) + "</section>")
    parts = ["<h3>Changed</h3>" + "".join(cards) if cards else
             "<p class='note'>No skill has changed since tracking began. Edit one and its next load shows here, with the diff.</p>"]
    if started:
        rows = []
        # skills loaded since tracking began first: those are the ones with a comparison
        for name, (before, now) in sorted(started.items(), key=lambda kv: (not kv[1][1]["loads"], weight(kv[1]))):
            rows.append((name, _loads(before["loads"]), _tok(before["tokens_median"]) if before["tokens_median"] else "–",
                         (f"<code>{html.escape(now['version'])}</code>", "raw"), (now["first_seen"] or "")[:10],
                         _loads(now["loads"]), now["tokens_median"] or 0, _vs(before["tokens_median"], now["tokens_median"])))
        parts.append("<h3>Tracking started</h3><p class='note'>Loads from before tokscope saw the skill against its current "
                     "version. The older loads may span several unknown versions.</p>"
                     + _table(["skill", "loads before", "median before", "version now", "since", "loads", "median tokens / load",
                               "vs before"], rows, 6))
    if single:
        parts.append(f"<p class='note'>One version, every load tracked: {html.escape(', '.join(single))}.</p>")
    if unknown:
        parts.append(f"<p class='note'>No folder found, so no version (built into Claude Code and not unpacked, or deleted): "
                     f"{html.escape(', '.join(unknown))}.</p>")
    return len(changed), f'<div class="versions">{"".join(parts)}</div>'


def _change_cards(conn, changes):
    if not changes:
        return ('<p class="note">No changes recorded. After editing an agent or skill, run '
                '<code>tokscope change "reviewer: fable -&gt; opus" --agent reviewer</code>.</p>')
    cards = []
    for change in changes:
        cid, at, note, agent_type, skill = change
        r = impact(conn, change)
        b, a = r["before"], r["after"]
        unit = "subagent run" if agent_type else "skill load"
        if b["n"] and a["n"] and b["tokens_median"]:
            pct = a["tokens_median"] / b["tokens_median"] - 1
            delta = f'<div class="delta">{pct:+.0%}</div><div class="note">median tokens per {unit}</div>'
        else:
            delta = f'<div class="note">Not enough {unit}s on both sides yet.</div>'
        rows = [(side, s["n"], s.get("tokens_median", 0), _tok(s.get("output_median", 0)), (_usd(s.get("usd_median")), "u"),
                 (", ".join(m.removeprefix("claude-") for m in s.get("models", [])), "lm"))
                for side, s in (("before", b), ("after", a))]
        cards.append(
            f'<section class="card" id="change-{cid}"><h3>#{cid} · {html.escape(note)}</h3>'
            f'<p class="note">{at[:16].replace("T", " ")} UTC · {html.escape(agent_type or skill)} · ±{r["window_days"]} days</p>{delta}'
            + _table(["window", "n", "tokens (median)", "output", "API-eq", "models"], rows, 2) + "</section>")
    return f'<div class="changes">{"".join(cards)}</div>'


def _sessions_json(conn, cond, params):
    base = f"FROM requests r JOIN sessions s USING (session_id) {cond}"
    sessions = {}
    for sid, proj, title, start, end, prompts, cwd, tokens, out, usd, main, agents, runs in conn.execute(
            f"""SELECT session_id, s.project, s.title, s.first_ts, s.last_ts, s.prompts, s.cwd, sum({TOKENS}), sum(output), sum(cost_usd),
                       sum(CASE WHEN agent_id IS NULL THEN {TOKENS} END), sum(CASE WHEN agent_id IS NOT NULL THEN {TOKENS} END),
                       count(DISTINCT agent_id) {base} GROUP BY session_id""", params):
        sessions[sid] = {"id": sid, "title": title or "", "start": start or "", "end": end or "", "prompts": prompts or 0,
                         "project": Path(cwd or "").name, "path": f"~/.claude/projects/{proj}/{sid}.jsonl", "tokens": tokens or 0, "output": out or 0, "usd": usd,
                         "main": main or 0, "agents": agents or 0, "runs": runs, "owners": {}, "skills": {}, "turns": []}
    for sid, owner, tk in conn.execute(
            f"SELECT session_id, COALESCE(agent_type, 'main thread'), sum({TOKENS}) {base} GROUP BY 1, 2", params):
        sessions[sid]["owners"][owner] = tk or 0
    for sid, skill, tk in conn.execute(
            f"SELECT session_id, skill, sum({TOKENS}) {base} AND skill IS NOT NULL GROUP BY 1, 2", params):
        sessions[sid]["skills"][skill] = tk or 0
    texts = {(sid, i): text for sid, i, text in conn.execute("SELECT session_id, prompt_idx, text FROM prompts")}
    agents = {}
    for sid, i, atype, models in conn.execute(
            f"SELECT session_id, prompt_idx, agent_type, group_concat(DISTINCT model) {base} AND agent_id IS NOT NULL "
            f"GROUP BY session_id, prompt_idx, agent_id", params):
        per = agents.setdefault((sid, i), {})
        a = per.setdefault(atype, {"type": atype, "n": 0, "models": set()})
        a["n"] += 1
        a["models"].update(m.removeprefix("claude-") for m in (models or "").split(",") if m)
    calls = turn_calls(conn)
    versions = skills.turn_versions(conn)
    for sid, i, skill, tk, out, usd, ag in conn.execute(
            f"SELECT session_id, prompt_idx, max(skill), sum({TOKENS}), sum(output), sum(cost_usd), "
            f"sum(CASE WHEN agent_id IS NOT NULL THEN {TOKENS} END) {base} "
            f"GROUP BY session_id, prompt_idx ORDER BY session_id, prompt_idx IS NULL, prompt_idx", params):
        sessions[sid]["turns"].append({
            "i": i, "text": texts.get((sid, i), ""), "skill": skill, "tokens": tk or 0, "output": out or 0, "usd": usd,
            "version": versions.get((sid, i, skill)),
            "agents_tokens": ag or 0, **calls.get((sid, i), {"requests": 0, "runs": [], "mcp": [], "tools": []}),
            "agents": [{"type": a["type"], "n": a["n"], "models": ", ".join(sorted(a["models"]))}
                       for a in sorted(agents.get((sid, i), {}).values(), key=lambda a: -a["n"])]})
    for s in sessions.values():
        if not s["title"]:
            first = next((t["text"] for t in s["turns"] if t["text"]), "")
            s["title"] = f"“{first[:80]}”" if first else ""
        s["top_skill"] = max(s["skills"], key=s["skills"].get) if s["skills"] else ""
    return list(sessions.values())


def _week_compare(conn, cond, params, now):
    def window(start, end):
        return conn.execute(f"SELECT sum({TOKENS}), count(DISTINCT session_id), sum(cost_usd) FROM requests r "
                            f"JOIN sessions s USING (session_id) {cond} AND r.ts >= ? AND r.ts < ?",
                            (*params, start.isoformat(), end.isoformat())).fetchone()
    return window(now - timedelta(days=7), now), window(now - timedelta(days=14), now - timedelta(days=7))


def _hero(conn, cond, params):
    now = datetime.now(timezone.utc)
    (tk, n, usd), (prev_tk, prev_n, _) = _week_compare(conn, cond, params, now)
    per, prev_per = (tk or 0) / max(n or 0, 1), (prev_tk or 0) / max(prev_n or 0, 1)
    if prev_per:
        pct = per / prev_per - 1
        trend = (f'<span class="trend {"up" if pct > 0 else "down"}">{pct:+.0%}</span> tokens per session vs the 7 days before '
                 f'({_tok(prev_per)} → {_tok(per)})')
    else:
        trend = "no sessions in the 7 days before to compare with"
    since = (now - timedelta(days=7)).isoformat()
    owner = conn.execute(f"""SELECT CASE WHEN agent_id IS NULL THEN 'the main thread' ELSE agent_type END, sum({TOKENS})
                             FROM requests r JOIN sessions s USING (session_id) {cond} AND r.ts >= ?
                             GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", (*params, since)).fetchone()
    skill = conn.execute(f"""SELECT skill, sum({TOKENS}) FROM requests r JOIN sessions s USING (session_id) {cond}
                             AND r.ts >= ? AND skill IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", (*params, since)).fetchone()
    top = []
    if owner and tk:
        top.append(f"{html.escape(owner[0])} uses {owner[1] / tk:.0%} of them")
    if skill:
        top.append(f"the costliest skill is <b>{html.escape(skill[0])}</b> ({_tok(skill[1])})")
    sentence = "; ".join(top)
    return (f'<section class="hero"><div class="big">Last 7 days: <em data-count="{tk or 0}" data-kind="tok">{_tok(tk)}</em> tokens in {n or 0} sessions</div>'
            f'<p>{trend}.</p>{f"<p>{sentence[:1].upper() + sentence[1:]}.</p>" if sentence else ""}'
            f'<p class="usd">{_usd(usd)} API-eq. {html.escape(API_EQ_NOTE.removeprefix("API-eq = "))[:1].upper()}{html.escape(API_EQ_NOTE.removeprefix("API-eq = "))[1:]} '
            f'<a href="{COSTS_DOC}" target="_blank" rel="noopener">How Claude Code usage is limited</a></p></section>')


def _word(text, start, end):
    # widen a match to its whole word, so "retr" shows as "retry" and a match inside another word is visible
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    while end < len(text) and text[end].isalnum():
        end += 1
    return start, end


def _highlight(text, patterns):
    """Escape the answer and wrap every grader-pattern match in <mark>."""
    spans = sorted(_word(text, m.start(), m.end()) for p in patterns for m in re.finditer(p, text, re.IGNORECASE))
    out, pos = [], 0
    for start, end in spans:
        if start < pos:
            continue
        out += [html.escape(text[pos:start]), "<mark>", html.escape(text[start:end]), "</mark>"]
        pos = end
    return "".join(out) + html.escape(text[pos:])


def _spread(values, fmt):
    if not values:
        return "–"
    return f"{fmt(median(values))}<span class='usd' style='display:block'>{fmt(min(values))}–{fmt(max(values))}</span>"


def _pass_class(passed, n):
    return "pass" if passed == n else "fail" if passed == 0 else ""


def _benchmarks(conn, tasks_dir):
    """Returns (one-line verdict per task, shown up front; the full detail for a collapsed section)."""
    try:
        runs = conn.execute(
            f"""SELECT b.task, b.variant, b.run_idx, b.passed, b.is_error, b.duration_s, b.result, b.commit_sha,
                       sum({TOKENS}), sum(r.output), sum(r.cost_usd),
                       sum(CASE WHEN r.agent_id IS NULL THEN {TOKENS} END), sum(CASE WHEN r.agent_id IS NOT NULL THEN {TOKENS} END),
                       group_concat(DISTINCT CASE WHEN r.agent_id IS NOT NULL THEN r.model END)
                FROM bench_runs b LEFT JOIN requests r USING (session_id)
                GROUP BY b.run_id ORDER BY b.task, b.variant, b.run_idx""").fetchall()
    except sqlite3.OperationalError:
        runs = []
    if not runs:
        return "<p class='note'>No benchmark runs yet: <code>tokscope bench run &lt;task&gt; --runs 3</code>.</p>", ""
    tasks = {}
    for r in runs:
        tasks.setdefault(r[0], []).append(r)
    verdicts, cards = [], []
    for name, rows in tasks.items():
        leaky = name.endswith("-leaky")
        spec_path = Path(tasks_dir) / f"{name.removesuffix('-leaky')}.json" if tasks_dir else None
        spec = json.loads(spec_path.read_text()) if spec_path and spec_path.exists() else {}
        variants = {}
        for r in rows:
            variants.setdefault(r[1], []).append(r)
        summary = {v: (sum(r[3] for r in rs), len(rs), median(r[8] or 0 for r in rs), median(r[10] or 0 for r in rs))
                   for v, rs in variants.items()}
        if not leaky:
            parts = [f"<b>{html.escape(v)}</b> <span class='{_pass_class(p, n)}'>{p}/{n}</span> {_tok(t)} tokens "
                     f"<span class='usd'>{_usd(c)}</span>" for v, (p, n, t, c) in summary.items()]
            verdicts.append(f"<tr><td>{html.escape(name)}</td><td class='lm'>{' · '.join(parts)}</td></tr>")
        patterns = spec.get("grader", {}).get("all", [])
        table_rows = []
        for v, rs in variants.items():
            p, n = summary[v][0], summary[v][1]
            models = sorted({m.removeprefix("claude-") for r in rs for m in (r[13] or "").split(",") if m})
            table_rows.append((
                v, (f"<span class='{_pass_class(p, n)}'>{p}/{n}</span>", "raw"), summary[v][2],
                (_spread([r[11] or 0 for r in rs], _tok), "raw"), (_spread([r[12] or 0 for r in rs], _tok), "raw"),
                (_spread([r[9] or 0 for r in rs], _tok), "raw"), (_spread([r[10] or 0 for r in rs], _usd), "raw"),
                (_spread([r[5] or 0 for r in rs], lambda s: f"{s:.0f}s"), "raw"), ", ".join(models)))
        details = "".join(
            f"<details><summary>{html.escape(r[1])} run {r[2]} · "
            f"{'<span class=pass>PASS</span>' if r[3] else '<span class=fail>FAIL</span>'} · {_tok(r[8])} tokens · "
            f"<span class='usd'>{_usd(r[10])}</span> · {r[5]:.0f}s</summary><pre class='answer'>{_highlight(r[6] or '', patterns)}</pre></details>"
            for r in rows)
        warn = "<p class='note'><b>Leaky:</b> the snapshot path named the bug; kept for reference only.</p>" if leaky else ""
        cards.append(
            f'<section class="card{" leaky" if leaky else ""}"><h3>{html.escape(name)}</h3>'
            f'<p class="note">{html.escape(spec.get("about", ""))} Snapshot {(rows[0][7] or "")[:10]}. Highlighted words are grader matches.</p>{warn}'
            + _table(["variant", "pass", "tokens", "main thread", "subagents", "output", "API-eq", "time", "subagent model"], table_rows, 2)
            + f"{details}</section>")
    toggle = ('<label class="note"><input type="checkbox" id="show-leaky"> show leaky runs</label>'
              if any(n.endswith("-leaky") for n in tasks) else "")
    head = f"<table><tr><th>task</th><th style='text-align:left'>variants: pass · median tokens · API-eq</th></tr>{''.join(verdicts)}</table>"
    return head, toggle + "".join(cards)


def _week_skills(conn, cond, params, now, n=10):
    """Skills ranked by their tokens in the last 7 days, with the 7 days before them for the change."""
    mid, start = (now - timedelta(days=7)).isoformat(), (now - timedelta(days=14)).isoformat()
    rows = conn.execute(
        f"SELECT skill, max(phase), sum(CASE WHEN r.ts >= ? THEN {TOKENS} ELSE 0 END), "
        f"sum(CASE WHEN r.ts < ? THEN {TOKENS} ELSE 0 END) FROM requests r JOIN sessions s USING (session_id) {cond} "
        f"AND skill IS NOT NULL AND r.ts >= ? AND r.ts < ? GROUP BY skill",
        (mid, mid, *params, start, now.isoformat())).fetchall()
    return sorted((r for r in rows if r[2]), key=lambda r: -r[2])[:n]


def _weekly_phases(conn, cond, params, today=None):
    """Tokens per phase per calendar week (Monday start), oldest first; the current week is labelled as partial."""
    weeks = {}
    for day, phase, t in conn.execute(
            f"SELECT substr(r.ts,1,10), COALESCE(phase,'unscoped'), sum({TOKENS}) FROM requests r JOIN sessions s "
            f"USING (session_id) {cond} GROUP BY 1, 2", params):
        d = datetime.fromisoformat(day).date()
        by = weeks.setdefault(d - timedelta(days=d.weekday()), {})
        by[phase] = by.get(phase, 0) + (t or 0)
    today = today or datetime.now(timezone.utc).date()
    return [(f"{w:%b %d}" + (" so far" if w > today - timedelta(days=7) else ""), weeks[w]) for w in sorted(weeks)]


def _pct(q):
    return lambda xs: xs[min(len(xs) - 1, int(q * len(xs)))]


def _breakdowns(conn, cond, params):
    base = f"FROM requests r JOIN sessions s USING (session_id) {cond}"
    q = lambda sql: conn.execute(sql, params).fetchall()  # noqa: E731
    total = q(f"SELECT sum({TOKENS}) {base}")[0][0] or 1
    share = lambda t: f"{(t or 0) / total:.1%}"  # noqa: E731
    phase = q(f"SELECT COALESCE(phase,'unscoped'), count(DISTINCT session_id), sum({TOKENS}), "
              f"sum(CASE WHEN {CARRIED} THEN {TOKENS} ELSE 0 END), sum(output), sum(cost_usd) {base} GROUP BY 1 ORDER BY 3 DESC")
    carried = sum(c for _, _, _, c, _, _ in phase)
    owner = q(f"SELECT CASE WHEN agent_id IS NULL THEN 'main thread' ELSE 'agent: ' || agent_type END, sum({TOKENS}), sum(output), "
              f"sum(cost_usd) {base} GROUP BY 1 ORDER BY 2 DESC")
    loads = dict(conn.execute("SELECT skill, count(*) FROM skill_calls GROUP BY skill"))
    skills = q(f"SELECT skill, count(DISTINCT session_id), sum({TOKENS}), sum(cost_usd), "
               f"sum(CASE WHEN agent_id IS NULL THEN {TOKENS} ELSE 0 END), sum(CASE WHEN agent_id IS NOT NULL THEN {TOKENS} ELSE 0 END) "
               f"{base} AND skill IS NOT NULL GROUP BY skill ORDER BY 3 DESC LIMIT 30")
    runs = q(f"SELECT agent_type, sum({TOKENS}), sum(output), sum(cost_usd), group_concat(DISTINCT model) {base} "
             f"AND agent_id IS NOT NULL GROUP BY session_id, agent_id")
    by_type = {}
    for t, tk, o, c, m in runs:
        by_type.setdefault(t, []).append((tk or 0, o or 0, c or 0, m or ""))
    agent_rows, spread = [], []
    for t, rs in sorted(by_type.items(), key=lambda kv: -sum(r[0] for r in kv[1]))[:20]:
        tks = sorted(r[0] for r in rs)
        models = sorted({x.removeprefix("claude-") for r in rs for x in r[3].split(",") if x})
        agent_rows.append((t, len(rs), sum(tks), _tok(median(tks)), _tok(_pct(0.9)(tks)),
                           (_usd(median(r[2] for r in rs)), "u"), (", ".join(models), "lm")))
        spread.append((t, len(rs), _pct(0.1)(tks), median(tks), _pct(0.9)(tks)))
    calls_rows = conn.execute(
        f"SELECT session_id, name, count(*), sum(result_chars) FROM tool_calls WHERE name != 'Agent' "
        f"AND session_id IN (SELECT session_id FROM requests r JOIN sessions s USING (session_id) {cond}) GROUP BY 1, 2",
        params).fetchall()
    servers, tools = {}, {}
    for sid, name, n, chars in calls_rows:
        target, key = (servers, mcp_server(name)) if name.startswith("mcp__") else (tools, name)
        g = target.setdefault(key, [0, set(), 0])
        g[0] += n
        g[1].add(sid)
        g[2] += chars or 0

    def call_rows(groups):
        return [(k, n, len(sids), est_tokens(chars), _tok(est_tokens(chars) / n))
                for k, (n, sids, chars) in sorted(groups.items(), key=lambda kv: -kv[1][2])[:25]]
    def usage(groups):
        return [(k, n, est_tokens(chars) / n, est_tokens(chars)) for k, (n, _, chars) in groups.items()]

    week = _week_skills(conn, cond, params, datetime.now(timezone.utc))
    week_rows = [(sk, ph or "", this, (_tok(last) if last else "–", "lm"),
                  (charts.change_text(last, this), "lm"))
                 for sk, ph, this, last in week]
    call_note = "~ tokens = size of the results put into the context, estimated at 4 characters per token"
    return "".join([
        _more("Week over week", "the last 7 days against the 7 before, per skill; ranked by this week",
              (charts.dumbbell([(sk, last, this) for sk, _, this, last in week], "tokens")
               + _table(["skill", "phase", "this week", "last week", "change"], week_rows, 2)) if week
              else "<p class='note'>No skill was loaded in the last 7 days.</p>", "by-week"),
        _more("By MCP server", call_note + "; the bar is each server's share of all MCP result tokens",
              charts.share_bar([(k, est_tokens(c)) for k, (_, _, c) in servers.items()], "~result tokens")
              + _table(["server", "calls", "sessions", "~result tokens", "per call"], call_rows(servers), 3), "by-mcp"),
        _more("By tool", call_note + "; Agent calls are under subagent types. Top right = called often and heavy each time",
              charts.scatter(usage(tools), "calls", "~tokens per call")
              + _table(["tool", "calls", "sessions", "~result tokens", "per call"], call_rows(tools), 3), "by-tool"),
        _more("By phase", f"direct = the phase's skill ran in that prompt; carried = a later prompt with no skill, which keeps "
              f"the last phase ({share(carried)} of all tokens); rows sum to the total; the chart splits each calendar week",
              charts.weekly_columns(_weekly_phases(conn, cond, params), "tokens")
              + _table(["phase", "sessions", "tokens", "direct", "carried", "output", "API-eq", "share"],
                       [(p, s, t, _tok((t or 0) - (cr or 0)), f"{_tok(cr)} ({(cr or 0) / (t or 1):.0%})" if cr else "–",
                         _tok(o), (_usd(c), "u"), share(t)) for p, s, t, cr, o, c in phase], 2), "by-phase"),
        _more("By owner", "main thread vs each subagent type; rows sum to the total",
              charts.share_bar([(o, t or 0) for o, t, *_ in owner], "tokens")
              + _table(["owner", "tokens", "output", "API-eq", "share"],
                       [(o, t, _tok(x), (_usd(c), "u"), share(t)) for o, t, x, c in owner[:20]], 1), "by-owner"),
        _more("By skill", "requests while a skill was loaded in that prompt. tokens = main thread + the subagents the skill "
              "started; the subagents column is also counted under By owner, so do not add the two tables. "
              "Top right = loaded often and heavy each time",
              charts.scatter([(sk, loads.get(sk, 0), (t or 0) / loads[sk], t or 0) for sk, _, t, *_ in skills if loads.get(sk)],
                             "loads", "tokens per load")
              + _table(["skill", "loads", "sessions", "tokens", "main thread", "subagents", "per load", "API-eq"],
                       [(sk, loads.get(sk, 0), s, t, _tok(m), _tok(a) if a else "–", _tok((t or 0) / max(loads.get(sk, 0), 1)),
                         (_usd(c), "u")) for sk, s, t, c, m, a in skills], 3), "by-skill"),
        _more("Subagent types", "one run = one subagent transcript; the line spans p10 to p90 of a run, the dot is the median",
              charts.ranges(spread[:12], "tokens")
              + _table(["agent type", "runs", "tokens", "median", "p90", "median API-eq", "models"], agent_rows, 2), "agent-types"),
    ])


PRIVACY_NOTE = {
    "redacted": "Redacted report: prompts, session titles, subagent descriptions, benchmark answers, change notes, "
                "paths and project names are removed. Numbers and skill, agent and tool names are unchanged.",
    "numbers": "Numbers-only report: all text is removed, and skill, agent, tool, MCP server and task names are replaced "
               "by stable aliases (the same name gets the same alias in every report from this machine). Numbers are unchanged.",
}


def write_report(db_path, out_path, where="", params=(), tasks_dir=None, level="full"):
    conn = connect(db_path)
    conn.executescript("CREATE TABLE IF NOT EXISTS prompts (session_id TEXT, prompt_idx INTEGER, ts TEXT, text TEXT)")
    tasks_dir = tasks_dir or paths.tasks()
    if level != "full":
        conn.close()
        conn = privacy.redacted_copy(db_path, level, where, params)
        where, params, tasks_dir = "", (), None  # the copy is already filtered; task specs hold text (about, grader words)
    cond = f"{where} {'AND' if where else 'WHERE'} s.project NOT LIKE '{BENCH_PROJECT}'"
    params = tuple(params)

    (n_sess, tokens, out, cache_read, usd, first, last, n_runs) = conn.execute(
        f"SELECT count(DISTINCT session_id), sum({TOKENS}), sum(output), sum(cache_read), sum(cost_usd), min(r.ts), max(r.ts), "
        f"count(DISTINCT CASE WHEN agent_id IS NOT NULL THEN session_id || agent_id END) "
        f"FROM requests r JOIN sessions s USING (session_id) {cond}", params).fetchone()
    kpis = [("Sessions", f"{n_sess:,}", n_sess, "int"), ("Tokens", _tok(tokens), tokens, "tok"),
            ("Output tokens", _tok(out), out, "tok"), ("Subagent runs", f"{n_runs:,}", n_runs, "int"),
            ("From cache", f"{(cache_read or 0) / (tokens or 1):.0%}", round(100 * (cache_read or 0) / (tokens or 1)), "pct"),
            ("API-eq", _usd(usd), round(usd or 0, 2), "usd")]
    api_eq_title = f' title="{html.escape(API_EQ_NOTE)}"'
    kpi_html = "".join(f'<div class="kpi" style="--i:{i}"{api_eq_title if k == "API-eq" else ""}><span>{k}</span><b data-count="{raw or 0}" data-kind="{kind}">{v}</b></div>'
                       for i, (k, v, raw, kind) in enumerate(kpis))

    changes = list_changes(conn)
    n_changed, versions_html = _skill_versions(conn, level)
    days = conn.execute(f"SELECT substr(r.ts,1,10) d, sum({TOKENS}), sum(cost_usd) FROM requests r JOIN sessions s "
                        f"USING (session_id) {cond} GROUP BY d ORDER BY d", params).fetchall()
    bench_head, bench_detail = _benchmarks(conn, tasks_dir)
    data = json.dumps(_sessions_json(conn, cond, params), separators=(",", ":")).replace("</", "<\\/")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tokscope report{"" if level == "full" else f" ({level})"}</title>{favicon_link()}<script>document.documentElement.classList.add('js');
try{{const t=localStorage.getItem('tokscope-theme');if(t)document.documentElement.dataset.theme=t}}catch(_){{}}</script>
<style>{fonts.face_css(True)}{CSS}</style></head><body><div id="progress"></div><div class="layout">
<aside class="side" aria-label="Sections"><div class="brand">{MARK}tokscope</div><nav class="toc">
<a href="#overview">Overview</a>
<a href="#sessions">Sessions<span class="cnt">{n_sess:,}</span></a>
<a href="#benchmarks">Benchmarks</a>
<a href="#trend">Daily trend</a>
<a href="#changes">Config changes<span class="cnt">{len(changes)}</span></a>
<a href="#skill-versions">Skill versions<span class="cnt">{n_changed}</span></a>
<a href="#breakdowns">Breakdowns</a>
<div class="sub-toc"><a href="#by-week">Week over week</a><a href="#by-mcp">By MCP server</a><a href="#by-tool">By tool</a><a href="#by-phase">By phase</a>
<a href="#by-owner">By owner</a><a href="#by-skill">By skill</a><a href="#agent-types">Subagent types</a></div>
</nav><div class="side-foot"><button type="button" class="chip" id="theme">Theme</button>
<button type="button" class="chip" id="keys-btn" aria-label="Keyboard shortcuts"><kbd>?</kbd></button></div></aside><main>
<div id="overview">
<h1>Claude Code token usage</h1>
{f'<p class="privacy" role="note"><b>{level}</b> {PRIVACY_NOTE[level]}</p>' if level != "full" else ""}
<p class="sub">{(first or '')[:10]} → {(last or '')[:10]} · real sessions (benchmarks separate) · generated {generated}</p>
{_hero(conn, cond, params)}
<div class="kpis">{kpi_html}</div></div>

<section class="card reveal" id="sessions"><h2>Sessions</h2>
<p class="note"><span class="key"><i></i>main thread</span><span class="key"><i class="a"></i>subagents</span>
Open a row to see each prompt, its skill, tokens and calls. Tick 2 to 4 rows, then press Compare.
Sessions do different work, so a comparison describes them; for a controlled before/after use a benchmark.</p>
<div class="tools"><input type="search" id="s-q" placeholder="Filter by title, skill or session id  ( / )">
<select id="s-sort"><option value="recent">Newest first</option><option value="tokens">Most tokens first</option></select>
<span class="note" id="s-count"></span></div>
<section class="card" id="compare"><h3>Compare</h3>
<p class="note">Bold = fewest. Tokens per prompt evens out sessions of different length.</p><table></table></section>
<div id="session-list"></div>
<div class="pickbar" id="pickbar" hidden><span id="pick-hint"></span><span class="acts"><button class="btn" id="clear-pick">Clear</button>
<button class="primary" id="do-compare" disabled>Compare</button></span></div>
<p><button class="btn" id="s-more">Show more</button></p></section>

<section class="card reveal" id="benchmarks"><h2>Benchmarks</h2>
<p class="note">Same task, fresh session per run, variants interleaved. Open the details to read each answer.</p>
{bench_head}
{_more("Benchmark details", "per-variant spread, main vs subagent tokens, every answer", bench_detail)}</section>

{_more("Daily trend", "tokens per day; the mustard line is the 7-day average; a dashed line marks a config change", _daily_chart(days, changes), "trend")}
{_more("Config changes", f"{len(changes)} recorded; before/after medians per run", _change_cards(conn, changes), "changes")}
{_more("Skill versions", f"{n_changed} skill{'' if n_changed == 1 else 's'} changed. A version is a hash of the skill's folder; each row is the median tokens of one "
       f"prompt's requests while that version was loaded. Few loads = fewer than {FEW_LOADS}: watch, do not judge. "
       f"For a fair comparison, run a benchmark or a replay", versions_html, "skill-versions")}
<div id="breakdowns">{_breakdowns(conn, cond, params)}</div>
</main></div><div id="tip"></div><div id="toast" role="status" aria-live="polite"></div>
<dialog class="keys" id="keys"><h3 style="margin:0">Keyboard shortcuts</h3><dl>
<dt><kbd>/</kbd></dt><dd>Filter sessions</dd><dt><kbd>t</kbd></dt><dd>Light or dark theme</dd>
<dt><kbd>c</kbd></dt><dd>Compare the ticked sessions</dd><dt><kbd>g</kbd></dt><dd>Back to the top</dd>
<dt><kbd>Esc</kbd></dt><dd>Clear the filter, close this</dd><dt><kbd>?</kbd></dt><dd>Show this list</dd></dl></dialog>
<button type="button" class="totop" id="totop" aria-label="Back to top" title="Back to top">↑</button>
<script type="application/json" id="sessions-data">{data}</script><script>{JS}</script></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page)
