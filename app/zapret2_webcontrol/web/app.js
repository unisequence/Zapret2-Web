const byId = (id) => document.getElementById(id);

const state = {
  system: null,
  strategies: [],
  lists: [],
  status: null,
  preview: null,
  blockcheck: null,
  autostart: null,
};

async function requestJson(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  let result = {};
  try {
    result = await response.json();
  } catch (_) {
    // The status and URL below are more useful than a JSON parse error.
  }
  if (!response.ok) {
    throw new Error(result.message || result.error || `${response.status} ${url}`);
  }
  return result;
}

function sendJson(method, url, payload) {
  return requestJson(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function setConnection(ok) {
  const element = byId("connection");
  element.textContent = ok ? "Подключено" : "Нет связи";
  element.className = `status-pill ${ok ? "status-ok" : "status-danger"}`;
}

function showFlash(message, isError = false) {
  const flash = byId("flash");
  flash.textContent = message;
  flash.className = `flash${isError ? " is-error" : ""}`;
  flash.hidden = false;
  window.clearTimeout(showFlash.timer);
  showFlash.timer = window.setTimeout(() => { flash.hidden = true; }, 3500);
}

function renderStatus(status) {
  const summary = byId("runtime-summary");
  summary.textContent = status.running ? `Работает: PID ${status.pid || "?"}` : "Не запущен";
  summary.className = `status-pill ${status.running ? "status-ok" : "status-muted"}`;
  const engine = state.system?.platform === "linux" ? "nfqws2 не найден" : "winws2.exe не найден";
  byId("engine-path").value = status.executable || engine;
  byId("stop-runtime").disabled = !status.running || !["managed", "service"].includes(status.control_mode);
  byId("checked-at").textContent = `проверено в ${new Date(status.checked_at).toLocaleTimeString("ru-RU")}`;
}

function renderReadiness(preview, status) {
  const summary = byId("configuration-summary");
  const ready = preview.warnings.length === 0;
  summary.textContent = ready ? `Готово: ${preview.active_strategy_ids.length} профилей` : `${preview.warnings.length} проблем`;
  summary.className = `status-pill ${ready ? "status-ok" : "status-danger"}`;
  const canControl = state.system?.capabilities?.includes("process_control");
  byId("start-runtime").disabled = status.running || !ready || !canControl;
}

function renderBlockcheck(status) {
  state.blockcheck = status;
  const summary = byId("blockcheck-status");
  if (!status.available) {
    summary.textContent = "Бандл не найден";
    summary.className = "status-pill status-danger";
  } else if (status.running) {
    summary.textContent = `Работает: PID ${status.pid}`;
    summary.className = "status-pill status-ok";
  } else if (status.exit_code !== null) {
    summary.textContent = status.exit_code === 0 ? "Завершён" : `Код выхода: ${status.exit_code}`;
    summary.className = `status-pill ${status.exit_code === 0 ? "status-ok" : "status-danger"}`;
  } else {
    summary.textContent = "Готов";
    summary.className = "status-pill status-muted";
  }
  byId("start-blockcheck").disabled = !status.available || status.running || Boolean(state.status?.running);
  byId("stop-blockcheck").disabled = !status.running;
  byId("blockcheck-timing").textContent = status.started_at
    ? `Запущен: ${new Date(status.started_at).toLocaleString("ru-RU")}`
    : "—";
  if (status.tests?.length) {
    const select = byId("blockcheck-test");
    const selected = select.value;
    select.replaceChildren();
    for (const test of status.tests) {
      const option = document.createElement("option");
      option.value = test;
      option.textContent = test;
      select.appendChild(option);
    }
    if (status.tests.includes(selected)) select.value = selected;
  }
}

function renderAutostart(status) {
  state.autostart = status;
  const summary = byId("autostart-summary");
  const toggle = byId("autostart-toggle");
  const sync = byId("sync-autostart");
  if (!status.installed) {
    summary.textContent = "Выключен";
    summary.className = "status-pill status-muted";
    toggle.textContent = "Включить автозапуск";
    toggle.className = "button button-ghost";
  } else if (!status.in_sync) {
    summary.textContent = "Требует применения";
    summary.className = "status-pill status-danger";
    toggle.textContent = "Выключить автозапуск";
    toggle.className = "button button-danger-outline";
  } else {
    summary.textContent = status.running ? "Включен · работает" : "Включен";
    summary.className = `status-pill ${status.running ? "status-ok" : "status-muted"}`;
    toggle.textContent = "Выключить автозапуск";
    toggle.className = "button button-danger-outline";
  }
  toggle.disabled = !status.can_manage;
  sync.hidden = !status.installed || status.in_sync;
  sync.disabled = status.running || !status.can_manage;
  byId("service-name").value = status.service;
  byId("service-state").value = !status.installed
    ? "Не установлена"
    : status.running
      ? "Работает, автоматический запуск"
      : status.in_sync
        ? "Остановлена, автоматический запуск"
        : "Остановлена, конфигурация устарела";
  if (status.installed && !status.in_sync) byId("start-runtime").disabled = true;
}

function makeCell(text) {
  const cell = document.createElement("span");
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function renderStrategies(items, running) {
  const container = byId("strategy-list");
  container.replaceChildren();
  byId("strategy-count").textContent = `${items.filter((item) => item.enabled).length} включено · ${items.length} всего`;
  byId("reset-strategies").disabled = running;
  byId("add-strategy").disabled = running;

  for (const strategy of items) {
    const row = document.createElement("div");
    row.className = "strategy-table strategy-row";

    const nameCell = document.createElement("span");
    nameCell.className = "strategy-name";
    const toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggle.checked = strategy.enabled;
    toggle.disabled = running;
    toggle.setAttribute("aria-label", `Включить ${strategy.name}`);
    toggle.addEventListener("change", async () => {
      toggle.disabled = true;
      try {
        await updateStrategy(strategy.id, { enabled: toggle.checked });
        showFlash(`Стратегия ${strategy.name} сохранена`);
      } catch (error) {
        toggle.checked = !toggle.checked;
        showFlash(error.message, true);
      } finally {
        toggle.disabled = Boolean(state.status?.running);
      }
    });
    const name = document.createElement("strong");
    name.textContent = strategy.name;
    nameCell.append(toggle, name);
    row.appendChild(nameCell);
    row.appendChild(makeCell(strategy.ports.join(", ")));
    row.appendChild(makeCell(strategy.protocol));
    row.appendChild(makeCell(strategy.filter_l7.join(", ") || "—"));
    row.appendChild(makeCell(strategy.hostlist || "—"));

    const actions = document.createElement("span");
    actions.className = "row-actions";
    const edit = document.createElement("button");
    edit.className = "button button-small button-ghost";
    edit.textContent = "Редактировать";
    edit.disabled = running;
    edit.addEventListener("click", () => openStrategyEditor(strategy.id));
    actions.appendChild(edit);

    const copy = document.createElement("button");
    copy.className = "button button-small button-ghost";
    copy.textContent = "Копировать";
    copy.disabled = running;
    copy.addEventListener("click", () => openNewStrategy(strategy));
    actions.appendChild(copy);

    if (strategy.source === "custom") {
      const remove = document.createElement("button");
      remove.className = "button button-small button-danger-outline";
      remove.textContent = "Удалить";
      remove.disabled = running;
      remove.addEventListener("click", () => deleteStrategy(strategy));
      actions.appendChild(remove);
    }
    row.appendChild(actions);
    container.appendChild(row);
  }
}

function renderLists(items, running) {
  const container = byId("list-resources");
  container.replaceChildren();
  for (const item of items) {
    const row = document.createElement("div");
    const main = document.createElement("span");
    main.className = "resource-main";
    const title = document.createElement("strong");
    title.textContent = item.label;
    const description = document.createElement("span");
    description.textContent = `${item.filename} · ${item.description}`;
    main.append(title, description);

    const meta = document.createElement("span");
    meta.className = "resource-meta";
    const details = document.createElement("span");
    details.textContent = `${item.entries} записей`;
    const edit = document.createElement("button");
    edit.className = "button button-small button-ghost";
    edit.textContent = "Редактировать";
    edit.disabled = running;
    edit.addEventListener("click", () => openListEditor(item.id));
    meta.append(details, edit);
    row.append(main, meta);
    container.appendChild(row);
  }
}

async function loadDashboard() {
  try {
    const [system, status, strategies, preview, lists, blockcheck, autostart] = await Promise.all([
      requestJson("/api/v1/system"),
      requestJson("/api/v1/status"),
      requestJson("/api/v1/strategies"),
      requestJson("/api/v1/strategies/preview"),
      requestJson("/api/v1/lists"),
      requestJson("/api/v1/blockcheck/status"),
      requestJson("/api/v1/autostart"),
    ]);
    state.system = system;
    state.status = status;
    state.strategies = strategies.items;
    state.preview = preview;
    state.lists = lists.items;
    renderStatus(status);
    renderReadiness(preview, status);
    renderStrategies(strategies.items, status.running);
    renderLists(lists.items, status.running);
    renderBlockcheck(blockcheck);
    renderAutostart(autostart);
    setConnection(true);
  } catch (error) {
    setConnection(false);
    byId("runtime-summary").textContent = "Ошибка API";
  }
}

async function updateStrategy(strategyId, patch) {
  const result = await sendJson("PATCH", `/api/v1/strategies/${encodeURIComponent(strategyId)}`, patch);
  state.preview = result.preview;
  await loadDashboard();
  return result.item;
}

async function openListEditor(listId) {
  const errorBox = byId("list-error");
  errorBox.hidden = true;
  try {
    const document = await requestJson(`/api/v1/lists/${encodeURIComponent(listId)}`);
    byId("list-id").value = listId;
    byId("list-dialog-title").textContent = document.info.label;
    byId("list-dialog-subtitle").textContent = `${document.info.path} · ${document.info.entries} записей`;
    byId("list-content").value = document.content;
    byId("list-dialog").showModal();
  } catch (error) {
    showFlash(error.message, true);
  }
}

function closeListEditor() {
  byId("list-dialog").close();
}

async function saveList(event) {
  event.preventDefault();
  const saveButton = byId("save-list");
  const errorBox = byId("list-error");
  saveButton.disabled = true;
  errorBox.hidden = true;
  try {
    const listId = byId("list-id").value;
    await sendJson("PUT", `/api/v1/lists/${encodeURIComponent(listId)}`, {
      content: byId("list-content").value,
    });
    closeListEditor();
    await loadDashboard();
    showFlash("Список сохранён");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    saveButton.disabled = false;
  }
}

async function loadAutolist() {
  try {
    const document = await requestJson("/api/v1/lists/auto");
    byId("autolist-content").value = document.content;
    byId("autolist-summary").textContent = `${document.info.entries} записей`;
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function saveAutolist() {
  try {
    await sendJson("PUT", "/api/v1/lists/auto", { content: byId("autolist-content").value });
    await loadDashboard();
    await loadAutolist();
    showFlash("Автолист сохранён");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function loadRuntimeLog() {
  try {
    const log = await requestJson("/api/v1/logs/runtime");
    byId("runtime-log-path").textContent = `${log.path}${log.truncated ? " · показан конец файла" : ""}`;
    byId("runtime-log").textContent = log.content || "Лог пока пуст.";
  } catch (error) {
    byId("runtime-log").textContent = error.message;
  }
}

async function clearRuntimeLog() {
  if (!window.confirm("Очистить локальный журнал winws2?")) return;
  try {
    await sendJson("POST", "/api/v1/logs/runtime/clear", { confirm: true });
    await loadRuntimeLog();
    showFlash("Журнал очищен");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function loadBlockcheck() {
  try {
    const [status, log] = await Promise.all([
      requestJson("/api/v1/blockcheck/status"),
      requestJson("/api/v1/blockcheck/log"),
    ]);
    renderBlockcheck(status);
    byId("blockcheck-log").textContent = log.content || "Лог пока пуст.";
  } catch (error) {
    byId("blockcheck-log").textContent = error.message;
  }
}

function blockcheckProtocols() {
  const protocols = [];
  if (byId("blockcheck-http").checked) protocols.push("http");
  if (byId("blockcheck-tls12").checked) protocols.push("https_tls12");
  if (byId("blockcheck-tls13").checked) protocols.push("https_tls13");
  if (byId("blockcheck-http3").checked) protocols.push("http3");
  return protocols;
}

async function startBlockcheck() {
  const warning = "Blockcheck2 остановит совместимость с работающими DPI bypass-процессами, временно запустит WinDivert-фильтры и может включить TCP timestamps в Windows. Запустить тест?";
  if (!window.confirm(warning)) return;
  try {
    await sendJson("POST", "/api/v1/blockcheck/start", {
      confirm: true,
      options: {
        domain: byId("blockcheck-domain").value.trim(),
        test: byId("blockcheck-test").value,
        scan_level: byId("blockcheck-level").value,
        ip_version: byId("blockcheck-ip").value,
        repeats: Number(byId("blockcheck-repeats").value),
        timeout: Number(byId("blockcheck-timeout").value),
        protocols: blockcheckProtocols(),
        parallel: byId("blockcheck-parallel").checked,
        skip_dns: byId("blockcheck-skip-dns").checked,
        skip_ip_block: byId("blockcheck-skip-ip").checked,
      },
    });
    await loadDashboard();
    await loadBlockcheck();
    showFlash("Blockcheck2 запущен");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function stopBlockcheck() {
  if (!window.confirm("Остановить Blockcheck2 и выполнить очистку временных фильтров?")) return;
  try {
    await sendJson("POST", "/api/v1/blockcheck/stop", { confirm: true });
    await loadDashboard();
    await loadBlockcheck();
    showFlash("Blockcheck2 остановлен");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function installAutostart() {
  const action = state.autostart?.installed ? "обновить" : "создать";
  if (!window.confirm(`${action === "создать" ? "Создать" : "Обновить"} Windows-службу zapret2-webcontrol с автоматическим запуском от имени системы?`)) return;
  try {
    await sendJson("POST", "/api/v1/autostart/install", { confirm: true });
    await loadDashboard();
    showFlash("Конфигурация автозапуска применена");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function toggleAutostart() {
  if (!state.autostart?.installed) {
    await installAutostart();
    return;
  }
  if (!window.confirm("Остановить и удалить Windows-службу zapret2-webcontrol? Стратегии и списки останутся на месте.")) return;
  try {
    await sendJson("POST", "/api/v1/autostart/remove", { confirm: true });
    await loadDashboard();
    showFlash("Автозапуск выключен");
  } catch (error) {
    showFlash(error.message, true);
  }
}

function openStrategyEditor(strategyId) {
  const strategy = state.strategies.find((item) => item.id === strategyId);
  if (!strategy) return;
  byId("strategy-id").value = strategy.id;
  byId("strategy-dialog-title").textContent = strategy.name;
  byId("strategy-dialog-subtitle").textContent = `Профиль ${strategy.id}`;
  byId("strategy-name").value = strategy.name;
  byId("strategy-enabled").checked = strategy.enabled;
  byId("strategy-protocol").value = strategy.protocol;
  byId("strategy-ports").value = strategy.ports.join(", ");
  byId("strategy-l7").value = strategy.filter_l7.join(", ");
  byId("strategy-hostlist").value = strategy.hostlist || "";
  byId("strategy-options").value = strategy.ordered_options.join("\n");
  byId("strategy-metadata").textContent = "Параметры перехвата, Lua и blob добавляются автоматически.";
  byId("strategy-error").hidden = true;
  byId("strategy-dialog").showModal();
}

function openNewStrategy(template = null) {
  byId("strategy-id").value = "";
  byId("strategy-dialog-title").textContent = template ? "Копирование стратегии" : "Новая стратегия";
  byId("strategy-dialog-subtitle").textContent = template
    ? `На основе ${template.name}; копия создаётся выключенной`
    : "Пользовательский профиль";
  byId("strategy-name").value = template ? `${template.name} copy` : "";
  byId("strategy-enabled").checked = false;
  byId("strategy-protocol").value = template?.protocol || "tcp";
  byId("strategy-ports").value = template?.ports.join(", ") || "443";
  byId("strategy-l7").value = template?.filter_l7.join(", ") || "tls";
  byId("strategy-hostlist").value = template?.hostlist || "";
  byId("strategy-options").value = template?.ordered_options.join("\n") || "--payload=tls_client_hello\n--lua-desync=multisplit:pos=1";
  byId("strategy-metadata").textContent = "Параметры перехвата, Lua и blob добавляются автоматически.";
  byId("strategy-error").hidden = true;
  byId("strategy-dialog").showModal();
  byId("strategy-name").focus();
}

function closeStrategyEditor() {
  byId("strategy-dialog").close();
}

function commaList(value) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

async function saveStrategy(event) {
  event.preventDefault();
  const strategyId = byId("strategy-id").value;
  const errorBox = byId("strategy-error");
  const saveButton = byId("save-strategy");
  errorBox.hidden = true;
  saveButton.disabled = true;
  try {
    const payload = {
      name: byId("strategy-name").value.trim(),
      enabled: byId("strategy-enabled").checked,
      protocol: byId("strategy-protocol").value,
      ports: commaList(byId("strategy-ports").value),
      filter_l7: commaList(byId("strategy-l7").value),
      hostlist: byId("strategy-hostlist").value.trim() || null,
      ordered_options: byId("strategy-options").value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
    };
    if (strategyId) {
      await updateStrategy(strategyId, payload);
    } else {
      const result = await sendJson("POST", "/api/v1/strategies", payload);
      state.preview = result.preview;
      await loadDashboard();
    }
    closeStrategyEditor();
    showFlash(strategyId ? "Изменения стратегии сохранены" : "Пользовательская стратегия добавлена");
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    saveButton.disabled = false;
  }
}

async function deleteStrategy(strategy) {
  if (!window.confirm(`Удалить пользовательскую стратегию «${strategy.name}»?`)) return;
  try {
    await sendJson("DELETE", `/api/v1/strategies/${encodeURIComponent(strategy.id)}`, { confirm: true });
    await loadDashboard();
    showFlash("Пользовательская стратегия удалена");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function showPreview() {
  const panel = byId("preview-panel");
  panel.hidden = false;
  byId("command-preview").textContent = "Формируем команду…";
  byId("preview-warnings").replaceChildren();
  try {
    const preview = await requestJson("/api/v1/strategies/preview");
    state.preview = preview;
    byId("command-preview").textContent = preview.command_line;
    for (const warning of preview.warnings) {
      const item = document.createElement("div");
      item.className = "warning-item";
      item.textContent = warning;
      byId("preview-warnings").appendChild(item);
    }
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    byId("command-preview").textContent = "Не удалось сформировать preview.";
  }
}

async function resetStrategies() {
  if (!window.confirm("Сбросить все пользовательские изменения, включая добавленные стратегии, к значениям по умолчанию?")) return;
  try {
    await sendJson("POST", "/api/v1/strategies/reset", { confirm: true });
    await loadDashboard();
    showFlash("Изменения сброшены");
  } catch (error) {
    showFlash(error.message, true);
  }
}

async function changeRuntime(action) {
  const message = action === "start"
    ? "Запустить winws2 и изменить перехват сетевого трафика?"
    : "Остановить управляемый winws2?";
  if (!window.confirm(message)) return;
  try {
    await sendJson("POST", `/api/v1/runtime/${action}`, { confirm: true });
    await loadDashboard();
  } catch (error) {
    showFlash(error.message, true);
  }
}

document.querySelectorAll("[data-tab]").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach((item) => item.classList.toggle("is-active", item === tab));
    document.querySelectorAll("[data-panel]").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.panel === tab.dataset.tab));
    if (tab.dataset.tab === "autolist") loadAutolist();
    if (tab.dataset.tab === "logs") loadRuntimeLog();
    if (tab.dataset.tab === "blockcheck") loadBlockcheck();
  });
});

byId("refresh").addEventListener("click", loadDashboard);
byId("preview-command").addEventListener("click", showPreview);
byId("start-runtime").addEventListener("click", () => changeRuntime("start"));
byId("stop-runtime").addEventListener("click", () => changeRuntime("stop"));
byId("close-preview").addEventListener("click", () => { byId("preview-panel").hidden = true; });
byId("reset-strategies").addEventListener("click", resetStrategies);
byId("add-strategy").addEventListener("click", () => openNewStrategy());
byId("strategy-form").addEventListener("submit", saveStrategy);
byId("cancel-strategy").addEventListener("click", closeStrategyEditor);
byId("cancel-strategy-top").addEventListener("click", closeStrategyEditor);
byId("list-form").addEventListener("submit", saveList);
byId("cancel-list").addEventListener("click", closeListEditor);
byId("cancel-list-top").addEventListener("click", closeListEditor);
byId("save-autolist").addEventListener("click", saveAutolist);
byId("reload-autolist").addEventListener("click", loadAutolist);
byId("refresh-log").addEventListener("click", loadRuntimeLog);
byId("clear-log").addEventListener("click", clearRuntimeLog);
byId("start-blockcheck").addEventListener("click", startBlockcheck);
byId("stop-blockcheck").addEventListener("click", stopBlockcheck);
byId("refresh-blockcheck").addEventListener("click", loadBlockcheck);
byId("autostart-toggle").addEventListener("click", toggleAutostart);
byId("sync-autostart").addEventListener("click", installAutostart);

loadDashboard();
window.setInterval(loadDashboard, 10000);
window.setInterval(() => {
  if (state.blockcheck?.running) loadBlockcheck();
}, 3000);
