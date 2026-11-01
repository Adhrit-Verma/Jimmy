// The onboarding page's only bridge (D61): checks, a folder picker, key tests, the
// provisioner's progress, and finish. No Node, no network in the page itself.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jimmySetup", {
  checks: () => ipcRenderer.invoke("setup:checks"),
  pickFolder: (start) => ipcRenderer.invoke("setup:pick-folder", start),
  testKey: (provider, key) => ipcRenderer.invoke("setup:test-key", provider, key),
  provision: (opts) => ipcRenderer.invoke("setup:provision", opts),
  finish: (opts) => ipcRenderer.invoke("setup:finish", opts),
  open: (what) => ipcRenderer.send("setup:open", what),
  quit: () => ipcRenderer.send("setup:quit"),
  minimize: () => ipcRenderer.send("setup:minimize"),
  onEvent: (cb) => {
    const h = (_e, ev) => cb(ev);
    ipcRenderer.on("setup:event", h);
    return () => ipcRenderer.removeListener("setup:event", h);
  },
});
