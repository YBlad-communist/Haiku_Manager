// Минимальный мост между окном и главным процессом.
// Ключи модели сюда не попадают: только адрес сервера и одноразовый токен сессии.

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("omega", {
  session: () => ipcRenderer.invoke("omega:session"),
  hide: () => ipcRenderer.invoke("omega:hide"),
  openExternal: (url) => ipcRenderer.invoke("omega:open-external", url),
  getSettings: () => ipcRenderer.invoke("omega:get-settings"),
  saveSettings: (patch) => ipcRenderer.invoke("omega:save-settings", patch),
  getPromptInfo: () => ipcRenderer.invoke("omega:prompt-info"),
  onFocusInput: (callback) => {
    const handler = () => callback();
    ipcRenderer.on("focus-input", handler);
    return () => ipcRenderer.removeListener("focus-input", handler);
  },
  onOpenSettings: (callback) => {
    const handler = () => callback();
    ipcRenderer.on("open-settings", handler);
    return () => ipcRenderer.removeListener("open-settings", handler);
  },
  onSettingsChanged: (callback) => {
    const handler = (_event, settings) => callback(settings);
    ipcRenderer.on("settings-changed", handler);
    return () => ipcRenderer.removeListener("settings-changed", handler);
  },
});
