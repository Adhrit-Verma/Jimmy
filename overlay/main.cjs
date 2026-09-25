// Jimmy overlay: Electron main process (Stage 4, D23).
//
// One transparent, click-through, always-on-top window over the primary display's
// work area: a pill at top-centre, cards at top-right. It never takes focus and has
// no taskbar entry. Only this process talks to the Python API (127.0.0.1 + token);
// the page has no network access and no Node, just the small bridge in preload.cjs.
//
// Flags: --demo (fake cards, no Python needed)  --snapshot <file.png> (render, save, quit)
const { app, BrowserWindow, screen, ipcMain, globalShortcut } = require("electron");
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
const OPEN_TIMELINE = process.argv.includes("--timeline");

let win = null;
let timeline = null;

// Stage 5: the recall timeline. A normal, focusable window (unlike the overlay),
// frameless with its own drag bar, same page bundle at #timeline.
function openTimeline() {
  if (timeline && !timeline.isDestroyed()) {
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
  timeline.loadFile(path.join(__dirname, "dist", "index.html"),
                    { hash: q ? `timeline?q=${encodeURIComponent(q)}` : "timeline" });
  timeline.once("ready-to-show", () => timeline.show());
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

function send(event) {
  if (win && !win.isDestroyed()) win.webContents.send("event", event);
}

async function call(route, body) {
  if (DEMO || !API) return null;
  const res = await fetch(`${API}/${route}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
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
  ipcMain.on("open-timeline", () => openTimeline());
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

  if (OPEN_TIMELINE) {
    const t = openTimeline();
    if (SNAPSHOT) {
      t.webContents.once("did-finish-load", () => setTimeout(async () => {
        const img = await t.webContents.capturePage();
        fs.writeFileSync(SNAPSHOT, img.toPNG());
        app.quit();
      }, 4000));
    }
  }
});

app.on("will-quit", () => globalShortcut.unregisterAll());
app.on("window-all-closed", () => app.quit());
