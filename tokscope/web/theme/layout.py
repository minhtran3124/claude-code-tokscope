"""The layout both skins share: grid, sizes, spacing, structure and every rule that differs between the skins only in value,
as one stylesheet (<style id="layout">).

Each page loads it once, before the skin sheets. A skin (Ink in report/styles.py and dashboard/scripts.py, Classic in classic.py) is its
tokens (the :root rules) plus a short look block: only what differs in kind, such as the answer-card emphasis, the hero glow,
hover and pressed looks, and the few rules where one skin sets a value the other leaves to the browser. A rule that reads the
same in both skins, or differs only in a value, lives here and reads a token (`border:var(--line-w) solid var(--line-c)`). The
skin tokens are listed above LAYOUT_TOKEN_CSS. Order of the sheets: LAYOUT_CSS, LAYOUT_DASH_CSS, LAYOUT_TOKEN_CSS (rules that
came from report.CSS), LAYOUT_TOKEN_DASH_CSS (from DASH_CSS); the report page loads LAYOUT_CSS and LAYOUT_TOKEN_CSS only.
The skin sheets load after this one and win at equal specificity, so once a rule here reads a token, the skin must not set
the same property for that element too (delete the skin copy). New markup gets its rules here first and reads tokens, so
Classic needs no copy."""

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
/* sessions: a dense table. Rows are 44px, the id selector keeps these ahead of the skins' older .srow card rules, and the
   skins add only the look (outline, radius, label case, tray colour). Child sessions keep their indent (--depth) in the title cell. */
#session-list{--scols:24px 100px minmax(0,1fr) 120px 60px 84px 70px 140px 14px;overflow:clip}
#session-list :is(.shead,.srow>summary){display:grid;grid-template-columns:var(--scols);gap:8px;align-items:center;padding:0 10px}
#session-list .shead{height:32px;font-size:11px;white-space:nowrap}
#session-list .shead>*{overflow:hidden;text-overflow:ellipsis}
#session-list .dayhd{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:0 12px;min-height:36px;padding:4px 10px}
#session-list .srow{margin:0;border-width:0;border-radius:0}
#session-list .srow.child{margin-left:0}
#session-list .srow.child::before{display:none}
#session-list .srow>summary{height:44px;border-radius:0}
#session-list .srow>summary:focus-visible{outline-offset:-2px}
#session-list .srow>summary .d,#session-list .srow>summary .n,#session-list .srow>summary .sk{white-space:nowrap}
#session-list .srow>summary .t{display:flex;gap:8px;align-items:baseline;min-width:0;padding-left:calc(var(--depth,0)*20px)}
#session-list .srow>summary .tt{flex:0 1 auto}
#session-list .srow>summary .sid8{flex:none;font-size:11px;color:var(--muted)}
#session-list .srow>summary .from{flex:0 1 auto}
#session-list .track{display:block;min-width:0}
#session-list .srow>summary .split{height:10px}
#session-list .srow .body{padding:4px 12px 12px 34px}
#session-list .btn.kids-more{margin:6px 10px 6px calc(34px + var(--depth)*20px)}
#sessions .tools .seg{flex:none}
#sessions .seg .chip{transition:color var(--t-state) var(--ease),background var(--t-state) var(--ease),border-color var(--t-state) var(--ease)}
/* the compare tray rises when a second session is ticked (travel is dropped under reduced motion, the fade stays) */
#sessions .pickbar{position:fixed;left:0;right:0;bottom:20px;z-index:30;width:min(520px,calc(100vw - 24px));margin:0 auto;animation:none;
opacity:0;visibility:hidden;transform:translateY(calc(100% + 24px));
transition:transform calc(var(--t-state)*.7) var(--ease-exit),opacity calc(var(--t-state)*.7) var(--ease-exit),visibility calc(var(--t-state)*.7)}
#sessions .pickbar.show{opacity:1;visibility:visible;transform:none;
transition:transform var(--t-layout) var(--ease-expo),opacity var(--t-state) var(--ease),visibility var(--t-state)}
#sessions .pickbar #pick-hint{font-variant-numeric:tabular-nums;white-space:nowrap}
body.picking .totop{bottom:96px}
/* a narrower page drops the top skill, then the split bar, so the title column never collapses (checked from 641 to 1200 px) */
@media (max-width:1200px){#session-list{--scols:24px 100px minmax(0,1fr) 60px 84px 70px 140px 14px}#session-list .sk{display:none}}
@media (max-width:1040px){#session-list{--scols:24px 100px minmax(0,1fr) 60px 84px 70px 14px}#session-list .track{display:none}}
@media (prefers-reduced-motion:reduce){#sessions .pickbar,#sessions .pickbar.show{transform:none}}
/* end sessions */
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
.dep-st{white-space:nowrap}
.dep-why{display:block;white-space:normal;overflow-wrap:anywhere}
/* an agent's toolsets, skills, multiagent and metadata: a long URL or value wraps inside its block on a phone
(the first card is .libhead, which already wraps) */
.agent-cfg .ids dd{display:block;min-width:0;overflow-wrap:anywhere}
.dash-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;margin:0 0 14px}
.dash-head h1{margin:0}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-left:auto}
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
/* a session that is working now: its dot pulses for as long as it works (the one loop besides the spinners; off under reduced motion) */
@keyframes pulse{from{box-shadow:0 0 0 0 color-mix(in oklch,var(--pass) 55%,transparent)}to{box-shadow:0 0 0 var(--pr,9px) transparent}}
.live-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 20px;margin:0 0 14px}
.live-head>h2,.live-head .runnow{margin:0}
.live-head [data-region=running]{flex:1 1 14rem;min-width:0}
.runnow{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 8px;font-size:15px}
.runnow b{font-size:28px;line-height:1}
.runnow .note{flex-basis:100%;margin:0 0 0 16px}
.runnow .dot{align-self:center}
.dot.off{background:transparent;box-shadow:inset 0 0 0 1.5px var(--muted)}
.dot.live.busy-now,.srow .live.working i{animation:pulse 1600ms var(--ease) infinite}
.srow .live{display:inline-flex;align-items:center;gap:6px;flex:none;font-size:11px;padding:1px 8px;border-radius:99px;margin-left:8px;color:var(--muted);box-shadow:inset 0 0 0 1px var(--line,currentColor)}
.srow .live i{--pr:5px;width:7px;height:7px;border-radius:50%;background:var(--muted)}
.srow .live.working{color:var(--ink)}
.srow .live.working i{background:var(--pass)}
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
/* overview */
/* Today: the answer card. Numbers and the typical-day line on the left, the chart on the right; the latest session below.
   Without a typical day (7 active days or fewer) the numbers take the full width. */
.today-top{display:grid;grid-template-columns:minmax(0,1fr);gap:12px 28px;align-items:stretch}
.today-top.has-chart{grid-template-columns:minmax(0,1fr) minmax(0,1.5fr)}
@media (max-width:760px){.today-top.has-chart{grid-template-columns:minmax(0,1fr)}.today-nums{gap:10px 20px}}
.today-main{display:flex;flex-direction:column;justify-content:center;gap:14px;min-width:0}
.today-nums{margin:0;gap:12px 28px}
.today-top:not(.has-chart) .today-nums{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}
.today-nums b{font-size:28px}
.vs{margin:0;font-size:15px;line-height:1.5}
.vs .trend{margin-right:4px}
.vs .note{display:inline;margin:0}
.today-chart{min-width:0;display:flex;flex-direction:column;gap:4px}
.today-chart svg{display:block;overflow:visible}
.tmed{fill:none;stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:5 4}
.tline{fill:none;stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round}
.tlegend{margin:0}
.tk{display:inline-block;width:14px;height:10px;border-radius:2px;background:color-mix(in oklch,var(--mark) 24%,transparent)}
.tk.med{height:0;border-top:2px dashed var(--ink2);background:none;border-radius:0}
.tk.now{height:3px;background:var(--mark-ink)}
.tk.band{background:var(--tint)}
.latest{margin-top:14px}
/* range totals: one container, 1px rules between the tiles (the grid gap shows the container's colour) */
.kpis.strip{display:grid;grid-template-columns:1.5fr repeat(5,minmax(0,1fr));gap:1px;background:var(--grid);overflow:hidden;margin:0 0 6px}
.strip .kpi{display:flex;flex-direction:column;gap:2px;min-width:0;border:0;border-radius:0;padding:14px 16px;background:var(--surface)}
.strip .kpi b{order:1}
.strip .kpi .dl{order:2;margin:0}
.strip .kpi .spark{order:3;margin-top:auto;padding-top:6px;width:100%;max-width:140px;height:auto}
.strip .kpi b{font-size:22px}
.strip .kpi:first-child b{font-size:28px}
.strip .kpi:first-child .spark{max-width:220px}
.strip-note{margin:0 0 16px}
@media (max-width:1200px){.kpis.strip{grid-template-columns:repeat(3,minmax(0,1fr))}}
/* biggest movers */
.cause{margin:0 0 10px}
.movers{width:100%}
.movers th:first-child,.movers td:first-child{text-align:left;white-space:normal;overflow-wrap:anywhere}
.movers :is(th,td):nth-child(2){text-align:left}
.movers :is(th,td):is(:nth-child(3),:nth-child(4),:nth-child(5)){text-align:right;white-space:nowrap}
.movers td{vertical-align:baseline}
.tag{display:inline-block;font-size:11px;font-weight:500;padding:1px 8px;border-radius:999px;background:var(--chip);color:var(--ink2)}
#trend .legend{margin:0 0 6px}
svg rect.m.a{fill:var(--agent)}
.key i.dash{height:0;width:14px;border-top:2px dashed var(--agent-ink);background:none;border-radius:0;box-shadow:none}
svg .vmark{cursor:default}
/* top spenders: one container, three columns split by 1px rules */
.spenders .cols3{display:grid;grid-template-columns:repeat(var(--n,3),minmax(0,1fr));gap:0}
.spenders .col{padding:0 18px;border-left:1px solid var(--grid);min-width:0}
.spenders .col:first-child{padding-left:0;border-left:0}
.spenders .col:last-child{padding-right:0}
.spenders .col h3{margin-top:4px}
.spenders .cols3 td:first-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;overflow-wrap:normal}
@media (max-width:900px){.spenders .cols3{grid-template-columns:1fr}.spenders .col{padding:12px 0 0;border-left:0;border-top:1px solid var(--grid)}
.spenders .col:first-child{border-top:0;padding-top:0}}
/* header: a label over each filter, the privacy level as a chip beside the title, the range dates after Apply */
.fl{display:flex;flex-direction:column;gap:3px}
.filters{align-items:flex-end}
.dash-head .privacy{display:inline-flex;align-items:center;margin:0;padding:2px 10px;border-radius:999px;font-size:12px}
.range-dates{flex:1 0 100%;margin:0;text-align:right}
/* sidebar: counts beside the pages; Theme and Design as segmented controls */
.side-foot.ctls{display:flex;flex-direction:column;align-items:stretch;gap:12px;margin:18px 0 0 4px}
.ctl{display:flex;flex-direction:column;gap:4px}
.segctl{display:flex}
.segctl .chip{flex:1;justify-content:center;border-radius:0;padding:5px 8px}
.segctl .chip+.chip{margin-left:calc(-1*var(--line-w,1px))}
.segctl .chip:first-child{border-radius:999px 0 0 999px}
.segctl .chip:last-child{border-radius:0 999px 999px 0}
#keys-btn{align-self:flex-start}
/* end overview */
/* phone */
/* Under 640 px (max-width:639px, the same in the script) the sidebar is a 52 px top bar. Its Menu button, or the filter pill, opens a full sheet with the pages, the
   filters, the theme controls and the privacy note (script in DASH_JS). On a wider screen the sheet is display:contents, so the
   sidebar looks as before, and the phone-only parts (button, pill, second filter form, note) stay hidden. The skin sheets load
   after this one and `.chip` resets everything (all:unset), so rules on a chip or a skin-styled part start with `body` or
   `.layout` to win on specificity. Sizes are layout; colours and outlines read tokens, and Classic restyles only the look. */
body .menu-btn,body .pill-btn,.sheet-filters,.sheet-priv,.menu-i,.pill-i{display:none}
.sheet{display:contents}
#trend svg.narrow{display:none}
@media (max-width:639px){
html.menu-open{overflow:hidden}
body .chip{box-sizing:border-box}
.layout{display:block}
.layout>.side{position:sticky;top:0;height:52px;padding:0 6px 0 16px;display:flex;align-items:center;justify-content:space-between;gap:8px;
overflow:visible;border-right:0;border-bottom:1px solid var(--edge);z-index:40}
.layout .brand{display:flex;margin:0}
body .menu-btn{display:inline-flex;align-items:center;gap:8px;min-height:44px;min-width:44px;padding:0 16px;font-size:14px}
.menu-i{display:block;width:16px;height:12px;background:linear-gradient(currentColor 0 0) 0 0/100% 2px no-repeat,linear-gradient(currentColor 0 0) 0 50%/100% 2px no-repeat,linear-gradient(currentColor 0 0) 0 100%/100% 2px no-repeat}
.menu-btn[aria-expanded=true] .menu-i{background:linear-gradient(currentColor 0 0) 0 50%/100% 2px no-repeat}
.layout .sheet{display:block;position:fixed;top:52px;left:0;right:0;bottom:0;overflow-y:auto;overscroll-behavior:contain;background:var(--page);padding:8px 16px 40px;
opacity:0;visibility:hidden;transform:translateY(-8px);
transition:opacity calc(var(--t-layout)*.7) var(--ease-exit),transform calc(var(--t-layout)*.7) var(--ease-exit),visibility calc(var(--t-layout)*.7)}
.layout .sheet.open{opacity:1;visibility:visible;transform:none;
transition:opacity var(--t-layout) var(--ease),transform var(--t-layout) var(--ease-expo),visibility calc(var(--t-fast)*0)}
.sheet .toc{flex-direction:column;white-space:normal;gap:2px}
.sheet .toc a{min-height:48px;padding:0 12px;font-size:16px}
.sheet .toc a .cnt{display:inline}
.sheet .sub-toc{display:none}
.sheet .sheet-filters{display:flex;flex-direction:column;align-items:stretch;gap:12px;margin:20px 0 0}
.sheet-filters .ctl-l{margin:0}
.sheet-filters .fl{gap:4px}
.layout .sheet-filters select{width:100%;max-width:none;min-height:44px;font-size:16px}
.sheet-filters .chip{align-self:flex-start;justify-content:center;min-height:44px;min-width:44px;padding:0 20px;font-size:14px}
.sheet-filters a{display:inline-flex;align-items:center;min-height:44px}
.sheet .side-foot.ctls{margin:20px 0 0}
.sheet .segctl .chip{min-height:44px;font-size:14px}
.sheet #keys-btn{display:none}
.sheet .sheet-priv{display:block;margin:20px 0 0}
/* the header: the title row, then the filters as one pill that opens the sheet */
.dash-head{gap:8px 12px}
.dash-head>.filters{display:none}
body .pill-btn{display:flex;flex:1 0 100%;align-items:center;justify-content:space-between;gap:10px;min-height:44px;padding:0 16px;font-size:14px;text-align:left}
.pill-btn>span:first-child{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pill-i{display:block;flex:none;width:8px;height:8px;border:solid currentColor;border-width:0 2px 2px 0;transform:rotate(45deg) translate(-2px,-2px)}
.range-dates{flex-basis:100%;text-align:left}
main{padding:16px 12px 72px}
/* range totals: two columns, Tokens across both, each tile keeps its sparkline */
.kpis.strip{grid-template-columns:repeat(2,minmax(0,1fr))}
.strip .kpi:first-child{grid-column:1/-1}
.strip .kpi:last-child:nth-child(even){grid-column:1/-1}
.strip .kpi .spark{max-width:none;height:36px}
/* tables become two-line rows: the name on the first line, its numbers on the second */
.movers tr:has(th),.spenders tr:has(th){display:none}
.movers,.movers tbody,.spenders table,.spenders tbody{display:block}
.movers tr{display:grid;grid-template-columns:auto minmax(0,1fr) auto;column-gap:12px;align-items:baseline;padding:8px 0;border-top:1px solid var(--grid)}
.movers td,.spenders td{border:0}
.movers td{padding:0;text-align:left;white-space:normal}
.movers td:first-child{grid-column:1/3;overflow-wrap:break-word;font-weight:600}
.movers td:last-child{grid-column:3;grid-row:1;text-align:right;white-space:nowrap}
.movers td:nth-child(2){grid-column:1;grid-row:2}
.movers td:nth-child(3){grid-column:2;grid-row:2;white-space:nowrap}
.movers td:nth-child(4){grid-column:3;grid-row:2;text-align:right;white-space:nowrap}
.movers td:nth-child(3)::before{content:"Before ";color:var(--muted)}
.movers td:nth-child(4)::before{content:"Now ";color:var(--muted)}
.spenders tr{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px;align-items:baseline;padding:2px 0;border-top:1px solid var(--grid)}
.spenders td{padding:0;white-space:nowrap}
.spenders .cols3 td:first-child{grid-column:1/-1;white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:break-word;text-align:left}
.spenders td:first-child a,.spenders td:first-child span{display:inline-flex;align-items:flex-end;min-height:44px;padding-bottom:2px}
.spenders td:nth-child(2){text-align:left}
.spenders .bar{justify-content:flex-start}
.spenders .bar i{display:none}
.spenders td:nth-child(3){text-align:right;padding-bottom:8px}
.spenders td:nth-child(2){padding-bottom:8px}
/* daily chart: a phone shows the 14-day chart with 4 labels, not the wide one */
#trend svg.wide{display:none}
#trend svg.narrow{display:block}
/* sessions: two lines. Title and tokens, then time, top skill and the split bar */
#session-list{--scols:44px auto minmax(0,1fr) 72px 24px}
#session-list .shead[aria-hidden]{display:none}
#session-list .srow>summary{height:auto;min-height:56px;padding:6px 6px 6px 0;gap:2px 8px}
#session-list .srow>summary>input{grid-column:1;grid-row:1/3}
#session-list .srow>summary .t{grid-column:2/4;grid-row:1;padding-left:calc(var(--depth,0)*14px)}
#session-list .srow>summary .r{grid-column:4;grid-row:1}
#session-list .srow>summary .cv{grid-column:5;grid-row:1/3}
#session-list .srow>summary .d{grid-column:2;grid-row:2;font-size:12px}
#session-list .srow>summary .sk{grid-column:3;grid-row:2;font-size:12px;min-width:0;overflow:hidden;text-overflow:ellipsis}
#session-list .srow>summary .track{grid-column:4;grid-row:2}
#session-list .srow>summary :is(.d,.sk,.track,.split){display:block}
#session-list :is(.n,.sid8){display:none}
#session-list .srow.orphan>summary .t{flex-direction:row}#session-list .srow>summary .from{max-width:45%}  /* an orphan child keeps its link to the parent (#28 review) */
#session-list .btn.kids-more{margin-left:calc(44px + var(--depth)*14px);min-height:44px}
#session-list .srow>summary>input{appearance:none;-webkit-appearance:none;width:44px;height:44px;margin:0;display:grid;place-items:center}
#session-list .srow>summary>input::before{content:"";width:18px;height:18px;border:var(--line-w,1px) solid var(--ink);border-radius:4px;background:var(--surface)}
#session-list .srow>summary>input:checked::before{background:var(--mark) linear-gradient(135deg,transparent 42%,var(--surface) 42% 52%,transparent 52%);}
#session-list .srow>summary>input:focus-visible{outline:2px solid var(--ink);outline-offset:-4px}
#sessions .tools .seg .chip,#sessions .tools input[type=search]{min-height:44px}
#sessions .pickbar .primary,#sessions .pickbar .btn{min-height:44px}
/* touch targets: 44 px */
body .btn,body .primary,body .chip:not(.menu-btn):not(.pill-btn),main select,main input[type=search],main input[type=text]{min-height:44px}
main .latest a,main td a,main li>a{display:inline-flex;align-items:center;min-height:44px}
main details>summary{min-height:44px}
main .totop{width:44px;height:44px}
/* a long word wraps whole at a space or a hyphen; only a word wider than the line breaks, and then at the line's edge */
main :is(td,li,p,h1,h2,h3,b,.tt){overflow-wrap:break-word;hyphens:manual}
}
@media (max-width:639px) and (prefers-reduced-motion:reduce){
/* the sheet and its button fade, they do not travel */
html .layout .sheet,html .layout .sheet.open{transform:none;transition:opacity var(--t-state) var(--ease),visibility var(--t-state)}
html .layout .sheet.open{transition:opacity var(--t-state) var(--ease),visibility calc(var(--t-fast)*0)}
}
@media (max-width:639px){#session-list .srow .live :is(.where,.lbl){display:none}#session-list .srow .live{padding:4px;margin-left:6px}}
/* end phone */
@media (prefers-reduced-motion:reduce){
@keyframes ring{from{opacity:.35}}
@keyframes chip-in{from{opacity:0}}
@keyframes chip-out{to{opacity:0}}
@keyframes toast-in{from{opacity:0}}
}
@media (prefers-reduced-motion:reduce){.dot.live.busy-now,.srow .live.working i{animation:none}}
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

# The skin tokens (set in the :root rule of both skins; the dark rules only change colours and the line weight and shadow tokens). Ink value | Classic value.
#   --line-w 1.5px | 1px         outline width of a card, control or tray
#   --line-c ink | edge          outline colour;  --focus-c ink | mark: focus ring;  --row-c grid | edge: row and day rules
#   --r-card 14px | 12px         radius of a card;  --r-tile 12px | 10px: tile, row, KPI;  --r-box 12px | 8px: panel, list
#   --r-ctl 999px | 8px          radius of an input, select, chip;  --r-btn 999px | 6px: small button;  --r-bar 5px | 4px: bar track
#   --bar-h 10px | 8px           height of a share or split bar;  --key-s 12px | 10px: legend swatch
#   --pad-sel / --pad-in / --pad-chip / --pad-btn: padding of a select, a text input, a chip, a small button
#   --in-bg surface | page       background of an input
#   --num-font mono | sans       font of labels, numbers and controls
#   --lab-case uppercase | none, --lab-track .08em | normal, --lab-size 11px | 12px, --lab-w 600 | 400, --lab-c muted | ink2:
#                                a label (KPI caption, column head, filter label)
#   --cell-size 13px | 1em       number cells;  --btn-w 500 | 400: button weight;  --ctl-size 12px | 13px: control text
#   --seg-ring 1px ink ring | none   ring around a stacked-bar segment;  --trace-c mark-ink | mark: sparkline and line colour
#   --dot-edge ink | surface     edge of a chart dot
#   Motion tokens (--t-fast, --t-state, --t-layout, --ease-exit) are the same in both skins and are set below.

LAYOUT_TOKEN_CSS = """
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 var(--sans);accent-color:var(--mark)}
.sub{color:var(--ink2);margin:0 0 16px}
pre.diff .add{color:var(--pass)}
pre.diff .del{color:var(--fail)}
pre.diff .hunk{color:var(--muted)}
.few{font-size:10px;font-weight:600;text-transform:uppercase;color:var(--muted);border:1px solid var(--line-c);border-radius:4px;padding:0 4px;margin-left:4px}
code.ver{font-size:11px;color:var(--muted);background:var(--chip);border-radius:4px;padding:0 4px;margin-left:2px}
.privacy{border:var(--line-w) solid var(--line-c);border-radius:var(--r-box);padding:8px 12px;margin:0 0 12px;font-size:13px;color:var(--ink2);background:var(--surface)}
.privacy b{color:var(--mark-ink);text-transform:uppercase;font-size:11px;margin-right:6px;margin:0}
.note{color:var(--muted);font-size:12px;margin:0 0 10px}
.usd{color:var(--muted);font-size:12px}
:focus-visible{outline:2px solid var(--focus-c);outline-offset:2px}
.hero{position:relative;overflow:hidden;border-radius:14px;padding:20px 22px;animation:rise-in var(--t-layout) var(--ease-expo) backwards}
.hero p{margin:2px 0;color:var(--ink2)}
.hero .big em{font-style:normal;font-weight:600}
.hero a{color:var(--mark-ink);text-underline-offset:2px}
.trend{display:inline-block;padding:1px 8px;border-radius:999px;font-weight:600}
.up{color:var(--fail);background:color-mix(in oklch,var(--fail) 13%,transparent)}
.down{color:var(--pass);background:color-mix(in oklch,var(--pass) 13%,transparent)}
.budgets li.bgt{display:grid;grid-template-columns:minmax(0,12em) minmax(60px,1fr) 4em;gap:2px 10px;align-items:center;margin:8px 0}
.bgt .bl{overflow-wrap:anywhere}
.bgt b{text-align:right;font-variant-numeric:tabular-nums}
.bgt .note{grid-column:1/-1;margin:0}
.bgt .bt{display:block;height:var(--bar-h);background:var(--track);border-radius:var(--r-bar);overflow:hidden}
.bgt .bt u{display:block;height:100%;background:var(--pass);border-radius:0 4px 4px 0}
.bgt.near .bt u{background:var(--agent)}
.bgt.over .bt u{background:var(--fail)}
.bgt.over b{color:var(--fail)}
.kpi{background:var(--surface);border:var(--line-w) solid var(--line-c);border-radius:var(--r-tile);padding:10px 14px;min-width:120px;position:relative;overflow:hidden;animation:rise-in var(--t-layout) var(--ease-expo) backwards;animation-delay:calc(120ms + var(--i,0)*70ms)}
.kpi span{display:block;color:var(--ink2);font-size:12px}
.kpi b{font-size:19px;font-variant-numeric:tabular-nums}
.card{background:var(--surface);border:var(--line-w) solid var(--line-c);border-radius:var(--r-card);padding:14px 16px;margin-bottom:14px;overflow-x:auto}
details.more{background:var(--surface);border:var(--line-w) solid var(--line-c);border-radius:var(--r-card);padding:10px 16px;margin-bottom:10px}
details.more>summary::before{content:"›";display:inline-block;color:var(--mark-ink);font-weight:600;transition:transform var(--t-state) var(--ease)}
details.more>summary .note{flex:1 1 18em;min-width:0;overflow-wrap:anywhere;font-weight:400;margin:0}
@media (max-width:640px){
details.more>summary .note{flex-basis:100%}
}
details::details-content{block-size:0;overflow:hidden;transition:block-size var(--t-layout) var(--ease),content-visibility var(--t-layout) allow-discrete}
details[open]::details-content{block-size:auto}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-weight:500;font-size:12px;border-bottom:1px solid var(--grid)}
tr+tr td{border-top:1px solid var(--grid)}
td.l{text-align:left;white-space:normal;color:var(--ink2);min-width:220px}
td.u{color:var(--muted);font-size:12px}
td.lm{text-align:left;white-space:normal;color:var(--ink2);font-size:12px}
.bar i{display:flex;gap:2px;width:90px;height:var(--bar-h);background:var(--track);border-radius:var(--r-bar);overflow:hidden}
.bar i u{display:block;height:100%;background:var(--mark);border-radius:0 4px 4px 0;transform-origin:left;animation:grow var(--t-layout) var(--ease-expo) both;animation-delay:calc(var(--i,0)*25ms)}
.bar i u.a{background:var(--agent);border-radius:0 4px 4px 0}
.bar i u:has(+u.a){border-radius:0}
.key i{width:var(--key-s);height:var(--key-s);border-radius:3px;background:var(--mark)}
.key i.a{background:var(--agent)}
svg rect.m{fill:var(--mark);transform-box:fill-box;transform-origin:bottom;transition:opacity var(--t-fast)}
svg rect.hit{fill:transparent}
#tip{position:fixed;pointer-events:none;background:var(--surface);border:var(--line-w) solid var(--line-c);border-radius:8px;padding:6px 9px;font-size:12px;max-width:320px;opacity:0;transform:translateY(6px);z-index:30}
#tip.on{opacity:1;transform:none}
.pass,.fail{font-weight:600;padding:0 7px;border-radius:999px}
.pass{color:var(--pass);background:color-mix(in oklch,var(--pass) 13%,transparent)}
.fail{color:var(--fail);background:color-mix(in oklch,var(--fail) 13%,transparent)}
.delta{font-size:22px;font-weight:600;color:var(--mark-ink)}
pre.answer{white-space:pre-wrap;font:12px/1.5 var(--mono);background:var(--page);padding:10px;border-radius:8px;max-height:480px;overflow:auto}
mark{background:var(--hl);color:inherit;border-radius:2px}
.tools input[type=search],.tools select{font:inherit;padding:var(--pad-in);border:var(--line-w) solid var(--line-c);border-radius:var(--r-ctl);background:var(--in-bg);color:var(--ink)}
.srow{border:var(--line-w) solid var(--line-c);border-radius:var(--r-tile);background:var(--surface);margin-bottom:8px}
.srow.ghost{position:absolute;left:0;right:0;margin:0;pointer-events:none;z-index:0}
.srow[open]{background:color-mix(in oklch,var(--mark) 4%,var(--surface))}
.srow>summary{display:grid;grid-template-columns:22px 92px 1fr 90px 74px 92px 150px 14px;gap:8px;align-items:center;padding:9px 10px;cursor:pointer;list-style:none;border-radius:10px}
.srow>summary:focus-visible{outline:2px solid var(--focus-c);outline-offset:2px}
.srow:hover>summary .t{color:var(--mark-ink)}
.cv{color:var(--muted);font-weight:600;text-align:center;transition:transform var(--t-state) var(--ease),color var(--t-fast) var(--ease)}
.srow:hover .cv{color:var(--mark-ink)}
.srow[open] .cv{transform:rotate(90deg);color:var(--mark-ink)}
.side{position:sticky;top:0;align-self:start;height:100vh;overflow-y:auto;padding:28px 12px 20px 16px;border-right:1px solid var(--edge);background:var(--page);z-index:10}
.brand{font-weight:600;font-size:13px;margin:0 0 14px 10px;display:flex;align-items:center;gap:7px}
.toc a{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 10px;border-radius:8px;color:var(--ink2);text-decoration:none;font-size:14px;transition:background var(--t-fast) var(--ease),color var(--t-fast) var(--ease),transform var(--t-fast) var(--ease);position:relative;z-index:1}
.toc a:hover{background:color-mix(in oklch,var(--mark) 10%,transparent);color:var(--ink);transform:translateX(2px)}
.toc a.on{background:color-mix(in oklch,var(--mark) 15%,transparent);color:var(--mark-ink);font-weight:600}
.toc a:focus-visible{outline:2px solid var(--focus-c);outline-offset:1px}
.sub-toc{display:flex;flex-direction:column;gap:1px;margin:2px 0 4px 14px;padding-left:6px;border-left:1px solid var(--grid)}
.sub-toc a{font-size:13px;padding:4px 10px}
.cnt{font-size:11px;font-weight:400;color:var(--muted);font-variant-numeric:tabular-nums;background:var(--chip);padding:1px 7px;border-radius:999px}
.totop{position:fixed;right:22px;bottom:22px;z-index:25;width:44px;height:44px;border-radius:50%;font:700 18px/1 inherit;background:var(--surface);opacity:0;visibility:hidden;transform:translateY(10px);transition:opacity var(--t-state) var(--ease),transform var(--t-state) var(--ease),visibility var(--t-state),bottom var(--t-state) var(--ease),background var(--t-fast) var(--ease),color var(--t-fast) var(--ease)}
.totop.show{opacity:1;visibility:visible;transform:none}
.totop.show:hover{transform:translateY(-2px)}
.totop:focus-visible{outline:2px solid var(--focus-c);outline-offset:2px}
body.picking .totop{bottom:92px}
@media (max-width:900px){
.layout{display:block}
.side{height:auto;padding:8px 16px;border-right:0;border-bottom:1px solid var(--edge);overflow-x:auto;overflow-y:hidden;scrollbar-width:none}
.side::-webkit-scrollbar{display:none}
.brand,.sub-toc,.cnt{display:none}
.toc{flex-direction:row;white-space:nowrap}
.toc a:hover{transform:none}
}
/* everything that reacts to a click shows the hand cursor */
a,summary,label,select,button:not(:disabled),input[type=checkbox],svg [data-change],[data-copy]{cursor:pointer}
.pickbar{position:sticky;bottom:12px;z-index:20;display:flex;gap:10px;align-items:center;justify-content:space-between;margin:4px 0 8px;padding:10px 14px;border-radius:12px;background:var(--surface);animation:pop var(--t-state) var(--ease) both}
.pickbar[hidden]{display:none}
.primary{all:unset;cursor:pointer;padding:6px 14px;border-radius:var(--r-ctl)}
.primary:focus-visible{outline:2px solid var(--focus-c);outline-offset:2px}
.primary:disabled{opacity:.45;cursor:not-allowed}
.srow>summary::-webkit-details-marker{display:none}
.srow.child{margin-left:calc(var(--depth)*24px);position:relative;overflow:visible}
.srow.child::before{content:'';position:absolute;left:-15px;top:-10px;height:calc(10px + 1.3em);width:10px;border-bottom-left-radius:6px}
.srow.child>summary .t::before,.srow.orphan>summary .tt::before{content:'↳ ';color:var(--muted)}
.srow.child.ghost{position:absolute}
.srow>summary .from{flex:none;max-width:45%;overflow:hidden;text-overflow:ellipsis;color:var(--muted);font-size:12px}
.srow>summary .n{white-space:nowrap;color:var(--ink2);font-size:13px}
.srow>summary .sk{color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.split{display:flex;gap:2px;height:var(--bar-h);border-radius:var(--r-bar);overflow:hidden;background:var(--track)}
.split u{display:block;height:100%;background:var(--mark)}
.split u.a{background:var(--agent)}
.srow .body td.calls{min-width:300px}
.run{display:grid;grid-template-columns:minmax(0,max-content) minmax(0,1fr) auto auto;column-gap:10px;align-items:baseline;padding:3px 8px 3px calc(8px + var(--d,0)*16px);border-radius:6px;line-height:1.5;transition:background var(--t-fast) var(--ease)}
.run .rt{color:var(--agent-ink);font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:240px}
tr.runs-row td{border-top:0;padding-top:0}
.runs{border-radius:8px;padding:4px;background:color-mix(in oklch,var(--agent) 4%,var(--surface));text-align:left;white-space:normal}
.run .rd{color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.runs-more>summary{padding:2px 8px;color:var(--mark-ink);font-size:12px}
.est{color:var(--ink);font-variant-numeric:tabular-nums}
.ck{display:inline-block;min-width:46px;margin-right:6px;font-size:11px;color:var(--muted)}
.ck.agents{color:var(--agent-ink)}
.ck.mcp{color:var(--mark-ink)}
.ids{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 12px;align-items:center;margin:4px 0 10px;padding:10px 12px;background:var(--surface);border:var(--line-w) solid var(--line-c);border-radius:var(--r-tile)}
.ids dt{color:var(--muted);font-size:12px}
.ids dt:first-child,.ids dt:first-child+dd .code{font-weight:600;color:var(--ink)}
.code{font:12px var(--mono);background:var(--chip);padding:2px 6px;border-radius:4px;user-select:all}
#compare{display:none}
#compare.on{display:block;animation:pop var(--t-state) var(--ease) both}
.btn{all:unset;cursor:pointer;font-size:12px;padding:var(--pad-btn);border-radius:var(--r-btn)}
@media (max-width:640px){
.srow>summary{grid-template-columns:22px 1fr 80px 14px}
.srow>summary .d,.srow>summary .sk,.srow>summary .n,.srow>summary .split{display:none}
.srow.child{margin-left:calc(var(--depth)*14px)}
.srow.child::before{left:-10px;width:6px}
.btn.kids-more{margin-left:calc(var(--depth)*14px)}
.srow.orphan>summary .t{flex-direction:column;align-items:stretch;gap:0}
.srow>summary .from{max-width:100%}
}
#progress{position:fixed;inset:0 0 auto 0;height:3px;z-index:40;transform-origin:0 50%;transform:scaleX(0)}
/* sidebar: one pill slides to the section in view */
.toc{position:relative}
.toc-pill{position:absolute;left:0;top:0;border-radius:8px;pointer-events:none;background:color-mix(in oklch,var(--mark) 15%,transparent);box-shadow:inset 3px 0 0 var(--mark);transition:transform var(--t-layout) var(--ease-expo),width var(--t-layout) var(--ease-expo),height var(--t-layout) var(--ease-expo),opacity var(--t-state)}
.has-pill .toc a.on{background:transparent}
.side-foot{display:flex;gap:6px;margin:18px 0 0 4px}
.chip{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2);padding:var(--pad-chip);border:var(--line-w) solid var(--line-c);border-radius:999px}
.chip:focus-visible{outline:2px solid var(--focus-c);outline-offset:2px}
.chip kbd,.keys kbd{font:600 11px var(--mono);padding:1px 6px;border-radius:5px;border:1px solid var(--edge);border-bottom-width:2px;background:var(--surface);color:var(--ink)}
::view-transition-old(root),::view-transition-new(root){animation:none;mix-blend-mode:normal}
/* chart: 7-day average draws itself in; a guide follows the pointer */
svg .ma{fill:none;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:0}
#trend[open] svg .ma{animation:draw calc(var(--t-layout)*2) var(--ease-expo) var(--t-state) backwards}
.key i.ln{height:3px;border-radius:2px}
/* copy feedback, empty state, shortcuts dialog */
.btn.ok{color:var(--pass);background:color-mix(in oklch,var(--pass) 14%,transparent);animation:pop var(--t-state) var(--ease) both}
#toast{position:fixed;left:50%;bottom:26px;z-index:50;transform:translate(-50%,16px);opacity:0;pointer-events:none;padding:9px 16px;border-radius:999px;background:var(--ink);color:var(--page);font-size:13px;font-weight:600}
#toast.on{opacity:1;transform:translate(-50%,0)}
.empty{text-align:center;padding:34px 12px;color:var(--muted);border:1px dashed var(--grid);border-radius:12px;animation:reveal var(--t-layout) var(--ease) both}
.empty b{display:block;color:var(--ink);font-size:15px;margin-bottom:4px}
#s-more{padding:6px 14px}
dialog.keys{border:var(--line-w) solid var(--line-c);border-radius:14px;background:var(--surface);color:var(--ink);padding:18px 22px;min-width:300px}
dialog.keys[open]{animation:pop-in var(--t-layout) var(--ease-expo) both}
dialog.keys::backdrop{background:#0005}
dialog.keys dd{margin:0;color:var(--ink2)}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--ink2);margin:8px 0 10px}
.legend b{color:var(--ink);font-weight:600}
.share{display:flex;gap:2px;height:16px;border-radius:4px;overflow:hidden;margin-top:6px}
.share i{display:block;min-width:3px;transform-origin:left;transition:filter var(--t-fast)}
.viz .dot{fill:var(--c1);transition:r var(--t-fast) var(--ease)}
.viz .dot:not(.hi){fill:color-mix(in oklch,var(--c1) 55%,var(--surface))}
.viz circle.hit,.viz rect.hit{fill:transparent}
.viz g.rg:hover rect.hit,.viz g.db:hover rect.hit{fill:color-mix(in oklch,var(--mark) 6%,transparent)}
#breakdowns details[open] .share i{animation:grow var(--t-layout) var(--ease-expo) both;animation-delay:calc(var(--i,0)*60ms)}
#breakdowns details[open] .viz g.seg{transform-box:fill-box;transform-origin:bottom;animation:rise var(--t-layout) var(--ease-expo) both;animation-delay:calc(var(--i,0)*70ms)}
#breakdowns details[open] .viz g.pt,#breakdowns details[open] .viz g.rg,#breakdowns details[open] .viz g.db{animation:rise-in var(--t-layout) var(--ease-expo) both;animation-delay:calc(min(var(--i,0),20)*25ms)}
#breakdowns details[open] .viz g.rg .span,#breakdowns details[open] .viz g.db .span{animation:draw calc(var(--t-layout)*2) var(--ease-expo) both;animation-delay:calc(var(--i,0)*30ms + .1s)}
td:first-child{white-space:normal;overflow-wrap:anywhere;min-width:8ch}
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
/* sessions look */
#session-list{border:var(--line-w) solid var(--line-c);border-radius:var(--r-box);background:var(--surface)}
#session-list .shead,#session-list .dayhd{color:var(--muted)}
#session-list .dayhd{background:var(--chip);border-top:1px solid var(--row-c);border-bottom:1px solid var(--row-c)}
#session-list .dayhd b{color:var(--ink);font-weight:600}
#session-list .shead+.dayhd{border-top:0}
#session-list .srow>summary{box-shadow:inset 0 -1px 0 var(--row-c)}
/* type. --num-font: labels, numbers and controls (mono in Ink, sans in Classic). --lab-*: size, weight, case, tracking and
   colour of a label. --cell-size: a number cell. --btn-w: a button's weight. --ctl-size: the text of a control. */
.kpi>span:first-child,.ids dt,th{font-size:var(--lab-size)}
.kpi>span:first-child,.today-nums span,.ck,.ids dt,.fm dt,th{font-family:var(--num-font);text-transform:var(--lab-case);letter-spacing:var(--lab-track)}
.kpi>span:first-child,.today-nums span,.ck,.ids dt,.fm dt{font-weight:var(--lab-w)}
.kpi>span:first-child{color:var(--lab-c)}
td:not(:first-child):not(.runs-row td),td[data-label="#"],td.u,.est,.run .usd,.cnt,.few,.trend,time,.srow>summary :is(.d,.r,.n,.sk),.note [data-count],.srow>summary .t.sid,.ids dd,.run .rt,.today-nums b,.pnums b,.btn,.primary,.chip,.tools select,.tools input[type=search]{font-family:var(--num-font)}
td:not(:first-child):not(.l):not(.lm):not(.u):not(:is(.runs-row,table.sbs) td){font-size:var(--cell-size)}
td.l,td.lm,td.calls,.md td{font-family:var(--sans)}
.today-nums b,.pnums b{font-weight:600}
.btn,.chip{font-weight:var(--btn-w)}
.bar i u,.key i,.split u,.share i,.runbar i{box-shadow:var(--seg-ring)}
"""

LAYOUT_TOKEN_DASH_CSS = """
main a{color:var(--mark-ink);text-underline-offset:2px}
.filters select{font:inherit;font-size:13px;padding:var(--pad-sel);border:var(--line-w) solid var(--line-c);border-radius:var(--r-ctl);background:var(--surface);color:var(--ink);max-width:220px}
.filters a{font-size:12px;color:var(--muted)}
.fresh{font-size:12px;color:var(--muted);display:inline-flex;align-items:center;gap:6px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--pass);margin-right:8px}
.fresh .dot{margin:0}
[data-region=kpis] .kpi{min-width:0}
.kpi{background:var(--surface);border:var(--line-w) solid var(--line-c);border-radius:var(--r-tile);padding:10px 14px;min-width:120px;position:relative;overflow:hidden;animation:rise-in var(--t-layout) var(--ease-expo) backwards;animation-delay:calc(120ms + var(--i,0)*70ms)}
.kpi .dl{display:block;font-size:11px;color:var(--muted);margin-top:2px}
.kpi .dl .trend{display:inline-block;font-size:11px;padding:0 6px}
.spark polyline{fill:none;stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
.cols2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr)}
.cols3 table{width:100%;table-layout:fixed}
.cols3 th:nth-child(2),.cols3 td:nth-child(2){width:130px}
.cols3 th:nth-child(3),.cols3 td:nth-child(3){width:48px}
.cols3 .bar i{width:48px}
.cols3 td:first-child{white-space:normal;overflow-wrap:anywhere}
@media (max-width:900px){
.cols2,.cols3{grid-template-columns:1fr}
}
.today-nums span{display:block;font-size:12px;color:var(--ink2)}
.today-nums b{font-size:22px;font-variant-numeric:tabular-nums}
.latest{display:flex;flex-direction:column;gap:3px;border-top:1px solid var(--grid);padding-top:10px}
.latest a{color:var(--ink);text-decoration:none}
.latest a:hover b{color:var(--mark-ink)}
ul.plain li{padding:4px 0;border-bottom:1px solid var(--grid)}
#newdata{position:fixed;right:20px;bottom:20px;z-index:40}
.libtools input[type=search]{min-width:min(100%,280px)}
.libgroup h2 .note{margin:0 0 0 8px;font-weight:400}
a.sk{display:flex;flex-direction:column;gap:6px;background:var(--surface);border:var(--line-w) solid var(--line-c);border-radius:12px;padding:12px 14px;color:var(--ink);text-decoration:none}
a.sk b{font-size:14px;overflow-wrap:anywhere}
a.sk p{margin:0;color:var(--ink2);font-size:12.5px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
a.sk .meta{margin-top:auto;font-size:11.5px;color:var(--muted)}
.badge{font-size:11px;font-weight:500;padding:1px 7px;border-radius:999px;background:var(--chip);color:var(--ink2);margin-left:8px;vertical-align:1px}
.badge.inst{color:var(--agent-ink)}
@media (max-width:860px){
.libview{grid-template-columns:minmax(0,1fr)}
.files{position:static;max-height:190px}
}
.files{position:sticky;top:12px;padding:8px;max-height:calc(100vh - 24px);overflow:auto}
.files a{display:block;padding:4px 8px;border-radius:6px;font:12px/1.4 var(--mono);color:var(--ink2);overflow-wrap:anywhere;text-decoration:none}
.files a:hover{color:var(--mark-ink)}
.files a.on{background:var(--tint);color:var(--mark-ink)}
.viewbar .note{margin:0}
.md{font-size:14px;line-height:1.6;max-width:84ch;overflow-wrap:anywhere}
.md>:first-child{margin-top:0}
.md h2{font-size:17px;border-bottom:1px solid var(--grid);padding-bottom:4px}
.md h1,.md h2,.md h3,.md h4{margin:20px 0 8px}
.md p,.md ul,.md ol{margin:0 0 10px}
.md li{margin:2px 0}
.md code{font:.88em var(--mono);background:var(--chip);border-radius:4px;padding:1px 4px}
.md pre,pre.src{font:12.5px/1.55 var(--mono);background:var(--page);border:var(--line-w) solid var(--line-c);border-radius:8px;padding:10px 12px;margin:0 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}
.md pre code{background:none;padding:0;font-size:inherit}
.md blockquote{margin:0 0 10px;padding:2px 12px;border-left:3px solid var(--grid);color:var(--ink2)}
.md table{margin:0 0 12px}
.md td,.md th{white-space:normal;overflow-wrap:anywhere;vertical-align:top;text-align:left}
.md hr{border:0;border-top:1px solid var(--grid);margin:16px 0}
.libhead .ids dd{display:block;min-width:0;overflow-wrap:anywhere}
.libhead .ids dt:first-child{font-weight:400;color:var(--muted)}
pre.src .ln::before{counter-increment:ln;content:counter(ln);display:inline-block;width:4ch;margin-right:1.5ch;text-indent:0;text-align:right;color:var(--muted);user-select:none}
pre.src .ln.hit{background:var(--hl);border-radius:3px}
.libtools select{font:inherit;font-size:13px;padding:var(--pad-sel);border:var(--line-w) solid var(--line-c);border-radius:var(--r-ctl);background:var(--surface);color:var(--ink)}
.seg .chip b{color:var(--fail);font-weight:600}
ol.ste{list-style:none;margin:10px 0 0;padding:0}
ol.ste li{display:grid;grid-template-columns:auto auto 1fr;gap:2px 10px;align-items:baseline;padding:8px 0;border-bottom:1px solid var(--grid)}
ol.ste .lvl{font-size:11px;color:var(--muted);justify-self:start}
ol.ste li.hard .lvl{color:var(--fail)}
ol.ste .line{font:12.5px/1.5 var(--mono);background:var(--page);border-radius:6px;padding:4px 8px;white-space:pre-wrap;overflow-wrap:anywhere}
ol.ste mark{background:var(--hl);color:inherit;border-radius:2px}
ol.ste .msg{font-size:12.5px;color:var(--ink2)}
.pnums{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--ink2)}
.pnums b{color:var(--ink);font-size:14px}
details.folders{margin-top:8px;font-size:13px}
details.folders summary{cursor:pointer;color:var(--mark-ink)}
table.mcp td{vertical-align:baseline}
table.mcp :is(th,td):is(:nth-child(2),:nth-child(3),:nth-child(8)){text-align:left}
table.mcp td:nth-child(3){white-space:normal;overflow-wrap:anywhere}
table.mcp td:nth-child(3) .note{display:block;margin:2px 0 0}
table.mcp .st{white-space:normal;text-align:left}
/* the status is what a reader looks for: a filled pill in the state's color, the text in ink for contrast */
.st .pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;line-height:1.5;background:var(--chip);color:var(--ink2);border:1px solid transparent}
.st.ok .pill{background:color-mix(in oklch,var(--pass) 16%,transparent);border-color:color-mix(in oklch,var(--pass) 45%,transparent);color:var(--ink)}
.st.warn .pill{background:color-mix(in oklch,var(--agent) 18%,transparent);border-color:color-mix(in oklch,var(--agent) 50%,transparent);color:var(--ink)}
.st.bad .pill{background:color-mix(in oklch,var(--fail) 18%,transparent);border-color:color-mix(in oklch,var(--fail) 50%,transparent);color:var(--ink)}
.st.off .pill{font-weight:500}
table.mcp tbody tr{transition:background var(--t-fast) var(--ease)}
table.mcp tbody tr:hover td:first-child{color:var(--mark-ink)}
.badge.flag{color:var(--agent-ink)}
code.login{display:block;margin-top:2px;font-size:11.5px;color:var(--ink2);overflow-wrap:anywhere}
#mcp-add{margin-top:14px}
#mcp-find{margin-top:14px}
#reg-form{margin:6px 0}
#reg-form input{flex:1 1 20em;font:inherit;font-size:13px;padding:var(--pad-in);border:var(--line-w) solid var(--line-c);border-radius:var(--r-ctl);background:var(--in-bg);color:var(--ink)}
.sk.reg:hover{transform:none}
.sk.reg .meta a{margin-right:8px}
#mcp-form label.wide{display:flex;flex-direction:column;gap:4px;font-size:13px;margin:0 0 8px}
#mcp-form input,#mcp-form textarea,#mcp-form select{font:inherit;font-size:13px;padding:6px 8px;border:var(--line-w) solid var(--line-c);border-radius:8px;background:var(--surface);color:var(--ink);min-width:0}
#mcp-form textarea{font-family:var(--mono)}
.pair{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 6px}
#mcp-form .namefield input{flex:1;min-width:12em}
.pair input{flex:1 1 12em}
.ask{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:10px 0;padding:10px 12px;border-radius:var(--r-tile);background:color-mix(in oklch,var(--mark) 9%,var(--surface));animation:reveal var(--t-state) var(--ease) both}
.ask p{margin:0;flex:1 1 20em}
.busy{position:relative;padding-left:30px!important;opacity:.9;cursor:progress}
.busy::before{content:"";position:absolute;left:11px;top:50%;width:11px;height:11px;margin-top:-7px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .8s linear infinite}
.spin{display:inline-block;width:12px;height:12px;margin-right:7px;vertical-align:-1px;border:2px solid var(--mark);border-right-color:transparent;border-radius:50%;animation:spin .8s linear infinite}
.runbar{background:var(--track);overflow:hidden;margin:14px 0 10px}
.runbar i{display:block;width:35%;height:100%;background:var(--mark);animation:slide 1.6s var(--ease) infinite}
/* a page takes a moment to render: DASH_JS adds html.loading from a click on a link until the next page arrives */
#navload{position:fixed;inset:0 0 auto 0;height:3px;z-index:50;overflow:hidden;opacity:0;pointer-events:none;transition:opacity var(--t-state) var(--ease)}
#navload i{display:block;width:35%;height:100%;background:var(--mark);animation:slide 1.6s var(--ease) infinite}
html.loading #navload{opacity:1}
html.loading main{opacity:.6;transition:opacity var(--t-state) var(--ease)}
.runline{margin:0 0 8px}
.runline b{font-variant-numeric:tabular-nums}
p.warn{color:var(--agent-ink);font-size:13px}
ol.steps{list-style:none;margin:6px 0 0;padding:0;max-height:360px;overflow-y:auto;font-size:12.5px}
ol.steps li{display:flex;gap:10px;padding:4px 0;border-bottom:1px solid var(--grid)}
ol.steps span{min-width:0;overflow-wrap:anywhere}
ol.steps time{flex:none;width:5.5em;color:var(--muted);font:12px var(--mono)}
ol.steps li.sub span{padding-left:16px;color:var(--ink2)}
ol.steps li.say span{color:var(--ink2);font-style:italic}
ol.steps li:is(.error,.denied) span{color:var(--fail)}
ol.steps li.retry span{color:var(--agent-ink)}
ol.steps li.start span,ol.steps li.end span{font-weight:600}
.outcome{display:flex;flex-direction:column;gap:4px;margin:12px 0 6px;padding:12px 14px;border:var(--line-w) solid var(--line-c);border-radius:var(--r-tile);animation:reveal var(--t-layout) var(--ease) both}
.outcome b{font-size:15px}
.outcome span{overflow-wrap:anywhere}
.outcome.ok{background:color-mix(in oklch,var(--pass) 12%,transparent)}
.outcome.bad{background:color-mix(in oklch,var(--fail) 12%,transparent)}
.outcome.off{background:var(--chip)}
a.outcome.run{color:var(--ink);text-decoration:none;background:color-mix(in oklch,var(--mark) 9%,var(--surface));margin:-4px 0 14px}
a.outcome.run:hover{background:color-mix(in oklch,var(--mark) 15%,var(--surface))}
@media (prefers-reduced-motion:reduce){
.runbar i,.spin,.busy::before{animation:none}
#navload i{animation:none;width:100%}
}
.cmp .viewbar{margin-bottom:8px}
.cmp .path{margin:0}
table.sbs{width:100%;table-layout:fixed;border-collapse:collapse;font:12.5px/1.5 var(--mono)}
table.sbs col.n{width:3.2em}
table.sbs th{text-align:left}
table.sbs td{vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere;padding:1px 6px;border-bottom:0;text-align:left}
table.sbs td.n{color:var(--muted);text-align:right;user-select:none;padding-right:8px}
table.sbs td.del mark{background:color-mix(in oklch,var(--fail) 32%,transparent);color:inherit;border-radius:2px}
table.sbs td.add mark{background:color-mix(in oklch,var(--pass) 34%,transparent);color:inherit;border-radius:2px}
table.sbs tr.fold td{color:var(--muted);text-align:center;font-family:var(--sans);background:var(--page);padding:3px}
@media (max-width:700px){
table.sbs col.n{width:2.4em}
table.sbs{font-size:11.5px}
}
/* the decision stays in sight while you read the comparison */
.decide{position:sticky;bottom:12px;z-index:6;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between;margin:14px 0 0;padding:10px 14px;border-radius:12px;background:var(--surface);animation:reveal var(--t-layout) var(--ease) both}
.decide .note{margin-left:6px}
.btn.danger{color:var(--fail)}
#bench .verdict{font-size:14px;margin:6px 0 10px}
#bench-form{margin:10px 0}
#bench-form select{font:inherit;font-size:13px;padding:var(--pad-sel);border:var(--line-w) solid var(--line-c);border-radius:var(--r-ctl);background:var(--surface);color:var(--ink);max-width:100%}
#task-form label.wide{display:flex;flex-direction:column;gap:4px;font-size:13px;margin:0 0 8px}
#task-form input,#task-form textarea{font:inherit;font-size:13px;padding:6px 8px;border:var(--line-w) solid var(--line-c);border-radius:8px;background:var(--surface);color:var(--ink)}
#task-form textarea{font-family:var(--mono)}
#task-new{margin-top:10px}
table.bres td:not(:first-child),table.bres th:not(:first-child){text-align:right}
table.bres td:last-child,table.bres th:last-child{text-align:left}
details.more#optimize-panel{margin:-4px 0 14px}
.opt .note{margin:0}
.optrow select,.optrow input{font:inherit;font-size:13px;padding:var(--pad-sel);border:var(--line-w) solid var(--line-c);border-radius:var(--r-ctl);background:var(--surface);color:var(--ink)}
.optrow input{width:6em}
select option{background:var(--surface);color:var(--ink)}
.err{color:var(--fail);font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere}
.sub3{font-size:13px;margin:14px 0 6px}
.state{font-size:12px;padding:1px 8px;border-radius:999px;background:var(--chip);color:var(--ink2)}
.state.done,.state.applied{color:var(--pass)}
.state.failed,.state.interrupted{color:var(--fail)}
.state.running{color:var(--mark-ink)}
#job table{margin:10px 0}
.fm{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 14px;font-size:12.5px;background:var(--page);border:var(--line-w) solid var(--line-c);border-radius:8px;padding:10px 12px;margin:0 0 16px}
.fm dt{color:var(--muted)}
.fm dd{margin:0}
.kpis.strip{border:var(--line-w) solid var(--line-c);border-radius:var(--r-card)}
.card.spenders{border-radius:var(--r-card)}
.cause{font-size:13px}
.cause b{font-weight:600}
.tdot{stroke-width:1.5}
.privacy{border:var(--line-w) solid var(--line-c);border-radius:var(--r-box);padding:8px 12px;margin:0 0 12px;font-size:13px;color:var(--ink2);background:var(--surface)}
.privacy b{color:var(--mark-ink);text-transform:uppercase;font-size:11px;margin-right:6px;margin:0}
.filters select,.libtools select,#bench-form select,.optrow select,.optrow input,#reg-form input,#mcp-form select{font-family:var(--num-font);font-size:var(--ctl-size);font-weight:400}
.filters a,.fresh,.kpi .dl .trend,.state,.st .pill,.badge,a.sk .meta,.libview .ste-n,.runline b,.range-dates,.cause,.vs .trend,.tag,.movers td:not(:first-child):not(.tagc),.movers th{font-family:var(--num-font)}
table.mcp td:is(:nth-child(2),:nth-child(3),:nth-child(8)),table.bres td:last-child,table.bres td:first-child{font-family:var(--sans)}
table.mcp td.st{font-family:var(--num-font)}
.latest>.note:first-child{font-family:var(--num-font);font-weight:var(--lab-w);font-size:var(--lab-size);text-transform:var(--lab-case);letter-spacing:var(--lab-track)}
.latest>.note:first-child time{font-weight:400}
.fl span,.ctl-l{font-family:var(--num-font);font-weight:var(--lab-w);font-size:var(--lab-size);text-transform:var(--lab-case);letter-spacing:var(--lab-track);color:var(--lab-c)}
.movers th{font-size:var(--lab-size);text-transform:var(--lab-case);letter-spacing:var(--lab-track);color:var(--lab-c)}
.spark polyline,.tline{stroke:var(--trace-c)}
.tdot{fill:var(--trace-c);stroke:var(--dot-edge)}
"""
