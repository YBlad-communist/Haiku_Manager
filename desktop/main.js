// Главный процесс Electron: запускает Python-сервер, создаёт окно,
// держит горячую клавишу и гасит сервер вместе с воркером при выходе.

const {
  app,
  BrowserWindow,
  dialog,
  globalShortcut,
  ipcMain,
  Menu,
  session,
  shell,
} = require("electron");
const { execFileSync, spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "..");
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

if (process.platform === "win32") {
  app.setAppUserModelId("ru.haiku.jarvis");
}

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
let serverProcess = null;
let serverOutput = "";
let apiBase = "";
let isQuitting = false;
let shutdownPromise = null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function startServer() {
  return new Promise((resolve, reject) => {
    let settled = false;
    const script = path.join(__dirname, "server", "app.py");
    const env = {
      ...process.env,
      JARVIS_TOKEN: TOKEN,
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
        const match = /^JARVIS_PORT=(\d+)$/.exec(line.trim());
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
        app.quit();
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
    title: "Джарвис",
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
    mainWindow.show();
    mainWindow.focus();
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

function showWindow() {
  if (!mainWindow) {
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
  mainWindow.webContents.send("focus-input");
}

function registerHotkey() {
  try {
    const ok = globalShortcut.register(CONFIG.hotkey, showWindow);
    if (!ok) {
      console.warn(`Не удалось зарегистрировать горячую клавишу ${CONFIG.hotkey}`);
    }
  } catch (error) {
    console.warn("Ошибка горячей клавиши:", error.message);
  }
}

function isHttpUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

function registerIpc() {
  ipcMain.handle("jarvis:session", (event) => {
    if (!mainWindow || event.sender !== mainWindow.webContents) {
      return null;
    }
    return { apiBase, token: TOKEN };
  });

  ipcMain.handle("jarvis:hide", (event) => {
    if (mainWindow && event.sender === mainWindow.webContents) {
      mainWindow.hide();
    }
  });

  ipcMain.handle("jarvis:open-external", async (event, url) => {
    if (!mainWindow || event.sender !== mainWindow.webContents) {
      return false;
    }
    if (!isHttpUrl(url)) {
      return false;
    }
    await shell.openExternal(url);
    return true;
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

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    showWindow();
  });

  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);

    session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => {
      callback(false);
    });
    session.defaultSession.setPermissionCheckHandler(() => false);

    registerIpc();

    try {
      const port = await startServer();
      apiBase = `http://127.0.0.1:${port}`;
      await waitForServer();
      createWindow();
      registerHotkey();
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
    app.quit();
  });

  app.on("before-quit", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    isQuitting = true;
    shutdownServer()
      .catch(() => {})
      .finally(() => app.quit());
  });

  app.on("will-quit", () => {
    globalShortcut.unregisterAll();
    killServerTree(serverProcess);
  });
}
