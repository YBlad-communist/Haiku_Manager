// Настройки приложения. Файл лежит в data/settings.json и не попадает в git.

const fs = require("node:fs");
const path = require("node:path");

const DEFAULTS = {
  hotkey: "CommandOrControl+Space",
  autostart: false,
  budget_limit_rub: 500,
  voice_language: "ru",
  allowed_folders: [],
  allowed_apps: [],
};

function settingsPath(projectRoot) {
  return path.join(projectRoot, "data", "settings.json");
}

function cleanPathList(value, limit = 50) {
  if (!Array.isArray(value)) {
    return [];
  }
  const result = [];
  const seen = new Set();
  for (const item of value) {
    if (typeof item !== "string") {
      continue;
    }
    const raw = item.trim();
    if (!raw || !path.isAbsolute(raw)) {
      continue;
    }
    let text = path.normalize(raw);
    const root = path.parse(text).root;
    if (text.length > root.length) {
      text = text.replace(/[\\/]+$/, "");
    }
    const key = process.platform === "win32" ? text.toLowerCase() : text;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(text);
    if (result.length >= limit) {
      break;
    }
  }
  return result;
}

function sanitizeSettings(value, base = DEFAULTS) {
  const source = value && typeof value === "object" ? value : {};
  const hotkey =
    typeof source.hotkey === "string" && source.hotkey.trim()
      ? source.hotkey.trim().slice(0, 120)
      : base.hotkey;
  let budget = Number(source.budget_limit_rub);
  if (!Number.isFinite(budget)) {
    budget = base.budget_limit_rub;
  }
  budget = Math.min(1_000_000, Math.max(0, Math.round(budget * 100) / 100));
  const voiceLanguage = ["ru", "en", "auto"].includes(source.voice_language)
    ? source.voice_language
    : base.voice_language || "ru";
  return {
    hotkey,
    autostart: Boolean(source.autostart),
    budget_limit_rub: budget,
    voice_language: voiceLanguage,
    allowed_folders: cleanPathList(source.allowed_folders),
    allowed_apps: cleanPathList(source.allowed_apps),
  };
}

function loadSettings(projectRoot, legacyHotkey = "") {
  const file = settingsPath(projectRoot);
  const defaults = {
    ...DEFAULTS,
    hotkey: legacyHotkey || DEFAULTS.hotkey,
  };
  let parsed = null;
  try {
    parsed = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") {
      console.error("Не удалось прочитать data/settings.json:", error.message);
    }
  }
  const settings = sanitizeSettings(parsed || {}, defaults);
  if (!parsed) {
    try {
      saveSettings(projectRoot, settings);
    } catch (error) {
      console.error("Не удалось создать data/settings.json:", error.message);
    }
  }
  return settings;
}

function saveSettings(projectRoot, settings) {
  const file = settingsPath(projectRoot);
  const clean = sanitizeSettings(settings);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.tmp`;
  fs.writeFileSync(temp, `${JSON.stringify(clean, null, 2)}\n`, "utf8");
  fs.renameSync(temp, file);
  return clean;
}

module.exports = {
  DEFAULTS,
  cleanPathList,
  loadSettings,
  saveSettings,
  sanitizeSettings,
  settingsPath,
};
