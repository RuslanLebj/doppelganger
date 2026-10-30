"use strict";
const data = JSON.parse(document.getElementById("app-data").textContent);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const paths = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  database:
    "M20 6c0 2-3.6 3.5-8 3.5S4 8 4 6s3.6-3.5 8-3.5S20 4 20 6z M4 6v12c0 2 3.6 3.5 8 3.5s8-1.5 8-3.5V6 M4 12c0 2 3.6 3.5 8 3.5s8-1.5 8-3.5",
  clock: "M12 7v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  history: "M3 11a9 9 0 1 1 2.6 7 M3 4v7h7 M12 7v5l3 2",
  archive: "M4 8v12h16V8 M3 3h18v5H3z M9 12h6",
  logout: "M9 4H4v16h5 M13 8l4 4-4 4 M8 12h13",
  plus: "M12 5v14 M5 12h14",
  pause: "M8 5v14 M16 5v14",
  check: "M5 12l4 4L19 6",
  alert: "M12 8v5 M12 17h.01 M10 3L2 19h20L14 3z",
  shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6",
  search: "M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  edit: "M14 5l5 5 M4 15L17 2l5 5L9 20l-6 1z",
  play: "M7 4l14 8-14 8z",
  arrow: "M5 12h14 M14 7l5 5-5 5",
  retry: "M20 7v5h-5 M20 12a8 8 0 1 1-2-6",
};
const icon = (name) =>
  `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.database}"/></svg>`;
document
  .querySelectorAll("[data-icon]")
  .forEach((node) => (node.innerHTML = icon(node.dataset.icon)));
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const targets = new Map(data.targets.map((item) => [item.id, item]));
const plans = new Map(data.plans.map((item) => [item.id, item]));
const statusNames = {
  success: "Успешно",
  failed: "Ошибка",
  interrupted: "Прервано",
  running: "Выполняется",
  queued: "В очереди",
};
const chip = (status) =>
  `<span class="chip ${esc(status)}">${esc(statusNames[status] || status)}</span>`;
const date = (value, short = false) =>
  value
    ? new Intl.DateTimeFormat(
        "ru-RU",
        short
          ? {
              day: "numeric",
              month: "short",
              hour: "2-digit",
              minute: "2-digit",
            }
          : {
              day: "numeric",
              month: "short",
              year: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            },
      ).format(new Date(value))
    : "—";
const size = (bytes) =>
  bytes == null
    ? "—"
    : bytes < 1048576
      ? `${Math.max(1, Math.round(bytes / 1024))} КБ`
      : bytes < 1073741824
        ? `${(bytes / 1048576).toFixed(1)} МБ`
        : `${(bytes / 1073741824).toFixed(2)} ГБ`;
const duration = (run) => {
  if (!run.started_at || !run.finished_at) return "—";
  const s = Math.round(
    (new Date(run.finished_at) - new Date(run.started_at)) / 1000,
  );
  return s < 60 ? `${s} сек.` : `${Math.floor(s / 60)} мин. ${s % 60} сек.`;
};
let view = "overview",
  search = "",
  filter = "",
  editingTarget = null,
  editingPlan = null;
let toastTimer;
function toast(message) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), 4200);
}
function errorMessage(result) {
  if (Array.isArray(result.detail))
    return result.detail
      .map((e) => {
        if (e.loc.includes("cron"))
          return "Укажите ежедневный cron: минута час * * *, например 0 2 * * *.";
        if (e.loc.includes("timezone"))
          return "Укажите существующий часовой пояс, например Asia/Yekaterinburg.";
        return `${e.loc.slice(1).join(".")}: ${e.msg}`;
      })
      .join("; ");
  const message = result.detail || "Не удалось выполнить действие";
  if (message.includes("run history"))
    return "У плана уже есть история. Для другой базы создайте новый план.";
  if (message.includes("Duplicate name"))
    return "Такое имя уже используется или запуск уже находится в очереди.";
  if (message.includes("disabled")) return "Исполнитель бэкапов отключён.";
  return message;
}
async function request(path, method = "POST", body) {
  const response = await fetch(`/admin${path}`, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401 || response.redirected) {
    location.href = "/admin/login";
    throw new Error("Войдите в рабочее пространство");
  }
  const result = await response.json();
  if (!response.ok) throw new Error(errorMessage(result));
  return result;
}
function reload(message) {
  sessionStorage.setItem("doppelganger-notice", message);
  location.reload();
}
const empty = (title, description, action = "") =>
  `<div class="empty-state"><div class="empty-icon">${icon("database")}</div><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
const newTargetButton = `<button class="button secondary small" data-action="new-target">${icon("plus")}Добавить базу</button>`;
const tableShell = (head, body) =>
  `<div class="table-scroll"><table><thead><tr>${head.map((t) => `<th>${t}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
function dbCell(target, fallback = "База данных") {
  return `<div class="db-cell"><span class="db-icon">${icon("database")}</span><span><strong class="cell-title">${esc(target?.name || fallback)}</strong><span class="cell-sub">${esc(target?.database || "")}</span></span></div>`;
}
function runRows(limit) {
  let rows = data.runs.filter((run) => {
    const plan = plans.get(run.plan_id),
      target = targets.get(plan?.target_id);
    return (
      (!filter || run.status === filter) &&
      `${target?.name || ""} ${plan?.name || ""} ${run.id}`
        .toLowerCase()
        .includes(search)
    );
  });
  if (limit) rows = rows.slice(0, limit);
  if (!rows.length)
    return empty(
      data.runs.length ? "Запуски не найдены" : "Первый бэкап ещё впереди",
      data.runs.length
        ? "Попробуйте другой запрос или фильтр."
        : "Добавьте базу и настройте расписание. Здесь появится история резервных копий.",
      !data.targets.length ? newTargetButton : "",
    );
  return tableShell(
    ["БАЗА ДАННЫХ", "ЗАПУСК", "ДЛИТЕЛЬНОСТЬ", "РАЗМЕР", "СТАТУС", ""],
    rows
      .map((run) => {
        const plan = plans.get(run.plan_id),
          target = targets.get(plan?.target_id);
        const retry =
          ["failed", "interrupted"].includes(run.status) && run.dump_path;
        return `<tr><td>${dbCell(target, plan?.name)}</td><td><span>${esc(date(run.started_at || run.created_at, true))}</span><span class="cell-sub">#${run.id} · ${run.trigger === "schedule" ? "По расписанию" : "Вручную"}</span></td><td>${esc(duration(run))}</td><td class="mono">${size(run.dump_bytes)}</td><td>${chip(run.status)}</td><td>${retry ? `<button class="icon-button" data-action="retry" data-id="${run.id}" ${data.execution_enabled ? "" : "disabled"} title="Повторить загрузку" aria-label="Повторить загрузку">${icon("retry")}</button>` : ""}</td></tr>${view === "history" && run.error ? `<tr class="error-row"><td colspan="6">${esc(run.error)}</td></tr>` : ""}`;
      })
      .join(""),
  );
}
function chart() {
  if (!data.runs.length)
    return empty(
      "Пока нет данных",
      "После первых запусков здесь появится активность за неделю.",
    );
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - 6 + i);
    return { date: d, ok: 0, failed: 0 };
  });
  data.runs.forEach((run) => {
    const d = new Date(run.created_at);
    const day = days.find(
      (x) =>
        d >= x.date &&
        d <
          new Date(
            x.date.getFullYear(),
            x.date.getMonth(),
            x.date.getDate() + 1,
          ),
    );
    if (day) {
      if (run.status === "success") day.ok++;
      else if (["failed", "interrupted"].includes(run.status)) day.failed++;
    }
  });
  const max = Math.max(1, ...days.map((d) => d.ok + d.failed));
  return `<div class="chart">${days.map((d) => `<div class="chart-day"><em>${d.ok + d.failed || ""}</em><div class="chart-bar" style="height:${Math.max(3, ((d.ok + d.failed) / max) * 115)}px"><span class="failed" style="height:${(d.failed / max) * 115}px"></span></div><label>${new Intl.DateTimeFormat("ru-RU", { weekday: "short" }).format(d.date)}</label></div>`).join("")}</div><div class="chart-caption"><span><i class="legend-dot"></i>Успешно</span><span><i class="legend-dot failed"></i>С ошибкой</span><span>До 100 последних запусков</span></div>`;
}
function overview() {
  const stats = [
    ["Подключено баз", data.targets.length, "database", "Источники PostgreSQL"],
    [
      "Планов включено",
      data.plans.filter((p) => p.enabled).length,
      "clock",
      "Ежедневные расписания",
    ],
    [
      "Успешно за 24 часа",
      data.counts.success || 0,
      "check",
      "Завершённые бэкапы",
    ],
    [
      "Ошибок за 24 часа",
      (data.counts.failed || 0) + (data.counts.interrupted || 0),
      "alert",
      "Требуют внимания",
    ],
  ];
  return `<div class="stats-grid">${stats.map((s, i) => `<div class="stat-card ${i === 3 ? "error" : ""}"><div class="stat-top"><span>${s[0]}</span>${icon(s[2])}</div><div class="stat-value ${i === 3 && s[1] ? "has-errors" : ""}">${s[1]}</div><div class="stat-bottom">${s[3]}</div></div>`).join("")}</div><div class="overview-grid"><section class="panel"><div class="panel-header"><div><h3>Активность бэкапов</h3><p>Последние 7 дней</p></div><a class="panel-link" href="#history">История ${icon("arrow")}</a></div>${chart()}</section><section class="panel retention-panel"><div class="retention-top">${icon("shield")}Политика хранения</div><div class="retention-main"><strong>${data.retention_days ? `${data.retention_days} дней` : "Без срока"}</strong><p>История резервных копий в S3-хранилище</p></div><div class="retention-footer">${icon("check")}Последняя копия — без срока</div></section></div><section class="panel"><div class="panel-header"><div><h3>Последние запуски</h3><p>Результаты резервного копирования</p></div><a class="panel-link" href="#history">Все запуски ${icon("arrow")}</a></div>${runRows(5)}</section>`;
}
function databaseRows() {
  const rows = data.targets.filter((t) =>
    `${t.name} ${t.database} ${t.host}`.toLowerCase().includes(search),
  );
  if (!rows.length)
    return empty(
      data.targets.length ? "Базы не найдены" : "Подключите первую базу",
      "Добавьте параметры подключения PostgreSQL, затем задайте время резервного копирования.",
      !data.targets.length ? newTargetButton : "",
    );
  return tableShell(
    ["БАЗА ДАННЫХ", "ПОДКЛЮЧЕНИЕ", "ПОЛЬЗОВАТЕЛЬ", "ЗАЩИТА", "РАСПИСАНИЯ", ""],
    rows
      .map(
        (t) =>
          `<tr><td>${dbCell(t)}</td><td class="mono">${esc(t.host)}:${t.port}</td><td>${esc(t.username)}</td><td><span class="chip ${t.sslmode === "disable" ? "neutral" : "success"}">${t.sslmode === "disable" ? "Без TLS" : "TLS"}</span></td><td>${data.plans.filter((p) => p.target_id === t.id).length}</td><td><button class="icon-button" data-action="edit-target" data-id="${t.id}" title="Редактировать базу" aria-label="Редактировать базу">${icon("edit")}</button></td></tr>`,
      )
      .join(""),
  );
}
function scheduleRows() {
  const rows = data.plans.filter((p) =>
    `${p.name} ${targets.get(p.target_id)?.name || ""} ${p.cron}`
      .toLowerCase()
      .includes(search),
  );
  if (!rows.length)
    return empty(
      data.plans.length
        ? "Расписания не найдены"
        : "Пусть бэкапы работают по расписанию",
      data.targets.length
        ? "Укажите cron и часовой пояс для ежедневного резервного копирования."
        : "Сначала добавьте базу, для которой нужно выполнять бэкапы.",
      data.targets.length
        ? `<button class="button secondary small" data-action="new-plan">${icon("plus")}Новое расписание</button>`
        : newTargetButton,
    );
  return tableShell(
    ["РАСПИСАНИЕ", "CRON", "СЛЕДУЮЩИЙ ЗАПУСК", "СОСТОЯНИЕ", ""],
    rows
      .map(
        (p) =>
          `<tr><td><strong class="cell-title">${esc(p.name)}</strong><span class="cell-sub">${esc(targets.get(p.target_id)?.name || "База данных")}</span></td><td><span class="mono">${esc(p.cron)}</span><span class="cell-sub">${esc(p.timezone)}</span></td><td>${p.enabled ? esc(date(p.next_run_at, true)) : "—"}</td><td><button class="toggle ${p.enabled ? "on" : ""}" data-action="toggle-plan" data-id="${p.id}" aria-label="${p.enabled ? "Отключить" : "Включить"} расписание" aria-pressed="${p.enabled}"></button><span>${p.enabled ? "Включено" : "Пауза"}</span></td><td><div class="row-actions"><button class="icon-button" data-action="run" data-id="${p.id}" ${data.execution_enabled ? "" : "disabled"} title="Создать бэкап сейчас" aria-label="Создать бэкап сейчас">${icon("play")}</button><button class="icon-button" data-action="edit-plan" data-id="${p.id}" title="Редактировать расписание" aria-label="Редактировать расписание">${icon("edit")}</button></div></td></tr>`,
      )
      .join(""),
  );
}
const descriptions = {
  overview: [
    "ВСЁ ПОД КОНТРОЛЕМ",
    "Обзор",
    "Состояние резервных копий вашего рабочего пространства.",
  ],
  databases: [
    "ИСТОЧНИКИ ДАННЫХ",
    "Базы данных",
    "Подключения PostgreSQL, для которых выполняются бэкапы.",
  ],
  schedules: [
    "АВТОМАТИЗАЦИЯ",
    "Расписания",
    "Время запуска, cron и часовой пояс для каждой базы.",
  ],
  history: [
    "ЖУРНАЛ ОПЕРАЦИЙ",
    "История запусков",
    "Последние 100 запусков: результат, время и размер копии.",
  ],
};
function paintTable() {
  const node = document.getElementById("table-content");
  if (node)
    node.innerHTML =
      view === "databases"
        ? databaseRows()
        : view === "schedules"
          ? scheduleRows()
          : runRows();
}
function render() {
  view = location.hash.slice(1);
  if (!descriptions[view]) view = "overview";
  search = "";
  filter = "";
  const info = descriptions[view];
  document.title = `${info[1]} · doppelganger`;
  document.getElementById("page-eyebrow").textContent = info[0];
  document.getElementById("page-title").textContent = info[1];
  document.getElementById("breadcrumb-page").textContent = info[1];
  document.getElementById("page-description").textContent = info[2];
  document.getElementById("main-action-label").textContent =
    view === "schedules" ? "Новое расписание" : "Добавить базу";
  document.getElementById("main-action").hidden = view === "history";
  document
    .querySelectorAll("[data-nav]")
    .forEach((node) =>
      node.classList.toggle("active", node.dataset.nav === view),
    );
  const body = document.getElementById("page-body");
  if (view === "overview") {
    body.innerHTML = overview();
    return;
  }
  body.innerHTML = `<section class="panel"><div class="toolbar"><label class="search-box">${icon("search")}<input id="table-search" placeholder="${view === "databases" ? "Найти базу..." : view === "schedules" ? "Найти расписание..." : "Найти запуск..."}" aria-label="Поиск"></label>${
    view === "history"
      ? `<select class="filter-select" id="status-filter" aria-label="Статус"><option value="">Все статусы</option>${Object.entries(
          statusNames,
        )
          .map(([key, name]) => `<option value="${key}">${name}</option>`)
          .join("")}</select>`
      : `<span class="muted">${view === "databases" ? data.targets.length : data.plans.length} записей</span>`
  }</div><div id="table-content"></div><div class="table-footer"><span>${view === "history" ? "Показано до 100 последних запусков" : "Настройки рабочего пространства"}</span><span>PostgreSQL backups</span></div></section>`;
  document.getElementById("table-search").addEventListener("input", (event) => {
    search = event.target.value.toLowerCase();
    paintTable();
  });
  document
    .getElementById("status-filter")
    ?.addEventListener("change", (event) => {
      filter = event.target.value;
      paintTable();
    });
  paintTable();
}
function openTarget(id) {
  editingTarget = id ?? null;
  const form = document.getElementById("target-form");
  form.reset();
  const t = targets.get(id);
  document.getElementById("target-dialog-title").textContent = t
    ? "Параметры базы"
    : "Новая база данных";
  for (const name of [
    "name",
    "host",
    "port",
    "database",
    "username",
    "sslmode",
  ])
    if (t) form.elements[name].value = t[name];
  form.elements.password.required = !t;
  form.elements.password.placeholder = t
    ? "Оставьте пустым, чтобы сохранить пароль"
    : "Пароль подключения";
  form.querySelector(".form-error").hidden = true;
  document.getElementById("target-dialog").showModal();
}
function openPlan(id) {
  if (!data.targets.length) {
    toast("Сначала добавьте базу данных");
    return;
  }
  editingPlan = id ?? null;
  const form = document.getElementById("plan-form");
  form.reset();
  form.elements.target_id.innerHTML = data.targets
    .map(
      (t) =>
        `<option value="${t.id}">${esc(t.name)} · ${esc(t.database)}</option>`,
    )
    .join("");
  const p = plans.get(id);
  document.getElementById("plan-dialog-title").textContent = p
    ? "Параметры расписания"
    : "Новое расписание";
  if (p) {
    for (const name of [
      "name",
      "target_id",
      "cron",
      "timezone",
      "max_dump_seconds",
      "lock_wait_seconds",
    ])
      form.elements[name].value = p[name];
    form.elements.enabled.checked = p.enabled;
  }
  form.querySelector(".form-error").hidden = true;
  document.getElementById("plan-dialog").showModal();
}
document
  .getElementById("main-action")
  .addEventListener("click", () =>
    view === "schedules" ? openPlan() : openTarget(),
  );
document
  .querySelectorAll(".close-dialog")
  .forEach((button) =>
    button.addEventListener("click", () => button.closest("dialog").close()),
  );
document
  .getElementById("target-form")
  .addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget,
      button = form.querySelector('[type="submit"]'),
      body = Object.fromEntries(new FormData(form));
    body.port = Number(body.port);
    if (editingTarget && !body.password) delete body.password;
    button.disabled = true;
    try {
      await request(
        editingTarget ? `/targets/${editingTarget}` : "/targets",
        editingTarget ? "PUT" : "POST",
        body,
      );
      reload("Подключение сохранено");
    } catch (error) {
      const box = form.querySelector(".form-error");
      box.textContent = error.message;
      box.hidden = false;
    } finally {
      button.disabled = false;
    }
  });
document
  .getElementById("plan-form")
  .addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget,
      button = form.querySelector('[type="submit"]'),
      body = Object.fromEntries(new FormData(form));
    for (const key of ["target_id", "max_dump_seconds", "lock_wait_seconds"])
      body[key] = Number(body[key]);
    body.enabled = form.elements.enabled.checked;
    button.disabled = true;
    try {
      await request(
        editingPlan ? `/plans/${editingPlan}` : "/plans",
        editingPlan ? "PUT" : "POST",
        body,
      );
      reload("Расписание сохранено");
    } catch (error) {
      const box = form.querySelector(".form-error");
      box.textContent = error.message;
      box.hidden = false;
    } finally {
      button.disabled = false;
    }
  });
document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action,
    id = Number(button.dataset.id);
  if (action === "new-target") return openTarget();
  if (action === "new-plan") return openPlan();
  if (action === "edit-target") return openTarget(id);
  if (action === "edit-plan") return openPlan(id);
  button.disabled = true;
  try {
    if (action === "run") {
      await request(`/plans/${id}/runs`);
      reload("Запуск добавлен в очередь");
    } else if (action === "retry") {
      await request(`/runs/${id}/retry`);
      reload("Загрузка добавлена в очередь повторно");
    } else if (action === "toggle-plan") {
      const p = plans.get(id);
      await request(`/plans/${id}`, "PUT", {
        name: p.name,
        target_id: p.target_id,
        cron: p.cron,
        timezone: p.timezone,
        enabled: !p.enabled,
        max_dump_seconds: p.max_dump_seconds,
        lock_wait_seconds: p.lock_wait_seconds,
      });
      reload(p.enabled ? "Расписание приостановлено" : "Расписание включено");
    }
  } catch (error) {
    toast(error.message);
    button.disabled = false;
  }
});
document.getElementById("logout").addEventListener("click", async () => {
  try {
    await request("/logout");
    location.href = "/admin/login";
  } catch (error) {
    toast(error.message);
  }
});
document.getElementById("execution-notice").hidden = data.execution_enabled;
document.getElementById("target-badge").textContent = data.targets.length;
document.getElementById("plan-badge").textContent = data.plans.length;
document.getElementById("footer-date").textContent = new Intl.DateTimeFormat(
  "ru-RU",
  { day: "numeric", month: "long", year: "numeric" },
).format(new Date());
window.addEventListener("hashchange", render);
render();
const notice = sessionStorage.getItem("doppelganger-notice");
if (notice) {
  sessionStorage.removeItem("doppelganger-notice");
  toast(notice);
}
