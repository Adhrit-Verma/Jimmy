// The only bridge the pages get: events in, a few actions and reads out.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jimmy", {
  // Returns an unsubscribe, so an effect can clean up after itself.
  onEvent: (cb) => {
    const h = (_e, ev) => cb(ev);
    ipcRenderer.on("event", h);
    return () => ipcRenderer.removeListener("event", h);
  },
  api: (route, body) => ipcRenderer.invoke("api", route, body),
  get: (route, params) => ipcRenderer.invoke("get", route, params),
  pointerOverUi: (over) => ipcRenderer.send("pointer-over-ui", over),
  openTimeline: (view, params) => ipcRenderer.send("open-timeline", view, params),
  closeWindow: () => ipcRenderer.send("close-window"),
  focusAsk: () => ipcRenderer.send("focus-ask"),
  releaseFocus: () => ipcRenderer.send("release-focus"),
  copy: (text) => ipcRenderer.send("copy", String(text)),
});
