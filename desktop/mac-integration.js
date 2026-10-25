// The Mac-only pieces of the app, without Electron so a test can call them on any OS.
const fs = require("fs");
const path = require("path");
const { serverCommand } = require("./server-command");

const MARK = "# written by tokscope's Install command line tool";

// single-quote a string for sh
function q(s) {
  return `'${String(s).replace(/'/g, `'\\''`)}'`;
}

// The ~/.local/bin/tokscope wrapper: the bundled Python runs the package, with the app's data folder, so the statusline
// and the SessionEnd hook see the same database as the app.
function wrapperScript(root) {
  return [
    "#!/bin/sh",
    MARK,
    'if [ -z "$TOKSCOPE_HOME" ]; then',
    '  if [ -d "$HOME/.local/share/tokscope" ]; then TOKSCOPE_HOME="$HOME/.local/share/tokscope"; else TOKSCOPE_HOME="$HOME/Library/Application Support/tokscope"; fi',
    "fi",
    `PYTHONPATH=${q(root)} PYTHONNOUSERSITE=1 TOKSCOPE_HOME="$TOKSCOPE_HOME" \\`,
    `  exec ${q(path.join(root, "python", "bin", "python3"))} -s -m tokscope.cli "$@"`,
    "",
  ].join("\n");
}

// `tokscope service install|uninstall|status` through the bundled Python: { cmd, env } to spawn
function serviceCommand({ action, root, home = "", env = {} }) {
  const python = path.join(root, "python", "bin", "python3");
  const run = serverCommand({ platform: "darwin", root, port: 0, env, home });
  const args = ["-s", "-m", "tokscope.cli", "service", action];
  if (action === "install") args.push("--python", python, "--root", root, "--home", run.env.TOKSCOPE_HOME);
  return { cmd: [python, ...args], env: run.env };
}

// Write the wrapper to <home>/.local/bin/tokscope. A file that is not ours, or a symlink (setup.sh links it to the
// clone's bin/tokscope), is left alone unless force is set; force replaces the link itself, never what it points to.
// Returns { path, status: "installed" | "updated" | "exists", symlink? }.
function installCli({ root, home, force = false, fsApi = fs }) {
  const dir = path.join(home, ".local", "bin");
  const target = path.join(dir, "tokscope");
  let status = "installed";
  let st = null;
  try { st = fsApi.lstatSync(target); } catch (e) { if (e.code !== "ENOENT") throw e; }
  const symlink = !!st && st.isSymbolicLink();
  if (st) {
    const ours = !symlink && String(fsApi.readFileSync(target, "utf8")).includes(MARK);
    if (!ours && !force) return { path: target, status: "exists", symlink };
    status = "updated";
  }
  fsApi.mkdirSync(dir, { recursive: true });
  const tmp = `${target}.tmp-${process.pid}`;
  fsApi.writeFileSync(tmp, wrapperScript(root), { mode: 0o755 });
  fsApi.chmodSync(tmp, 0o755);
  fsApi.renameSync(tmp, target); // replaces a symlink itself, not its target
  return { path: target, status };
}

// true when dir is one of the PATH entries (the wrapper is only found from a terminal then)
function onPath(dir, pathVar) {
  return String(pathVar || "").split(":").includes(dir);
}

function aboutOptions({ version }) {
  return {
    applicationName: "tokscope",
    applicationVersion: version,
    copyright: "MIT License",
    website: "https://github.com/minhtran3124/claude-code-tokscope",
  };
}

// Dock click: make the window again only when none is open (one that exists is only shown)
function shouldReopen({ windowCount }) {
  return windowCount === 0;
}

module.exports = { wrapperScript, serviceCommand, installCli, onPath, aboutOptions, shouldReopen, MARK };
