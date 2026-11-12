// Jimmy overlay: Electron main process (Stage 4, D23).
//
// One transparent, click-through, always-on-top window over the primary display's
// work area: a pill at top-centre, cards at top-right. It never takes focus and has
// no taskbar entry. Only this process talks to the Python API (127.0.0.1 + token);
// the page has no network access and no Node, just the small bridge in preload.cjs.
//
// Flags: --demo (fake cards, no Python needed)  --snapshot <file.png> (render, save, quit)
const { app, BrowserWindow, clipboard, screen, shell, ipcMain, globalShortcut } = require("electron");
const fs = require("fs");
const path = require("path");

// D61: an installed Jimmy keeps Chromium's caches beside itself (the drive the user chose),
// in both modes (launcher and overlay), never in %APPDATA% on C:.
if (app.isPackaged) app.setPath("userData", path.join(path.dirname(process.execPath), "userdata"));

const API = process.env.JIMMY_OVERLAY_URL;
const TOKEN = process.env.JIMMY_OVERLAY_TOKEN;
const DEMO = process.argv.includes("--demo");
const snapAt = process.argv.indexOf("--snapshot");
const SNAPSHOT = snapAt > 0 ? process.argv[snapAt + 1] : null;
const delayAt = process.argv.indexOf("--snap-delay");
const SNAP_DELAY = delayAt > 0 ? Number(process.argv[delayAt + 1]) : 2600;
const HOTKEY = "Control+Alt+J";
const TIMELINE_HOTKEY = "Control+Alt+T";
const INSIGHTS_HOTKEY = "Control+Alt+I";
const CURTAIN_HOTKEY = "Control+Alt+L";   // D34: the privacy curtain, by hand
const OPEN_TIMELINE = process.argv.includes("--timeline");

// D61: the installed Jimmy.exe, started by the user (Start menu, desktop, sign-in), is the
// launcher: the onboarding the first time, then it starts Jimmy's Python and quits. Started
// by that Python with the API in its environment, it's the overlay, as before.
const SETUP_FLAGS = ["--onboarding", "--provision", "--self-test"];
if (!API && !DEMO && !SNAPSHOT && !OPEN_TIMELINE && (app.isPackaged || process.argv.some((a) => SETUP_FLAGS.includes(a)))) {
  require("./launcher.cjs")();
  return;
}

let win = null;
let timeline = null;
// D33: voice navigation ("next", "scroll down") goes to whichever Jimmy surface you
// were last shown: the overlay's answer, or the timeline window.
let target = "overlay";
let curtain = false;
let quitting = false;

// Stage 5: the recall timeline. A normal, focusable window (unlike the overlay),
// frameless with its own drag bar, same page bundle at #timeline. D31: the same
// window has an Insights view (#insights), and can open at a moment (?ts=).
function openTimeline(view, params) {
  view = ["insights", "memory", "settings"].includes(view) ? view : "timeline";
  const p = params || {};
  const deep = {};                                   // only what the page understands
  if (Number.isFinite(Number(p.ts)) && p.ts) deep.ts = String(Number(p.ts));
  if (/^\d{4}-\d{2}-\d{2}$/.test(p.day || "")) deep.day = p.day;
  if (typeof p.q === "string" && p.q) deep.q = p.q.slice(0, 200);
  if (typeof p.filter === "string") deep.filter = p.filter.slice(0, 60);
  target = "timeline";
  if (timeline && !timeline.isDestroyed()) {
    timeline.webContents.send("event", { type: "goto", view, ...deep });
    timeline.show();
    timeline.focus();
    return timeline;
  }
  timeline = new BrowserWindow({
    width: 1180, height: 760, minWidth: 820, minHeight: 540,
    frame: false,
    backgroundColor: "#0a0a0a",
    title: "Jimmy · Timeline",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  const q = process.env.JIMMY_TIMELINE_QUERY;
  if (q && !deep.q) deep.q = q;
  const qs = new URLSearchParams(deep).toString();
  timeline.loadFile(path.join(__dirname, "dist", "index.html"), { hash: qs ? `${view}?${qs}` : view });
  timeline.once("ready-to-show", () => timeline.show());
  // Its page errors reach the log too, like the overlay's (D26); a blank Settings tab said nothing (D60).
  timeline.webContents.on("console-message", (e, ...args) => {
    const level = e.level ?? args[0];
    const message = e.message ?? args[1];
    if (level === "error" || level === "warning" || level >= 2) console.error(`[timeline page] ${message}`);
  });
  timeline.on("focus", () => { target = "timeline"; });
  timeline.on("close", (e) => {
    if (quitting) return;
    e.preventDefault();          // D38: keep it for next time (~0.5-1 s to rebuild)
    timeline.hide();
    target = "overlay";
  });
  timeline.on("closed", () => { target = "overlay"; });
  return timeline;
}

async function get(route, params) {
  if (!API) return null;
  const qs = new URLSearchParams(params || {}).toString();
  const res = await fetch(`${API}/${route}${qs ? `?${qs}` : ""}`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  return res.ok ? res.json() : null;
}

// Only pages Jimmy saw in a browser's address bar, and only web links.
function openUrl(url) {
  if (typeof url === "string" && /^https?:\/\/[^\s]+$/i.test(url)) shell.openExternal(url);
}

function send(event) {
  if (event.type === "vitals") {                     // D66: plus the overlay's own processes
    const ms = app.getAppMetrics();
    const cores = require("os").cpus().length || 1;
    event = { ...event, ui_cpu: Math.round((10 * ms.reduce((a, m) => a + (m.cpu?.percentCPUUsage || 0), 0)) / cores) / 10,
              ui_ram_mb: Math.round(ms.reduce((a, m) => a + (m.memory?.workingSetSize || 0), 0) / 1024) };
  }
  if (event.type === "open_view") return openTimeline(event.view, event);   // "Jimmy, open insights"
  if (event.type === "open_url") return openUrl(event.url);                  // "Jimmy, open that page"
  if (event.type === "copy") clipboard.writeText(String(event.text || "").slice(0, 20_000));   // drafts
  if (["answer_start", "open_evidence", "card"].includes(event.type)) target = "overlay";
  if (event.type === "presence" || event.type === "state") {
    const on = !!event.curtain;
    if (on !== curtain && win && !win.isDestroyed()) {
      curtain = on;
      // Down: cover the whole display, taskbar included. Up: back to the work area.
      const d = screen.getPrimaryDisplay();
      win.setBounds(on ? d.bounds : d.workArea);
    }
  }
  if (event.type === "close_all" && timeline && !timeline.isDestroyed()) timeline.close();   // D35
  // D41: the Memory tab follows changes made by voice.
  if (event.type === "memory_changed" && timeline && !timeline.isDestroyed()) timeline.webContents.send("event", event);
  // D41: the virtual cursor. UI Automation gives physical pixels; the page draws in
  // DIPs, relative to the overlay window.
  if (event.type === "cursor" && Array.isArray(event.rect) && win && !win.isDestroyed()) {
    const [l, t, r, b] = event.rect;
    const d = screen.screenToDipRect(null, { x: l, y: t, width: r - l, height: b - t });
    const wb = win.getBounds();
    event = { ...event, box: [d.x - wb.x, d.y - wb.y, d.width, d.height] };
  }
  // D40: history was deleted. The timeline window only ever hides, so it still held the
  // deleted days and pictures; the next open builds it fresh.
  if (event.type === "data_changed" && timeline && !timeline.isDestroyed()) { timeline.destroy(); return; }
  // Navigation goes to the timeline only while you're in it; after you click back into
  // another app, "scroll down" means that app (D35).
  if (event.type === "ui" && target === "timeline" && timeline && !timeline.isDestroyed() && timeline.isFocused()) {
    return timeline.webContents.send("event", event);
  }
  if (win && !win.isDestroyed()) win.webContents.send("event", event);
}

// D68: Jimmy's Python is gone without closing us (a quit closes the overlay first): it crashed.
// The installed app starts itself again, at most 3 times an hour, so a crash loop ends.
function restartJimmy() {
  if (app.isPackaged) {
    const f = path.join(app.getPath("userData"), "restarts.json");
    let times = [];
    try { times = JSON.parse(fs.readFileSync(f, "utf8")).filter((t) => Date.now() - t < 3600_000); } catch { /* first */ }
    if (times.length < 3) {
      try { fs.writeFileSync(f, JSON.stringify([...times, Date.now()])); } catch { /* still restart */ }
      const env = { ...process.env };
      delete env.JIMMY_OVERLAY_URL;                 // without these, Jimmy.exe is the launcher
      delete env.JIMMY_OVERLAY_TOKEN;
      require("child_process").spawn(process.execPath, [], { detached: true, stdio: "ignore", env }).unref();
    }
  }
  app.quit();
}

async function call(route, body) {
  if (DEMO || !API) return null;
  const res = await fetch(`${API}/${route}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(`${route}: HTTP ${res.status}`);
  const state = await res.json();
  if (!/^(settings|storage)/.test(route)) send({ type: "state", ...state });   // D60: Settings' replies aren't state
  return state;
}

// Server-Sent Events from Python, re-dialled if the connection drops. If Python is
// gone for good (capture stopped), the overlay quits with it.
async function listen() {
  let failures = 0;
  while (true) {
    try {
      const res = await fetch(`${API}/events`, { headers: { Authorization: `Bearer ${TOKEN}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      failures = 0;
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          for (const line of chunk.split("\n")) {
            if (line.startsWith("data: ")) {
              try { send(JSON.parse(line.slice(6))); } catch { /* ignore a malformed event */ }
            }
          }
        }
      }
    } catch {
      failures += 1;
    }
    if (failures > 10) return restartJimmy();      // ~15 s of nothing: capture has stopped
    await new Promise((r) => setTimeout(r, 1500));
  }
}

// D56/D57: --demo-ui <template> shows one Intelligent UI card on invented data, for a
// snapshot (README images are never real captures).
const demoUiAt = process.argv.indexOf("--demo-ui");
const DEMO_UI = demoUiAt > -1 ? process.argv[demoUiAt + 1] : null;
const DEMO_CARDS = {
  steps: { template: "steps", data: { title: "", steps: ["Type “carryminati” in the search box", "Press Enter",
    "Open the Videos tab"], status: ["done", "done", "running"], state: "running", auto: true } },
  choice: { template: "choice", data: { question: "Which one?", options: ["Search (box)", "Search (button)", "Search settings"] } },
  confirm: { template: "confirm", data: { what: "Close Spotify?", why: "", yes: "Do it", no: "Cancel" } },
  table: { template: "table", data: { title: "Trains to Pune tomorrow", columns: ["Train", "Leaves", "Arrives", "Fare"],
    rows: [["Deccan Queen", "17:10", "20:25", "₹ 245"], ["Intercity", "06:40", "09:57", "₹ 180"],
           ["Pragati", "16:25", "19:50", "₹ 210"]] } },
  checklist: { template: "checklist", data: { title: "Clear the DNS cache", items: ["Open Terminal as admin",
    "Run ipconfig /flushdns", "Restart the browser"] } },
  chart: { template: "chart", data: { title: "This week", unit: "h", bars: [{ label: "VS Code", value: 14.5 },
    { label: "Chrome", value: 9 }, { label: "Discord", value: 3.2 }, { label: "Spotify", value: 1 }] } },
  list: { template: "list", data: { title: "Reminders", items: [{ text: "Call the bank", note: "today 17:00" },
    { text: "Submit the form", note: "Fri" }], more: 0 } },
};
const DEMO_SAY = { steps: "", choice: "Which one: “Search (box)”, “Search (button)” or “Search settings”?",
  confirm: "Close Spotify? Careful: that may not be undoable.", table: "Three trains tomorrow; the Deccan Queen is fastest.",
  checklist: "Three steps; tick them off as you go.", chart: "Mostly VS Code this week.", list: "You have two reminders." };

// D66: --demo-ui dock: the status dock open, on invented readings.
function demoDock() {
  send({ type: "state", paused: false, paused_until: 0, cards: true, timers: [] });
  const cpus = [3.1, 4.4, 2.2, 6.8, 12.5, 9.1, 4.2, 3.3, 2.9, 5.5, 18.2, 7.4, 3.8, 2.4, 3.0];
  let i = 0;
  const vitals = () => send({ type: "vitals", cpu: cpus[i++ % cpus.length], ram_mb: 1840, listen_until: Date.now() + 31_000,
    nav_until: Date.now() + 12_000, mic: { on: true, paused: false, call: [] },
    camera: { on: true, state: "present", why: "", contact: true, faces: 1 },
    capture: { paused: false, curtain: false, frames: 214 }, brain: { model: "gemini-3.5-flash-lite", online: true } });
  for (let k = 0; k < 14; k++) vitals();
  setInterval(vitals, 2000);
  setTimeout(() => win && !win.isDestroyed() && win.webContents.send("event", { type: "update", phase: "downloading",
    version: "1.0.2", latest: "1.0.3", progress: 0.62, checked: Date.now() - 60_000 }), 800);
  send({ type: "dock", open: true });
}

function demoUi(name) {
  if (name === "dock") return demoDock();
  send({ type: "state", paused: false, paused_until: 0, cards: true, timers: [] });
  if (name === "steps") { send({ type: "steps", ui: DEMO_CARDS.steps }); return; }
  const id = "demo-ui";
  send({ type: "answer_start", id, question: "Jimmy, " + { choice: "click search", confirm: "close spotify",
    table: "trains to pune tomorrow?", checklist: "how do I clear the DNS cache?", chart: "how was my week?",
    list: "what are my reminders?" }[name], source: "voice", mode: ["choice", "confirm"].includes(name) ? "ask" : "chat", history: [] });
  send({ type: "answer_evidence", id, mode: ["choice", "confirm"].includes(name) ? "ask" : "chat", evidence: [] });
  send({ type: "answer_delta", id, text: DEMO_SAY[name] });
  send({ type: "answer_end", id, awaiting: ["choice", "confirm"].includes(name) });
  send({ type: "answer_ui", id, ui: DEMO_CARDS[name] });
}

function demo() {
  if (DEMO_UI) return demoUi(DEMO_UI);
  const lines = [
    { kind: "RECALL", line: "Same Sunandha UI/UX resume as Tue 15:02" },
    { kind: "FOCUS", line: "Back to: apply for jobs and review" },
  ];
  send({ type: "state", paused: false, paused_until: 0, cards: true,
         timers: [{ id: 1, text: "check the oven, 10 min timer", due: Date.now() + 9 * 60_000 + 42_000 }] });
  send({ type: "presence", state: "present", curtain: false, contact: true });   // D39: looking at Jimmy
  let i = 0;
  const next = () => send({ type: "card", id: ++i, ts: Date.now(), ...lines[(i - 1) % lines.length] });
  setTimeout(next, 600);
  setTimeout(next, 1400);
  if (!SNAPSHOT) setInterval(next, 9000);
}

app.whenReady().then(() => {
  const { workArea } = screen.getPrimaryDisplay();
  win = new BrowserWindow({
    ...workArea,
    transparent: true,
    frame: false,
    resizable: false,
    movable: false,
    skipTaskbar: true,
    focusable: false,          // never steals focus from what the user is doing
    hasShadow: false,
    alwaysOnTop: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  win.setAlwaysOnTop(true, "screen-saver");
  win.setIgnoreMouseEvents(true, { forward: true }); // click-through until the pointer is on UI
  win.loadFile(path.join(__dirname, "dist", "index.html"));
  // Page errors surface in the `ambient run` terminal instead of vanishing (D26:
  // a render error once blanked the whole overlay and nothing said why).
  win.webContents.on("console-message", (e, ...args) => {
    const level = e.level ?? args[0];
    const message = e.message ?? args[1];
    if (level === "error" || level === "warning" || level >= 2) console.error(`[overlay page] ${message}`);
  });
  // D68: a crashed page used to stay blank until Jimmy was restarted by hand.
  win.webContents.on("render-process-gone", (_e, d) => {
    console.error(`[overlay page] crashed: ${d.reason}; reloading`);
    if (d.reason !== "clean-exit" && !win.isDestroyed()) setTimeout(() => !win.isDestroyed() && win.reload(), 1000);
  });

  win.webContents.once("did-finish-load", () => {
    win.showInactive();
    if (DEMO || !API) demo();
    else listen();
    if (SNAPSHOT && !OPEN_TIMELINE) {
      win.webContents.executeJavaScript(`window.__errs=[];addEventListener('error',e=>__errs.push(String(e.message)));
        addEventListener('unhandledrejection',e=>__errs.push('rejection: '+String(e.reason)));`);
      setTimeout(async () => {
        const probe = await win.webContents.executeJavaScript(
          `JSON.stringify({root: document.getElementById('root').innerHTML.length, errs: window.__errs,
            visible: document.visibilityState})`);
        console.error(`[snapshot] ${probe} window visible=${win.isVisible()}`);
        const img = await win.webContents.capturePage();
        fs.writeFileSync(SNAPSHOT, img.toPNG());
        app.quit();
      }, SNAP_DELAY);
    }
  });

  // D65: only on a change; every hover in and out of a child used to re-set the full-screen
  // window's hit-testing, which made the overlay sluggish.
  let overUi = null;
  ipcMain.on("pointer-over-ui", (_e, over) => {
    if (over === overUi) return;
    overUi = over;
    win.setIgnoreMouseEvents(!over, { forward: true });
  });
  ipcMain.handle("api", (_e, route, body) => call(route, body));
  // D60: Settings. Start with Windows (HKCU Run, the packaged exe only), the data folder,
  // and the onboarding again (change the profile, repair).
  ipcMain.handle("login-item", (_e, on) => {
    if (!app.isPackaged) return null;
    if (typeof on === "boolean") app.setLoginItemSettings({ openAtLogin: on, path: process.execPath });
    return app.getLoginItemSettings({ path: process.execPath }).openAtLogin;
  });
  ipcMain.on("open-data", (_e, dir) => { if (typeof dir === "string" && fs.existsSync(dir)) shell.openPath(dir); });
  ipcMain.on("run-setup", () => {
    if (!app.isPackaged) return;
    require("child_process").spawn(process.execPath, ["--onboarding"], { detached: true, stdio: "ignore",
      env: Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith("JIMMY_OVERLAY"))) }).unref();
  });
  ipcMain.handle("get", (_e, route, params) => get(route, params));
  ipcMain.on("open-timeline", (_e, view, params) => openTimeline(view, params));
  ipcMain.on("copy", (_e, text) => clipboard.writeText(String(text).slice(0, 20_000)));
  ipcMain.on("open-url", (_e, url) => openUrl(url));
  // Typing a question (D25) is the one time the overlay may take focus; it gives
  // it back as soon as the question is sent or dismissed.
  const focusAsk = () => {
    win.setFocusable(true);
    win.setIgnoreMouseEvents(false);
    win.focus();
    send({ type: "focus-ask" });
  };
  ipcMain.on("focus-ask", focusAsk);
  ipcMain.on("release-focus", () => {
    win.setFocusable(false);
    win.setIgnoreMouseEvents(true, { forward: true });
    win.blur();
  });
  globalShortcut.register("Control+Alt+Space", focusAsk);
  ipcMain.on("close-window", (e) => BrowserWindow.fromWebContents(e.sender)?.close());
  globalShortcut.register(HOTKEY, () => call("toggle-pause"));
  globalShortcut.register(TIMELINE_HOTKEY, () => openTimeline());
  globalShortcut.register(INSIGHTS_HOTKEY, () => openTimeline("insights"));
  globalShortcut.register(CURTAIN_HOTKEY, () => call("curtain", { on: !curtain }).catch(() => {}));

  if (OPEN_TIMELINE) {
    const t = openTimeline(process.argv.includes("--insights") ? "insights" : process.argv.includes("--memory") ? "memory"
      : process.argv.includes("--settings") ? "settings" : "timeline");
    if (SNAPSHOT) {
      t.webContents.once("did-finish-load", () => setTimeout(async () => {
        const img = await t.webContents.capturePage();
        fs.writeFileSync(SNAPSHOT, img.toPNG());
        app.quit();
      }, 4000));
    }
  }
});

app.on("before-quit", () => { quitting = true; });
// D64: updates. The installed overlay checks GitHub Releases 10 minutes after start and every 6 h;
// a newer setup is downloaded and verified in the background, then one notification: click to
// update now, otherwise the launcher installs it the next time Jimmy starts.
// D66: the status dock shows every step (checking, downloading %, ready) and has "Check now" and
// "Update now"; the first check is 2 minutes after start. A development copy says so.
const update = { phase: app.isPackaged ? "idle" : "dev", version: app.getVersion(), checked: 0 };
let pendingUpdate = null;
function setUpdate(patch) {
  Object.assign(update, patch, patch.phase && patch.phase !== "downloading" ? { progress: undefined } : {});
  if (win && !win.isDestroyed()) win.webContents.send("event", { type: "update", ...update });
}
if (app.isPackaged && API) {
  const updater = require("./updater.cjs");
  const { Notification } = require("electron");
  let told = "", busy = false;
  const install = () => {
    if (!pendingUpdate) return false;
    setUpdate({ phase: "installing" });
    updater.apply(pendingUpdate, updater.dataDir(), path.dirname(process.execPath));
    setTimeout(() => app.exit(0), 1200);           // the dock shows "installing" first
    return true;
  };
  const check = () => {
    if (busy) return;
    busy = true;
    const data = updater.dataDir();
    updater.check({ version: app.getVersion(), data, log: (s) => console.log(s), state: setUpdate }).then((p) => {
      setUpdate({ checked: Date.now() });
      pendingUpdate = p;
      if (!p || told === p.version || !Notification.isSupported()) return;
      told = p.version;
      const n = new Notification({ title: `Jimmy ${p.version} is ready`,
        body: "Click to update now (Jimmy restarts in a minute), or it installs the next time Jimmy starts." });
      n.on("click", install);
      n.show();
    }).catch((e) => {
      console.log(`[update] check failed: ${e.message}`);
      setUpdate({ phase: "error", error: "couldn't reach GitHub", checked: Date.now() });
    }).finally(() => { busy = false; });
  };
  ipcMain.on("update-check", check);
  ipcMain.on("update-now", install);
  app.whenReady().then(() => {
    app.setAppUserModelId("dev.jimmy.ambient");      // the toast's sender, as the Start menu shortcut names it
    setTimeout(check, 2 * 60 * 1000);
    setInterval(check, 6 * 60 * 60 * 1000);
  });
}
ipcMain.handle("update-state", () => ({ type: "update", ...update }));

app.on("will-quit", () => globalShortcut.unregisterAll());
app.on("window-all-closed", () => app.quit());
