// Настройки приложения. Файл лежит в data/settings.json и не попадает в git.

const fs = require("node:fs");
const path = require("node:path");

const MODELS = [
  { id: "deepseek-v4.1-flash", label: "DEEPSEEK V4.1 Flash" },
  { id: "glm-5.3-flash", label: "GLM 5.3 Flash" },
  { id: "gpt-6-luna", label: "GPT 6 Luna" },
  { id: "claude-haiku-5.5", label: "Haiku 5.5" },
];
const MODEL_IDS = new Set(MODELS.map((item) => item.id));
const PROMPT_LIMIT = 20_000;

const DEFAULTS = {
  hotkey: "CommandOrControl+Space",
  autostart: false,
  budget_limit_rub: 500,
  voice_language: "ru",
  model: "claude-haiku-5.5",
  system_prompt: "",
  theme: "light",
};

function settingsPath(projectRoot) {
  return path.join(projectRoot, "data", "settings.json");
}

function readDefaultPrompt(projectRoot) {
  try {
    return fs.readFileSync(
      path.join(projectRoot, "prompts", "omega.md"),
      "utf8",
    ).trim();
  } catch {
    return "";
  }
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
  const model = MODEL_IDS.has(source.model)
    ? source.model
    : MODEL_IDS.has(base.model)
      ? base.model
      : DEFAULTS.model;
  const hasPrompt = Object.prototype.hasOwnProperty.call(source, "system_prompt");
  const systemPrompt = hasPrompt
    ? typeof source.system_prompt === "string"
      ? source.system_prompt.trim().slice(0, PROMPT_LIMIT)
      : ""
    : typeof base.system_prompt === "string"
      ? base.system_prompt
      : "";
  const theme =
    source.theme === "dark" || source.theme === "light"
      ? source.theme
      : base.theme === "dark"
        ? "dark"
        : "light";
  return {
    hotkey,
    autostart: Boolean(source.autostart),
    budget_limit_rub: budget,
    voice_language: voiceLanguage,
    model,
    system_prompt: systemPrompt,
    theme,
  };
}

function loadSettings(projectRoot, legacyHotkey = "") {
  const file = settingsPath(projectRoot);
  const defaults = {
    ...DEFAULTS,
    hotkey: legacyHotkey || DEFAULTS.hotkey,
    system_prompt: readDefaultPrompt(projectRoot),
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
  if (!settings.system_prompt) {
    settings.system_prompt = readDefaultPrompt(projectRoot);
  }
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
  if (!clean.system_prompt) {
    clean.system_prompt = readDefaultPrompt(projectRoot);
  }
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.tmp`;
  fs.writeFileSync(temp, `${JSON.stringify(clean, null, 2)}\n`, "utf8");
  fs.renameSync(temp, file);
  return clean;
}

module.exports = {
  DEFAULTS,
  MODELS,
  loadSettings,
  saveSettings,
  sanitizeSettings,
  settingsPath,
};
