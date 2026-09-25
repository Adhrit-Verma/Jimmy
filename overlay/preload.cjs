// The only bridge the overlay page gets: events in, three actions out.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jimmy", {
  onEvent: (cb) => ipcRenderer.on("event", (_e, ev) => cb(ev)),
  api: (route, body) => ipcRenderer.invoke("api", route, body),
  pointerOverUi: (over) => ipcRenderer.send("pointer-over-ui", over),
});
