// The only bridge the pages get: events in, a few actions and reads out.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jimmy", {
  onEvent: (cb) => ipcRenderer.on("event", (_e, ev) => cb(ev)),
  api: (route, body) => ipcRenderer.invoke("api", route, body),
  get: (route, params) => ipcRenderer.invoke("get", route, params),
  pointerOverUi: (over) => ipcRenderer.send("pointer-over-ui", over),
  openTimeline: () => ipcRenderer.send("open-timeline"),
  closeWindow: () => ipcRenderer.send("close-window"),
  focusAsk: () => ipcRenderer.send("focus-ask"),
  releaseFocus: () => ipcRenderer.send("release-focus"),
});
