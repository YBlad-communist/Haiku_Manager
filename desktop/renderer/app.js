// Логика окна. Ответы модели проходят через безопасный Markdown без сырого HTML.

const SVG_NS = "http://www.w3.org/2000/svg";

const state = {
  apiBase: "",
  token: "",
  running: false,
  maxSteps: 8,
  cost: 0,
  pending: null,
  editing: false,
  modalBusy: false,
  settings: null,
  settingsOpen: false,
  chatId: "",
  chats: [],
  recordingHotkey: false,
  settingsBusy: false,
  promptInfo: null,
  memory: [],
  memoryEnabled: true,
  reminders: [],
  editingMemoryId: null,
  voiceToken: 0,
  voiceRecording: false,
  voiceBusy: false,
  voiceChunks: [],
  voiceRecorder: null,
  voiceStream: null,
  voiceAudioContext: null,
  voiceAnalyser: null,
  voiceMeterSource: null,
  voiceMeterSink: null,
  voiceMeterFrame: 0,
  voiceTimer: null,
  voiceStartedAt: 0,
  voiceAbort: null,
  voices: [],
  speaking: false,
};

let currentCard = null;
let lastFocus = null;
let settingsLastFocus = null;
let toastTimer = null;

const els = {
  app: document.getElementById("app"),
  feed: document.getElementById("feed"),
  input: document.getElementById("input"),
  composer: document.getElementById("composer"),
  send: document.getElementById("send"),
  mic: document.getElementById("mic"),
  clipboardBtn: document.getElementById("clipboardBtn"),
  speakStop: document.getElementById("speakStop"),
  newTask: document.getElementById("newTask"),
  recent: document.getElementById("recent"),
  budgetValue: document.getElementById("budgetValue"),
  assistantTpl: document.getElementById("assistantTpl"),
  modal: document.getElementById("modal"),
  modalTitle: document.getElementById("modalTitle"),
  modalSubtitle: document.getElementById("modalSubtitle"),
  draftText: document.getElementById("draftText"),
  draftEdit: document.getElementById("draftEdit"),
  modalChips: document.getElementById("modalChips"),
  modalPreview: document.getElementById("modalPreview"),
  chipChannel: document.getElementById("chipChannel"),
  chipToday: document.getElementById("chipToday"),
  modalError: document.getElementById("modalError"),
  alwaysRow: document.getElementById("alwaysRow"),
  alwaysCheck: document.getElementById("alwaysCheck"),
  reject: document.getElementById("reject"),
  edit: document.getElementById("edit"),
  approve: document.getElementById("approve"),
  voice: document.getElementById("voice"),
  toast: document.getElementById("toast"),
  settingsBtn: document.getElementById("settingsBtn"),
  settings: document.getElementById("settings"),
  settingsClose: document.getElementById("settingsClose"),
  settingsDone: document.getElementById("settingsDone"),
  settingsError: document.getElementById("settingsError"),
  hotkeyInput: document.getElementById("hotkeyInput"),
  autostartToggle: document.getElementById("autostartToggle"),
  budgetInput: document.getElementById("budgetInput"),
  voiceLanguage: document.getElementById("voiceLanguage"),
  salesToggle: document.getElementById("salesToggle"),
  modelSelect: document.getElementById("modelSelect"),
  modelNote: document.getElementById("modelNote"),
  themeSelect: document.getElementById("themeSelect"),
  speechToggle: document.getElementById("speechToggle"),
  speechVoice: document.getElementById("speechVoice"),
  speechRate: document.getElementById("speechRate"),
  speechVolume: document.getElementById("speechVolume"),
  memoryToggle: document.getElementById("memoryToggle"),
  reminderList: document.getElementById("reminderList"),
  reminderEmpty: document.getElementById("reminderEmpty"),
  memoryList: document.getElementById("memoryList"),
  memoryEmpty: document.getElementById("memoryEmpty"),
  memoryExport: document.getElementById("memoryExport"),
  memoryClear: document.getElementById("memoryClear"),
  launchToggle: document.getElementById("launchToggle"),
  allowedApps: document.getElementById("allowedApps"),
  allowedAppsEmpty: document.getElementById("allowedAppsEmpty"),
  userPrompt: document.getElementById("userPrompt"),
  promptCounter: document.getElementById("promptCounter"),
  promptReset: document.getElementById("promptReset"),
  policyView: document.getElementById("policyView"),
  voiceCircle: document.getElementById("voiceCircle"),
  voiceBars: document.getElementById("voiceBars"),
  voiceTitle: document.getElementById("voiceTitle"),
  voiceText: document.getElementById("voiceText"),
  voiceTimer: document.getElementById("voiceTimer"),
  voiceHint: document.getElementById("voiceHint"),
  voiceStop: document.getElementById("voiceStop"),
  voiceRetry: document.getElementById("voiceRetry"),
  voiceCancel: document.getElementById("voiceCancel"),
};

const PROMPT_LIMIT = 4000;
const SPEECH_MAX_CHARS = 700;
const CLIPBOARD_MAX_CHARS = 20000;
const VOICE_MAX_MS = 60_000;
const VOICE_MIN_BYTES = 800;
const VOICE_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
];

const TOOL_LABELS = {
  search_web: "Ищу в интернете",
  fetch_page: "Читаю страницу",
  save_to_table: "Сохраняю таблицу",
  search_companies_2gis: "Ищу компании в 2ГИС",
  draft_message: "Готовлю черновик",
  send_message: "Проверяю отправку",
  list_files: "Смотрю файлы",
  read_file: "Читаю файл",
  write_file: "Записываю файл",
  create_folder: "Создаю папку",
  delete_files: "Удаляю в корзину",
  open_path: "Открываю папку",
  launch_app: "Запускаю программу",
  download_file: "Скачиваю файл",
  screenshot: "Делаю снимок экрана",
};

const markdown = window.markdownit
  ? window.markdownit({
      html: false,
      linkify: true,
      breaks: true,
      typographer: false,
    })
  : null;

const CALLOUTS = {
  важно: { className: "important", title: "Важно" },
  внимание: { className: "warning", title: "Внимание" },
  итог: { className: "summary", title: "Итог" },
  совет: { className: "tip", title: "Совет" },
};

const MARKDOWN_TAGS = [
  "p", "br", "strong", "em", "del", "code", "pre", "blockquote",
  "ul", "ol", "li", "a", "h1", "h2", "h3", "h4", "h5", "h6",
  "table", "thead", "tbody", "tr", "th", "td", "hr", "span",
];

if (window.DOMPurify) {
  window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName !== "A") {
      return;
    }
    const href = node.getAttribute("href") || "";
    if (!/^https?:\/\//i.test(href)) {
      node.removeAttribute("href");
      return;
    }
    node.setAttribute("data-external", "1");
    node.setAttribute("rel", "noreferrer noopener");
  });
}

function removeCalloutMarker(paragraph, marker) {
  let remaining = marker.length;
  const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node && remaining > 0) {
    const length = node.nodeValue.length;
    if (remaining >= length) {
      remaining -= length;
      node.nodeValue = "";
    } else {
      node.nodeValue = node.nodeValue.slice(remaining);
      remaining = 0;
    }
    node = walker.nextNode();
  }
  while (
    paragraph.firstChild &&
    (paragraph.firstChild.nodeName === "BR" ||
      (paragraph.firstChild.nodeType === Node.TEXT_NODE &&
        !paragraph.firstChild.nodeValue))
  ) {
    paragraph.firstChild.remove();
  }
  if (!paragraph.textContent.trim() && !paragraph.querySelector("*")) {
    paragraph.remove();
  }
}

function promoteCallout(blockquote) {
  const paragraph = blockquote.querySelector("p");
  if (!paragraph) {
    return;
  }
  const match = /^\s*\[!(важно|внимание|итог|совет)\]\s*/i.exec(paragraph.textContent);
  if (!match) {
    return;
  }
  const kind = CALLOUTS[match[1].toLowerCase()];
  if (!kind) {
    return;
  }
  removeCalloutMarker(paragraph, match[0]);
  blockquote.classList.add("callout", `callout-${kind.className}`);
  const title = document.createElement("p");
  title.className = "callout-title";
  title.textContent = kind.title;
  blockquote.prepend(title);
}

function enhanceCodeBlocks(container) {
  for (const pre of container.querySelectorAll("pre")) {
    if (pre.parentElement && pre.parentElement.classList.contains("code-block")) {
      continue;
    }
    const code = pre.querySelector("code");
    const languageMatch = code && /(?:^|\s)language-([\w-]+)/.exec(code.className);
    const language = languageMatch ? languageMatch[1] : "код";

    const wrapper = document.createElement("div");
    wrapper.className = "code-block";
    const head = document.createElement("div");
    head.className = "code-head";
    const label = document.createElement("span");
    label.className = "code-lang";
    label.textContent = language;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ci code-copy";
    button.textContent = "Копировать";
    head.append(label, button);
    pre.replaceWith(wrapper);
    wrapper.append(head, pre);
  }
}

function enhanceTables(container) {
  for (const table of container.querySelectorAll("table")) {
    if (table.parentElement && table.parentElement.classList.contains("table-wrap")) {
      continue;
    }
    const wrapper = document.createElement("div");
    wrapper.className = "table-wrap";
    table.replaceWith(wrapper);
    wrapper.append(table);
  }
}

function renderMarkdown(container, text) {
  const value = String(text || "");
  container.replaceChildren();
  if (!markdown || !window.DOMPurify) {
    renderTextWithLinks(container, value);
    return;
  }
  const clean = window.DOMPurify.sanitize(markdown.render(value), {
    ALLOWED_TAGS: MARKDOWN_TAGS,
    ALLOWED_ATTR: ["href", "title", "class", "data-external", "rel"],
    ALLOWED_URI_REGEXP: /^https?:\/\//i,
  });
  container.innerHTML = clean;
  for (const blockquote of container.querySelectorAll("blockquote")) {
    promoteCallout(blockquote);
  }
  enhanceCodeBlocks(container);
  enhanceTables(container);
  for (const link of container.querySelectorAll("a")) {
    if (!link.getAttribute("href")) {
      continue;
    }
    link.dataset.external = "1";
    link.rel = "noreferrer noopener";
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.className = "copy-helper";
    document.body.append(area);
    area.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    }
    area.remove();
    return copied;
  }
}

function syncInert() {
  els.app.inert = !els.modal.hidden || !els.settings.hidden || !els.voice.hidden;
}


function api(path) {
  return `${state.apiBase}${path}`;
}

function authHeaders(extra = {}) {
  return { Authorization: `Bearer ${state.token}`, ...extra };
}

async function apiJson(path, options = {}) {
  const response = await fetch(api(path), {
    ...options,
    headers: authHeaders({
      "Content-Type": "application/json",
      ...(options.headers || {}),
    }),
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.error || `Сервер ответил ${response.status}.`);
  }
  return data;
}

function formatRub(value, digits = 1) {
  const number = Number(value || 0);
  return `${number.toLocaleString("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} ₽`;
}

function formatCost(value) {
  return formatRub(value, 2);
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function truncate(text, limit = 34) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

function makeSvg(paths, size = 16) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  for (const pathData of paths) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", pathData);
    svg.append(path);
  }
  return svg;
}

function checkIcon() {
  return makeSvg(["M3.5 8.5l3 3 6-7"]);
}

function crossIcon() {
  return makeSvg(["M4 4l8 8", "M12 4l-8 8"]);
}

function showToast(message, action = null) {
  els.toast.replaceChildren();
  const text = document.createElement("span");
  text.textContent = message;
  els.toast.append(text);
  if (action && action.label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "toast-action";
    button.textContent = action.label;
    button.addEventListener("click", () => {
      els.toast.hidden = true;
      if (typeof action.run === "function") {
        action.run();
      }
    });
    els.toast.append(button);
  }
  els.toast.hidden = false;
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    els.toast.hidden = true;
  }, action ? 9000 : 2600);
}

function scrollFeed() {
  els.feed.scrollTop = els.feed.scrollHeight;
}

function addUserMessage(text) {
  const node = document.createElement("div");
  node.className = "user-msg";
  node.textContent = text;
  els.feed.append(node);
  scrollFeed();
}

function renderTextWithLinks(container, text) {
  const pattern = /https?:\/\/[^\s<>"']+/g;
  const value = String(text || "");
  let lastIndex = 0;
  let match = pattern.exec(value);
  while (match) {
    let url = match[0];
    let suffix = "";
    while (/[.,;:!?)]$/.test(url)) {
      suffix = url.slice(-1) + suffix;
      url = url.slice(0, -1);
    }
    if (match.index > lastIndex) {
      container.append(document.createTextNode(value.slice(lastIndex, match.index)));
    }
    const link = document.createElement("a");
    link.href = url;
    link.textContent = url;
    link.className = "link";
    link.dataset.external = "1";
    link.rel = "noreferrer noopener";
    container.append(link);
    if (suffix) {
      container.append(document.createTextNode(suffix));
    }
    lastIndex = match.index + match[0].length;
    match = pattern.exec(value);
  }
  container.append(document.createTextNode(value.slice(lastIndex)));
}

function createAssistantCard(title = "Работаю над задачей") {
  const node = els.assistantTpl.content.firstElementChild.cloneNode(true);
  const titleNode = node.querySelector(".assistant-title");
  titleNode.textContent = title;
  const stopButton = node.querySelector(".stop-btn:not(.msg-delete)");
  stopButton.hidden = true;
  const deleteButton = node.querySelector(".msg-delete");
  deleteButton.hidden = true;
  const refs = {
    card: node,
    title: titleNode,
    stop: stopButton,
    remove: deleteButton,
    steps: node.querySelector(".steps"),
    media: node.querySelector(".media"),
    foot: node.querySelector(".card-foot"),
    answer: node.querySelector(".answer"),
  };
  stopButton.addEventListener("click", stopTask);
  deleteButton.addEventListener("click", () => {
    if (deleteButton.dataset.messageId) {
      deleteMessage(deleteButton.dataset.chatId || state.chatId, deleteButton.dataset.messageId);
    }
  });
  els.feed.append(node);
  scrollFeed();
  return { refs, pending: [], finalReceived: false };
}

function setStepStatus(step, status, text) {
  step.icon.className = `step-icon ${status}`;
  step.icon.replaceChildren();
  if (status === "success") {
    step.icon.append(checkIcon());
  } else if (status === "error") {
    step.icon.append(crossIcon());
  } else {
    const dot = document.createElement("span");
    dot.className = "dot";
    step.icon.append(dot);
  }
  if (text !== undefined) {
    step.sub.textContent = text;
    step.sub.hidden = !text;
  }
}

function addPendingStep(label) {
  if (!currentCard) {
    return;
  }
  const row = document.createElement("div");
  row.className = "step";

  const icon = document.createElement("span");
  icon.className = "step-icon pending";
  const dot = document.createElement("span");
  dot.className = "dot";
  icon.append(dot);

  const body = document.createElement("div");
  body.className = "step-body";
  const text = document.createElement("p");
  text.className = "step-text";
  text.textContent = label;
  const sub = document.createElement("p");
  sub.className = "step-sub";
  sub.hidden = true;
  body.append(text, sub);
  row.append(icon, body);

  currentCard.refs.steps.append(row);
  const step = { row, icon, sub };
  currentCard.pending.push(step);
  scrollFeed();
}

function updateFooter(step, cost) {
  if (!currentCard) {
    return;
  }
  const stepNumber = Number(step || 0);
  currentCard.refs.foot.textContent =
    `Шаг ${stepNumber} из ${state.maxSteps} · ${formatCost(cost || 0)}`;
}

function finishPending(status = "success") {
  if (!currentCard) {
    return;
  }
  for (const step of currentCard.pending) {
    setStepStatus(step, status);
  }
  currentCard.pending = [];
}

function handleEvent(event) {
  if (!currentCard) {
    return;
  }
  if (event.type === "step") {
    state.maxSteps = Number(event.max_steps || state.maxSteps || 8);
    currentCard.refs.stop.hidden = false;
    updateFooter(event.step, state.cost);
    return;
  }
  if (event.type === "tool") {
    currentCard.refs.stop.hidden = false;
    addPendingStep(TOOL_LABELS[event.name] || event.name || "Инструмент");
    return;
  }
  if (event.type === "tool_result") {
    const step = currentCard.pending.shift();
    if (step) {
      setStepStatus(step, event.ok ? "success" : "error", String(event.summary || ""));
    }
    scrollFeed();
    return;
  }
  if (event.type === "usage") {
    state.cost = Number(event.cost || 0);
    if (!currentCard.finalReceived) {
      updateFooter(event.step, state.cost);
    }
    return;
  }
  if (event.type === "confirm") {
    openConfirm(event);
    return;
  }
  if (event.type === "screenshot") {
    showScreenshot(event);
    return;
  }
  if (event.type === "draft_edited") {
    showToast("Текст черновика изменён.");
    return;
  }
  if (event.type === "final") {
    finishCard(event);
  }
}

async function showScreenshot(event) {
  const name = String(event.file || "");
  if (!name || !currentCard || !currentCard.refs.media) {
    return;
  }
  try {
    const response = await fetch(api(`/api/screenshot?name=${encodeURIComponent(name)}`), {
      headers: authHeaders(),
    });
    if (!response.ok) {
      return;
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const figure = document.createElement("figure");
    figure.className = "shot";
    const image = document.createElement("img");
    image.src = objectUrl;
    image.alt = "Снимок экрана";
    const caption = document.createElement("figcaption");
    caption.textContent = `Снимок экрана · ${name}`;
    figure.append(image, caption);
    currentCard.refs.media.append(figure);
    scrollFeed();
  } catch {
    // Снимок не показался — задача продолжается.
  }
}

function finishCard(event) {
  if (!currentCard) {
    return;
  }
  if (!els.modal.hidden) {
    closeConfirm();
  }
  currentCard.finalReceived = true;
  state.running = false;
  setRunning(false);

  const reason = String(event.stopped_reason || "done");
  finishPending(reason === "cancelled" || reason === "error" ? "error" : "success");
  currentCard.refs.title.textContent =
    reason === "done" ? "Готово" : reason === "cancelled" ? "Остановлено" : "Задача завершена";
  currentCard.refs.stop.hidden = true;

  const cost = Number(event.cost || state.cost || 0);
  const steps = Number(event.steps || 0);
  currentCard.refs.foot.textContent =
    `Шаг ${steps} из ${state.maxSteps} · ${formatCost(cost)}`;

  if (event.chat_id) {
    state.chatId = String(event.chat_id);
  }
  if (event.message_id) {
    currentCard.refs.remove.hidden = false;
    currentCard.refs.remove.dataset.messageId = String(event.message_id);
    currentCard.refs.remove.dataset.chatId = state.chatId;
  }

  const answer = String(event.answer || "").trim() || "Готово.";
  currentCard.refs.answer.hidden = false;
  currentCard.refs.answer.classList.toggle(
    "error",
    reason !== "done" && reason !== "max_steps",
  );
  if (reason === "done" || reason === "max_steps") {
    renderMarkdown(currentCard.refs.answer, answer);
    speakAnswer(answer);
  } else {
    currentCard.refs.answer.textContent = answer;
  }

  if (event.remaining_rub !== undefined && event.remaining_rub !== null) {
    els.budgetValue.textContent = formatRub(event.remaining_rub, 2);
  }

  currentCard = null;
  refreshSummary();
  loadChats();
  els.input.focus();
  scrollFeed();
}

function failCard(card, message) {
  if (!card || card.finalReceived) {
    return;
  }
  if (!els.modal.hidden) {
    closeConfirm();
  }
  card.finalReceived = true;
  finishPending("error");
  card.refs.title.textContent = "Не удалось";
  card.refs.stop.hidden = true;
  card.refs.answer.hidden = false;
  card.refs.answer.classList.add("error");
  card.refs.answer.textContent = message;
  state.running = false;
  setRunning(false);
  currentCard = null;
  scrollFeed();
}

function setRunning(running) {
  els.send.disabled = running;
  els.mic.disabled = running;
  els.newTask.disabled = false;
}

async function streamTask(task) {
  const response = await fetch(api("/api/task"), {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ task, chat_id: state.chatId }),
  });

  if (!response.ok) {
    let data = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    throw new Error(data.error || `Сервер ответил ${response.status}.`);
  }
  if (!response.body) {
    throw new Error("Сервер не отдал поток событий.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let index = buffer.indexOf("\n\n");
    while (index >= 0) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      parseBlock(block);
      index = buffer.indexOf("\n\n");
    }
  }

  if (currentCard && !currentCard.finalReceived) {
    throw new Error("Поток завершился без итогового ответа.");
  }
}

function parseBlock(block) {
  const dataLines = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!dataLines.length) {
    return;
  }
  let event;
  try {
    event = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }
  if (event && event.type !== "ping") {
    handleEvent(event);
  }
}

const MEMORY_COMMAND_RE = /^\s*запомни[,:\s]+(.+)$/i;
const CLIPBOARD_COMMAND_RE = /^\s*(?:возьми|вставь|взять)\s+из\s+буфера\s*!?\s*$/i;

// Текст для озвучки: без кода, таблиц и врезок, длинное — по главному.
function speechText(markdown) {
  const lines = String(markdown || "").split("\n");
  const kept = [];
  let inCode = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      inCode = !inCode;
      continue;
    }
    if (inCode) continue;
    if (!trimmed) continue;
    if (trimmed.startsWith("|")) continue;
    if (trimmed.startsWith(">")) continue;
    if (/^#{1,6}\s/.test(trimmed)) {
      kept.push(trimmed.replace(/^#{1,6}\s*/, ""));
      continue;
    }
    kept.push(trimmed.replace(/^[-*]\s+/, "").replace(/^\d+\.\s+/, ""));
  }
  let text = kept.join(" ").replace(/\s+/g, " ").trim();
  if (text.length > SPEECH_MAX_CHARS) {
    const cut = text.slice(0, SPEECH_MAX_CHARS);
    const stop = Math.max(
      cut.lastIndexOf(". "),
      cut.lastIndexOf("! "),
      cut.lastIndexOf("? "),
      cut.lastIndexOf("."),
    );
    text = stop > 120 ? `${cut.slice(0, stop + 1).trim()}…` : `${cut.trim()}…`;
  }
  return text;
}

function loadVoices() {
  if (!window.speechSynthesis) {
    return [];
  }
  const all = window.speechSynthesis.getVoices() || [];
  state.voices = all.filter((voice) => /^ru/i.test(voice.lang || ""));
  return state.voices;
}

function renderVoiceOptions() {
  const current = state.settings?.speech_voice || "";
  els.speechVoice.replaceChildren();
  const fallback = document.createElement("option");
  fallback.value = "";
  fallback.textContent = "Голос по умолчанию";
  els.speechVoice.append(fallback);
  for (const voice of state.voices) {
    const option = document.createElement("option");
    option.value = voice.name;
    option.textContent = `${voice.name} (${voice.lang})`;
    els.speechVoice.append(option);
  }
  els.speechVoice.value = current;
  if (els.speechVoice.value !== current) {
    els.speechVoice.value = "";
  }
}

function stopSpeaking() {
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  state.speaking = false;
  els.speakStop.hidden = true;
}

function speakAnswer(markdown) {
  if (!state.settings || !state.settings.speech_enabled) {
    return;
  }
  if (!window.speechSynthesis) {
    showToast("В этом окне нет синтеза речи.");
    return;
  }
  const text = speechText(markdown);
  if (!text) {
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  const wanted = state.settings.speech_voice || "";
  const voice = state.voices.find((item) => item.name === wanted);
  if (voice) {
    utterance.voice = voice;
    utterance.lang = voice.lang;
  } else {
    utterance.lang = "ru-RU";
  }
  const rate = Number(state.settings.speech_rate);
  const volume = Number(state.settings.speech_volume);
  utterance.rate = Number.isFinite(rate) && rate > 0 ? rate : 1;
  utterance.volume = Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 1;
  const finish = () => {
    state.speaking = false;
    els.speakStop.hidden = true;
  };
  utterance.onend = finish;
  utterance.onerror = finish;
  state.speaking = true;
  els.speakStop.hidden = false;
  window.speechSynthesis.speak(utterance);
}

async function takeFromClipboard() {
  try {
    const data = await window.omega.readClipboard();
    if (!data) {
      showToast("Не удалось прочитать буфер обмена.");
      return;
    }
    const text = String(data.text || "").trim();
    if (!text) {
      showToast("В буфере обмена пусто.");
      return;
    }
    const preview = text.slice(0, 400);
    if (!window.confirm(`Вставить из буфера?\n\n${preview}${text.length > 400 ? "…" : ""}`)) {
      return;
    }
    els.input.value = text.slice(0, CLIPBOARD_MAX_CHARS);
    els.input.focus();
    showToast("Текст из буфера в поле ввода. Проверь и отправляй.");
  } catch (error) {
    showToast(error.message || "Не удалось прочитать буфер обмена.");
  }
}

async function proposeMemory(text) {
  if (state.settings && state.settings.memory_enabled === false) {
    showToast("Память выключена в настройках.");
    return;
  }
  try {
    const data = await apiJson("/api/memory/propose", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    openConfirm({
      kind: "memory_propose",
      local: true,
      title: "Запомнить?",
      text: data.text || text,
      always_path: "",
    });
  } catch (error) {
    showToast(error.message || "Не удалось проверить запись памяти.");
  }
}

async function submitTask() {
  const task = els.input.value.trim();
  if (!task || state.running) {
    return;
  }

  const memoryMatch = task.match(MEMORY_COMMAND_RE);
  if (memoryMatch) {
    els.input.value = "";
    addUserMessage(task);
    await proposeMemory(memoryMatch[1].trim());
    return;
  }

  if (CLIPBOARD_COMMAND_RE.test(task)) {
    els.input.value = "";
    addUserMessage(task);
    await takeFromClipboard();
    return;
  }

  state.running = true;
  state.cost = 0;
  setRunning(true);
  addUserMessage(task);
  els.input.value = "";
  currentCard = createAssistantCard();
  updateFooter(0, 0);

  try {
    await streamTask(task);
  } catch (error) {
    failCard(currentCard, error.message || "Не удалось выполнить задачу.");
  } finally {
    if (state.running) {
      state.running = false;
      setRunning(false);
    }
  }
}

async function stopTask() {
  if (!state.running) {
    return;
  }
  if (currentCard) {
    currentCard.refs.stop.disabled = true;
  }
  try {
    await apiJson("/api/stop", { method: "POST", body: "{}" });
    showToast("Останавливаю задачу…");
  } catch (error) {
    showToast(error.message);
    if (currentCard) {
      currentCard.refs.stop.disabled = false;
    }
  }
}

function renderRecent(chats) {
  els.recent.replaceChildren();
  if (!chats || !chats.length) {
    const empty = document.createElement("p");
    empty.className = "recent-empty";
    empty.textContent = "Пока пусто.";
    els.recent.append(empty);
    return;
  }
  for (const chat of chats.slice(0, 30)) {
    const row = document.createElement("div");
    row.className = "recent-row";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ci recent-item";
    button.classList.toggle("active", chat.id === state.chatId);
    button.textContent = truncate(chat.title || "Новый чат", 32);
    button.title = chat.title || "";
    button.addEventListener("click", () => showChat(chat.id));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ci recent-delete";
    remove.textContent = "×";
    remove.title = "Удалить чат";
    remove.setAttribute("aria-label", `Удалить чат ${chat.title || ""}`);
    remove.addEventListener("click", () => deleteChat(chat.id));
    row.append(button, remove);
    els.recent.append(row);
  }
}

function renderHistoryMessage(message, chatId) {
  if (message.role === "user") {
    addUserMessage(message.text || "");
    return;
  }
  const card = document.createElement("article");
  card.className = "assistant cl";
  const head = document.createElement("div");
  head.className = "assistant-head";
  const title = document.createElement("h2");
  title.className = "assistant-title";
  const reason = message.stopped_reason || "done";
  title.textContent =
    reason === "done" || reason === "max_steps"
      ? "Готово"
      : reason === "cancelled"
        ? "Остановлено"
        : "Задача завершена";
  const actions = document.createElement("div");
  actions.className = "assistant-actions";
  if (message.task_id && message.id) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ci stop-btn";
    remove.textContent = "Удалить";
    remove.title = "Удалить задачу";
    remove.addEventListener("click", () => deleteMessage(chatId, message.id));
    actions.append(remove);
  }
  head.append(title, actions);
  const answer = document.createElement("div");
  answer.className = "answer";
  if (reason === "done" || reason === "max_steps") {
    renderMarkdown(answer, message.text || "Готово.");
  } else {
    answer.textContent = message.text || "Готово.";
    answer.classList.add("error");
  }
  const foot = document.createElement("p");
  foot.className = "card-foot";
  foot.textContent =
    `${Number(message.steps || 0)} шаг(ов) · ${formatCost(message.cost || 0)} · ${formatDate(message.created_at)}`;
  card.append(head, answer, foot);
  els.feed.append(card);
}

function showChat(chatId) {
  if (state.running) {
    showToast("Сначала дождись конца текущей задачи или нажми «Стоп».");
    return;
  }
  const chat = state.chats.find((item) => item.id === chatId);
  if (!chat) {
    return;
  }
  state.chatId = chat.id;
  els.feed.replaceChildren();
  for (const message of chat.messages || []) {
    renderHistoryMessage(message, chat.id);
  }
  renderRecent(state.chats);
  scrollFeed();
  els.input.focus();
}

async function loadChats() {
  try {
    const data = await apiJson("/api/chats");
    state.chats = Array.isArray(data.chats) ? data.chats : [];
    renderRecent(state.chats);
    if (state.chatId && !state.chats.some((chat) => chat.id === state.chatId)) {
      state.chatId = "";
    }
  } catch (error) {
    showToast(`Не удалось загрузить чаты: ${error.message}`);
  }
}

async function refreshSummary() {
  try {
    const data = await apiJson("/api/summary");
    state.maxSteps = Number(data.max_steps || 8);
    els.budgetValue.textContent = formatRub(data.remaining_rub, 2);
  } catch (error) {
    showToast(`Не удалось загрузить историю: ${error.message}`);
  }
}

async function deleteChat(chatId) {
  if (state.running) {
    showToast("Сначала дождись конца задачи.");
    return;
  }
  if (!window.confirm("Удалить этот чат вместе с задачами?")) {
    return;
  }
  try {
    await apiJson(`/api/chats/${encodeURIComponent(chatId)}`, { method: "DELETE" });
    if (state.chatId === chatId) {
      state.chatId = "";
      els.feed.replaceChildren();
    }
    await loadChats();
    await refreshSummary();
    showToast("Чат удалён.");
  } catch (error) {
    showToast(error.message || "Не удалось удалить чат.");
  }
}

async function deleteMessage(chatId, messageId) {
  if (state.running) {
    showToast("Сначала дождись конца задачи.");
    return;
  }
  if (!window.confirm("Удалить этот ответ? Его можно будет вернуть.")) {
    return;
  }
  try {
    await apiJson(
      `/api/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}`,
      { method: "DELETE" },
    );
    await loadChats();
    await refreshSummary();
    if (state.chatId === chatId) {
      showChat(chatId);
    }
    showToast("Ответ удалён.", {
      label: "Вернуть",
      run: () => restoreMessage(chatId, messageId),
    });
  } catch (error) {
    showToast(error.message || "Не удалось удалить задачу.");
  }
}

async function restoreMessage(chatId, messageId) {
  try {
    await apiJson(
      `/api/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}/restore`,
      { method: "POST", body: "{}" },
    );
    await loadChats();
    await refreshSummary();
    if (state.chatId === chatId) {
      showChat(chatId);
    }
    showToast("Ответ возвращён.");
  } catch (error) {
    showToast(error.message || "Не удалось вернуть ответ.");
  }
}

function confirmSubtitle(event) {
  const isSend = event.kind === "send_message";
  if (isSend) {
    return `Помощник хочет написать компании «${event.company || event.recipient || "без названия"}»`;
  }
  if (event.kind === "memory_propose") {
    return "Помощник хочет запомнить сведения о тебе.";
  }
  const subtitles = {
    delete_files: "Помощник хочет удалить файлы или папки. Они уйдут в корзину.",
    launch_app: "Помощник хочет запустить программу.",
    download_file: "Помощник хочет скачать файл из интернета.",
    screenshot: "Помощник хочет сделать снимок экрана.",
    write_file: "Помощник хочет записать файл.",
    create_folder: "Помощник хочет создать папку.",
  };
  return subtitles[event.kind] || "Помощник просит подтверждение действия.";
}

function openConfirm(event) {
  if (!els.voice.hidden) {
    closeVoice();
  }
  state.pending = event;
  state.editing = false;
  state.modalBusy = false;

  const isSend = event.kind === "send_message";
  const isMemory = event.kind === "memory_propose";
  els.modalTitle.textContent = event.title || "Подтвердить действие?";
  els.modalSubtitle.textContent = confirmSubtitle(event);
  els.draftText.textContent = String(event.text || "");
  els.draftText.hidden = false;
  els.draftEdit.value = String(event.text || "");
  els.draftEdit.hidden = true;
  els.modalChips.hidden = !isSend;
  els.chipChannel.textContent = `Канал: ${event.channel || "—"}`;
  els.chipToday.textContent = `Сегодня: ${event.today || 0} из ${event.limit || 0}`;
  els.edit.hidden = !isSend && !isMemory;
  els.approve.textContent = isSend
    ? "Отправить"
    : isMemory
      ? "Запомнить"
      : "Подтвердить";
  els.reject.textContent = isMemory ? "Не надо" : "Отклонить";
  const canAlways = event.kind === "launch_app" && Boolean(event.always_path);
  els.alwaysRow.hidden = !canAlways;
  els.alwaysCheck.checked = false;
  const previewName = String(event.image || "");
  els.modalPreview.hidden = !previewName;
  if (previewName) {
    els.modalPreview.src = api(`/api/screenshot?name=${encodeURIComponent(previewName)}`);
  } else {
    els.modalPreview.removeAttribute("src");
  }
  els.modalError.hidden = true;
  els.modalError.textContent = "";
  setModalBusy(false);

  lastFocus = document.activeElement;
  els.modal.hidden = false;
  syncInert();
  els.reject.focus();
}

function closeConfirm() {
  els.modal.hidden = true;
  syncInert();
  state.pending = null;
  state.editing = false;
  state.modalBusy = false;
  if (lastFocus && typeof lastFocus.focus === "function") {
    lastFocus.focus();
  } else {
    els.input.focus();
  }
  lastFocus = null;
}

function setModalBusy(busy) {
  state.modalBusy = busy;
  els.reject.disabled = busy;
  els.edit.disabled = busy;
  els.approve.disabled = busy;
}

async function answerConfirm(action) {
  const event = state.pending;
  if (!event || state.modalBusy) {
    return;
  }

  const isMemory = event.kind === "memory_propose";
  let text = "";
  if (action === "edit") {
    text = els.draftEdit.value.trim();
    const minLength = isMemory ? 1 : 20;
    if (text.length < minLength) {
      els.modalError.textContent = isMemory
        ? "Пустую запись сохранять нельзя."
        : "Текст слишком короткий: нужно минимум 20 символов.";
      els.modalError.hidden = false;
      els.draftEdit.focus();
      return;
    }
  }

  const always =
    action === "approve" &&
    !els.alwaysRow.hidden &&
    els.alwaysCheck.checked &&
    Boolean(event.always_path);
  const finalAction = always ? "always" : action;

  setModalBusy(true);
  els.modalError.hidden = true;
  try {
    if (isMemory && event.local) {
      if (action !== "approve" && action !== "edit") {
        closeConfirm();
        return;
      }
      const finalText = state.editing
        ? els.draftEdit.value.trim()
        : String(event.text || "").trim();
      await apiJson("/api/memory", {
        method: "POST",
        body: JSON.stringify({ text: finalText }),
      });
      closeConfirm();
      await refreshMemory();
      showToast("Запомнил.");
      return;
    }
    await apiJson("/api/confirm", {
      method: "POST",
      body: JSON.stringify({ id: event.id, action: finalAction, text }),
    });
    closeConfirm();
    if (isMemory) {
      await refreshMemory();
      showToast("Запомнил.");
    } else if (always) {
      await rememberAllowedApp(event.always_path);
      showToast("Приложение разрешено навсегда.");
    } else if (action === "edit") {
      showToast("Текст изменён и подтверждён.");
    }
  } catch (error) {
    els.modalError.textContent = error.message;
    els.modalError.hidden = false;
    setModalBusy(false);
  }
}

function enterEditMode() {
  const kind = state.pending?.kind;
  if (!state.pending || (kind !== "send_message" && kind !== "memory_propose") || state.editing) {
    return;
  }
  state.editing = true;
  els.draftText.hidden = true;
  els.draftEdit.hidden = false;
  els.edit.hidden = true;
  els.draftEdit.focus();
  els.draftEdit.setSelectionRange(els.draftEdit.value.length, els.draftEdit.value.length);
}

function trapFocus(event) {
  if (event.key !== "Tab") {
    return;
  }
  const scope = !els.modal.hidden
    ? els.modal
    : !els.settings.hidden
      ? els.settings
      : !els.voice.hidden
        ? els.voice
        : null;
  if (!scope) {
    return;
  }
  const focusable = Array.from(
    scope.querySelectorAll(
      "button, textarea, input, select, [tabindex]:not([tabindex='-1'])",
    ),
  ).filter(
    (node) =>
      !node.hidden &&
      !node.disabled &&
      node.offsetParent !== null,
  );
  if (!focusable.length) {
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function formatVoiceDuration(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function resetVoiceBars() {
  for (const bar of els.voiceBars.querySelectorAll(".bar")) {
    bar.style.transform = "";
  }
}

function setVoiceMode(mode, message = "") {
  const titles = {
    starting: "Подключаю…",
    recording: "Слушаю…",
    processing: "Распознаю…",
    error: "Не получилось",
  };
  const texts = {
    starting: "Подключаю микрофон…",
    recording: "Говори, я запишу.",
    processing: "Разбираю запись…",
  };
  const hints = {
    starting: "Разреши доступ к микрофону · Esc — отмена",
    recording: "Максимум 60 секунд · Esc — отмена",
    processing: "Обработка на этом компьютере",
    error: "Проверь микрофон и попробуй ещё раз",
  };
  els.voiceTitle.textContent = titles[mode] || "Голос";
  els.voiceText.classList.toggle("error", mode === "error");
  els.voiceText.textContent = mode === "error" ? message : texts[mode] || "";
  els.voiceHint.textContent = hints[mode] || "";
  els.voiceCircle.classList.toggle("listening", mode === "recording");
  els.voiceStop.hidden = mode === "error";
  els.voiceStop.disabled = mode !== "recording";
  els.voiceStop.textContent =
    mode === "recording" ? "Остановить" : mode === "starting" ? "Подожди" : "Распознаю…";
  els.voiceRetry.hidden = mode !== "error";
  els.voiceCancel.textContent =
    mode === "processing" || mode === "error" ? "Закрыть" : "Отмена";
  els.voiceTimer.hidden = mode === "error";
}

function stopVoiceStream(stream) {
  if (!stream) {
    return;
  }
  for (const track of stream.getTracks()) {
    try {
      track.stop();
    } catch {
      // Дорожка уже остановлена.
    }
  }
}

function stopVoiceTimer() {
  if (state.voiceTimer) {
    clearInterval(state.voiceTimer);
    state.voiceTimer = null;
  }
}

function stopVoiceMeter() {
  if (state.voiceMeterFrame) {
    cancelAnimationFrame(state.voiceMeterFrame);
    state.voiceMeterFrame = 0;
  }
  if (state.voiceMeterSource) {
    try {
      state.voiceMeterSource.disconnect();
    } catch {
      // Источник уже отключён.
    }
    state.voiceMeterSource = null;
  }
  if (state.voiceMeterSink) {
    try {
      state.voiceMeterSink.disconnect();
    } catch {
      // Приёмник уже отключён.
    }
    state.voiceMeterSink = null;
  }
  state.voiceAnalyser = null;
  if (state.voiceAudioContext) {
    state.voiceAudioContext.close().catch(() => {});
    state.voiceAudioContext = null;
  }
  resetVoiceBars();
}

function cleanupVoiceMedia() {
  const recorder = state.voiceRecorder;
  state.voiceRecorder = null;
  if (recorder) {
    recorder.ondataavailable = null;
    recorder.onstop = null;
    recorder.onerror = null;
    try {
      if (recorder.state !== "inactive") {
        recorder.stop();
      }
    } catch {
      // Запись уже остановлена.
    }
  }
  stopVoiceStream(state.voiceStream);
  state.voiceStream = null;
  stopVoiceMeter();
}

function pickVoiceMime() {
  if (typeof MediaRecorder === "undefined") {
    return "";
  }
  return (
    VOICE_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) || ""
  );
}

function startVoiceMeter(stream) {
  stopVoiceMeter();
  const AudioCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtor) {
    return;
  }
  const context = new AudioCtor();
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.75;
  const sink = context.createGain();
  sink.gain.value = 0;
  source.connect(analyser);
  analyser.connect(sink);
  sink.connect(context.destination);
  state.voiceAudioContext = context;
  state.voiceAnalyser = analyser;
  state.voiceMeterSource = source;
  state.voiceMeterSink = sink;
  context.resume().catch(() => {});
  const bars = Array.from(els.voiceBars.querySelectorAll(".bar"));
  const data = new Uint8Array(analyser.fftSize);
  const tick = () => {
    if (!state.voiceAnalyser) {
      return;
    }
    analyser.getByteTimeDomainData(data);
    let peak = 0;
    for (const value of data) {
      peak = Math.max(peak, Math.abs(value - 128) / 128);
    }
    const level = Math.min(1, peak * 3.5);
    bars.forEach((bar, index) => {
      const idle = Math.sin(performance.now() / 240 + index * 1.3) * 0.08;
      const wave = Math.sin(performance.now() / 130 + index * 1.7);
      const factor = 0.25 + idle + level * (0.75 + wave * 0.15);
      bar.style.transform = `scaleY(${Math.max(0.15, factor).toFixed(2)})`;
    });
    state.voiceMeterFrame = requestAnimationFrame(tick);
  };
  tick();
}

function startVoiceTimer(token) {
  stopVoiceTimer();
  state.voiceStartedAt = performance.now();
  const tick = () => {
    if (token !== state.voiceToken || !state.voiceRecording) {
      return;
    }
    const elapsed = performance.now() - state.voiceStartedAt;
    els.voiceTimer.textContent = formatVoiceDuration(elapsed);
    if (elapsed >= VOICE_MAX_MS) {
      stopVoiceRecording(token);
    }
  };
  tick();
  state.voiceTimer = setInterval(tick, 200);
}

function insertVoiceText(text) {
  const current = els.input.value.trim();
  els.input.value = current ? `${current} ${text}` : text;
  const end = els.input.value.length;
  els.input.setSelectionRange(end, end);
  els.input.focus();
}

function handleVoiceError(token, message) {
  if (token !== state.voiceToken) {
    return;
  }
  state.voiceRecording = false;
  state.voiceBusy = false;
  stopVoiceTimer();
  cleanupVoiceMedia();
  state.voiceChunks = [];
  setVoiceMode("error", message || "Не удалось записать голос.");
}

async function transcribeVoiceBlob(blob, token) {
  const controller = new AbortController();
  state.voiceAbort = controller;
  const language = state.settings?.voice_language || "ru";
  try {
    const response = await fetch(
      api(`/api/transcribe?language=${encodeURIComponent(language)}`),
      {
        method: "POST",
        headers: authHeaders({ "Content-Type": blob.type || "audio/webm" }),
        body: blob,
        signal: controller.signal,
      },
    );
    let data = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    if (token !== state.voiceToken) {
      return;
    }
    if (!response.ok) {
      throw new Error(data.error || `Сервер ответил ${response.status}.`);
    }
    const text = String(data.text || "").trim();
    if (!text) {
      throw new Error("Речь не распознана.");
    }
    insertVoiceText(text);
    closeVoice();
    if (state.running) {
      showToast("Голос распознан. Дождись конца текущей задачи.");
    } else {
      showToast("Голос распознан, отправляю…");
      submitTask();
    }
  } catch (error) {
    if (error.name === "AbortError" || token !== state.voiceToken) {
      return;
    }
    handleVoiceError(token, error.message || "Не удалось распознать речь.");
  } finally {
    if (state.voiceAbort === controller) {
      state.voiceAbort = null;
    }
  }
}

async function finishVoiceRecording(token) {
  if (token !== state.voiceToken) {
    return;
  }
  const chunks = state.voiceChunks.slice();
  state.voiceChunks = [];
  const recorder = state.voiceRecorder;
  const type = (recorder && recorder.mimeType) || (chunks[0] && chunks[0].type) || "audio/webm";
  state.voiceRecorder = null;
  stopVoiceTimer();
  stopVoiceMeter();
  stopVoiceStream(state.voiceStream);
  state.voiceStream = null;
  if (!chunks.length) {
    handleVoiceError(token, "Запись пустая. Попробуй ещё раз.");
    return;
  }
  const blob = new Blob(chunks, { type });
  if (blob.size < VOICE_MIN_BYTES) {
    handleVoiceError(token, "Запись слишком короткая. Попробуй ещё раз.");
    return;
  }
  await transcribeVoiceBlob(blob, token);
}

function stopVoiceRecording(token = state.voiceToken) {
  if (token !== state.voiceToken || !state.voiceRecording) {
    return;
  }
  state.voiceRecording = false;
  state.voiceBusy = true;
  stopVoiceTimer();
  stopVoiceMeter();
  setVoiceMode("processing");
  const recorder = state.voiceRecorder;
  if (!recorder || recorder.state === "inactive") {
    finishVoiceRecording(token);
    return;
  }
  try {
    recorder.stop();
  } catch {
    handleVoiceError(token, "Не удалось остановить запись.");
  }
}

async function startVoiceRecording(token) {
  if (token !== state.voiceToken) {
    return;
  }
  cleanupVoiceMedia();
  state.voiceChunks = [];
  state.voiceRecording = false;
  state.voiceBusy = false;
  els.voiceTimer.textContent = "0:00";
  setVoiceMode("starting");
  try {
    if (
      !navigator.mediaDevices ||
      typeof navigator.mediaDevices.getUserMedia !== "function"
    ) {
      throw new Error("Микрофон недоступен в этом окне.");
    }
    if (typeof MediaRecorder === "undefined") {
      throw new Error("Запись звука не поддерживается.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    if (token !== state.voiceToken) {
      stopVoiceStream(stream);
      return;
    }
    state.voiceStream = stream;
    const mimeType = pickVoiceMime();
    const options = { audioBitsPerSecond: 64000 };
    if (mimeType) {
      options.mimeType = mimeType;
    }
    const recorder = new MediaRecorder(stream, options);
    state.voiceRecorder = recorder;
    recorder.addEventListener("dataavailable", (event) => {
      if (token === state.voiceToken && event.data && event.data.size) {
        state.voiceChunks.push(event.data);
      }
    });
    recorder.addEventListener("error", (event) => {
      if (token === state.voiceToken) {
        handleVoiceError(
          token,
          (event.error && event.error.message) || "Ошибка записи звука.",
        );
      }
    });
    recorder.addEventListener("stop", () => {
      if (token === state.voiceToken) {
        finishVoiceRecording(token);
      }
    });
    recorder.start(250);
    state.voiceRecording = true;
    setVoiceMode("recording");
    startVoiceMeter(stream);
    startVoiceTimer(token);
  } catch (error) {
    if (token !== state.voiceToken) {
      return;
    }
    let message = "Не удалось включить микрофон.";
    if (error && (error.name === "NotAllowedError" || error.name === "SecurityError")) {
      message = "Доступ к микрофону запрещён. Разреши его в Windows и попробуй снова.";
    } else if (
      error &&
      (error.name === "NotFoundError" || error.name === "DevicesNotFoundError")
    ) {
      message = "Микрофон не найден. Подключи его и попробуй снова.";
    } else if (
      error &&
      (error.name === "NotReadableError" || error.name === "TrackStartError")
    ) {
      message = "Микрофон занят другой программой.";
    } else if (error && error.message) {
      message = error.message;
    }
    handleVoiceError(token, message);
  }
}

async function openVoice() {
  if (!els.voice.hidden) {
    return;
  }
  if (state.running) {
    showToast("Дождись конца текущей задачи.");
    return;
  }
  if (!els.modal.hidden) {
    showToast("Сначала ответь на подтверждение.");
    return;
  }
  if (state.settingsOpen) {
    showToast("Сначала закрой настройки.");
    return;
  }
  state.voiceToken += 1;
  const token = state.voiceToken;
  els.voice.hidden = false;
  syncInert();
  els.voice.focus();
  await startVoiceRecording(token);
}

function closeVoice() {
  if (els.voice.hidden) {
    return;
  }
  state.voiceToken += 1;
  if (state.voiceAbort) {
    state.voiceAbort.abort();
    state.voiceAbort = null;
  }
  state.voiceRecording = false;
  state.voiceBusy = false;
  stopVoiceTimer();
  cleanupVoiceMedia();
  state.voiceChunks = [];
  els.voice.hidden = true;
  syncInert();
  els.input.focus();
}

async function retryVoice() {
  if (state.voiceBusy) {
    return;
  }
  state.voiceToken += 1;
  const token = state.voiceToken;
  state.voiceChunks = [];
  await startVoiceRecording(token);
}

const HOTKEY_LABELS = {
  CommandOrControl: "Ctrl",
  Control: "Ctrl",
  Command: "Cmd",
  Super: "Win",
  Alt: "Alt",
  Option: "Alt",
  Shift: "Shift",
  Space: "Пробел",
  Up: "↑",
  Down: "↓",
  Left: "←",
  Right: "→",
  PageUp: "PageUp",
  PageDown: "PageDown",
};

function formatHotkey(value) {
  return String(value || "")
    .split("+")
    .filter(Boolean)
    .map((part) => HOTKEY_LABELS[part] || part)
    .join(" + ");
}

function keyFromEvent(event) {
  const key = event.key;
  if (["Control", "Shift", "Alt", "Meta", "OS"].includes(key)) {
    return "";
  }
  if (key === " ") {
    return "Space";
  }
  if (key.startsWith("Arrow")) {
    return key.slice(5);
  }
  const named = {
    Enter: "Enter",
    Tab: "Tab",
    Backspace: "Backspace",
    Delete: "Delete",
    Home: "Home",
    End: "End",
    PageUp: "PageUp",
    PageDown: "PageDown",
    Insert: "Insert",
  };
  if (named[key]) {
    return named[key];
  }
  if (/^F([1-9]|1\d|2[0-4])$/i.test(key)) {
    return key.toUpperCase();
  }
  if (/^Key[A-Z]$/.test(event.code)) {
    return event.code.slice(3);
  }
  if (/^Digit[0-9]$/.test(event.code)) {
    return event.code.slice(5);
  }
  if (/^[a-z0-9]$/i.test(key)) {
    return key.toUpperCase();
  }
  return "";
}

function acceleratorFromEvent(event) {
  const key = keyFromEvent(event);
  if (!key) {
    return null;
  }
  const parts = [];
  if (event.ctrlKey) {
    parts.push("CommandOrControl");
  }
  if (event.altKey) {
    parts.push("Alt");
  }
  if (event.shiftKey) {
    parts.push("Shift");
  }
  if (event.metaKey) {
    parts.push("Super");
  }
  const functionKey = /^F([1-9]|1\d|2[0-4])$/.test(key);
  if (!event.ctrlKey && !event.altKey && !event.metaKey && !functionKey) {
    return { error: "Добавь Ctrl, Alt или Win к клавише." };
  }
  if (!parts.length) {
    return { error: "Не удалось распознать сочетание." };
  }
  return { accelerator: [...parts, key].join("+") };
}

function showSettingsError(message) {
  els.settingsError.textContent = message;
  els.settingsError.hidden = false;
}

function clearSettingsError() {
  els.settingsError.textContent = "";
  els.settingsError.hidden = true;
}

function applyTheme(value) {
  const theme = value === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
}

function promptLimit() {
  const limit = Number(state.promptInfo?.limit);
  return Number.isFinite(limit) && limit > 0 ? limit : PROMPT_LIMIT;
}

function updatePromptCounter() {
  const value = els.userPrompt.value || "";
  const limit = promptLimit();
  els.promptCounter.textContent = `${value.length} / ${limit}`;
  els.promptCounter.classList.toggle("near-limit", value.length > limit * 0.9);
}

function applyModelNote(model) {
  const caps = (state.promptInfo?.models || []).find((item) => item.id === model);
  if (!caps) {
    els.modelNote.textContent = "";
    els.modelNote.hidden = true;
    return;
  }
  const parts = [
    caps.tools ? "инструменты работают" : "только чат, инструменты недоступны",
    caps.multiTurn ? "контекст диалога работает" : "контекст диалога может теряться",
  ];
  if (caps.warning) {
    parts.push(caps.warning);
  }
  els.modelNote.textContent = parts.join(" · ");
  els.modelNote.hidden = false;
  els.modelNote.classList.toggle("warn", !caps.tools || Boolean(caps.warning));
}

function applySettingsToUi() {
  if (!state.settings) {
    return;
  }
  if (!state.recordingHotkey) {
    els.hotkeyInput.value = formatHotkey(state.settings.hotkey);
  }
  const autostart = Boolean(state.settings.autostart);
  els.autostartToggle.setAttribute("aria-checked", String(autostart));
  els.autostartToggle.classList.toggle("on", autostart);
  if (document.activeElement !== els.budgetInput) {
    els.budgetInput.value = String(state.settings.budget_limit_rub);
  }
  const voiceLanguage = ["ru", "en", "auto"].includes(state.settings.voice_language)
    ? state.settings.voice_language
    : "ru";
  if (document.activeElement !== els.voiceLanguage) {
    els.voiceLanguage.value = voiceLanguage;
  }
  const salesModule = Boolean(state.settings.sales_module);
  els.salesToggle.setAttribute("aria-checked", String(salesModule));
  els.salesToggle.classList.toggle("on", salesModule);
  const model = ["deepseek-v4.1-flash", "glm-5.3-flash", "gpt-6-luna", "claude-haiku-5.5"]
    .includes(state.settings.model)
    ? state.settings.model
    : "claude-haiku-5.5";
  if (document.activeElement !== els.modelSelect) {
    els.modelSelect.value = model;
  }
  const theme = state.settings.theme === "dark" ? "dark" : "light";
  if (document.activeElement !== els.themeSelect) {
    els.themeSelect.value = theme;
  }
  const launch = Boolean(state.settings.launch_without_confirm);
  els.launchToggle.setAttribute("aria-checked", String(launch));
  els.launchToggle.classList.toggle("on", launch);
  renderAllowedApps();
  const memoryEnabled = state.settings.memory_enabled !== false;
  els.memoryToggle.setAttribute("aria-checked", String(memoryEnabled));
  els.memoryToggle.classList.toggle("on", memoryEnabled);
  const speechEnabled = Boolean(state.settings.speech_enabled);
  els.speechToggle.setAttribute("aria-checked", String(speechEnabled));
  els.speechToggle.classList.toggle("on", speechEnabled);
  if (document.activeElement !== els.speechRate) {
    els.speechRate.value = String(state.settings.speech_rate ?? 1);
  }
  if (document.activeElement !== els.speechVolume) {
    els.speechVolume.value = String(state.settings.speech_volume ?? 1);
  }
  renderVoiceOptions();
  applyTheme(theme);
  if (document.activeElement !== els.userPrompt) {
    els.userPrompt.value = state.settings.user_prompt || "";
  }
  updatePromptCounter();
  applyModelNote(state.settings.model);
}

function renderAllowedApps() {
  const apps = Array.isArray(state.settings?.allowed_apps)
    ? state.settings.allowed_apps
    : [];
  els.allowedApps.replaceChildren();
  els.allowedAppsEmpty.hidden = apps.length > 0;
  for (const item of apps) {
    const row = document.createElement("li");
    row.className = "allowed-app";
    const name = document.createElement("span");
    name.className = "allowed-app-name";
    name.textContent = item;
    name.title = item;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ci btn allowed-app-remove";
    remove.textContent = "Убрать";
    remove.addEventListener("click", () => removeAllowedApp(item));
    row.append(name, remove);
    els.allowedApps.append(row);
  }
}

async function rememberAllowedApp(path) {
  const apps = Array.isArray(state.settings?.allowed_apps)
    ? [...state.settings.allowed_apps]
    : [];
  if (!apps.includes(path)) {
    apps.push(path);
  }
  await saveSettingsPatch({ allowed_apps: apps });
}

async function removeAllowedApp(path) {
  const apps = Array.isArray(state.settings?.allowed_apps)
    ? state.settings.allowed_apps
    : [];
  const ok = await saveSettingsPatch({
    allowed_apps: apps.filter((item) => item !== path),
  });
  if (ok) {
    showToast("Приложение убрано из разрешённых.");
  }
}

function renderMemory() {
  const entries = Array.isArray(state.memory) ? state.memory : [];
  els.memoryList.replaceChildren();
  els.memoryEmpty.hidden = entries.length > 0;
  for (const item of entries) {
    const row = document.createElement("li");
    row.className = "memory-item";
    if (state.editingMemoryId === item.id) {
      const area = document.createElement("textarea");
      area.className = "ci memory-edit";
      area.value = item.text || "";
      area.maxLength = 300;
      area.setAttribute("aria-label", "Текст записи памяти");
      const actions = document.createElement("div");
      actions.className = "memory-actions";
      const save = document.createElement("button");
      save.type = "button";
      save.className = "ci btn";
      save.textContent = "Сохранить";
      save.addEventListener("click", () => saveMemoryEntry(item.id, area.value));
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "ci btn";
      cancel.textContent = "Отмена";
      cancel.addEventListener("click", () => {
        state.editingMemoryId = null;
        renderMemory();
      });
      actions.append(save, cancel);
      row.append(area, actions);
    } else {
      const text = document.createElement("p");
      text.className = "memory-text";
      text.textContent = item.text || "";
      const date = document.createElement("span");
      date.className = "memory-date";
      date.textContent = item.date || "";
      const actions = document.createElement("div");
      actions.className = "memory-actions";
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "ci btn";
      edit.textContent = "Изменить";
      edit.addEventListener("click", () => {
        state.editingMemoryId = item.id;
        renderMemory();
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "ci btn";
      remove.textContent = "Удалить";
      remove.addEventListener("click", () => deleteMemoryEntry(item.id));
      actions.append(edit, remove);
      row.append(text, date, actions);
    }
    els.memoryList.append(row);
  }
}

function renderReminders() {
  const items = Array.isArray(state.reminders) ? state.reminders : [];
  els.reminderList.replaceChildren();
  els.reminderEmpty.hidden = items.length > 0;
  for (const item of items) {
    const row = document.createElement("li");
    row.className = "memory-item";
    const text = document.createElement("p");
    text.className = "memory-text";
    text.textContent = item.text || "";
    const date = document.createElement("span");
    date.className = "memory-date";
    date.textContent = formatReminderTime(item.at);
    const actions = document.createElement("div");
    actions.className = "memory-actions";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ci btn";
    remove.textContent = "Удалить";
    remove.addEventListener("click", () => deleteReminder(item.id));
    actions.append(remove);
    row.append(text, date, actions);
    els.reminderList.append(row);
  }
}

function formatReminderTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value || "");
  }
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function refreshReminders() {
  try {
    const data = await apiJson("/api/reminders");
    state.reminders = Array.isArray(data.reminders) ? data.reminders : [];
    renderReminders();
  } catch {
    // Напоминания недоступны — список останется пустым.
  }
}

async function deleteReminder(id) {
  if (!window.confirm("Удалить напоминание?")) {
    return;
  }
  try {
    await apiJson(`/api/reminders/${encodeURIComponent(id)}`, { method: "DELETE" });
    await refreshReminders();
    showToast("Напоминание удалено.");
  } catch (error) {
    showToast(error.message || "Не удалось удалить напоминание.");
  }
}

async function refreshMemory() {
  try {
    const data = await apiJson("/api/memory");
    state.memory = Array.isArray(data.entries) ? data.entries : [];
    state.memoryEnabled = data.enabled !== false;
    renderMemory();
  } catch {
    // Память недоступна — экран настроек просто останется пустым.
  }
}

async function saveMemoryEntry(id, text) {
  try {
    await apiJson(`/api/memory/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({ text }),
    });
    state.editingMemoryId = null;
    await refreshMemory();
    showToast("Запись памяти изменена.");
  } catch (error) {
    showToast(error.message || "Не удалось изменить запись.");
  }
}

async function deleteMemoryEntry(id) {
  if (!window.confirm("Удалить эту запись из памяти?")) {
    return;
  }
  try {
    await apiJson(`/api/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
    state.editingMemoryId = null;
    await refreshMemory();
    showToast("Запись удалена.");
  } catch (error) {
    showToast(error.message || "Не удалось удалить запись.");
  }
}

async function clearMemory() {
  if (!window.confirm("Удалить всю память? Восстановить её будет нельзя.")) {
    return;
  }
  try {
    await apiJson("/api/memory/clear", { method: "POST", body: "{}" });
    state.editingMemoryId = null;
    await refreshMemory();
    showToast("Память очищена.");
  } catch (error) {
    showToast(error.message || "Не удалось очистить память.");
  }
}

async function exportMemory() {
  try {
    const data = await apiJson("/api/memory/export");
    const blob = new Blob([data.text || ""], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = data.file || "omega-memory.txt";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    showToast("Файл памяти сохранён в загрузки.");
  } catch (error) {
    showToast(error.message || "Не удалось выгрузить память.");
  }
}

async function toggleSpeechEnabled() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  state.settingsBusy = true;
  els.speechToggle.disabled = true;
  const desired = !state.settings.speech_enabled;
  const ok = await saveSettingsPatch({ speech_enabled: desired });
  els.speechToggle.disabled = false;
  state.settingsBusy = false;
  if (ok) {
    if (!desired) {
      stopSpeaking();
    }
    showToast(desired ? "Озвучка включена." : "Озвучка выключена.");
  } else {
    applySettingsToUi();
  }
}

async function saveSpeechVoice() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  const value = els.speechVoice.value || "";
  if (value === (state.settings.speech_voice || "")) {
    return;
  }
  state.settingsBusy = true;
  const ok = await saveSettingsPatch({ speech_voice: value });
  state.settingsBusy = false;
  if (!ok) {
    applySettingsToUi();
  }
}

async function saveSpeechRange() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  const rate = Number(els.speechRate.value);
  const volume = Number(els.speechVolume.value);
  state.settingsBusy = true;
  const ok = await saveSettingsPatch({
    speech_rate: Number.isFinite(rate) ? rate : 1,
    speech_volume: Number.isFinite(volume) ? volume : 1,
  });
  state.settingsBusy = false;
  if (!ok) {
    applySettingsToUi();
  }
}

async function toggleMemoryEnabled() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  state.settingsBusy = true;
  els.memoryToggle.disabled = true;
  const desired = !state.settings.memory_enabled;
  const ok = await saveSettingsPatch({ memory_enabled: desired });
  els.memoryToggle.disabled = false;
  state.settingsBusy = false;
  if (ok) {
    state.memoryEnabled = desired;
    showToast(
      desired ? "Память включена." : "Память выключена: модель её не получает.",
    );
  } else {
    applySettingsToUi();
  }
}

async function toggleLaunchWithoutConfirm() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  state.settingsBusy = true;
  els.launchToggle.disabled = true;
  const desired = !state.settings.launch_without_confirm;
  const ok = await saveSettingsPatch({ launch_without_confirm: desired });
  els.launchToggle.disabled = false;
  state.settingsBusy = false;
  if (ok) {
    showToast(
      desired
        ? "Запуск приложений без вопроса включён."
        : "Запуск приложений без вопроса выключен.",
    );
  } else {
    applySettingsToUi();
  }
}

async function saveSettingsPatch(patch) {
  clearSettingsError();
  try {
    const result = await window.omega.saveSettings(patch);
    if (!result || !result.ok) {
      throw new Error((result && result.error) || "Не удалось сохранить настройки.");
    }
    state.settings = result.settings;
    applySettingsToUi();
    return true;
  } catch (error) {
    showSettingsError(error.message || String(error));
    if (!state.settingsOpen) {
      showToast(error.message || String(error));
    }
    return false;
  }
}

async function openSettings() {
  if (state.settingsOpen) {
    els.settingsClose.focus();
    return;
  }
  if (!els.modal.hidden) {
    showToast("Сначала ответь на подтверждение.");
    return;
  }
  if (!els.voice.hidden) {
    closeVoice();
  }
  try {
    const settings = await window.omega.getSettings();
    if (!settings) {
      throw new Error("Приложение не передало настройки.");
    }
    state.settings = settings;
    const info = await window.omega.getPromptInfo();
    if (info) {
      state.promptInfo = info;
      els.policyView.textContent = info.policy || "";
      els.userPrompt.maxLength = promptLimit();
      updatePromptCounter();
      applyModelNote(settings.model);
    }
    await refreshMemory();
    await refreshReminders();
  } catch (error) {
    showToast(error.message || "Не удалось открыть настройки.");
    return;
  }
  settingsLastFocus = document.activeElement;
  state.settingsOpen = true;
  applySettingsToUi();
  clearSettingsError();
  els.settings.hidden = false;
  syncInert();
  els.settingsClose.focus();
}

function closeSettings() {
  if (!state.settingsOpen) {
    return;
  }
  stopHotkeyCapture(true);
  els.settings.hidden = true;
  state.settingsOpen = false;
  syncInert();
  if (settingsLastFocus && typeof settingsLastFocus.focus === "function") {
    settingsLastFocus.focus();
  } else {
    els.input.focus();
  }
  settingsLastFocus = null;
}

function startHotkeyCapture() {
  if (!state.settingsOpen || state.recordingHotkey) {
    return;
  }
  state.recordingHotkey = true;
  els.hotkeyInput.classList.add("recording");
  els.hotkeyInput.value = "Нажми сочетание…";
  clearSettingsError();
}

function stopHotkeyCapture(restore = true) {
  if (!state.recordingHotkey) {
    return;
  }
  state.recordingHotkey = false;
  els.hotkeyInput.classList.remove("recording");
  if (restore) {
    applySettingsToUi();
  }
}

async function saveHotkey(accelerator) {
  state.recordingHotkey = false;
  els.hotkeyInput.classList.remove("recording");
  const ok = await saveSettingsPatch({ hotkey: accelerator });
  if (ok) {
    showToast(`Горячая клавиша: ${formatHotkey(accelerator)}`);
    els.hotkeyInput.blur();
  } else {
    applySettingsToUi();
  }
}

async function toggleAutostart() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  state.settingsBusy = true;
  els.autostartToggle.disabled = true;
  const desired = !state.settings.autostart;
  const ok = await saveSettingsPatch({ autostart: desired });
  els.autostartToggle.disabled = false;
  state.settingsBusy = false;
  if (ok) {
    showToast(desired ? "Автозапуск включён." : "Автозапуск выключен.");
  } else {
    applySettingsToUi();
  }
}

async function saveBudget() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  const value = Number(String(els.budgetInput.value).replace(",", "."));
  if (!Number.isFinite(value) || value < 0 || value > 1000000) {
    showSettingsError("Бюджет должен быть числом от 0 до 1 000 000 ₽.");
    applySettingsToUi();
    return;
  }
  if (Math.abs(value - Number(state.settings.budget_limit_rub)) < 0.001) {
    return;
  }
  state.settingsBusy = true;
  const ok = await saveSettingsPatch({ budget_limit_rub: value });
  state.settingsBusy = false;
  if (ok) {
    showToast("Лимит бюджета сохранён.");
    refreshSummary();
  } else {
    applySettingsToUi();
  }
}

async function saveVoiceLanguage() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  const value = els.voiceLanguage.value;
  if (!["ru", "en", "auto"].includes(value)) {
    applySettingsToUi();
    return;
  }
  if (value === state.settings.voice_language) {
    return;
  }
  state.settingsBusy = true;
  const ok = await saveSettingsPatch({ voice_language: value });
  state.settingsBusy = false;
  if (ok) {
    showToast("Язык голосового ввода сохранён.");
  } else {
    applySettingsToUi();
  }
}

async function toggleSalesModule() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  state.settingsBusy = true;
  els.salesToggle.disabled = true;
  const desired = !state.settings.sales_module;
  const ok = await saveSettingsPatch({ sales_module: desired });
  els.salesToggle.disabled = false;
  state.settingsBusy = false;
  if (ok) {
    showToast(desired ? "Модуль продаж включён." : "Модуль продаж выключен.");
  } else {
    applySettingsToUi();
  }
}

async function saveModel() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  const value = els.modelSelect.value;
  if (!["deepseek-v4.1-flash", "glm-5.3-flash", "gpt-6-luna", "claude-haiku-5.5"].includes(value)) {
    applySettingsToUi();
    return;
  }
  if (value === state.settings.model) {
    return;
  }
  state.settingsBusy = true;
  const ok = await saveSettingsPatch({ model: value });
  state.settingsBusy = false;
  if (ok) {
    showToast("Модель сохранена.");
  } else {
    applySettingsToUi();
  }
}

async function saveTheme() {
  if (!state.settings || state.settingsBusy) {
    return;
  }
  const value = els.themeSelect.value === "dark" ? "dark" : "light";
  applyTheme(value);
  if (value === state.settings.theme) {
    return;
  }
  state.settingsBusy = true;
  const ok = await saveSettingsPatch({ theme: value });
  state.settingsBusy = false;
  if (!ok) {
    applySettingsToUi();
  }
}

async function saveUserPrompt() {
  if (!state.settings || state.settingsBusy) {
    return false;
  }
  const value = els.userPrompt.value.trim().slice(0, promptLimit());
  if (value === (state.settings.user_prompt || "")) {
    return true;
  }
  state.settingsBusy = true;
  const ok = await saveSettingsPatch({ user_prompt: value });
  state.settingsBusy = false;
  if (ok) {
    showToast("Системный промт сохранён.");
  } else {
    applySettingsToUi();
  }
  return ok;
}

async function resetUserPrompt() {
  const fallback = (state.promptInfo?.default_prompt || "").slice(0, promptLimit());
  els.userPrompt.value = fallback;
  updatePromptCounter();
  const ok = await saveUserPrompt();
  if (ok) {
    showToast("Промт сброшен к стандартному.");
  }
}

function handleSettingsChanged(settings) {
  if (!settings) {
    return;
  }
  state.settings = settings;
  if (!state.recordingHotkey) {
    applySettingsToUi();
  }
}

function bindEvents() {
  els.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    submitTask();
  });

  els.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      els.composer.requestSubmit();
    }
  });

  els.newTask.addEventListener("click", () => {
    if (state.running) {
      showToast("Сначала дождись конца задачи или нажми «Стоп».");
      return;
    }
    state.chatId = "";
    els.feed.replaceChildren();
    currentCard = null;
    renderRecent(state.chats);
    els.input.focus();
  });

  els.mic.addEventListener("click", openVoice);
  els.voiceStop.addEventListener("click", () => stopVoiceRecording());
  els.voiceRetry.addEventListener("click", retryVoice);
  els.voiceCancel.addEventListener("click", closeVoice);

  els.voice.addEventListener("click", (event) => {
    if (event.target === els.voice) {
      closeVoice();
    }
  });

  els.reject.addEventListener("click", () => answerConfirm("reject"));
  els.edit.addEventListener("click", enterEditMode);
  els.approve.addEventListener("click", () =>
    answerConfirm(state.editing ? "edit" : "approve"),
  );

  els.settingsBtn.addEventListener("click", openSettings);
  els.settingsClose.addEventListener("click", closeSettings);
  els.settingsDone.addEventListener("click", closeSettings);
  els.settings.addEventListener("click", (event) => {
    if (event.target === els.settings) {
      closeSettings();
    }
  });

  els.hotkeyInput.addEventListener("click", startHotkeyCapture);
  els.hotkeyInput.addEventListener("blur", () => stopHotkeyCapture(true));
  els.hotkeyInput.addEventListener("keydown", async (event) => {
    if (!state.recordingHotkey) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        startHotkeyCapture();
      }
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "Escape") {
      stopHotkeyCapture(true);
      els.hotkeyInput.blur();
      return;
    }
    const result = acceleratorFromEvent(event);
    if (!result) {
      return;
    }
    if (result.error) {
      showSettingsError(result.error);
      return;
    }
    await saveHotkey(result.accelerator);
  });

  els.autostartToggle.addEventListener("click", toggleAutostart);

  els.budgetInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      els.budgetInput.blur();
    }
  });
  els.budgetInput.addEventListener("blur", saveBudget);
  els.voiceLanguage.addEventListener("change", saveVoiceLanguage);
  els.salesToggle.addEventListener("click", toggleSalesModule);
  els.speechToggle.addEventListener("click", toggleSpeechEnabled);
  els.speechVoice.addEventListener("change", saveSpeechVoice);
  els.speechRate.addEventListener("change", saveSpeechRange);
  els.speechVolume.addEventListener("change", saveSpeechRange);
  els.speakStop.addEventListener("click", stopSpeaking);
  els.clipboardBtn.addEventListener("click", takeFromClipboard);
  els.memoryToggle.addEventListener("click", toggleMemoryEnabled);
  els.memoryClear.addEventListener("click", clearMemory);
  els.memoryExport.addEventListener("click", exportMemory);
  els.launchToggle.addEventListener("click", toggleLaunchWithoutConfirm);
  els.modelSelect.addEventListener("change", saveModel);
  els.themeSelect.addEventListener("change", saveTheme);
  els.userPrompt.addEventListener("input", updatePromptCounter);
  els.userPrompt.addEventListener("blur", saveUserPrompt);
  els.promptReset.addEventListener("click", resetUserPrompt);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Tab") {
      trapFocus(event);
      return;
    }
    if (event.key !== "Escape") {
      return;
    }
    if (!els.modal.hidden) {
      event.preventDefault();
      if (!state.modalBusy) {
        answerConfirm("reject");
      }
      return;
    }
    if (state.settingsOpen) {
      event.preventDefault();
      if (state.recordingHotkey) {
        stopHotkeyCapture(true);
        els.hotkeyInput.blur();
      } else {
        closeSettings();
      }
      return;
    }
    if (!els.voice.hidden) {
      event.preventDefault();
      closeVoice();
      return;
    }
    window.omega.hide();
  });

  document.addEventListener("click", async (event) => {
    const copyButton = event.target.closest(".code-copy");
    if (copyButton) {
      const wrapper = copyButton.closest(".code-block");
      const code = wrapper && wrapper.querySelector("code");
      if (code) {
        const copied = await copyText(code.textContent);
        copyButton.textContent = copied ? "Скопировано" : "Не вышло";
        window.setTimeout(() => {
          copyButton.textContent = "Копировать";
        }, 1600);
      }
      return;
    }
    const link = event.target.closest("a[data-external]");
    if (link) {
      event.preventDefault();
      window.omega.openExternal(link.href);
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && !els.voice.hidden) {
      closeVoice();
    }
    if (document.hidden) {
      stopSpeaking();
    }
  });

  window.omega.onFocusInput(() => {
    if (!els.modal.hidden || state.settingsOpen || !els.voice.hidden) {
      return;
    }
    els.input.focus();
  });

  window.omega.onOpenSettings(openSettings);
  window.omega.onSettingsChanged(handleSettingsChanged);
}

async function init() {
  bindEvents();
  if (window.speechSynthesis) {
    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", () => {
      loadVoices();
      renderVoiceOptions();
    });
  }
  try {
    const session = await window.omega.session();
    if (!session || !session.apiBase || !session.token) {
      throw new Error("Приложение не передало параметры соединения.");
    }
    state.apiBase = session.apiBase;
    state.token = session.token;
    try {
      const settings = await window.omega.getSettings();
      if (settings) {
        state.settings = settings;
        applySettingsToUi();
      }
    } catch {
      state.settings = null;
    }
    await refreshSummary();
    await loadChats();
    els.input.focus();
  } catch (error) {
    const card = createAssistantCard("Ошибка запуска");
    failCard(card, error.message || String(error));
  }
}

init();
