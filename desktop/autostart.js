// Linux: turn the background service on the first time the app runs, without a question. Without Electron, so a test can call it.
const fs = require("fs");
const path = require("path");

// `tokscope service install` for the launcher in <root>/bin; the path is quoted in the unit (it may hold spaces)
function installCommand({ root }) {
  const exe = path.join(root, "bin", "tokscope");
  return { cmd: [exe, "service", "install", "--exe", exe, "--quote-exe"] };
}

// Once per user: the marker file is written even when the install fails, so a user who turns the service off
// (Settings card or systemctl) is not switched back on at the next start.
function firstRun({ dir, platform, fsApi = fs }) {
  if (platform !== "linux") return false;
  const marker = path.join(dir, "service-autostart");
  if (fsApi.existsSync(marker)) return false;
  fsApi.mkdirSync(dir, { recursive: true });
  fsApi.writeFileSync(marker, "");
  return true;
}

module.exports = { installCommand, firstRun };
