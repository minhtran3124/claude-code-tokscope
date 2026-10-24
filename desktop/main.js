// A window around `tokscope serve`: start the server on a free port, show it, stop it on quit.
const { app, BrowserWindow, nativeTheme, shell } = require("electron");
const { spawn } = require("child_process");
const net = require("net");
const http = require("http");
const path = require("path");

// a clone keeps bin/ and tokscope/ next to desktop/; the .deb puts them in resources/
const ROOT = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
let server = null;
let win = null;

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

// the first start may ingest a large ~/.claude/projects before the socket opens, so allow a minute
function waitFor(url, tries = 600) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      const again = () => (n <= 0 ? reject(new Error("the tokscope server did not start")) : setTimeout(() => attempt(n - 1), 100));
      const req = http.get(new URL("api/version", url), (res) => { res.resume(); if (res.statusCode === 200) resolve(); else again(); });  // not the Overview: it can take over 2 s
      req.setTimeout(2000, () => req.destroy());
      req.on("error", again);
    };
    attempt(tries);
  });
}

// The background service (install.sh) keeps `tokscope serve` on this port. Same number as in install.sh.
const SERVICE_PORT = 8770;

// true when url answers like a tokscope dashboard (a different program on the port must not be shown). It asks
// /api/version, which answers at once; the Overview can take longer than the timeout on a large database.
function isTokscope(url) {
  return new Promise((resolve) => {
    const req = http.get(new URL("api/version", url), (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => { if (body.length < 65536) body += c; });
      res.on("end", () => {
        try { const j = JSON.parse(body); resolve(res.statusCode === 200 && !!j && typeof j === "object" && "stamp" in j && "live" in j); } catch (e) { resolve(false); }
      });
    });
    req.setTimeout(2000, () => req.destroy());
    req.on("error", () => resolve(false));
  });
}

async function start() {
  createWindow();  // at once, with a loading page: the server and the first page can take seconds
  const serviceUrl = `http://127.0.0.1:${SERVICE_PORT}/`;
  if (await isTokscope(serviceUrl)) return showDashboard(serviceUrl);  // the service is up: just show it
  const port = await freePort();
  // The server runs under a small sh that stops it when this process is gone, however it went (a quit, a signal,
  // SIGKILL, a crash). Killing the sh runs its trap, which stops the server.
  const guard = 'trap \'kill "$S" 2>/dev/null\' EXIT TERM INT HUP; "$@" & S=$!; while kill -0 "$PPID" 2>/dev/null && kill -0 "$S" 2>/dev/null; do sleep 1; done; kill "$S" 2>/dev/null; wait "$S"';
  server = spawn("sh", ["-c", guard, "sh", path.join(ROOT, "bin", "tokscope"), "serve", "--no-open", "--port", String(port)], { stdio: "inherit" });
  // the server is gone (it failed to bind, crashed or was killed): leave rather than show a dead page
  server.once("exit", (code) => { server = null; app.exit(code || 1); });
  const url = `http://127.0.0.1:${port}/`;
  await waitFor(url);
  showDashboard(url);
}

// Only web links leave the window, and only to the browser. Whatever answers on the port could ask for a file:, smb: or
// app-scheme URL, so nothing else is passed to the desktop.
function openExternal(u) {
  try {
    if (["http:", "https:"].includes(new URL(u).protocol)) shell.openExternal(u);
  } catch (e) { /* not a URL: ignore */ }
}

// page and ink colours of the dashboard (--page and --ink in the light and dark themes)
function loadingPage(dark) {
  const bg = dark ? "#1d1a15" : "#f2efe7", fg = dark ? "#f2efe7" : "#231e16", mark = dark ? "#76a0e2" : "#2f5aa8";
  const html = `<!doctype html><meta charset="utf-8"><title>tokscope</title><style>
html,body{height:100%;margin:0;background:${bg};color:${fg};font:15px system-ui,sans-serif}
body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
i{width:26px;height:26px;border:3px solid ${mark};border-right-color:transparent;border-radius:50%;animation:s .8s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}@media (prefers-reduced-motion:reduce){i{animation:none}}</style>
<i></i><div>Starting tokscope…</div>`;
  return "data:text/html;charset=utf-8," + encodeURIComponent(html);
}

let base = null;  // the dashboard's address once it answers; nothing else may be shown in the window

function createWindow() {
  const dark = nativeTheme.shouldUseDarkColors;
  // backgroundColor is what shows before anything is painted, so the window never flashes white
  win = new BrowserWindow({ width: 1440, height: 900, title: "tokscope", autoHideMenuBar: true, backgroundColor: dark ? "#1d1a15" : "#f2efe7" });
  // anything that is not the local dashboard opens in the real browser
  win.webContents.setWindowOpenHandler(({ url: u }) => { openExternal(u); return { action: "deny" }; });
  // a server redirect must not move the window off the dashboard either
  for (const ev of ["will-navigate", "will-redirect"]) {
    win.webContents.on(ev, (e, u) => { if (!base || !u.startsWith(base)) { e.preventDefault(); openExternal(u); } });
  }
  win.on("closed", () => { win = null; });
  win.loadURL(loadingPage(dark));
}

function showDashboard(url) {
  if (!win) return;  // the window was closed while the server started
  base = url;
  win.loadURL(url);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(start).catch((e) => { console.error(`tokscope: ${e.message}`); app.exit(1); });
  app.on("window-all-closed", () => app.quit());
  // every way out stops the server: a normal quit, app.exit() on a failed start, and a signal (not SIGKILL)
  process.on("exit", () => { if (server) server.kill(); });
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) process.on(sig, () => app.quit());
}
