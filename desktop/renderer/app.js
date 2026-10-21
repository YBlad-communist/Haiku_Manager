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
  recordingHotkey: false,
  settingsBusy: false,
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
  chipChannel: document.getElementById("chipChannel"),
  chipToday: document.getElementById("chipToday"),
  modalError: document.getElementById("modalError"),
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
};

const TOOL_LABELS = {
  search_web: "Ищу в интернете",
  fetch_page: "Читаю страницу",
  save_to_table: "Сохраняю таблицу",
  search_companies_2gis: "Ищу компании в 2ГИС",
  draft_message: "Готовлю черновик",
  send_message: "Проверяю отправку",
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

function showToast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    els.toast.hidden = true;
  }, 2600);
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
  const stopButton = node.querySelector(".stop-btn");
  stopButton.hidden = true;
  const refs = {
    card: node,
    title: titleNode,
    stop: stopButton,
    steps: node.querySelector(".steps"),
    foot: node.querySelector(".card-foot"),
    answer: node.querySelector(".answer"),
  };
  stopButton.addEventListener("click", stopTask);
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
  if (event.type === "draft_edited") {
    showToast("Текст черновика изменён.");
    return;
  }
  if (event.type === "final") {
    finishCard(event);
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

  const answer = String(event.answer || "").trim() || "Готово.";
  currentCard.refs.answer.hidden = false;
  currentCard.refs.answer.classList.toggle(
    "error",
    reason !== "done" && reason !== "max_steps",
  );
  if (reason === "done" || reason === "max_steps") {
    renderMarkdown(currentCard.refs.answer, answer);
  } else {
    currentCard.refs.answer.textContent = answer;
  }

  if (event.remaining_rub !== undefined && event.remaining_rub !== null) {
    els.budgetValue.textContent = formatRub(event.remaining_rub, 2);
  }

  currentCard = null;
  refreshSummary();
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
  els.newTask.disabled = false;
}

async function streamTask(task) {
  const response = await fetch(api("/api/task"), {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ task }),
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

async function submitTask() {
  const task = els.input.value.trim();
  if (!task || state.running) {
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

function renderRecent(tasks) {
  els.recent.replaceChildren();
  if (!tasks || !tasks.length) {
    const empty = document.createElement("p");
    empty.className = "recent-empty";
    empty.textContent = "Пока пусто.";
    els.recent.append(empty);
    return;
  }
  for (const item of tasks.slice(0, 8)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ci recent-item";
    button.textContent = truncate(item.task);
    button.title = item.task || "";
    button.addEventListener("click", () => showHistory(item));
    els.recent.append(button);
  }
}

function showHistory(item) {
  if (state.running) {
    showToast("Сначала дождись конца текущей задачи или нажми «Стоп».");
    return;
  }
  els.feed.replaceChildren();
  addUserMessage(item.task || "");
  const card = document.createElement("article");
  card.className = "assistant cl";
  const title = document.createElement("h2");
  title.className = "assistant-title";
  title.textContent = "Прошлая задача";
  const answer = document.createElement("div");
  answer.className = "answer";
  renderMarkdown(answer, item.answer || "Ответ не сохранился.");
  const foot = document.createElement("p");
  foot.className = "card-foot";
  foot.textContent =
    `${Number(item.steps || 0)} шаг(ов) · ${formatCost(item.cost || 0)} · ${formatDate(item.created_at)}`;
  card.append(title, answer, foot);
  els.feed.append(card);
  scrollFeed();
  els.input.focus();
}

async function refreshSummary() {
  try {
    const data = await apiJson("/api/summary");
    state.maxSteps = Number(data.max_steps || 8);
    els.budgetValue.textContent = formatRub(data.remaining_rub, 2);
    renderRecent(data.history || []);
  } catch (error) {
    showToast(`Не удалось загрузить историю: ${error.message}`);
  }
}

function openConfirm(event) {
  state.pending = event;
  state.editing = false;
  state.modalBusy = false;

  const isSend = event.kind === "send_message";
  els.modalTitle.textContent = event.title || "Подтвердить действие?";
  els.modalSubtitle.textContent = isSend
    ? `Помощник хочет написать компании «${event.company || event.recipient || "без названия"}»`
    : "Помощник просит подтверждение действия.";
  els.draftText.textContent = String(event.text || "");
  els.draftText.hidden = false;
  els.draftEdit.value = String(event.text || "");
  els.draftEdit.hidden = true;
  els.modalChips.hidden = !isSend;
  els.chipChannel.textContent = `Канал: ${event.channel || "—"}`;
  els.chipToday.textContent = `Сегодня: ${event.today || 0} из ${event.limit || 0}`;
  els.edit.hidden = !isSend;
  els.approve.textContent = isSend ? "Отправить" : "Подтвердить";
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

  let text = "";
  if (action === "edit") {
    text = els.draftEdit.value.trim();
    if (text.length < 20) {
      els.modalError.textContent = "Текст слишком короткий: нужно минимум 20 символов.";
      els.modalError.hidden = false;
      els.draftEdit.focus();
      return;
    }
  }

  setModalBusy(true);
  els.modalError.hidden = true;
  try {
    await apiJson("/api/confirm", {
      method: "POST",
      body: JSON.stringify({ id: event.id, action, text }),
    });
    closeConfirm();
    if (action === "edit") {
      showToast("Текст изменён и подтверждён.");
    }
  } catch (error) {
    els.modalError.textContent = error.message;
    els.modalError.hidden = false;
    setModalBusy(false);
  }
}

function enterEditMode() {
  if (!state.pending || state.pending.kind !== "send_message" || state.editing) {
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
      : null;
  if (!scope) {
    return;
  }
  const focusable = Array.from(
    scope.querySelectorAll(
      "button, textarea, input, [tabindex]:not([tabindex='-1'])",
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

function openVoice() {
  els.voice.hidden = false;
  syncInert();
  els.voice.focus();
}

function closeVoice() {
  els.voice.hidden = true;
  syncInert();
  els.input.focus();
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
    els.feed.replaceChildren();
    currentCard = null;
    els.input.focus();
  });

  els.mic.addEventListener("click", openVoice);

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
    els.input.focus();
  } catch (error) {
    const card = createAssistantCard("Ошибка запуска");
    failCard(card, error.message || String(error));
  }
}

init();
