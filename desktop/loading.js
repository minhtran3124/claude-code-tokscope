// The page the window shows before the dashboard answers: an ink gauge whose needle sweeps, a card with the offset block
// of the dashboard's hero, and a shimmering line of text. Colours are the dashboard's --page, --ink, --mark and --agent
// (light and dark). No script: the page is a data: URL, and its text is escaped here.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };

function statusPage(dark, message, spin = true) {
  const c = dark
    ? { page: "#1d1a15", surface: "#27231c", ink: "#f2efe7", muted: "#b0a796", mark: "#76a0e2", agent: "#f4b829", shadow: "#0c0b09" }
    : { page: "#f2efe7", surface: "#fbf9f4", ink: "#231e16", muted: "#665e51", mark: "#76a0e2", agent: "#f4b829", shadow: "#231e16" };
  const text = String(message).replace(/[&<>"]/g, (ch) => ESC[ch]);
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tokscope</title><style>
:root{--page:${c.page};--surface:${c.surface};--ink:${c.ink};--muted:${c.muted};--mark:${c.mark};--agent:${c.agent};--shadow:${c.shadow}}
html,body{height:100%;margin:0;background:var(--page);color:var(--ink);font:15px/1.4 system-ui,"Segoe UI",sans-serif}
body{display:flex;align-items:center;justify-content:center;padding:24px;box-sizing:border-box}
.card{position:relative;display:flex;flex-direction:column;align-items:center;gap:18px;min-width:240px;padding:34px 40px 28px;
  background:var(--surface);border:2.5px solid var(--ink);border-radius:14px;box-shadow:10px 12px 0 var(--shadow);
  animation:rise .6s cubic-bezier(.16,1,.3,1) both}
.gauge{width:96px;height:96px}
.gauge .arc{fill:none;stroke:var(--ink);stroke-width:3.6;stroke-linecap:round}
.gauge .needle{transform-origin:16px 24px;animation:sweep 1.8s cubic-bezier(.45,0,.55,1) infinite alternate}
.gauge .needle path{stroke:var(--mark);stroke-width:3.6;stroke-linecap:round;fill:none}
.gauge .hub{fill:var(--ink)}
.bars{display:flex;gap:6px}
.bars i{display:block;width:6px;height:18px;border-radius:3px;background:var(--mark);transform-origin:50% 100%;animation:bar 1.1s ease-in-out infinite}
.bars i:nth-child(2){background:var(--agent);animation-delay:.15s}
.bars i:nth-child(3){animation-delay:.3s}
.bars i:nth-child(4){background:var(--agent);animation-delay:.45s}
.bars i:nth-child(5){animation-delay:.6s}
.msg{font-weight:600;letter-spacing:.01em;background:linear-gradient(90deg,var(--ink) 35%,var(--mark) 50%,var(--ink) 65%) 0 0/250% 100%;
  -webkit-background-clip:text;background-clip:text;color:transparent;animation:shimmer 2.4s linear infinite}
.note{font:12px ui-monospace,"SFMono-Regular",Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
  opacity:0;animation:fade .6s ease 6s forwards}
.card.plain .gauge,.card.plain .bars,.card.plain .note{display:none}
.card.plain .msg{animation:none;background:none;-webkit-text-fill-color:var(--ink);color:var(--ink)}
.card.plain{animation:none}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes sweep{from{transform:rotate(-42deg)}to{transform:rotate(42deg)}}
@keyframes bar{0%,100%{transform:scaleY(.35)}50%{transform:scaleY(1)}}
@keyframes shimmer{from{background-position:100% 0}to{background-position:-100% 0}}
@keyframes fade{to{opacity:1}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important}.note{opacity:1}
  .msg{background:none;-webkit-text-fill-color:var(--ink);color:var(--ink)}}
</style></head><body>
<div class="card${spin ? "" : " plain"}" role="status" aria-live="polite">
  ${spin ? `<svg class="gauge" viewBox="0 0 32 32" aria-hidden="true">
    <path class="arc" d="M5.5 24a10.5 10.5 0 0 1 17.9-7.4"/><path class="arc" d="M23.4 16.6a10.5 10.5 0 0 1 3.1 7.4"/>
    <g class="needle"><path d="M16 24l4.4-6.4"/></g><circle class="hub" cx="16" cy="24" r="3"/></svg>
  <div class="bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>` : ""}
  <div class="msg">${text}</div>
  ${spin ? `<div class="note">The first start reads your transcripts and can take a while</div>` : ""}
</div></body></html>`;
  return "data:text/html;charset=utf-8," + encodeURIComponent(html);
}

module.exports = { statusPage };
