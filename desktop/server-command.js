// How to start `tokscope serve`, without Electron so a test can call it on any OS.
const path = require("path");

// returns the command (run under the guard in main.js) and the environment to add for the child
function serverCommand({ platform, root, port, env = {}, home = "" }) {
  const args = ["serve", "--no-open", "--port", String(port)];
  if (platform !== "darwin") return { cmd: [path.join(root, "bin", "tokscope"), ...args], env: {} };
  // Finder gives an app PATH=/usr/bin:/bin:/usr/sbin:/sbin and Apple's python3 is 3.9, so use the bundled one.
  // PATH gains the usual homes of git, claude and ant for the child.
  const extra = ["/opt/homebrew/bin", "/usr/local/bin", path.join(home, ".local", "bin"), path.join(home, ".claude", "local")];
  const base = (env.PATH || "/usr/bin:/bin:/usr/sbin:/sbin").split(":");
  return {
    cmd: [path.join(root, "python", "bin", "python3"), "-s", "-m", "tokscope.cli", ...args],
    env: {
      PYTHONPATH: root,
      PYTHONNOUSERSITE: "1",
      TOKSCOPE_HOME: path.join(home, "Library", "Application Support", "tokscope"),
      PATH: [...new Set([...base, ...extra])].join(":"),
    },
  };
}

module.exports = { serverCommand };
