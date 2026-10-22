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
#session-list{--scols:24px 100px minmax(0,1fr) 120px 60px 68px 70px 140px 14px;overflow:clip}
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
.spenders .cols3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:0}
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
#session-list :is(.n,.sid8,.from){display:none}
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
/* end phone */
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
