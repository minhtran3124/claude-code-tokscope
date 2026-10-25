// A window around `tokscope serve`: start the server on a free port, show it, stop it on quit.
const { app, BrowserWindow, Menu, WebContentsView, dialog, nativeTheme, shell } = require("electron");
const { statusPage } = require("./loading");
const { serverCommand } = require("./server-command");
const mac = require("./mac-integration");
const os = require("os");
const { spawn, execFile } = require("child_process");
const net = require("net");
const http = require("http");
const path = require("path");

// a clone keeps bin/ and tokscope/ next to desktop/; the .deb and the macOS .app put them in resources/ (the .app adds python/)
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
  const run = serverCommand({ platform: process.platform, root: ROOT, port, env: process.env, home: os.homedir() });
  server = spawn("sh", ["-c", guard, "sh", ...run.cmd], { stdio: "inherit", env: { ...process.env, ...run.env } });
  // the server is gone (it failed to bind, crashed or was killed): leave rather than show a dead page
  server.once("exit", (code) => { server = null; if (!base && win) showFailure(`the server stopped (exit ${code})`); else app.exit(code || 1); });
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

// the server did not start: say so in the window instead of a spinner that never ends
function showFailure(message) {
  console.error(`tokscope: ${message}`);
  if (win) showCover(`tokscope did not start: ${message}`, false);
  else app.exit(1);
}

let base = null;  // the dashboard's address once it answers; nothing else may be shown in the window

// The loading page is a view over the dashboard, not the dashboard's own page: the dashboard's first paint is blank, so
// the cover stays until the dashboard reports that it has loaded (start and every reload).
let cover = null;  // WebContentsView with the loading page
let coverShown = false;
// the dashboard's own theme choice (localStorage tokscope-theme), read after each load so the cover matches it; null is
// Auto, which follows the system. The first start has no choice yet and uses the system's.
let themeDark = null;
let loadFailed = false;  // the last main-frame load of the dashboard failed: its error page is not the dashboard

function useDark() {
  return themeDark === null ? nativeTheme.shouldUseDarkColors : themeDark;
}

function coverBounds() {
  const [width, height] = win.getContentSize();
  return { x: 0, y: 0, width, height };
}

function showCover(message, spin = true) {
  if (!win) return;
  const dark = useDark();
  if (!cover) {
    cover = new WebContentsView();
    cover.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    cover.webContents.on("will-navigate", (e) => e.preventDefault());  // the page has no links; keep it that way
  }
  cover.setBackgroundColor(dark ? "#1d1a15" : "#f2efe7");  // the colour before the page paints, in the current theme
  if (!coverShown) { win.contentView.addChildView(cover); coverShown = true; }  // added last: it is on top
  cover.setBounds(coverBounds());
  cover.webContents.loadURL(statusPage(dark, message, spin)).catch(() => {});
}

function hideCover() {
  if (win && coverShown) { win.contentView.removeChildView(cover); coverShown = false; }
}

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
  // the dashboard has painted: take the loading page away
  // a failed load is followed by Chromium's error page and maybe a did-finish-load for it: keep the failure message then
  win.webContents.on("did-start-navigation", (e, u, inPlace, isMain) => { if (isMain) loadFailed = false; });
  win.webContents.on("did-finish-load", async () => {
    if (!base || loadFailed || !win.webContents.getURL().startsWith(base)) return;
    hideCover();
    const choice = await win.webContents.executeJavaScript("localStorage.getItem('tokscope-theme')").catch(() => null);
    themeDark = choice === "dark" ? true : choice === "light" ? false : null;
  });
  win.webContents.on("did-fail-load", (e, code, desc, u, isMain) => {
    if (isMain && code !== -3 && base && u.startsWith(base)) {  // -3 is an aborted load
      loadFailed = true;
      showFailure(`the dashboard did not load (${desc})`);
    }
  });
  win.on("resize", () => { if (coverShown) cover.setBounds(coverBounds()); });
  win.on("closed", () => {
    if (cover) cover.webContents.close();
    win = null; cover = null; coverShown = false;
  });
  showCover("Starting tokscope");
}

// Reload (F5, Ctrl+R, Ctrl+Shift+R) covers the window with the loading page while the dashboard renders again.
function reloadDashboard() {
  if (!win || !base) return;
  const here = win.webContents.getURL();
  showCover("Reloading tokscope");
  win.webContents.loadURL(here.startsWith(base) ? here : base).catch(() => {});  // a failure arrives as did-fail-load
}

// The default menu's Reload would reload the dashboard with no loading page, so the menu gets our own Reload items
// (on Linux the menu sees Ctrl+R before the page does, so a key handler on the page would never run).
// Start at login: the service is opt-in, so the box starts empty and follows `tokscope service status`.
let loginOn = false;

function runService(action) {
  const run = mac.serviceCommand({ action, root: ROOT, home: os.homedir(), env: process.env });
  return new Promise((resolve) => {
    execFile(run.cmd[0], run.cmd.slice(1), { env: { ...process.env, ...run.env } }, (err, out, errOut) => resolve({ ok: !err, text: String(out || errOut || (err && err.message) || "").trim() }));
  });
}

async function refreshLogin() {
  loginOn = (await runService("status")).ok;
  Menu.setApplicationMenu(appMenu());
}

async function toggleLogin() {
  const r = await runService(loginOn ? "uninstall" : "install");
  if (!r.ok) dialog.showErrorBox("Start at login", r.text || "the service command failed");
  await refreshLogin();
}

async function installCli() {
  try {
    let r = mac.installCli({ root: ROOT, home: os.homedir() });
    if (r.status === "exists") {
      const { response } = await dialog.showMessageBox({ type: "question", buttons: ["Replace", "Cancel"], defaultId: 1, message: `${r.path} ${r.symlink ? "is a symbolic link" : "exists"} and was not written by tokscope.`, detail: "Replace it with the tokscope command line tool?" });
      if (response !== 0) return;
      r = mac.installCli({ root: ROOT, home: os.homedir(), force: true });
    }
    const dir = path.dirname(r.path);
    const note = mac.onPath(dir, process.env.PATH) ? "" : `\n\n${dir} is not on the PATH of this app; add it to your shell profile (export PATH="$HOME/.local/bin:$PATH") to run tokscope from a terminal.`;
    dialog.showMessageBox({ message: `Command line tool ${r.status}: ${r.path}`, detail: "The statusline and the SessionEnd hook can call tokscope now." + note });
  } catch (e) {
    dialog.showErrorBox("Install command line tool", e.message);
  }
}

function appMenu() {
  const isMac = process.platform === "darwin";
  const macMenu = isMac ? [{ role: "appMenu" }] : [];
  const macFile = isMac ? [
    { type: "separator" },
    { label: "Start at login", type: "checkbox", checked: loginOn, click: toggleLogin },
    { label: "Install command line tool", click: installCli },
  ] : [];
  return Menu.buildFromTemplate([
    ...macMenu,
    { label: "File", submenu: [{ role: "close" }, ...macFile] },
    { role: "editMenu" },
    { label: "View", submenu: [
      { label: "Reload", accelerator: "CmdOrCtrl+R", click: reloadDashboard },
      { label: "Reload page", accelerator: "F5", click: reloadDashboard },
      { label: "Force reload", accelerator: "CmdOrCtrl+Shift+R", click: reloadDashboard },
      { role: "toggleDevTools" }, { type: "separator" }, { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" },
      { type: "separator" }, { role: "togglefullscreen" },
    ] },
    { role: "windowMenu" },
  ]);
}

function showDashboard(url) {
  if (!win) return;  // the window was closed while the server started
  base = url;
  win.webContents.loadURL(url).catch(() => {});  // a failure arrives as did-fail-load; the cover goes when it has loaded
}

// a Dock click with no window: show the dashboard again
function reopen() {
  if (!base) return;
  createWindow();
  showDashboard(base);
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.on("activate", () => { if (mac.shouldReopen({ windowCount: BrowserWindow.getAllWindows().length })) reopen(); });
  app.whenReady().then(() => {
    Menu.setApplicationMenu(appMenu());
    if (process.platform === "darwin") {
      app.setAboutPanelOptions(mac.aboutOptions({ version: app.getVersion() }));
      refreshLogin();
    }
    return start();
  }).catch((e) => showFailure(e.message));
  app.on("window-all-closed", () => app.quit());
  // every way out stops the server: a normal quit, app.exit() on a failed start, and a signal (not SIGKILL)
  process.on("exit", () => { if (server) server.kill(); });
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) process.on(sig, () => app.quit());
}
