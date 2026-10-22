// Настройки приложения. Файл лежит в data/settings.json и не попадает в git.

const fs = require("node:fs");
const path = require("node:path");

const MODELS = [
  {
    id: "deepseek-v4.1-flash",
    label: "DEEPSEEK V4.1 Flash",
    tools: true,
    multiTurn: true,
    warning: "",
  },
  {
    id: "glm-5.3-flash",
    label: "GLM 5.3 Flash",
    tools: true,
    multiTurn: true,
    warning: "",
  },
  {
    id: "gpt-6-luna",
    label: "GPT 6 Luna",
    tools: true,
    multiTurn: true,
    warning: "",
  },
  {
    id: "claude-haiku-5.5",
    label: "Haiku 5.5",
    tools: true,
    multiTurn: true,
    warning: "",
  },
];
const MODEL_IDS = new Set(MODELS.map((item) => item.id));
const PROMPT_LIMIT = 4000;

const DEFAULTS = {
  hotkey: "CommandOrControl+Space",
  autostart: false,
  budget_limit_rub: 500,
  voice_language: "ru",
  sales_module: false,
  model: "claude-haiku-5.5",
  user_prompt: "",
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
  const salesModule =
    typeof source.sales_module === "boolean"
      ? source.sales_module
      : Boolean(base.sales_module);
  const model = MODEL_IDS.has(source.model)
    ? source.model
    : MODEL_IDS.has(base.model)
      ? base.model
      : DEFAULTS.model;
  const hasPrompt = Object.prototype.hasOwnProperty.call(source, "user_prompt");
  let userPrompt;
  if (hasPrompt) {
    userPrompt =
      typeof source.user_prompt === "string"
        ? source.user_prompt.trim().slice(0, PROMPT_LIMIT)
        : "";
  } else if (
    Object.prototype.hasOwnProperty.call(source, "system_prompt") &&
    typeof source.system_prompt === "string"
  ) {
    // Миграция со старой версии: старый полный промт становится редактируемой частью.
    const legacy = source.system_prompt.trim();
    const basePrompt =
      typeof base.system_prompt === "string" ? base.system_prompt.trim() : "";
    userPrompt = legacy && legacy !== basePrompt ? legacy.slice(0, PROMPT_LIMIT) : "";
  } else {
    userPrompt = typeof base.user_prompt === "string" ? base.user_prompt : "";
  }
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
    sales_module: salesModule,
    model,
    user_prompt: userPrompt,
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
  const hasLegacyPrompt =
    parsed && Object.prototype.hasOwnProperty.call(parsed, "system_prompt");
  if (!parsed || hasLegacyPrompt) {
    try {
      saveSettings(projectRoot, settings);
    } catch (error) {
      console.error("Не удалось сохранить data/settings.json:", error.message);
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
  MODELS,
  PROMPT_LIMIT,
  loadSettings,
  readDefaultPrompt,
  saveSettings,
  sanitizeSettings,
  settingsPath,
};
