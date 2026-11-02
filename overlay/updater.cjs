// D64: Jimmy updates itself from this repo's GitHub Releases. No library: one JSON request,
// two downloads, a SHA-256 check, then the release's own setup, run silently.
//
// The overlay (long-running) checks 10 minutes after start and every 6 h after; a newer setup is
// downloaded into <data>\cache\update (the drive the user chose, never C:) and verified
// against the release's .sha256. Then a Windows notification: click to update now, or it
// installs the next time Jimmy.exe starts (the launcher). Installing stops Jimmy (its Python
// in <data>\runtime and the Jimmy.exe processes), runs the setup with /S --force-run, and the
// setup starts Jimmy again. `auto_update: false` in settings.json turns all of it off.
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const https = require("https");
const crypto = require("crypto");

const REPO = "Adhrit-Verma/Jimmy";
const UA = { "User-Agent": "Jimmy-Updater" };
const POINTER = path.join(process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"), "Jimmy", "location.json");
const readJson = (f) => JSON.parse(fs.readFileSync(f, "utf8").replace(/^﻿/, ""));
const dataDir = () => { try { return readJson(POINTER).data || null; } catch { return null; } };
const dir = (data) => path.join(data, "cache", "update");

// "1.2.10" > "1.2.9"; a leading "v" is fine; anything after "-" is ignored.
function newer(a, b) {
  const n = (v) => String(v).replace(/^v/, "").split("-")[0].split(".").map((x) => parseInt(x, 10) || 0);
  const [x, y] = [n(a), n(b)];
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  }
  return false;
}

function enabled(data) {
  try { return readJson(path.join(data, "settings.json")).auto_update !== false; } catch { return true; }
}

// GET with redirects (release assets redirect to a CDN). onRes gets the final 200 response.
function get(url, onRes, onError, hops = 0) {
  https.get(url, { headers: { ...UA, Accept: "application/vnd.github+json" }, timeout: 30000 }, (res) => {
    if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && hops < 6) {
      res.resume();
      return get(new URL(res.headers.location, url).toString(), onRes, onError, hops + 1);
    }
    if (res.statusCode !== 200) { res.resume(); return onError(new Error(`HTTP ${res.statusCode} for ${url}`)); }
    onRes(res);
  }).on("error", onError).on("timeout", function () { this.destroy(new Error(`timed out: ${url}`)); });
}

const text = (url) => new Promise((resolve, reject) => get(url, (res) => {
  let s = "";
  res.setEncoding("utf8");
  res.on("data", (c) => { s += c; if (s.length > 1e6) res.destroy(new Error("too big")); });
  res.on("end", () => resolve(s));
  res.on("error", reject);
}, reject));

// A file, its SHA-256 checked as it streams; it only gets its real name when it matches.
function download(url, dest, sha256, onProgress) {
  return new Promise((resolve, reject) => get(url, (res) => {
    const total = Number(res.headers["content-length"] || 0);
    const hash = crypto.createHash("sha256");
    const out = fs.createWriteStream(dest + ".part");
    let done = 0;
    res.on("data", (c) => { done += c.length; hash.update(c); onProgress?.(done, total); });
    res.pipe(out);
    out.on("finish", () => {
      if (sha256 && hash.digest("hex") !== sha256) {
        fs.rmSync(dest + ".part", { force: true });
        return reject(new Error("download doesn't match its SHA-256"));
      }
      fs.renameSync(dest + ".part", dest);
      resolve(dest);
    });
    out.on("error", reject);
  }, reject));
}

function sha256File(f) {
  const h = crypto.createHash("sha256");
  h.update(fs.readFileSync(f));
  return h.digest("hex");
}

// A downloaded, verified update newer than `version`, or null. Clears what an installed
// update left behind, and one that was tried and didn't take: a setup that fails must not
// stop Jimmy from starting, every time (the overlay downloads it again later).
function pending(data, version) {
  if (!data || !enabled(data)) return null;
  try {
    const p = readJson(path.join(dir(data), "pending.json"));
    if (!p.tried && newer(p.version, version) && fs.existsSync(p.file) && sha256File(p.file) === p.sha256) return p;
  } catch { /* nothing pending */ }
  fs.rmSync(dir(data), { recursive: true, force: true });
  return null;
}

// Look for a newer release; download and verify it. Resolves to the pending update or null.
async function check({ version, data, log = () => {} }) {
  if (!data || !enabled(data)) return null;
  const have = pending(data, version);
  const rel = JSON.parse(await text(`https://api.github.com/repos/${REPO}/releases/latest`));
  const latest = String(rel.tag_name || "").replace(/^v/, "");
  if (!latest || !newer(latest, version)) return null;
  if (have && have.version === latest) return have;
  const exe = (rel.assets || []).find((a) => /^Jimmy-Setup-[\d.]+\.exe$/.test(a.name));
  const sum = (rel.assets || []).find((a) => exe && a.name === exe.name + ".sha256");
  if (!exe || !sum) { log(`[update] ${latest}: the release has no setup and .sha256`); return null; }
  const sha256 = (await text(sum.browser_download_url)).trim().split(/\s+/)[0].toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(sha256)) { log(`[update] ${latest}: unreadable .sha256`); return null; }
  fs.rmSync(dir(data), { recursive: true, force: true });
  fs.mkdirSync(dir(data), { recursive: true });
  const file = path.join(dir(data), exe.name);
  log(`[update] downloading Jimmy ${latest} (${Math.round(exe.size / 1e6)} MB)`);
  await download(exe.browser_download_url, file, sha256);
  const p = { version: latest, file, sha256 };
  fs.writeFileSync(path.join(dir(data), "pending.json"), JSON.stringify(p));
  log(`[update] Jimmy ${latest} is ready`);
  return p;
}

// Stop Jimmy, run the setup silently over the same folder, start Jimmy again (--force-run).
// A detached PowerShell does it, so it outlives the Jimmy.exe that asked.
function apply(p, data, install) {
  // 0. One try per download (see pending()).
  fs.writeFileSync(path.join(path.dirname(p.file), "pending.json"), JSON.stringify({ ...p, tried: true }));
  // 1. Jimmy's Python (its files are in use) stops first, while we wait.
  const q = (s) => String(s).replace(/'/g, "''");
  cp.spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
    `Get-Process | Where-Object { $_.Path -like '${q(data)}\\runtime\\*' } | Stop-Process -Force; Start-Sleep -Seconds 1`],
    { stdio: "ignore", windowsHide: true, timeout: 30000 });
  // 2. The setup, detached: Node puts other children in a job that dies with their parent, and
  // the setup outlives us (the caller exits next). It stops any other Jimmy.exe itself.
  // /D= must come last and unquoted (NSIS), hence the verbatim command line.
  cp.spawn(p.file, ["/S", "--force-run", `/D=${install}`],
           { detached: true, stdio: "ignore", windowsVerbatimArguments: true, argv0: `"${p.file}"` }).unref();
}

module.exports = { newer, enabled, pending, check, apply, download, dataDir, REPO };

if (require.main === module) {          // node overlay/updater.cjs: self-check of the comparison
  const assert = require("assert");
  assert(newer("1.0.1", "1.0.0") && newer("v1.2.10", "1.2.9") && newer("2.0", "1.9.9"));
  assert(!newer("1.0.0", "1.0.0") && !newer("1.0.0", "1.0.1") && !newer("1.0.0-beta", "1.0.0"));
  console.log("updater ok");
}
