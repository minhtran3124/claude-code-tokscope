"""The Ink skin's stylesheet, shared by the report and the dashboard (the layout sheet is web/theme/layout.py)."""

from ..theme import fonts


CSS = """
:root{--page:#f2efe7;--surface:#fbf9f4;--ink:#231e16;--ink2:#4a4337;--muted:#665e51;--grid:#ddd6c8;--edge:#bfb6a6;--mark:#76a0e2;--agent:#f4b829;--mark-ink:#2f5aa8;--agent-ink:#8a5a00;
--tint:#e4ebf7;--track:#ebe6db;--c1:var(--mark);--c2:var(--agent);--c3:#d9708c;--c4:#4a4337;--c5:#8a8172;--c0:#bdb4a4;--chip:#ebe6db;--hl:#fbe6a6;--pass:#1a6934;--fail:#a33a23;
--line-w:1px;--shadow:#41538f;--sans:SANS;--mono:MONO;--ease:cubic-bezier(0.22,1,0.36,1);--ease-expo:cubic-bezier(0.16,1,0.3,1);interpolate-size:allow-keywords;color-scheme:light;--line-c:var(--edge);--focus-c:var(--ink);--row-c:var(--grid);--in-bg:var(--surface);--r-card:10px;--r-tile:8px;--r-box:8px;--r-ctl:8px;--r-btn:8px;--r-bar:4px;--bar-h:10px;--key-s:12px;--pad-sel:6px 12px;--pad-in:6px 14px;--pad-chip:5px 12px;--pad-btn:5px 12px;--num-font:var(--mono);--lab-case:uppercase;--lab-track:.08em;--lab-size:11px;--lab-w:600;--lab-c:var(--muted);--cell-size:13px;--btn-w:500;--ctl-size:12px;--seg-ring:inset 0 0 0 1px var(--ink);--trace-c:var(--mark-ink);--dot-edge:var(--ink)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){DARK}}
:root[data-theme=dark]{DARK}
.privacy b{letter-spacing:.04em}
.hero{border:var(--line-w) solid var(--ink);margin:12px 10px 28px 0;background:var(--surface);box-shadow:10px 12px 0 var(--shadow)}
.hero .big em{color:var(--mark-ink)}
svg rect.m{stroke:var(--ink);stroke-width:1}
.tools input[type=search]:focus,.tools select:focus{outline:2px solid var(--ink);outline-offset:2px}
.srow{transition:background var(--t-state) var(--ease)}
.srow:hover{background:color-mix(in oklch,var(--mark) 4%,var(--surface))}
.srow.picked{outline:2px solid var(--ink);outline-offset:2px}
.brand{color:var(--ink)}
.totop{border:var(--line-w) solid var(--line-c);color:var(--ink)}
.totop.show:hover{background:var(--ink);color:var(--page)}
.pickbar{border:var(--line-w) solid var(--ink)}
.primary{font-weight:600;font-size:13px;border:var(--line-w) solid var(--ink);background:var(--ink);color:var(--page);transition:background var(--t-fast) var(--ease),color var(--t-fast) var(--ease),opacity var(--t-fast) var(--ease)}
.primary:hover:not(:disabled){background:var(--surface);color:var(--ink)}
.srow.child::before{border-left:var(--line-w) solid var(--grid);border-bottom:var(--line-w) solid var(--grid)}
.runs{border:var(--line-w) solid var(--line-c)}
.btn{display:inline-block;line-height:1.45;color:var(--ink);border:var(--line-w) solid var(--line-c);background:var(--surface);transition:background var(--t-fast) var(--ease),color var(--t-fast) var(--ease)}
.btn:hover{background:var(--ink);color:var(--page)}
.btn:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
#progress{background:var(--mark)}
.side-foot{flex-wrap:wrap}
.chip{background:var(--surface);transition:color var(--t-fast) var(--ease),background var(--t-fast) var(--ease)}
.chip:hover,.chip.on,.chip[aria-pressed=true]{background:var(--ink);color:var(--page)}
svg .ma{stroke:var(--agent-ink)}
.key i.ln{background:var(--agent-ink);box-shadow:none}
.legend .key i.was{background:var(--surface);border-radius:50%}
.viz .dot{stroke:var(--ink);stroke-width:1.5px}
.viz .dot.was{fill:var(--surface)}
.viz g.seg path,.viz g.seg rect:not(.hit){stroke:var(--ink);stroke-width:1}
#compare th,.md th{font:500 12px/1.45 var(--sans);text-transform:none;letter-spacing:0;color:var(--ink2)}
.primary{font-size:12px;font-weight:500}
#session-list .shead,#session-list .dayhd{font:11px var(--mono);letter-spacing:.08em;text-transform:uppercase}
#session-list .srow.picked{outline:2px solid var(--ink);outline-offset:-2px}
#sessions .pickbar{background:var(--ink);color:var(--page);border-radius:999px;padding:8px 10px 8px 20px;font:12px var(--mono)}
#sessions .pickbar .btn{background:transparent;color:var(--page);border-color:var(--page)}
#sessions .pickbar .btn:hover{background:var(--page);color:var(--ink)}
#sessions .pickbar .primary{background:var(--page);color:var(--ink);border-color:var(--page)}
#sessions .pickbar .primary:hover:not(:disabled){background:transparent;color:var(--page)}
#sessions .pickbar :focus-visible{outline-color:var(--page)}
/* end sessions look */
.tools select,.tools input[type=search]{font-size:12px;font-weight:400}
.fm dt{font-size:11px}
th .usd{font-family:var(--mono);text-transform:none;letter-spacing:0}
.kpi>span:first-child,.today-nums span,.ck,.ids dt,.fm dt,th,.latest>.note:first-child,.fl span,.ctl-l{font-variant-numeric:normal;line-height:1.45}
""".replace("SANS", fonts.SANS).replace("MONO", fonts.MONO).replace("DARK", "--page:#171613;--surface:#221f1a;--ink:#f2efe7;--ink2:#d6cfc2;--muted:#b0a796;--grid:#383329;--edge:#4a4437;--mark:#76a0e2;--agent:#f4b829;--mark-ink:#8fb3ec;--agent-ink:#f4b829;--tint:#25304a;--track:#2b2822;--chip:#2b2822;--hl:#5a4500;--pass:#93d3b0;--fail:#f08a70;--c3:#c4607d;--c4:#d6cfc2;--c5:#8f8676;--c0:#5e5649;--line-w:1px;--shadow:#41538f;color-scheme:dark")

# the page script in parts: every page takes JS_CORE; the report takes them all, a dashboard page only its own
