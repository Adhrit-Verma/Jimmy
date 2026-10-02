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
  view = view === "insights" ? "insights" : "timeline";
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
  // Navigation goes to the timeline only while you're in it; after you click back into
  // another app, "scroll down" means that app (D35).
  if (event.type === "ui" && target === "timeline" && timeline && !timeline.isDestroyed() && timeline.isFocused()) {
    return timeline.webContents.send("event", event);
  }
  if (win && !win.isDestroyed()) win.webContents.send("event", event);
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
  send({ type: "state", ...state });
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
    if (failures > 10) return app.quit();          // ~15 s of nothing: capture has stopped
    await new Promise((r) => setTimeout(r, 1500));
  }
}

function demo() {
  const lines = [
    { kind: "RECALL", line: "Same Sunandha UI/UX resume as Tue 15:02" },
    { kind: "FOCUS", line: "Back to: apply for jobs and review" },
  ];
  send({ type: "state", paused: false, paused_until: 0, cards: true });
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
  win.webContents.on("render-process-gone", (_e, d) => console.error(`[overlay page] crashed: ${d.reason}`));

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

  ipcMain.on("pointer-over-ui", (_e, over) => win.setIgnoreMouseEvents(!over, { forward: true }));
  ipcMain.handle("api", (_e, route, body) => call(route, body));
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
    const t = openTimeline(process.argv.includes("--insights") ? "insights" : "timeline");
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
app.on("will-quit", () => globalShortcut.unregisterAll());
app.on("window-all-closed", () => app.quit());
