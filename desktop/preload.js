// Минимальный мост между окном и главным процессом.
// Ключи модели сюда не попадают: только адрес сервера и одноразовый токен сессии.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("jarvis", {
  session: () => ipcRenderer.invoke("jarvis:session"),
  hide: () => ipcRenderer.invoke("jarvis:hide"),
  openExternal: (url) => ipcRenderer.invoke("jarvis:open-external", url),
  onFocusInput: (callback) => {
    const handler = () => callback();
    ipcRenderer.on("focus-input", handler);
    return () => ipcRenderer.removeListener("focus-input", handler);
  },
});
