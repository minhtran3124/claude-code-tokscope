// A window around `tokscope serve`: start the server on a free port, show it, stop it on quit.
const { app, BrowserWindow, shell } = require("electron");
const { spawn } = require("child_process");
const net = require("net");
const http = require("http");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
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

function waitFor(url, tries = 100) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      const req = http.get(url, (res) => { res.resume(); resolve(); });
      req.on("error", () => (n <= 0 ? reject(new Error("the tokscope server did not start")) : setTimeout(() => attempt(n - 1), 100)));
    };
    attempt(tries);
  });
}

async function start() {
  const port = await freePort();
  // The server runs under a small sh that stops it when this process is gone, however it went (a quit, a signal,
  // SIGKILL, a crash). Killing the sh runs its trap, which stops the server.
  const guard = 'trap \'kill "$S" 2>/dev/null\' EXIT TERM INT HUP; "$@" & S=$!; while kill -0 "$PPID" 2>/dev/null && kill -0 "$S" 2>/dev/null; do sleep 1; done; kill "$S" 2>/dev/null; wait "$S"';
  server = spawn("sh", ["-c", guard, "sh", path.join(ROOT, "bin", "tokscope"), "serve", "--no-open", "--port", String(port)], { stdio: "inherit" });
  server.once("exit", (code) => { server = null; if (code) app.exit(code); });
  const url = `http://127.0.0.1:${port}/`;
  await waitFor(url);
  win = new BrowserWindow({ width: 1440, height: 900, title: "tokscope", autoHideMenuBar: true });
  // anything that is not the local dashboard opens in the real browser
  win.webContents.setWindowOpenHandler(({ url: u }) => { shell.openExternal(u); return { action: "deny" }; });
  win.webContents.on("will-navigate", (e, u) => { if (!u.startsWith(url)) { e.preventDefault(); shell.openExternal(u); } });
  win.on("closed", () => { win = null; });
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
