"""The layout both skins share: grid, sizes, spacing and structure, as one stylesheet (<style id="layout">).

Each page loads it once, before the skin sheets. A skin (Ink in report.py and dashboard.py, Classic in classic.py)
adds its tokens and a look block: outline, radius, shadow, label case and font, control shape. A rule that reads the
same in both skins belongs here, but only when no skin rule that comes before it in either skin sheet sets the same
property on the same element: a skin sheet loads after this one and would win. New markup gets its rules here first
and reads tokens (`--line-w`, `--radius-*`) instead of a skin's colours or sizes."""

LAYOUT_CSS = """
/* motion tokens, shared by both skins. --t-fast: press, hover colour. --t-state: toggles, segments, tooltips, delta chip.
   --t-layout: row open, sheet, toast, first-paint entrances. An exit is 0.7 times its entrance (calc(var(--t-state)*.7)).
   Not tokens, on purpose: the stagger delays (a step per item, not a duration), the endless spinner and run bar (they
   show that work is going on), the one-ring live dot (600 ms, #125 Pulse) and the Classic hero glow (ambient). */
:root{--t-fast:120ms;--t-state:200ms;--t-layout:320ms;--ease-exit:cubic-bezier(.55,.06,.68,.19)}
b,strong{font-weight:600}
.kpi b,.hero .big em,.delta{font-family:var(--mono)}
.kpi b{font-weight:600}
*{box-sizing:border-box}
[hidden]{display:none!important}
main{max-width:1180px;margin:0 auto;padding:28px 16px 72px}
h1{font-size:22px;margin:0 0 2px;text-wrap:balance}
h2{font-size:17px;margin:0 0 4px}
h3{font-size:14px;margin:14px 0 6px}
pre.diff{white-space:pre-wrap;font:12px/1.5 var(--mono);background:var(--page);padding:10px;border-radius:8px;max-height:420px;overflow:auto;margin:6px 0 10px}
#skill-versions .versions h3{margin:14px 0 8px}
#skill-versions .card{margin:0 0 12px}
details.vdiff>summary{cursor:pointer;font-size:13px;margin:6px 0}
.hero .big{font-size:28px;font-weight:700;letter-spacing:-0.01em;margin:0 0 6px;font-variant-numeric:tabular-nums}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:16px}
details.more>summary{cursor:pointer;font-weight:600;list-style:none;display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 6px}
details.more>summary::-webkit-details-marker{display:none}
details.more[open]>summary::before{transform:rotate(90deg)}
details.more>summary .ttl{flex:none;white-space:nowrap}
details[open]>:not(summary){animation:reveal var(--t-layout) var(--ease) both}
@keyframes reveal{from{opacity:.4;transform:translateY(-4px)}}
.kpi b,.hero .big em{display:inline-block}
th,td{padding:5px 8px;text-align:right;white-space:nowrap;vertical-align:top}
td:first-child,th:first-child{text-align:left}
.bar{display:flex;align-items:center;gap:8px;justify-content:flex-end}
@keyframes grow{from{transform:scaleX(0)}}
.key{display:inline-flex;align-items:center;gap:4px;margin-right:10px}
svg text{fill:var(--muted);font-size:11px}
svg .g{stroke:var(--grid)}
#trend[open] svg rect.m{animation:rise var(--t-layout) var(--ease-expo) both;animation-delay:calc(var(--i,0)*12ms)}
@keyframes rise{from{transform:scaleY(0)}}
svg .chg{stroke:var(--agent);stroke-width:1.5;stroke-dasharray:3 3}
svg text.chg-l{fill:var(--agent-ink);font-weight:600}
svg:hover rect.m{opacity:.45}
svg g.d:hover rect.m{opacity:1}
.changes{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 10px}
.tools input[type=search]{flex:1;min-width:180px}
#session-list{position:relative}
.bar [data-count],.note [data-count]{font-variant-numeric:tabular-nums}
.srow>summary input{accent-color:var(--mark);cursor:pointer}
.srow>summary .t{transition:color var(--t-fast) var(--ease)}
.srow>summary .split{transition:transform var(--t-state) var(--ease);transform-origin:left}
.srow:hover>summary .split{transform:scaleY(1.35)}
.srow .body tr td{transition:background var(--t-fast) var(--ease)}
.srow .body tr:hover td{background:color-mix(in oklch,var(--mark) 7%,transparent)}
/* left sidebar: every section one click away; the link of the section in view is highlighted */
.layout>main{min-width:0}
.layout{display:grid;grid-template-columns:224px minmax(0,1fr);max-width:1460px;margin:0 auto}
.brand .logo{width:24px;height:15px;flex:none;position:relative;top:-1px}
.toc{display:flex;flex-direction:column;gap:2px}
[id]{scroll-margin-top:16px}
#sessions{overflow:visible}  /* a scrolling card would stop the pick bar from sticking */
.pickbar .acts{display:flex;gap:8px;align-items:center}
.srow.dim:not(:hover):not([open]){opacity:.6}
.btn.kids-more{margin:0 0 8px calc(var(--depth)*24px);padding:7px 14px}
.srow.orphan>summary .t{display:flex;gap:8px;align-items:baseline}
.srow>summary .tt{overflow:hidden;text-overflow:ellipsis;min-width:0}
.srow>summary .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.srow>summary .r{text-align:right;font-variant-numeric:tabular-nums}
.srow .body{padding:4px 4px 12px 30px}
.srow .body td.l{overflow-wrap:anywhere}
.scroll{overflow-x:auto}
.run:hover{background:color-mix(in oklch,var(--agent) 9%,transparent)}
.run .est{text-align:right}
.run .usd{white-space:nowrap}
.cl{line-height:1.6}
.cl+.cl{margin-top:2px}
.ids dd{margin:0;display:flex;gap:6px;align-items:center;min-width:0}
.ids dd .code{overflow-wrap:anywhere}
@keyframes pop{from{opacity:.4;transform:translateY(-6px)}}
/* motion layer: entrance, scroll reveal; all of it off under reduced motion */
html{scroll-behavior:smooth}
body{transition:background-color var(--t-layout) var(--ease),color var(--t-layout) var(--ease)}
@keyframes rise-in{from{opacity:0;transform:translateY(12px) scale(.98)}}
.js .reveal{opacity:0;transform:translateY(16px);transition:opacity var(--t-layout) var(--ease-expo),transform var(--t-layout) var(--ease-expo)}
.js .reveal.in{opacity:1;transform:none}
@keyframes draw{from{stroke-dashoffset:1}}
svg .guide{stroke:var(--ink2);stroke-width:1;stroke-dasharray:2 3;opacity:0;transition:opacity var(--t-fast)}
svg:hover .guide{opacity:.6}
@keyframes pop-in{from{opacity:0;transform:translateY(8px) scale(.97)}}
dialog.keys dl{display:grid;grid-template-columns:auto 1fr;gap:8px 14px;margin:10px 0 0}
/* breakdown charts: categorical slots in both modes (cobalt, mustard, blush, dark ink tint, mid ink tint); --c0 is "Other",
the palest tint; neighbours in the share bar differ by at least 1.5:1 in luminance */
.viz{margin:4px 0 16px}
.viz svg{display:block;overflow:visible}
.viz svg text.ax,.viz svg text.name{fill:var(--ink2)}
.viz svg text.val{fill:var(--ink2);font-weight:600;font-variant-numeric:tabular-nums}
.viz svg text.lbl{fill:var(--ink);font-size:11.5px;paint-order:stroke;stroke:var(--surface);stroke-width:3px}
.legend .key{margin:0}
.share:hover i{filter:saturate(.35) opacity(.55)}
.share i:hover{filter:none}
.viz g[data-tip]:hover .dot{r:7px}
.viz .span{stroke:color-mix(in oklch,var(--c1) 45%,var(--surface));stroke-width:2px;stroke-linecap:round}
.viz g.seg:hover path,.viz g.seg:hover rect:not(.hit){filter:brightness(1.12)}
#breakdowns details[open] .viz .span{stroke-dasharray:1;stroke-dashoffset:0}
/* narrow cards shrink, then drop, the bars and let headers and the calls column wrap, so a table fits its card
   instead of scrolling sideways; the numbers always stay */
th{white-space:normal}
.card,.srow .body,details.more{container-type:inline-size}
/* #054 Tooltip rises 6 px in --t-state; #056 Toast rises in --t-layout; each leaves in 0.7 times that, on the exit curve */
#tip{transition:opacity calc(var(--t-state)*.7) var(--ease-exit),transform calc(var(--t-state)*.7) var(--ease-exit)}
#tip.on{transition:opacity var(--t-state) var(--ease),transform var(--t-state) var(--ease)}
#toast{transition:opacity calc(var(--t-state)*.7) var(--ease-exit),transform calc(var(--t-layout)*.7) var(--ease-exit)}
#toast.on{transition:opacity var(--t-state) var(--ease),transform var(--t-layout) var(--ease-expo)}
/* first paint only: <html> gets .settled once the entrances are done (and before the first poll swaps a region), and a
   region that a poll swaps in never plays an entrance again. The ids and classes beat the skin rules by specificity. */
html.settled [data-region] :is(.hero,.kpi,.empty,.bar i u){animation:none}
/* reduced motion: opacity and colour stay, travel and scale go. A keyframes set below replaces the one above, so each
   entrance still fades in and an update still shows; transitions lose their transform and keep colour and opacity.
   Selectors start with `html` to beat the skin rules that load after this sheet. */
@media (prefers-reduced-motion:reduce){
html{scroll-behavior:auto}
@keyframes reveal{from{opacity:.4}}
@keyframes pop{from{opacity:.4}}
@keyframes pop-in{from{opacity:0}}
@keyframes rise-in{from{opacity:0}}
@keyframes rise{from{opacity:0}}
@keyframes grow{from{opacity:0}}
@keyframes draw{from{opacity:0}}
html.js .reveal{transform:none;transition:opacity var(--t-layout) var(--ease)}
html .toc a,html a.sk{transition:background var(--t-fast) var(--ease),color var(--t-fast) var(--ease)}
html .toc a:hover,html a.sk:hover,html .totop.show:hover,html .srow:hover>summary .split,html .kpi:hover,html .primary:hover:not(:disabled){transform:none}
html .toc-pill{transition:opacity var(--t-state)}
html .cv{transition:color var(--t-fast) var(--ease)}
html #tip,html #toast,html .totop{transform:none;transition:opacity var(--t-state) var(--ease),visibility var(--t-state)}
html #toast{transform:translate(-50%,0)}
html details::details-content{transition:content-visibility var(--t-state) allow-discrete}
html details.more>summary::before{transition:none}
}
"""

LAYOUT_DASH_CSS = """
main{width:100%;min-width:0}
.dash-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;margin:0 0 14px}
.dash-head h1{margin:0}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-left:auto}
/* the report's .kpis is a content-sized flex row; here the six tiles fill the width, edge to edge with .cols2 below */
[data-region=kpis]>.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px}
@media (max-width:1200px){[data-region=kpis]>.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:560px){[data-region=kpis]>.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
.spark{display:block;margin-top:4px}
/* spender cards share one width: two to a row on a desktop (the third starts the next row), one on a phone;
   wide enough that a long name (compound-engineering:ce-simplify-code) fits on one line, and it wraps whole if not */
.cols3{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,400px),1fr));gap:14px}
.cols3 td{vertical-align:baseline}
[data-region=changed] td{vertical-align:baseline}
h2.sec{font-size:15px;margin:6px 0 10px}
.card h2{display:flex;align-items:center}
.today-nums{display:flex;gap:22px;flex-wrap:wrap;margin:6px 0 12px}
ul.plain{list-style:none;margin:0;padding:0}
.libtools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 14px}
.libtools .chip input{margin:0}
.libgroup{margin:0 0 18px}
.libgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:12px}
.libview{display:grid;grid-template-columns:minmax(150px,230px) minmax(0,1fr);gap:14px;align-items:start}
.viewer{overflow:visible}
.viewer .path{font:600 13px var(--mono);margin:0 0 8px;overflow-wrap:anywhere}
.viewbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;margin:0 0 10px}
.seg{display:inline-flex;gap:4px}
.md h1{font-size:20px}
.md h3{font-size:15px}
.md h4{font-size:14px}
.md ul,.md ol{padding-left:22px}
pre.src{counter-reset:ln}
pre.src .ln{display:block;padding-left:5.5ch;text-indent:-5.5ch}
.ste-n{white-space:nowrap}
ol.ste .lnk{font:12px var(--mono);text-decoration:none}
ol.ste .rule{font:600 12px var(--mono)}
ol.ste .line,ol.ste .msg{grid-column:1/-1}
details.folders li{overflow-wrap:anywhere}
table.mcp tbody tr:hover{background:color-mix(in oklch,var(--mark) 8%,transparent)}
.badge{white-space:nowrap}
.sk.reg{cursor:default}
.sk.reg .acts{display:flex;flex-wrap:wrap;gap:4px}
#mcp-form .namefield{flex:1 1 20em;display:flex;align-items:center;gap:8px;font-size:13px}
.ask .acts{display:flex;gap:8px}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes slide{from{transform:translateX(-100%)}to{transform:translateX(290%)}}
table.sbs td.del{background:color-mix(in oklch,var(--fail) 12%,transparent)}
table.sbs td.add{background:color-mix(in oklch,var(--pass) 12%,transparent)}
.decide .acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.optform{display:flex;flex-direction:column;gap:8px}
.opt{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.optrow{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
/* a poll that finds new data: the live dot gives one ring (#125 Pulse, 600 ms, not a token), never a loop; offline shows a hollow dot */
@keyframes ring{from{box-shadow:0 0 0 0 color-mix(in oklch,var(--pass) 60%,transparent)}to{box-shadow:0 0 0 8px transparent}}
.dot.ring{animation:ring 600ms var(--ease) 1}
.fresh.stale .dot,body.offline h2>.dot{background:transparent;box-shadow:inset 0 0 0 1.5px var(--muted)}
/* a live value changes at once; this chip says by how much for 2 s (#071 Badge: in --t-state, out 0.7 times that) */
.kpi,.today-nums>div{position:relative}
.dchip{font:600 11px/1.5 var(--mono);padding:0 7px;border-radius:999px;background:var(--chip);color:var(--ink);white-space:nowrap;
pointer-events:none;animation:chip-in var(--t-state) var(--ease) both}
.kpi .dchip{position:absolute;top:8px;right:8px}
.today-nums .dchip{margin-left:6px;vertical-align:4px}
.dchip.out{animation:chip-out calc(var(--t-state)*.7) var(--ease-exit) both}
@keyframes chip-in{from{opacity:0;transform:translateY(4px)}}
@keyframes chip-out{to{opacity:0;transform:translateY(-4px)}}
/* #056 Toast: "New data · reload" on the pages that do not refresh themselves */
#newdata{animation:toast-in var(--t-layout) var(--ease-expo) both}
@keyframes toast-in{from{opacity:0;transform:translateY(12px)}}
@media (prefers-reduced-motion:reduce){
@keyframes ring{from{opacity:.35}}
@keyframes chip-in{from{opacity:0}}
@keyframes chip-out{to{opacity:0}}
@keyframes toast-in{from{opacity:0}}
}
/* breakdowns: a folded section shows its finding; the "how this is counted" text sits inside the section, shown only when it is opened */
details.more>summary .finding b{color:var(--ink);font-weight:600}
details.more>summary .mini{display:inline-block;vertical-align:middle;width:84px;height:6px;margin-left:10px;border-radius:3px;background:var(--track);overflow:hidden}
details.more>summary .mini i{display:block;height:100%;min-width:2px;border-radius:3px;background:var(--mark)}
details.more>.how{margin:2px 0 10px;max-width:84ch}
details.finding-sec>.empty{text-align:left;padding:18px 16px}
details.finding-sec .empty code{overflow-wrap:anywhere}
@media (max-width:640px){details.more>summary .mini{display:block;margin:6px 0 0;width:min(100%,160px)}}
/* end breakdowns */
"""
