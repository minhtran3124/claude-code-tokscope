"""The Classic design (the look before the ink redesign), kept as a second skin next to Ink.

Pages carry both skin stylesheets: <style id="skin-ink"> and <style id="skin-classic" media="not all">. The Classic/Ink button
(key `s`) flips their media attributes; SKIN_APPLY restores the saved choice (localStorage `tokscope-skin`) before paint.
The code of the switch is named "skin" (`grep -rn -i skin tokscope tests`); the `s` rows of both shortcut dialogs say
"Classic or Ink design" instead. The skin block in report.py's JS_CORE reads #skin-ink and #skin-classic
unguarded: a page without them stops the page script. #skin (the report's button) and the dashboard's [data-set-skin]
segments are both optional.

Pages also carry <style id="layout"> (layout.py): the grid, sizes and every rule that differs from Ink only in value. A skin is
its tokens plus a short look block. This sheet holds the Classic tokens (the :root rules, listed in layout.py) and the look
block: the hero aurora and gradient text, the tinted answer card with no shadow, the tinted delta chip, hover lifts and
glows, the selected-nav and pressed-segment colours. New markup gets its rules in layout.py and reads tokens, so Classic
shows it without a copy."""
from . import fonts

CLASSIC_CSS = """
:root{--page:#f6f6f3;--surface:#ffffff;--ink:#1d1d1b;--ink2:#3e3e3a;--muted:#62625c;--grid:#e3e3dc;--edge:#c6c6bc;--mark:#0086b9;--agent:#e49921;--mark-ink:#00749f;--agent-ink:#9a5f00;
--tint:#e2f5ff;--track:#ecece6;--c1:var(--mark);--c2:var(--agent);--c3:#1baf7a;--c4:#6250d6;--c5:#e87ba4;--c0:#c4c4bc;--chip:#efefea;--hl:#ffe9a8;--pass:#1f7a3d;--fail:#b3261e;
--sans:SANS;--mono:MONO;--ease:cubic-bezier(0.22,1,0.36,1);--ease-expo:cubic-bezier(0.16,1,0.3,1);interpolate-size:allow-keywords;color-scheme:light;--line-w:1px;--line-c:var(--edge);--focus-c:var(--mark);--row-c:var(--edge);--in-bg:var(--page);--r-card:12px;--r-tile:10px;--r-box:8px;--r-ctl:8px;--r-btn:6px;--r-bar:4px;--bar-h:8px;--key-s:10px;--pad-sel:5px 8px;--pad-in:6px 10px;--pad-chip:5px 10px;--pad-btn:2px 6px;--num-font:var(--sans);--lab-case:none;--lab-track:normal;--lab-size:12px;--lab-w:400;--lab-c:var(--ink2);--cell-size:1em;--btn-w:400;--ctl-size:13px;--seg-ring:none;--trace-c:var(--mark);--dot-edge:var(--surface)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){DARK}}
:root[data-theme=dark]{DARK}
.privacy{border-left:3px solid var(--mark)}
.privacy b{letter-spacing:.04em}
:where(:focus-visible){border-radius:4px}
.hero{border:1px solid color-mix(in oklch,var(--mark) 30%,var(--edge));margin:12px 0 16px;background:radial-gradient(120% 160% at 0% 0%,color-mix(in oklch,var(--mark) 16%,transparent),transparent 55%),
radial-gradient(70% 140% at 100% 100%,color-mix(in oklch,var(--agent) 12%,transparent),transparent 60%),var(--surface)}
.hero .big em{color:var(--mark-ink)}
.kpi{transition:border-color var(--t-state) var(--ease),transform var(--t-state) var(--ease)}
.kpi:hover{border-color:color-mix(in oklch,var(--mark) 45%,var(--edge));transform:translateY(-1px)}
details.more{transition:border-color var(--t-state) var(--ease)}
details.more:hover,details.more[open]{border-color:color-mix(in oklch,var(--mark) 35%,var(--edge))}
#tip{box-shadow:0 6px 20px #0003}
.tools input[type=search],.tools select{transition:border-color var(--t-fast) var(--ease),box-shadow var(--t-fast) var(--ease)}
.tools input[type=search]:focus,.tools select:focus{outline:none;border-color:var(--mark);box-shadow:0 0 0 3px color-mix(in oklch,var(--mark) 22%,transparent)}
.srow{transition:border-color var(--t-state) var(--ease),background var(--t-state) var(--ease)}
.srow:hover{border-color:color-mix(in oklch,var(--mark) 40%,var(--edge))}
.srow[open]{border-color:color-mix(in oklch,var(--mark) 55%,var(--edge));box-shadow:0 8px 26px -14px color-mix(in oklch,var(--mark) 60%,transparent)}
.srow.picked{border-color:var(--mark);box-shadow:0 0 0 2px color-mix(in oklch,var(--mark) 22%,transparent)}
.brand{color:var(--mark-ink);--tok-accent:var(--agent)}
.totop{border:1px solid color-mix(in oklch,var(--mark) 40%,var(--edge));color:var(--mark-ink);box-shadow:0 8px 22px -10px #0006}
.totop.show:hover{background:var(--mark);color:#fff}
.pickbar{border:1px solid color-mix(in oklch,var(--mark) 45%,var(--edge));box-shadow:0 10px 30px -12px #0005}
.primary{font-weight:600;font-size:13px;background:var(--mark);color:#fff;transition:transform var(--t-fast) var(--ease),box-shadow var(--t-fast) var(--ease),opacity var(--t-fast) var(--ease)}
.primary:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 6px 16px -6px var(--mark)}
.primary:active:not(:disabled){transform:none}
.srow.child::before{border-left:1px solid var(--grid);border-bottom:1px solid var(--grid)}
.runs{border:1px solid color-mix(in oklch,var(--agent) 30%,var(--edge))}
#compare{border:1px solid color-mix(in oklch,var(--mark) 45%,var(--edge));background:linear-gradient(var(--tint),transparent 120px),var(--surface)}
.btn{color:var(--mark-ink);transition:background var(--t-fast) var(--ease)}
.btn:hover{background:color-mix(in oklch,var(--mark) 14%,transparent)}
#progress{background:linear-gradient(90deg,var(--mark),var(--agent));box-shadow:0 0 12px color-mix(in oklch,var(--mark) 60%,transparent)}
.hero::before{content:"";position:absolute;inset:-40%;pointer-events:none;opacity:.55;background:radial-gradient(30% 40% at 30% 40%,color-mix(in oklch,var(--mark) 22%,transparent),transparent 70%),
radial-gradient(25% 35% at 70% 60%,color-mix(in oklch,var(--agent) 20%,transparent),transparent 70%);animation:drift 18s ease-in-out infinite alternate}
@keyframes drift{to{transform:translate(6%,-4%) rotate(8deg) scale(1.08)}}
@media (prefers-reduced-motion:reduce){
.hero::before{animation:none}  /* the glow travels, rotates and scales: still under reduced motion */
}
.hero>*{position:relative}
.hero .big em{background:linear-gradient(90deg,var(--mark),color-mix(in oklch,var(--mark) 45%,var(--agent)));-webkit-background-clip:text;background-clip:text;color:transparent}
.kpi::after,.hero::after,.changes .card::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:opacity var(--t-layout) var(--ease);background:radial-gradient(220px circle at var(--mx,50%) var(--my,50%),color-mix(in oklch,var(--mark) 16%,transparent),transparent 70%)}
.kpi:hover::after,.hero:hover::after,.changes .card:hover::after{opacity:1}
.changes .card{position:relative}
.kpi:hover{box-shadow:0 10px 24px -16px color-mix(in oklch,var(--mark) 70%,transparent)}
.chip{transition:border-color var(--t-fast) var(--ease),color var(--t-fast) var(--ease),background var(--t-fast) var(--ease)}
.chip:hover{border-color:var(--mark);color:var(--mark-ink)}
/* chart: 7-day average draws itself in; a guide follows the pointer */
svg .ma{stroke:var(--agent)}
.key i.ln{background:var(--agent)}
#toast{box-shadow:0 12px 30px -12px #0008}
#s-more{border:1px solid var(--edge);border-radius:8px}
dialog.keys{box-shadow:0 30px 60px -20px #0009}
dialog.keys::backdrop{backdrop-filter:blur(3px)}
.legend .key i.was,.viz .dot.was{background:color-mix(in oklch,var(--c1) 40%,var(--muted))}
.viz .dot{stroke:var(--surface);stroke-width:2px}
#session-list .shead,#session-list .dayhd{font-size:12px}
#session-list .srow:hover{background:color-mix(in oklch,var(--mark) 5%,var(--surface))}
#session-list .srow[open]{box-shadow:none;background:color-mix(in oklch,var(--mark) 5%,var(--surface))}
#session-list .srow.picked{background:color-mix(in oklch,var(--mark) 10%,var(--surface));box-shadow:inset 3px 0 0 var(--mark)}
#sessions .seg .chip{border-radius:8px}
#sessions .pickbar{background:color-mix(in oklch,var(--mark) 10%,var(--surface));border:1px solid color-mix(in oklch,var(--mark) 45%,var(--edge));border-radius:12px;box-shadow:0 10px 30px -12px #0006;padding:10px 14px}
/* end sessions look */
.legend .key i.was,.viz .dot.was.hi{fill:color-mix(in oklch,var(--c1) 40%,var(--muted))}
""".replace("SANS", fonts.SANS).replace("MONO", fonts.MONO).replace("DARK", "--page:#151514;--surface:#1f1f1d;--ink:#ecece8;--ink2:#c9c9c3;--muted:#a5a59e;--grid:#34342f;--edge:#34342f;--mark:#0398cd;--agent:#c68206;--mark-ink:#0398cd;--agent-ink:#e0a030;--tint:#102635;--track:#2b2b28;--chip:#2b2b28;--hl:#5a4b00;--pass:#5cc183;--fail:#f08a80;--c3:#199e70;--c4:#9085e9;--c5:#d55181;--c0:#55554f;color-scheme:dark")

CLASSIC_DASH_CSS = """
.cols2{gap:14px}
a.sk{transition:border-color var(--t-fast) var(--ease),transform var(--t-fast) var(--ease)}
a.sk:hover{border-color:var(--mark);transform:translateY(-1px)}
.seg .chip.on{border-color:var(--mark);color:var(--mark-ink)}
.ask{border:1px solid var(--mark)}
.runbar{height:4px;border-radius:2px}
.runbar i{border-radius:2px}
.outcome.ok{border-color:color-mix(in oklch,var(--pass) 45%,transparent)}
.outcome.bad{border-color:color-mix(in oklch,var(--fail) 45%,transparent)}
a.outcome.run{border-color:var(--mark)}
table.sbs th{font:600 12px var(--sans)}
table.sbs td.gap{background:repeating-linear-gradient(135deg,transparent 0 6px,var(--chip) 6px 8px)}
/* the decision stays in sight while you read the comparison */
.decide{border:1px solid var(--mark);box-shadow:0 10px 30px -12px color-mix(in oklch,var(--ink) 45%,transparent)}
.btn.danger:hover{background:color-mix(in oklch,var(--fail) 14%,transparent)}
/* overview: look only (the layout is in layout.py, between "overview" and "end overview") */
.answer{border-color:color-mix(in oklch,var(--mark) 55%,var(--edge));background:linear-gradient(var(--tint),transparent 110px),var(--surface)}
.tband{fill:var(--tint)}
.tk.now{background:var(--mark)}
.movers th{font-weight:600}
.tag{background:var(--tint);color:var(--mark-ink)}
.vs .trend.up,.vs .trend.down,.vs .trend.flat{padding:1px 8px}
.privacy b{letter-spacing:.04em}
.segctl .chip[aria-pressed=true]{background:var(--tint);border-color:var(--mark);color:var(--mark-ink)}
.segctl .chip:first-child{border-radius:8px 0 0 8px}
.segctl .chip:last-child{border-radius:0 8px 8px 0}
#trend svg rect.m{stroke:var(--surface);stroke-width:1}
.key i.dash{border-top-color:var(--agent-ink)}
/* end overview */
/* phone: the current page in the menu sheet is ink on the tint (the blue is 4.69:1 on it, ink reads clearer) */
@media (max-width:639px){
.sheet .toc a.on{color:var(--ink)}
/* phone: the new controls have no other cue than their outline, so it reads 3:1 (--edge is 1.5:1 and stays for cards and rows) */
body .menu-btn,body .pill-btn,.sheet-filters select,.sheet-filters .chip,.sheet .segctl .chip{border-color:var(--muted)}
}
.movers th{font-weight:600}
"""

SKIN_APPLY = ("<script>try{if(localStorage.getItem('tokscope-skin')==='classic'){"
              "document.getElementById('skin-ink').media='not all';document.getElementById('skin-classic').media='all';"
              "document.documentElement.dataset.skin='classic'}}catch(_){}</script>")
SKIN_BUTTON = ('<button type="button" class="chip" id="skin" aria-pressed="false" '
               'title="Switch between the Classic and Ink designs">Classic</button>')
