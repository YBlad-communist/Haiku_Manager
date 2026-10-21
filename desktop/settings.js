// Настройки приложения. Файл лежит в data/settings.json и не попадает в git.

const fs = require("node:fs");
const path = require("node:path");

const DEFAULTS = {
  hotkey: "CommandOrControl+Space",
  autostart: false,
  budget_limit_rub: 500,
  allowed_folders: [],
  allowed_apps: [],
};

function settingsPath(projectRoot) {
  return path.join(projectRoot, "data", "settings.json");
}

function cleanStringList(value, limit = 100) {
  if (!Array.isArray(value)) {
    return [];
  }
  const result = [];
  for (const item of value) {
    if (typeof item !== "string") {
      continue;
    }
    const text = item.trim();
    if (text && !result.includes(text)) {
      result.push(text);
    }
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
  return {
    hotkey,
    autostart: Boolean(source.autostart),
    budget_limit_rub: budget,
    allowed_folders: cleanStringList(source.allowed_folders),
    allowed_apps: cleanStringList(source.allowed_apps),
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
  loadSettings,
  saveSettings,
  sanitizeSettings,
  settingsPath,
};
