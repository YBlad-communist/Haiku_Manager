// Главный процесс Electron: запускает Python-сервер, создаёт окно и трей,
// держит горячую клавишу и гасит сервер вместе с воркером при выходе.

const {
  app,
  BrowserWindow,
  dialog,
  globalShortcut,
  ipcMain,
  Menu,
  nativeImage,
  session,
  shell,
  Tray,
} = require("electron");
const { execFileSync, spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {
  MODELS,
  PROMPT_LIMIT,
  loadSettings,
  readDefaultPrompt,
  sanitizeSettings,
  saveSettings,
} = require("./settings");

const PROJECT_ROOT = path.resolve(__dirname, "..");

function readTextFile(file) {
  try {
    return fs.readFileSync(file, "utf8").trim();
  } catch {
    return "";
  }
}
const DEFAULT_CONFIG = {
  hotkey: "CommandOrControl+Space",
  python: { command: "py", args: ["-3.14"] },
};

function readConfig() {
  const file = path.join(__dirname, "config.json");
  try {
    const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
    const python =
      parsed && typeof parsed.python === "object" && parsed.python !== null
        ? parsed.python
        : {};
    const command =
      typeof python.command === "string" && python.command.trim()
        ? python.command.trim()
        : DEFAULT_CONFIG.python.command;
    const args = Array.isArray(python.args)
      ? python.args.filter((item) => typeof item === "string")
      : DEFAULT_CONFIG.python.args;
    return {
      hotkey:
        typeof parsed.hotkey === "string" && parsed.hotkey.trim()
          ? parsed.hotkey.trim()
          : DEFAULT_CONFIG.hotkey,
      python: { command, args },
    };
  } catch (error) {
    console.error("Не удалось прочитать desktop/config.json:", error.message);
    return DEFAULT_CONFIG;
  }
}

const CONFIG = readConfig();
const TOKEN = crypto.randomBytes(32).toString("hex");
const START_HIDDEN = process.argv.includes("--hidden");

app.setName("Омега");
if (process.platform === "win32") {
  app.setAppUserModelId("ru.haiku.omega");
}
try {
  const userData = path.join(app.getPath("appData"), "Omega");
  fs.mkdirSync(userData, { recursive: true });
  app.setPath("userData", userData);
} catch (error) {
  console.error("Не удалось задать папку данных Omega:", error.message);
}

let SETTINGS = loadSettings(PROJECT_ROOT, CONFIG.hotkey);

// py.exe на Windows запускает python.exe дочерним процессом. Если убить
// обёртку, сервер останется жить, поэтому сразу получаем путь к самому Python.
function resolvePython(config) {
  try {
    const resolved = execFileSync(
      config.python.command,
      [...config.python.args, "-c", "import sys; print(sys.executable)"],
      {
        cwd: PROJECT_ROOT,
        encoding: "utf8",
        windowsHide: true,
        timeout: 8000,
      },
    ).trim();
    if (resolved && fs.existsSync(resolved)) {
      return { command: resolved, args: [] };
    }
  } catch (error) {
    console.error("Не удалось определить путь Python:", error.message);
  }
  return config.python;
}

const PYTHON = resolvePython(CONFIG);

let mainWindow = null;
let tray = null;
let serverProcess = null;
let serverOutput = "";
let apiBase = "";
let isQuitting = false;
let shutdownPromise = null;
let currentHotkey = "";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function startServer() {
  return new Promise((resolve, reject) => {
    let settled = false;
    const script = path.join(__dirname, "server", "app.py");
    const env = {
      ...process.env,
      OMEGA_TOKEN: TOKEN,
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
    };

    try {
      serverProcess = spawn(
        PYTHON.command,
        [...PYTHON.args, script],
        {
          cwd: PROJECT_ROOT,
          env,
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
        },
      );
    } catch (error) {
      reject(error);
      return;
    }

    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error("Python-сервер не сообщил порт за 20 секунд."));
      }
    }, 20000);

    serverProcess.on("error", (error) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(
          new Error(
            `Не удалось запустить Python (${CONFIG.python.command}). ` +
              `Проверь desktop/config.json. ${error.message}`,
          ),
        );
      }
    });

    serverProcess.stdout.setEncoding("utf8");
    serverProcess.stdout.on("data", (chunk) => {
      serverOutput += chunk;
      const lines = serverOutput.split(/\r?\n/);
      serverOutput = lines.pop() || "";
      for (const line of lines) {
        const match = /^OMEGA_PORT=(\d+)$/.exec(line.trim());
        if (match && !settled) {
          settled = true;
          clearTimeout(timer);
          resolve(Number(match[1]));
        }
      }
    });

    serverProcess.stderr.setEncoding("utf8");
    serverProcess.stderr.on("data", (chunk) => {
      process.stderr.write(`[python] ${chunk}`);
    });

    serverProcess.on("exit", (code) => {
      serverProcess = null;
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(new Error(`Python-сервер завершился с кодом ${code}.`));
        return;
      }
      if (!isQuitting && mainWindow) {
        dialog.showErrorBox(
          "Сервер остановился",
          `Python-сервер завершился с кодом ${code}. Приложение будет закрыто.`,
        );
        requestQuit();
      }
    });
  });
}

async function waitForServer() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(`${apiBase}/api/health`, {
        headers: { Authorization: `Bearer ${TOKEN}` },
      });
      if (response.ok) {
        return true;
      }
    } catch {
      // Сервер ещё поднимается.
    }
    await sleep(250);
  }
  throw new Error("Сервер не ответил на проверку здоровья.");
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 960,
    height: 640,
    center: true,
    show: false,
    title: "Омега (Ω)",
    icon: path.join(__dirname, "assets", "icon.ico"),
    backgroundColor: "#E4DFF7",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });

  mainWindow.loadURL(`${apiBase}/index.html`);

  mainWindow.once("ready-to-show", () => {
    if (!START_HIDDEN && !isQuitting) {
      mainWindow.show();
      mainWindow.focus();
    }
  });

  mainWindow.on("close", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    mainWindow.hide();
  });

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));

  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(apiBase)) {
      event.preventDefault();
    }
  });

  mainWindow.webContents.on("console-message", (...args) => {
    const details =
      args[1] && typeof args[1] === "object"
        ? args[1]
        : {
            level: args[1],
            message: args[2],
            lineNumber: args[3],
            sourceId: args[4],
          };
    const level = details.level;
    const isError = level === "error" || level === 3;
    if (isError) {
      console.error(
        `[renderer] ${details.message} (${details.sourceId}:${details.lineNumber})`,
      );
    }
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function showWindow(focusInput = true) {
  if (!mainWindow) {
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
  if (focusInput) {
    mainWindow.webContents.send("focus-input");
  }
}

function sendOpenSettings() {
  if (mainWindow) {
    mainWindow.webContents.send("open-settings");
  }
}

function registerHotkey(accelerator) {
  if (!accelerator) {
    return false;
  }
  if (accelerator === currentHotkey) {
    return true;
  }
  let ok = false;
  try {
    ok = globalShortcut.register(accelerator, () => showWindow());
  } catch (error) {
    console.warn("Ошибка горячей клавиши:", error.message);
    ok = false;
  }
  if (!ok) {
    return false;
  }
  if (currentHotkey) {
    try {
      globalShortcut.unregister(currentHotkey);
    } catch {
      // Старое сочетание уже не зарегистрировано.
    }
  }
  currentHotkey = accelerator;
  return true;
}

function loginItemOptions(enabled) {
  if (app.isPackaged) {
    return {
      openAtLogin: enabled,
      path: process.execPath,
      args: ["--hidden"],
    };
  }
  const launcher = path.join(PROJECT_ROOT, "Омега.exe");
  if (fs.existsSync(launcher)) {
    return {
      openAtLogin: enabled,
      path: launcher,
      args: ["--hidden"],
    };
  }
  return {
    openAtLogin: enabled,
    path: process.execPath,
    args: [app.getAppPath(), "--hidden"],
  };
}

function applyAutostart(enabled) {
  try {
    const options = loginItemOptions(enabled);
    app.setLoginItemSettings(options);
    const actual = app.getLoginItemSettings({
      path: options.path,
      args: options.args,
    });
    return Boolean(actual.openAtLogin) === Boolean(enabled);
  } catch (error) {
    console.error("Не удалось изменить автозапуск:", error.message);
    return false;
  }
}

function broadcastSettings() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("settings-changed", SETTINGS);
  }
}

function updateSettings(patch) {
  const previous = SETTINGS;
  const candidate = sanitizeSettings({ ...SETTINGS, ...patch }, previous);

  if (
    candidate.hotkey !== previous.hotkey &&
    !registerHotkey(candidate.hotkey)
  ) {
    return {
      ok: false,
      error: `Сочетание ${candidate.hotkey} занято или не поддерживается. Оставил прежнее.`,
    };
  }

  const autostartChanged = candidate.autostart !== previous.autostart;
  if (autostartChanged && !applyAutostart(candidate.autostart)) {
    if (candidate.hotkey !== previous.hotkey) {
      registerHotkey(previous.hotkey);
    }
    return {
      ok: false,
      error: "Не удалось изменить автозапуск Windows.",
    };
  }

  try {
    SETTINGS = saveSettings(PROJECT_ROOT, candidate);
  } catch (error) {
    if (candidate.hotkey !== previous.hotkey) {
      registerHotkey(previous.hotkey);
    }
    if (autostartChanged) {
      applyAutostart(previous.autostart);
    }
    return { ok: false, error: `Не удалось сохранить настройки: ${error.message}` };
  }

  updateTrayMenu();
  broadcastSettings();
  return { ok: true, settings: SETTINGS };
}

function updateTrayMenu() {
  if (!tray) {
    return;
  }
  const menu = Menu.buildFromTemplate([
    {
      label: "Показать",
      click: () => showWindow(),
    },
    {
      label: "Настройки",
      click: () => {
        showWindow(false);
        sendOpenSettings();
      },
    },
    { type: "separator" },
    {
      label: "Автозапуск с Windows",
      type: "checkbox",
      checked: Boolean(SETTINGS.autostart),
      click: (item) => {
        const result = updateSettings({ autostart: item.checked });
        if (!result.ok) {
          item.checked = Boolean(SETTINGS.autostart);
          dialog.showErrorBox("Автозапуск", result.error);
          return;
        }
        if (mainWindow) {
          mainWindow.webContents.send("settings-changed", SETTINGS);
        }
      },
    },
    { type: "separator" },
    {
      label: "Выход",
      click: () => requestQuit(),
    },
  ]);
  tray.setContextMenu(menu);
}

function createTray() {
  const iconPath = path.join(__dirname, "assets", "tray-32.png");
  let image = nativeImage.createFromPath(iconPath);
  if (image.isEmpty()) {
    image = nativeImage.createFromPath(
      path.join(__dirname, "assets", "icon.ico"),
    );
  }
  tray = new Tray(image);
  tray.setToolTip("Омега (Ω)");
  tray.on("click", () => showWindow());
  tray.on("double-click", () => showWindow());
  updateTrayMenu();
}

function isHttpUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

function isMicrophonePermission(webContents, permission, details, requestingOrigin = "") {
  if (permission !== "media" || !mainWindow || !apiBase) {
    return false;
  }
  if (webContents !== mainWindow.webContents) {
    return false;
  }
  const source = String(details?.requestingUrl || requestingOrigin || "");
  if (source !== apiBase && !source.startsWith(`${apiBase}/`)) {
    return false;
  }
  const mediaTypes = details?.mediaTypes;
  if (Array.isArray(mediaTypes) && mediaTypes.some((type) => type !== "audio")) {
    return false;
  }
  if (details?.mediaType && details.mediaType !== "audio") {
    return false;
  }
  return true;
}

function registerIpc() {
  ipcMain.handle("omega:session", (event) => {
    if (!mainWindow || event.sender !== mainWindow.webContents) {
      return null;
    }
    return { apiBase, token: TOKEN };
  });

  ipcMain.handle("omega:hide", (event) => {
    if (mainWindow && event.sender === mainWindow.webContents) {
      mainWindow.hide();
    }
  });

  ipcMain.handle("omega:open-external", async (event, url) => {
    if (!mainWindow || event.sender !== mainWindow.webContents) {
      return false;
    }
    if (!isHttpUrl(url)) {
      return false;
    }
    await shell.openExternal(url);
    return true;
  });

  ipcMain.handle("omega:get-settings", (event) => {
    if (!mainWindow || event.sender !== mainWindow.webContents) {
      return null;
    }
    return SETTINGS;
  });

  ipcMain.handle("omega:save-settings", (event, patch) => {
    if (!mainWindow || event.sender !== mainWindow.webContents) {
      return { ok: false, error: "Нет доступа." };
    }
    if (!patch || typeof patch !== "object" || Array.isArray(patch)) {
      return { ok: false, error: "Неверные настройки." };
    }
    const allowed = {};
    for (const key of [
      "hotkey",
      "autostart",
      "budget_limit_rub",
      "voice_language",
      "sales_module",
      "model",
      "user_prompt",
      "theme",
    ]) {
      if (Object.prototype.hasOwnProperty.call(patch, key)) {
        allowed[key] = patch[key];
      }
    }
    return updateSettings(allowed);
  });

  ipcMain.handle("omega:prompt-info", (event) => {
    if (!mainWindow || event.sender !== mainWindow.webContents) {
      return null;
    }
    return {
      policy: readTextFile(path.join(PROJECT_ROOT, "prompts", "policy.md")),
      default_prompt: readDefaultPrompt(PROJECT_ROOT),
      limit: PROMPT_LIMIT,
      models: MODELS,
    };
  });
}

function killServerTree(proc) {
  if (!proc || proc.exitCode !== null) {
    return;
  }
  if (process.platform === "win32") {
    try {
      execFileSync("taskkill", ["/PID", String(proc.pid), "/T", "/F"], {
        stdio: "ignore",
        windowsHide: true,
        timeout: 5000,
      });
      return;
    } catch {
      // Если taskkill не сработал, пробуем обычный kill.
    }
  }
  try {
    proc.kill();
  } catch {
    // Процесс уже завершился.
  }
}

async function shutdownServer() {
  if (shutdownPromise) {
    return shutdownPromise;
  }
  shutdownPromise = (async () => {
    const proc = serverProcess;
    if (!apiBase || !proc) {
      return;
    }
    try {
      await fetch(`${apiBase}/api/shutdown`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${TOKEN}`,
          Origin: apiBase,
          "Content-Type": "application/json",
        },
        body: "{}",
      });
    } catch {
      // Сервер мог уже закрыться.
    }
    const exited = await Promise.race([
      new Promise((resolve) => proc.once("exit", () => resolve(true))),
      sleep(6000).then(() => false),
    ]);
    if (!exited && proc.exitCode === null) {
      killServerTree(proc);
    }
  })();
  return shutdownPromise;
}

function requestQuit() {
  if (isQuitting) {
    app.quit();
    return;
  }
  isQuitting = true;
  shutdownServer()
    .catch(() => {})
    .finally(() => app.quit());
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    showWindow();
  });

  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);

    session.defaultSession.setPermissionRequestHandler(
      (webContents, permission, callback, details) => {
        callback(isMicrophonePermission(webContents, permission, details));
      },
    );
    session.defaultSession.setPermissionCheckHandler(
      (webContents, permission, requestingOrigin, details) =>
        isMicrophonePermission(
          webContents,
          permission,
          details,
          requestingOrigin,
        ),
    );

    registerIpc();

    if (!applyAutostart(SETTINGS.autostart)) {
      console.warn("Не удалось применить настройку автозапуска.");
    }

    try {
      const port = await startServer();
      apiBase = `http://127.0.0.1:${port}`;
      await waitForServer();
      createWindow();
      createTray();
      if (!registerHotkey(SETTINGS.hotkey)) {
        console.warn(
          `Не удалось зарегистрировать горячую клавишу ${SETTINGS.hotkey}`,
        );
      }
    } catch (error) {
      dialog.showErrorBox(
        "Не удалось запустить помощника",
        `${error.message}\n\nПроверь .env и desktop/config.json.`,
      );
      isQuitting = true;
      await shutdownServer();
      app.quit();
    }
  });

  app.on("window-all-closed", () => {
    // Приложение живёт в трее, пока пользователь не выберет «Выход».
  });

  app.on("before-quit", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    requestQuit();
  });

  app.on("will-quit", () => {
    globalShortcut.unregisterAll();
    if (tray) {
      tray.destroy();
      tray = null;
    }
    killServerTree(serverProcess);
  });
}
