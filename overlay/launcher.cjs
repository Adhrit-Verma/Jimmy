// Jimmy, installed (D61): the launcher, the onboarding's main process, and the provisioner.
//
// The packaged Jimmy.exe runs this when it is started by the user (Start menu, desktop,
// sign-in). When Jimmy's Python starts Jimmy.exe as its overlay it passes the API in the
// environment and main.cjs never gets here.
//
//   Jimmy.exe                       set up?  start Jimmy's backend and quit : the onboarding
//   Jimmy.exe --onboarding          the onboarding again (repair, change the profile)
//   Jimmy.exe --provision --data D --profile lite|balanced|full [--whisper M] [--gpu 0|1]
//                         [--local-ai 0|1] --log FILE      headless (the clean-machine test)
//   Jimmy.exe --self-test --log FILE                        import everything, run doctor and Jimmy 20 s
//
// Where things go (docs/PLAN-2026-11-01-installer.md): the app and its runtime next to
// Jimmy.exe, on whatever drive the setup was given; data, models and caches in the folder
// the onboarding was given; on C: only %APPDATA%\Jimmy\location.json (where the data is),
// the shortcuts and the HKCU uninstall/startup entries. Electron's own cache is moved off
// C: too (userData in the install folder).
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");
const https = require("https");
const crypto = require("crypto");
const updater = require("./updater.cjs");
const { download } = updater;

const DEV = !app.isPackaged;
const INSTALL = DEV ? path.join(__dirname, "..", "installer", "dev-install") : path.dirname(process.execPath);
const RES = DEV ? path.join(__dirname, "..", "installer", "stage") : process.resourcesPath;
const CODE = path.join(RES, "jimmy");
const TOOLS = path.join(RES, "tools");
const UV = path.join(TOOLS, "uv.exe");
const POINTER = path.join(process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"), "Jimmy", "location.json");
// Windows tools often write UTF-8 with a byte-order mark; JSON.parse refuses it.
const readJson = (f) => JSON.parse(fs.readFileSync(f, "utf8").replace(/^\uFEFF/, ""));
const pointer = () => { try { return readJson(POINTER).data || null; } catch { return null; } };
// Jimmy's Python and local AI live in the data folder, not beside Jimmy.exe: an update replaces
// the install folder whole (found in the D61 upgrade test), and the data folder is on the
// drive the user chose anyway.
let RUNTIME, PY_HOME, VENV, PY, PYW, READY, OLLAMA_DIR;
function useData(data) {
  const base = data || INSTALL;
  RUNTIME = path.join(base, "runtime");
  PY_HOME = path.join(RUNTIME, "python");
  VENV = path.join(RUNTIME, "venv");
  PY = path.join(VENV, "Scripts", "python.exe");
  PYW = path.join(VENV, "Scripts", "pythonw.exe");
  READY = path.join(RUNTIME, "ready.json");
  OLLAMA_DIR = path.join(base, "ollama");
}
useData(pointer());
const PY_VERSION = "3.12.10";
const OLLAMA = { version: "v0.40.13", url: "https://github.com/ollama/ollama/releases/download/v0.40.13/ollama-windows-amd64.zip",
                 sha256: "7afa38624fa62ee5d8293422d0ab084c1bb4603134c7f4dafce11a033b57cc19", models: ["qwen2.5:3b", "bge-m3"] };
// Rough sizes, for the onboarding's choices (measured on this project's own runtime).
const PROFILES = {
  lite: { whisper: "small", gpu: false, localAi: false, gb: 2.5, ramGb: 2 },
  balanced: { whisper: "large-v3-turbo", gpu: true, localAi: false, gb: 4.5, ramGb: 4 },
  full: { whisper: "large-v3-turbo", gpu: true, localAi: true, gb: 11, ramGb: 8 },
};

// Off C: from the first moment: Chromium's caches live beside the app, not in %APPDATA%.
if (!DEV) app.setPath("userData", path.join(INSTALL, "userdata"));

const arg = (name, dflt) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : dflt; };
const has = (name) => process.argv.includes(name);
const ready =() => fs.existsSync(READY) && fs.existsSync(PYW) && !!pointer();
// The packages this version of Jimmy needs, as a fingerprint: an update that changes them is
// applied at the next start (incrementally), before Jimmy runs.
const lockHash = (gpu) => crypto.createHash("sha256").update(fs.readFileSync(path.join(CODE, "requirements.lock")))
  .update(gpu ? fs.readFileSync(path.join(CODE, "requirements-gpu.lock")) : "").digest("hex").slice(0, 16);
const readyInfo = () => { try { return readJson(READY); } catch { return {}; } };

let logFile = null;
function log(line) {
  const s = `${new Date().toISOString()} ${line}`;
  if (logFile) {
    try {
      // Only when missing: a recursive mkdir of a drive root (a log at D:\x.log) can throw EPERM
      // on Windows, and then the clean-machine test's logs were never written.
      const dir = path.dirname(logFile);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.appendFileSync(logFile, s + "\n");
    } catch { /* a log must never stop the setup */ }
  }
  if (DEV) console.log(s);
}

// --- running things -------------------------------------------------------------------------
function cleanEnv(extra) {
  const env = { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", ...extra };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.PYTHONHOME;       // someone else's Python must never leak in
  return env;
}

function pyEnv(data) {
  return cleanEnv({ JIMMY_DATA: data, PYTHONPATH: CODE, UV_CACHE_DIR: path.join(data, "cache", "uv"),
                    HF_HOME: path.join(data, "models", "hf"), OLLAMA_MODELS: path.join(data, "models", "ollama") });
}

// Run a program; each output line goes to onLine. Resolves with the exit code.
function run(exe, args, { env, cwd, input, onLine } = {}) {
  return new Promise((resolve) => {
    log(`run ${path.basename(exe)} ${args.join(" ")}`);
    let p;
    try {
      p = cp.spawn(exe, args, { env: env || cleanEnv(), cwd: cwd || INSTALL, windowsHide: true });
    } catch (e) {
      log(`spawn failed: ${e.message}`);
      return resolve(-1);
    }
    const feed = (buf) => String(buf).split(/\r?\n|\r/).forEach((l) => { if (l.trim()) { log(`  ${l}`); onLine?.(l); } });
    p.stdout.on("data", feed);
    p.stderr.on("data", feed);
    p.on("error", (e) => { log(`error: ${e.message}`); resolve(-1); });
    p.on("close", (code) => resolve(code ?? -1));
    if (input !== undefined) { p.stdin.write(input); }
    p.stdin.end();
  });
}

// download(url, dest, sha256, onProgress): shared with the updater (D64).

// --- the PC, as the onboarding shows it -----------------------------------------------------
const CHECK_PS = `
$ErrorActionPreference = 'SilentlyContinue'
$os = Get-CimInstance Win32_OperatingSystem
$gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object { @{ name = $_.Name; driver = $_.DriverVersion } })
$smi = $null
$nv = Get-Command nvidia-smi.exe
if ($nv) { $smi = (& nvidia-smi.exe --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null | Select-Object -First 1) }
$mics = @(Get-PnpDevice -Class AudioEndpoint -PresentOnly | Where-Object { $_.FriendlyName -match 'Microphone|Mic|Headset|Array' -and $_.Status -eq 'OK' } | Sort-Object { $_.FriendlyName -match 'Virtual|Oculus|VB-Audio|Voicemeeter|Steam' } | ForEach-Object { $_.FriendlyName })
$cams = @(Get-PnpDevice -Class Camera,Image -PresentOnly | Where-Object { $_.Status -eq 'OK' } | ForEach-Object { $_.FriendlyName })
function consent($cap) {
  $base = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\$cap"
  @{ all = (Get-ItemProperty $base).Value; desktop = (Get-ItemProperty "$base\\NonPackaged").Value }
}
$drives = @(Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -ne $null -and $_.Used -ne $null } | ForEach-Object { @{ name = $_.Name; free = [int64]$_.Free; used = [int64]$_.Used } })
@{ caption = $os.Caption; build = $os.BuildNumber; version = $os.Version; gpus = $gpu; smi = $smi; mics = $mics; cams = $cams;
   mic = (consent 'microphone'); cam = (consent 'webcam'); drives = $drives } | ConvertTo-Json -Depth 4 -Compress
`;

async function checks() {
  let raw = "";
  await run("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", CHECK_PS],
            { onLine: (l) => { raw += l; } });
  let s = {};
  try { s = JSON.parse(raw); } catch { s = {}; }
  const arch = process.env.PROCESSOR_ARCHITEW6432 || process.env.PROCESSOR_ARCHITECTURE || os.arch();
  const build = Number(s.build || os.release().split(".")[2] || 0);
  const smi = String(s.smi || "");
  const nvidia = /nvidia/i.test(smi) || (s.gpus || []).some((g) => /nvidia/i.test(g.name || ""));
  const driver = smi.split(",")[1]?.trim() || "";
  const vram = Number((smi.split(",")[2] || "").replace(/[^0-9]/g, "")) || 0;
  const ok = (v) => (v === undefined || v === null || /allow/i.test(String(v)));
  const ramGb = os.totalmem() / 2 ** 30;
  return {
    windows: { name: s.caption || `Windows (build ${build})`, build, ok: build >= 19045, win11: build >= 22000 },
    arch: { value: arch, ok: /amd64|x64/i.test(arch) },
    ram: { gb: Math.round(ramGb * 10) / 10, ok: ramGb >= 7.5, low: ramGb < 15.5 },
    cpu: { name: (os.cpus()[0] || {}).model || "", cores: os.cpus().length },
    gpu: { nvidia, name: nvidia ? (smi.split(",")[0] || (s.gpus || []).find((g) => /nvidia/i.test(g.name))?.name || "NVIDIA") :
           ((s.gpus || [])[0] || {}).name || "", driver, vramMb: vram,
           cudaOk: nvidia && (!driver || Number(driver.split(".")[0]) >= 528) },
    mic: { devices: s.mics || [], allowed: ok(s.mic?.all) && ok(s.mic?.desktop) },
    camera: { devices: s.cams || [], allowed: ok(s.cam?.all) && ok(s.cam?.desktop) },
    drives: (s.drives || []).map((d) => ({ name: `${d.name}:`, free: d.free, used: d.used })),
    install: INSTALL, dataSuggestion: suggestData(s.drives || []), profiles: PROFILES, pointer: POINTER,
  };
}

function suggestData(drives) {
  const sys = (process.env.SystemDrive || "C:").replace(":", "").toUpperCase();
  const installDrive = path.parse(INSTALL).root.replace(/[:\\]/g, "").toUpperCase();
  // The drive Jimmy itself went on, if it isn't the system drive; else the roomiest other drive.
  if (installDrive && installDrive !== sys) return `${installDrive}:\\JimmyData`;
  const other = drives.filter((d) => d.name.toUpperCase() !== sys && d.free > 12 * 2 ** 30).sort((a, b) => b.free - a.free)[0];
  return other ? `${other.name}:\\JimmyData` : path.join(os.homedir(), "JimmyData");
}

// --- the provisioner: Jimmy's own Python, packages, models ----------------------------------
// opts: { data, profile, whisper, gpu, localAi, settings, keys }. emit({step, state, ...}).
async function provision(opts, emit) {
  const data = path.resolve(opts.data);
  useData(data);
  const p = PROFILES[opts.profile] || PROFILES.balanced;
  const gpu = opts.gpu ?? p.gpu;
  const whisper = opts.whisper || (gpu ? p.whisper : "small");
  const localAi = opts.localAi ?? p.localAi;
  const env = pyEnv(data);
  const uvEnv = cleanEnv({ UV_CACHE_DIR: path.join(data, "cache", "uv"), UV_PYTHON_INSTALL_DIR: PY_HOME,
                           UV_PYTHON_PREFERENCE: "only-managed", UV_NO_CONFIG: "1" });
  const fail = (step, msg) => { emit({ step, state: "failed", error: msg }); throw new Error(`${step}: ${msg}`); };
  const say = (step, extra) => emit({ step, ...extra });
  for (const d of [data, path.join(data, "cache"), path.join(data, "models"), path.join(data, "logs"), RUNTIME]) {
    if (!fs.existsSync(d)) fs.mkdirSync(d, { recursive: true });
  }
  log(`provision: data=${data} profile=${opts.profile} whisper=${whisper} gpu=${gpu} localAi=${localAi}`);

  say("python", { state: "running", detail: `Python ${PY_VERSION}, Jimmy's own` });
  if (await run(UV, ["python", "install", PY_VERSION, "--install-dir", PY_HOME], { env: uvEnv,
      onLine: (l) => say("python", { state: "running", detail: l }) }) !== 0) fail("python", "couldn't install Python");
  let base = "";
  await run(UV, ["python", "find", PY_VERSION], { env: uvEnv, onLine: (l) => { if (/python\.exe$/i.test(l.trim())) base = l.trim(); } });
  if (!base) fail("python", "Python installed but not found");
  // The C++ runtime, app-locally: next to the interpreter, found before System32's copy.
  for (const f of fs.readdirSync(path.join(TOOLS, "vcrt")).filter((n) => n.endsWith(".dll"))) {
    fs.copyFileSync(path.join(TOOLS, "vcrt", f), path.join(path.dirname(base), f));
  }
  if (!fs.existsSync(PY) && await run(UV, ["venv", VENV, "--python", base, "--seed"], { env: uvEnv }) !== 0) {
    fail("python", "couldn't make Jimmy's environment");
  }
  say("python", { state: "done" });

  say("packages", { state: "running", detail: gpu ? "with GPU speech (cuBLAS)" : "CPU only" });
  const locks = ["-r", path.join(CODE, "requirements.lock"), ...(gpu ? ["-r", path.join(CODE, "requirements-gpu.lock")] : [])];
  let n = 0;
  if (await run(UV, ["pip", "install", "--python", PY, "--require-hashes", "--no-config", ...locks], { env: uvEnv,
      onLine: (l) => say("packages", { state: "running", detail: l, n: ++n }) }) !== 0) fail("packages", "a package didn't install (see the log)");
  say("packages", { state: "done" });

  say("settings", { state: "running" });
  const settings = { profile: opts.profile, whisper_model: whisper, whisper_device: gpu ? "cuda" : "cpu",
                     local_ai: !!localAi, webcam: opts.settings?.webcam ?? opts.profile !== "lite", ...(opts.settings || {}) };
  await run(PY, ["-m", "ambient.setup", "settings"], { env, cwd: CODE, input: JSON.stringify(settings) });
  const keys = Object.fromEntries(Object.entries(opts.keys || {}).filter(([, v]) => v));
  if (Object.keys(keys).length) {
    await run(PY, ["-m", "ambient.setup", "keys"], { env, cwd: CODE, input: JSON.stringify(keys) });
  }
  say("settings", { state: "done" });

  say("verify", { state: "running" });
  const bad = [];
  let vcrtFrom = "";
  const vcode = await run(PY, ["-m", "ambient.setup", "verify"], { env, cwd: CODE, onLine: (l) => {
    try {
      const j = JSON.parse(l);
      if (j.module && !j.ok) bad.push(`${j.module}: ${j.error}`);
      if (j.dll === "msvcp140.dll") vcrtFrom = j.path || "";
      say("verify", { state: "running", detail: j.module ? `${j.module} ${j.ok ? "✓" : "✗"}` : "" });
    } catch { /* not JSON: a warning */ }
  } });
  if (vcode !== 0 || bad.length) fail("verify", bad.join("; ") || "a piece of Jimmy didn't load");
  say("verify", { state: "done", vcrtFrom });

  say("model", { state: "running", detail: `speech model: ${whisper}` });
  const mcode = await run(PY, ["-m", "ambient.setup", "models", "--whisper", whisper], { env, cwd: CODE, onLine: (l) => {
    try { const j = JSON.parse(l); if (j.step === "model") say("model", { state: "running", done: j.done, total: j.total }); } catch { /* */ }
  } });
  if (mcode !== 0) fail("model", "the speech model didn't download");
  say("model", { state: "done" });

  if (localAi) {
    say("local_ai", { state: "running", detail: "Ollama (local AI)" });
    await setupOllama(data, (d, t) => say("local_ai", { state: "running", done: d, total: t }), (l) => say("local_ai", { state: "running", detail: l }));
    say("local_ai", { state: "done" });
  }

  // The pointer last: until it exists, Jimmy isn't "set up" and the onboarding comes back.
  fs.mkdirSync(path.dirname(POINTER), { recursive: true });
  fs.writeFileSync(POINTER, JSON.stringify({ data, app: INSTALL }, null, 1));
  fs.writeFileSync(path.join(path.dirname(POINTER), "data-path.txt"), data);   // for the uninstaller's question
  fs.writeFileSync(READY, JSON.stringify({ at: new Date().toISOString(), profile: opts.profile, whisper, gpu, localAi, data,
                                          lock: lockHash(gpu) }, null, 1));
  await run(UV, ["cache", "clean"], { env: uvEnv });          // ~1 GB of wheels the user doesn't need twice
  say("done", { state: "done", data });
  return { data, whisper, gpu, localAi };
}

async function setupOllama(data, onBytes, onLine) {
  const exe = path.join(OLLAMA_DIR, "ollama.exe");
  if (!fs.existsSync(exe)) {
    const zip = path.join(data, "cache", "ollama-windows-amd64.zip");
    if (!fs.existsSync(zip)) await download(OLLAMA.url, zip, OLLAMA.sha256, onBytes);
    fs.mkdirSync(OLLAMA_DIR, { recursive: true });
    if (await run("tar.exe", ["-xf", zip, "-C", OLLAMA_DIR], {}) !== 0) throw new Error("couldn't unpack Ollama");
    fs.rmSync(zip, { force: true });
  }
  startOllama(data);
  await new Promise((r) => setTimeout(r, 2500));
  for (const m of OLLAMA.models) {
    await run(exe, ["pull", m], { env: cleanEnv({ OLLAMA_MODELS: path.join(data, "models", "ollama"), OLLAMA_HOST: "127.0.0.1:11434" }), onLine });
  }
}

function startOllama(data) {
  const exe = path.join(OLLAMA_DIR, "ollama.exe");
  if (!fs.existsSync(exe)) return;
  const p = cp.spawn(exe, ["serve"], { env: cleanEnv({ OLLAMA_MODELS: path.join(data, "models", "ollama"), OLLAMA_HOST: "127.0.0.1:11434" }),
                                       detached: true, stdio: "ignore", windowsHide: true });
  p.unref();          // already running (the user's own Ollama, or ours): this one exits on its own
}

// After an update: the packages the new version needs, before Jimmy starts (a few seconds;
// uv only fetches what changed). Returns false if it failed (the onboarding repairs it).
async function updatePackages() {
  const info = readyInfo();
  if (info.lock === lockHash(!!info.gpu)) return true;
  const data = pointer();
  const uvEnv = cleanEnv({ UV_CACHE_DIR: path.join(data, "cache", "uv"), UV_PYTHON_INSTALL_DIR: PY_HOME,
                           UV_PYTHON_PREFERENCE: "only-managed", UV_NO_CONFIG: "1" });
  const locks = ["-r", path.join(CODE, "requirements.lock"), ...(info.gpu ? ["-r", path.join(CODE, "requirements-gpu.lock")] : [])];
  log(`update: packages changed (${info.lock} -> ${lockHash(!!info.gpu)})`);
  if (await run(UV, ["pip", "install", "--python", PY, "--require-hashes", "--no-config", ...locks], { env: uvEnv }) !== 0) return false;
  fs.writeFileSync(READY, JSON.stringify({ ...info, lock: lockHash(!!info.gpu), updated: new Date().toISOString() }, null, 1));
  await run(UV, ["cache", "clean"], { env: uvEnv });
  return true;
}

// --- start Jimmy ------------------------------------------------------------------------------
function startJimmy() {
  const data = pointer();
  let settings = {};
  try { settings = JSON.parse(fs.readFileSync(path.join(data, "settings.json"), "utf8")); } catch { /* defaults */ }
  // D65: Jimmy's Python starts Ollama (a hidden console its helpers share). Started from here,
  // detached, it had no console, and each GPU check and model runner it started flashed one up.
  const ollama = path.join(OLLAMA_DIR, "ollama.exe");
  const local = settings.local_ai && fs.existsSync(ollama)
    ? { JIMMY_OLLAMA_EXE: ollama, OLLAMA_HOST: "127.0.0.1:11434" } : {};
  const p = cp.spawn(PYW, ["-m", "ambient", "run"], { cwd: CODE, detached: true, stdio: "ignore", windowsHide: true,
    env: { ...pyEnv(data), JIMMY_OVERLAY_EXE: process.execPath, ...local } });
  p.unref();
  log(`started Jimmy (pid ${p.pid}) with data in ${data}`);
}

// --- the onboarding window --------------------------------------------------------------------
function onboarding() {
  const w = new BrowserWindow({
    width: 980, height: 660, frame: false, transparent: true, resizable: false, show: false, center: true,
    title: "Jimmy — setup", icon: path.join(__dirname, "build", "icon.ico"), backgroundColor: "#00000000",
    webPreferences: { preload: path.join(__dirname, "setup-preload.cjs"), contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  const shot = arg("--shot", null);              // dev: render step --step N to a PNG and quit
  w.loadFile(path.join(__dirname, "dist", "index.html"), { hash: `onboarding${shot ? `?step=${arg("--step", "0")}` : ""}` });
  w.once("ready-to-show", () => w.show());
  if (shot) {
    w.webContents.once("did-finish-load", () => setTimeout(async () => {
      fs.writeFileSync(shot, (await w.webContents.capturePage()).toPNG());
      app.exit(0);
    }, Number(arg("--delay", "4500"))));
  }
  const send = (ev) => { if (!w.isDestroyed()) w.webContents.send("setup:event", ev); };
  ipcMain.handle("setup:checks", () => checks());
  ipcMain.handle("setup:pick-folder", async (_e, start) => {
    const r = await dialog.showOpenDialog(w, { title: "Where should Jimmy keep its data?", defaultPath: start,
                                              properties: ["openDirectory", "createDirectory"] });
    return r.canceled ? null : r.filePaths[0];
  });
  ipcMain.handle("setup:test-key", (_e, provider, key) => testKey(provider, key));
  ipcMain.handle("setup:provision", async (_e, opts) => {
    try { return { ok: true, ...(await provision(opts, send)) }; }
    catch (e) { return { ok: false, error: String(e.message || e), log: logFile }; }
  });
  ipcMain.handle("setup:finish", (_e, o) => {
    app.setLoginItemSettings({ openAtLogin: !!o?.startWithWindows, path: process.execPath });
    startJimmy();
    setTimeout(() => app.quit(), 600);
  });
  ipcMain.on("setup:open", (_e, what) => {
    const urls = { mic: "ms-settings:privacy-microphone", cam: "ms-settings:privacy-webcam",
                   gemini: "https://aistudio.google.com/apikey", nvidia: "https://build.nvidia.com/settings/api-keys" };
    if (urls[what]) shell.openExternal(urls[what]);
    if (what === "log" && logFile) shell.showItemInFolder(logFile);
  });
  ipcMain.on("setup:quit", () => app.quit());
  ipcMain.on("setup:minimize", () => w.minimize());
}

function testKey(provider, key) {
  const req = provider === "gemini"
    ? { host: "generativelanguage.googleapis.com", path: "/v1beta/openai/models", method: "GET" }
    : { host: "integrate.api.nvidia.com", path: "/v1/chat/completions", method: "POST",
        body: JSON.stringify({ model: "openai/gpt-oss-20b", messages: [{ role: "user", content: "hi" }], max_tokens: 1 }) };
  return new Promise((resolve) => {
    const r = https.request({ host: req.host, path: req.path, method: req.method, timeout: 15000,
      headers: { Authorization: `Bearer ${String(key).trim()}`, "Content-Type": "application/json" } }, (res) => {
      res.resume();
      resolve({ ok: res.statusCode === 200, status: res.statusCode });
    });
    r.on("timeout", () => { r.destroy(); resolve({ ok: false, status: 0, error: "timed out" }); });
    r.on("error", (e) => resolve({ ok: false, status: 0, error: e.message }));
    if (req.body) r.write(req.body);
    r.end();
  });
}

// --- headless: the clean-machine test ---------------------------------------------------------
async function headless() {
  logFile = arg("--log", path.join(INSTALL, "setup.log"));
  try {
    if (has("--provision")) {
      const yes = (v, d) => (v === undefined ? d : v === "1");
      await provision({ data: arg("--data", path.join(os.homedir(), "JimmyData")), profile: arg("--profile", "lite"),
                        whisper: arg("--whisper", undefined), gpu: yes(arg("--gpu"), undefined),
                        localAi: yes(arg("--local-ai"), false) }, (() => {
        let last = "";                    // one line per change, not one per progress tick
        return (ev) => {
          const line = `[${ev.step}] ${ev.state || ""} ${ev.detail || ev.error || ""}`.trim();
          if (line !== last) log(line);
          last = line;
        };
      })());
    }
    if (has("--self-test")) {
      const data = pointer();
      if (!data) throw new Error("not set up");
      const env = pyEnv(data);
      for (const [label, args] of [["verify", ["-m", "ambient.setup", "verify"]], ["ambient doctor", ["-m", "ambient", "doctor"]],
                                   ["jimmy doctor", ["-m", "jimmy", "doctor"]],
                                   ["run 20 s", ["-m", "ambient", "run", "--seconds", "20", "--no-overlay", "--no-audio"]]]) {
        const code = await run(PY, args, { env, cwd: CODE });
        log(`self-test ${label}: exit ${code}`);
        if (label === "verify" && code !== 0) throw new Error("verify failed");
      }
    }
    log("headless: done");
    app.exit(0);
  } catch (e) {
    log(`headless FAILED: ${e.message}`);
    app.exit(1);
  }
}

module.exports = function launch() {
  if (!app.requestSingleInstanceLock()) {
    // Another Jimmy.exe is open. A headless run must say so: quitting quietly with 0 looked
    // like a finished setup on the clean-machine test (a Jimmy left running by the install).
    if (has("--provision") || has("--self-test")) {
      logFile = arg("--log", path.join(INSTALL, "setup.log"));
      log("headless FAILED: another Jimmy.exe is running; close it first");
      app.exit(2);
    } else app.quit();
    return;
  }
  app.whenReady().then(() => {
    if (has("--provision") || has("--self-test")) return headless();
    logFile = path.join(INSTALL, "setup.log");
    // D64: an update the overlay downloaded and verified installs now, before Jimmy starts;
    // the setup starts Jimmy again when it's done.
    const update = DEV ? null : updater.pending(pointer(), app.getVersion());
    if (update && !has("--onboarding")) {
      log(`update: installing Jimmy ${update.version} over ${app.getVersion()}`);
      updater.apply(update, pointer(), INSTALL);
      setTimeout(() => app.exit(0), 300);
      return;
    }
    if (ready() && !has("--onboarding")) {
      updatePackages().then((ok) => {
        if (!ok) return onboarding();               // couldn't update: the onboarding repairs it
        startJimmy();
        setTimeout(() => app.quit(), 400);
      });
      return;
    }
    onboarding();
  });
  app.on("window-all-closed", () => app.quit());
};
module.exports.paths = { INSTALL, CODE, POINTER };
