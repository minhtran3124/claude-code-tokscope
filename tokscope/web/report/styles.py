"""The look: the colour, font and shape tokens plus a short block of look rules, shared by the report and the dashboard
(the layout sheet is web/theme/layout.py)."""

from ..theme import fonts


CSS = """
:root{--page:#F5F5FA;--surface:#FFFFFF;--ink:#1B1B2F;--ink2:#3D3D55;--muted:#66667F;--grid:#E2E2EE;--edge:#D2D2E2;--mark:#4B4FD8;--agent:#1E9C86;--mark-ink:#4B4FD8;--agent-ink:#17695A;--tint:#E9E9FC;--track:#EEEEF6;--c1:var(--mark);--c2:var(--agent);--c3:#C9479B;--c4:#D9702A;--c5:#7A7A92;--c0:#D2D2E2;--chip:#EEEEF6;--hl:#FBEFD5;--pass:#1C7C54;--fail:#B8344A;--accent-ink:#FFFFFF;--on-bg:#E9E9FC;--on-fg:var(--mark-ink);--on-line:#C9CAF5;--bar:#1B1B2F;--bar-ink:#E8E8F5;--avg:#845411;--warn:#9A6212;--line-w:1px;--shadow:rgba(27,27,47,.14);--sans:SANS;--mono:MONO;--ease:cubic-bezier(0.22,1,0.36,1);--ease-expo:cubic-bezier(0.16,1,0.3,1);interpolate-size:allow-keywords;color-scheme:light;--line-c:var(--grid);--focus-c:var(--mark);--row-c:var(--grid);--in-bg:var(--surface);--r-card:12px;--r-tile:12px;--r-box:8px;--r-ctl:8px;--r-btn:8px;--r-bar:99px;--bar-h:10px;--key-s:10px;--pad-sel:6px 12px;--pad-in:6px 12px;--pad-chip:5px 12px;--pad-btn:5px 12px;--num-font:var(--sans);--lab-case:uppercase;--lab-track:.06em;--lab-size:11px;--lab-w:600;--lab-c:var(--muted);--cell-size:14px;--btn-w:600;--ctl-size:13px;--seg-ring:inset 0 0 0 1px var(--on-line);--trace-c:var(--mark-ink);--dot-edge:var(--surface)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){DARK}}
:root[data-theme=dark]{DARK}
body{font-variant-numeric:tabular-nums}
h1,h2,h3{letter-spacing:-.01em}
.privacy b{letter-spacing:.04em}
.hero{border:var(--line-w) solid var(--line-c);margin:12px 0 28px;background:var(--surface)}
.hero .big em{color:var(--mark-ink)}
.tools input[type=search]:focus,.tools select:focus{border-color:var(--mark);outline:2px solid var(--on-bg)}
.srow{transition:background var(--t-state) var(--ease)}
.srow:hover{background:var(--track)}
.srow.picked{background:var(--on-bg)}
.brand{color:var(--ink)}
.totop{border:var(--line-w) solid var(--line-c);color:var(--ink)}
.totop.show:hover{background:var(--on-bg);color:var(--on-fg)}
.pickbar{border:0}
.primary{font-weight:600;font-size:13px;border:var(--line-w) solid var(--mark);background:var(--mark);color:var(--accent-ink);transition:filter var(--t-fast) var(--ease),opacity var(--t-fast) var(--ease)}
.primary:hover:not(:disabled){filter:brightness(1.08)}
.srow.child::before{border-left:var(--line-w) solid var(--grid);border-bottom:var(--line-w) solid var(--grid)}
.runs{border:var(--line-w) solid var(--line-c)}
.btn{display:inline-block;line-height:1.45;color:var(--ink);border:var(--line-w) solid var(--line-c);background:var(--surface);transition:background var(--t-fast) var(--ease),border-color var(--t-fast) var(--ease)}
.btn:hover{background:var(--on-bg);border-color:var(--on-line)}
.btn:focus-visible{outline:2px solid var(--focus-c);outline-offset:2px}
#progress{background:var(--mark)}
.side-foot{flex-wrap:wrap}
.chip{background:var(--surface);transition:color var(--t-fast) var(--ease),background var(--t-fast) var(--ease)}
.chip:hover,.chip.on,.chip[aria-pressed=true]{background:var(--on-bg);color:var(--on-fg);border-color:var(--on-line)}
svg .ma{stroke:var(--avg)}
.key i.ln{background:var(--avg);box-shadow:none}
.legend .key i.was{background:var(--surface);border-radius:50%}
.viz .dot{stroke:var(--surface);stroke-width:1.5px}
.viz .dot.was{fill:var(--surface);stroke:var(--mark)}
#compare th,.md th{font:600 12px/1.45 var(--sans);text-transform:none;letter-spacing:0;color:var(--ink2)}
#session-list .shead,#session-list .dayhd{font:600 11px var(--sans);letter-spacing:.06em;text-transform:uppercase}
#session-list .srow.picked{outline:0}
#sessions .pickbar{background:var(--bar);color:var(--bar-ink);border-radius:12px;padding:8px 8px 8px 16px;font:13px var(--sans);box-shadow:0 8px 30px var(--shadow)}
#sessions .pickbar .btn{background:transparent;color:var(--bar-ink);border-color:transparent}
#sessions .pickbar .btn:hover{background:rgba(255,255,255,.14)}
#sessions .pickbar :focus-visible{outline-color:var(--bar-ink)}
/* end sessions look */
.tools select,.tools input[type=search]{font-size:13px;font-weight:400}
.fm dt{font-size:11px}
th .usd{text-transform:none;letter-spacing:0}
code,pre,kbd,.mono,.sid,code.ver{font-family:var(--mono)}
.kpi>span:first-child,.today-nums span,.ck,.ids dt,.fm dt,th,.latest>.note:first-child,.fl span,.ctl-l{line-height:1.45}
""".replace("SANS", fonts.SANS).replace("MONO", fonts.MONO).replace("DARK", "--page:#12121C;--surface:#1B1B29;--ink:#E9E9F6;--ink2:#C9C9DE;--muted:#9A9AB5;--grid:#2D2D42;--edge:#3A3A55;--mark:#8B8EF5;--agent:#4CC9AE;--mark-ink:#8B8EF5;--agent-ink:#8ADBC8;--tint:#25264A;--track:#262638;--chip:#2B2B3E;--hl:#3A2D12;--pass:#5DD3A0;--fail:#F08196;--c3:#D56CB4;--c4:#E8935A;--c5:#9A9AB5;--c0:#3A3A55;--accent-ink:#12122A;--on-bg:#25264A;--on-line:#3C3E7A;--bar:#0A0A12;--bar-ink:#C9C9E0;--avg:#F0C47A;--warn:#E8B45C;--shadow:rgba(0,0,0,.5);color-scheme:dark")

# the page script in parts: every page takes JS_CORE; the report takes them all, a dashboard page only its own
