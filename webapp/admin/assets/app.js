/* global Telegram */

const tg = window.Telegram?.WebApp;
if (tg) {
  tg.expand();
  tg.ready();
}

function apiUrl(path) {
  const base = document.querySelector("base")?.href || `${window.location.origin}/admin/`;
  return new URL(path, base).toString();
}

function getInitData() {
  return tg?.initData || "";
}

async function api(path, body = {}) {
  const initData = getInitData();
  const res = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ init_data: initData, ...body }),
  });
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error("Некорректный ответ сервера");
  }
  if (!res.ok) {
    const msg = data?.error || data?.message || res.statusText;
    throw new Error(typeof msg === "string" ? msg : "Ошибка запроса");
  }
  if (data.ok === false) throw new Error(data.error || "Ошибка");
  return data;
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => {
    el.hidden = true;
  }, 3200);
}

function esc(s) {
  if (s == null) return "";
  const d = document.createElement("div");
  d.textContent = String(s);
  return d.innerHTML;
}

let route = "dash";
let usersPage = 1;
let usersQ = "";
let payPeriod = "month";
let selectedUserId = null;

const main = document.getElementById("main");
const sidebar = document.getElementById("sidebar");
const navToggle = document.getElementById("navToggle");
const envPill = document.getElementById("envPill");

function closeDrawer() {
  sidebar.classList.remove("open");
  document.getElementById("backdrop")?.classList.remove("show");
}

function openDrawer() {
  sidebar.classList.add("open");
  let bd = document.getElementById("backdrop");
  if (!bd) {
    bd = document.createElement("div");
    bd.id = "backdrop";
    bd.className = "drawer-backdrop";
    bd.addEventListener("click", closeDrawer);
    document.body.appendChild(bd);
  }
  bd.classList.add("show");
}

navToggle?.addEventListener("click", () => {
  if (sidebar.classList.contains("open")) closeDrawer();
  else openDrawer();
});

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    route = btn.dataset.route;
    closeDrawer();
    render();
  });
});

async function renderDashboard() {
  main.innerHTML = '<p class="empty">Загрузка дашборда…</p>';
  const { data } = await api("api/dashboard");
  const rev = data.revenue;
  const act = data.active_users;
  main.innerHTML = `
    <div class="grid-stats">
      <div class="card"><h3>Пользователей</h3><div class="val">${data.users_total}</div></div>
      <div class="card"><h3>Открытий рецептов</h3><div class="val">${data.opens_total}</div></div>
      <div class="card"><h3>Покупок рецептов</h3><div class="val">${data.purchases_total}</div></div>
    </div>
    <div class="section-title">Активные пользователи (открывали рецепт)</div>
    <div class="grid-stats">
      <div class="card"><h3>За день</h3><div class="val">${act.day}</div></div>
      <div class="card"><h3>За 7 дней</h3><div class="val">${act.week}</div></div>
      <div class="card"><h3>За 30 дней</h3><div class="val">${act.month}</div></div>
    </div>
    <div class="section-title">Доход (Telegram Stars, сумма из учёта оплат)</div>
    <div class="grid-stats">
      <div class="card"><h3>Сегодня</h3><div class="val">${rev.today} ⭐</div></div>
      <div class="card"><h3>7 дней</h3><div class="val">${rev.week} ⭐</div></div>
      <div class="card"><h3>30 дней</h3><div class="val">${rev.month} ⭐</div></div>
    </div>
    <p class="row-muted" style="margin:8px 0 16px">Раньше оплаты могли не попадать в учёт — строки появляются после обновления бота.</p>
    <div class="section-title">Популярные рецепты</div>
    <div class="table-wrap"><table><thead><tr><th>ID</th><th>Название</th><th>Открытий</th></tr></thead>
    <tbody>${data.popular_recipes.map((r) => `<tr><td>${r.recipe_id}</td><td>${esc(r.title)}</td><td>${r.opens}</td></tr>`).join("") || '<tr><td colspan="3" class="empty">Нет данных</td></tr>'}</tbody></table></div>
    <div class="section-title">Популярные кухни</div>
    <div class="table-wrap"><table><thead><tr><th>Кухня</th><th>Открытий</th></tr></thead>
    <tbody>${data.popular_cuisines.map((c) => `<tr><td>${esc(c.cuisine_label || c.cuisine)}</td><td>${c.opens}</td></tr>`).join("") || '<tr><td colspan="2" class="empty">Нет данных</td></tr>'}</tbody></table></div>
  `;
}

async function renderUsers() {
  main.innerHTML = '<p class="empty">Загрузка…</p>';
  const { data } = await api("api/users/list", { page: usersPage, page_size: 20, q: usersQ });
  const rows = data.items
    .map(
      (u) => `
    <tr data-uid="${u.user_id}">
      <td><code>${u.user_id}</code></td>
      <td>${esc(u.username ? "@" + u.username : "—")}</td>
      <td>${esc(u.first_name || "—")}</td>
      <td>${u.created_at ? u.created_at.slice(0, 10) : "—"}</td>
      <td>${u.opened_recipes}</td>
      <td>${u.purchased_recipes}</td>
      <td>${u.stars_paid_total} ⭐</td>
      <td>${u.referral_free_bonus}</td>
      <td><span class="chip ${u.is_blocked ? "" : "ok"}">${u.is_blocked ? "блок" : "ок"}</span></td>
      <td><button type="button" class="btn btn-secondary btn-small btn-open-user">Подробнее</button></td>
    </tr>`
    )
    .join("");
  main.innerHTML = `
    <div class="toolbar">
      <input type="search" id="userSearch" placeholder="ID или часть @username / имени" value="${esc(usersQ)}" />
      <button type="button" class="btn btn-primary" id="userSearchBtn">Поиск</button>
    </div>
    <div class="table-wrap"><table><thead><tr>
      <th>ID</th><th>Username</th><th>Имя</th><th>Регистрация</th><th>Открыто</th><th>Куплено</th><th>Звёзды оплач.</th><th>Бонус откр.</th><th>Статус</th><th></th>
    </tr></thead><tbody>${rows || '<tr><td colspan="10" class="empty">Никого не найдено</td></tr>'}</tbody></table></div>
    <div class="pager">
      <button type="button" class="btn btn-secondary" id="prevPage" ${data.page <= 1 ? "disabled" : ""}>Назад</button>
      <span class="row-muted">стр. ${data.page} · всего ${data.total}</span>
      <button type="button" class="btn btn-secondary" id="nextPage" ${data.items.length < 20 ? "disabled" : ""}>Вперёд</button>
    </div>
    <div id="userDetailMount"></div>
  `;
  document.getElementById("userSearchBtn").onclick = () => {
    usersQ = document.getElementById("userSearch").value.trim();
    usersPage = 1;
    render();
  };
  document.getElementById("prevPage").onclick = () => {
    usersPage = Math.max(1, usersPage - 1);
    render();
  };
  document.getElementById("nextPage").onclick = () => {
    usersPage += 1;
    render();
  };
  main.querySelectorAll(".btn-open-user").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const tr = e.target.closest("tr");
      selectedUserId = +tr.dataset.uid;
      loadUserDetail(selectedUserId);
    });
  });
  if (selectedUserId) loadUserDetail(selectedUserId);
}

async function loadUserDetail(uid) {
  const mount = document.getElementById("userDetailMount");
  if (!mount) return;
  mount.innerHTML = '<p class="empty">Загрузка карточки…</p>';
  try {
    const { data } = await api(`api/users/${uid}`);
    const blocked = data.is_blocked;
    mount.innerHTML = `
      <div class="detail-panel">
        <h2>Пользователь ${data.user_id}</h2>
        <dl class="kv">
          <dt>Username</dt><dd>${data.username ? "@" + esc(data.username) : "—"}</dd>
          <dt>Имя</dt><dd>${esc(data.first_name || "—")}</dd>
          <dt>Регистрация</dt><dd>${esc(data.created_at || "—")}</dd>
          <dt>Последняя активность</dt><dd>${esc(data.last_seen_at || "—")}</dd>
          <dt>Открыто рецептов</dt><dd>${data.opened_recipes}</dd>
          <dt>Куплено рецептов</dt><dd>${data.purchased_recipes}</dd>
          <dt>Звёзды (сумма оплат в боте)</dt><dd>${data.stars_paid_total} ⭐ <span class="row-muted">баланс кошелька Telegram боту недоступен</span></dd>
          <dt>Бонусные открытия</dt><dd>${data.referral_free_bonus}</dd>
          <dt>Бесплатных «ещё» использовано</dt><dd>${data.free_show_more_uses}</dd>
          <dt>Ожидает реферера</dt><dd>${data.pending_referrer_id ?? "—"}</dd>
          <dt>Подписка до</dt><dd>${esc(data.subscription_expires_at || "—")}</dd>
          <dt>Халяль только</dt><dd>${data.halal_only ? "да" : "нет"}</dd>
          <dt>Макс. время (мин)</dt><dd>${data.max_time_minutes ?? "—"}</dd>
          <dt>Строго по времени</dt><dd>${data.time_strict ? "да" : "нет"}</dd>
        </dl>
        <div class="actions-row">
          <button type="button" class="btn ${blocked ? "btn-primary" : "btn-danger"}" id="toggleBlock">${blocked ? "Разблокировать" : "Заблокировать"}</button>
          <input type="number" min="1" max="500" value="10" id="bonusAmount" style="max-width:100px" />
          <button type="button" class="btn btn-secondary" id="grantBonus">Выдать бонус открытий</button>
          <button type="button" class="btn btn-secondary" id="grantFreeRecipes">+10 бесплатных открытий</button>
        </div>
      </div>`;
    document.getElementById("toggleBlock").onclick = async () => {
      await api(`api/users/${uid}/block`, { blocked: !blocked });
      toast(blocked ? "Разблокирован" : "Заблокирован");
      render();
    };
    document.getElementById("grantBonus").onclick = async () => {
      const n = +document.getElementById("bonusAmount").value;
      await api(`api/users/${uid}/bonus`, { bonus_opens: n });
      toast(`Начислено +${n} открытий`);
      render();
    };
    document.getElementById("grantFreeRecipes").onclick = async () => {
      await api(`api/users/${uid}/bonus`, { bonus_opens: 10 });
      toast("+10 бесплатных открытий");
      render();
    };
  } catch (e) {
    mount.innerHTML = `<p class="empty">${esc(e.message)}</p>`;
  }
}

async function renderPayments() {
  main.innerHTML = '<p class="empty">Загрузка…</p>';
  const { data } = await api("api/payments/list", { period: payPeriod });
  const rows = data.items
    .map(
      (p) => `
    <tr>
      <td>${p.created_at ? p.created_at.replace("T", " ").slice(0, 19) : "—"}</td>
      <td><code>${p.user_id}</code> ${esc(p.user_label || "")}</td>
      <td>${esc(p.payment_type)}</td>
      <td>${p.recipe_id ? "#" + p.recipe_id + " " + esc(p.recipe_title || "") : "—"}</td>
      <td>${p.amount} ⭐</td>
    </tr>`
    )
    .join("");
  main.innerHTML = `
    <div class="toolbar">
      <label class="row-muted">Период:</label>
      <select id="payPeriod">
        <option value="today" ${payPeriod === "today" ? "selected" : ""}>Сегодня</option>
        <option value="week" ${payPeriod === "week" ? "selected" : ""}>Неделя</option>
        <option value="month" ${payPeriod === "month" ? "selected" : ""}>Месяц</option>
      </select>
    </div>
    <div class="table-wrap"><table><thead><tr><th>Дата</th><th>Пользователь</th><th>Тип</th><th>Рецепт</th><th>Сумма</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="5" class="empty">Нет платежей за период</td></tr>'}</tbody></table></div>
  `;
  document.getElementById("payPeriod").onchange = (e) => {
    payPeriod = e.target.value;
    render();
  };
}

async function renderSettings() {
  main.innerHTML = '<p class="empty">Загрузка…</p>';
  const { data } = await api("api/settings");
  main.innerHTML = `
    <p class="row-muted" style="margin-bottom:16px">Значения применяются сразу к новым счетам и логике бота. Цены на уже отправленные инвойсы не меняются.</p>
    <form class="form-grid" id="settingsForm">
      <label>Бесплатных полных открытий (база)<input type="number" name="base_free_recipe_opens" value="${data.base_free_recipe_opens}" min="0" max="999" /></label>
      <label>Цена рецепта (⭐)<input type="number" name="recipe_star_price" value="${data.recipe_star_price}" min="1" max="99999" /></label>
      <label>Цена «Показать ещё» (⭐)<input type="number" name="show_more_star_price" value="${data.show_more_star_price}" min="1" max="99999" /></label>
      <label>Цена подписки (⭐)<input type="number" name="subscription_star_price" value="${data.subscription_star_price}" min="1" max="99999" /></label>
      <label>Подписка по умолчанию (дней)<input type="number" name="subscription_default_days" value="${data.subscription_default_days}" min="1" max="3650" /></label>
      <label>Бесплатно «Показать ещё» (раз)<input type="number" name="free_show_more_count" value="${data.free_show_more_count}" min="0" max="999" /></label>
      <label>Реф. бонус (открытий)<input type="number" name="referral_bonus_opens" value="${data.referral_bonus_opens}" min="0" max="9999" /></label>
    </form>
    <div style="margin-top:16px"><button type="button" class="btn btn-primary" id="saveSettings">Сохранить</button></div>
    ${data.updated_at ? `<p class="row-muted" style="margin-top:12px">Последнее обновление в БД: ${esc(data.updated_at)}</p>` : ""}
  `;
  document.getElementById("saveSettings").onclick = async () => {
    const fd = new FormData(document.getElementById("settingsForm"));
    const patch = {};
    for (const [k, v] of fd.entries()) patch[k] = +v;
    await api("api/settings/update", patch);
    toast("Сохранено");
    render();
  };
}

async function renderReferrals() {
  main.innerHTML = '<p class="empty">Загрузка…</p>';
  const { data } = await api("api/referrals/list");
  const rows = data.items
    .map(
      (r) => `
    <tr>
      <td>${r.created_at ? r.created_at.slice(0, 19).replace("T", " ") : "—"}</td>
      <td><code>${r.referrer_id}</code> ${esc(r.referrer_label || "")}</td>
      <td><code>${r.invitee_id}</code> ${esc(r.invitee_label || "")}</td>
      <td>${r.bonus_granted ? '<span class="chip ok">начислен</span>' : '<span class="chip">ожидает</span>'}</td>
    </tr>`
    )
    .join("");
  main.innerHTML = `
    <div class="table-wrap"><table><thead><tr><th>Дата</th><th>Пригласивший</th><th>Приглашённый</th><th>Бонус</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="4" class="empty">Нет записей</td></tr>'}</tbody></table></div>
  `;
}

async function render() {
  try {
    if (route === "dash") await renderDashboard();
    else if (route === "users") await renderUsers();
    else if (route === "pay") await renderPayments();
    else if (route === "settings") await renderSettings();
    else if (route === "ref") await renderReferrals();
  } catch (e) {
    main.innerHTML = `<div class="card"><p>${esc(e.message)}</p><p class="row-muted">Откройте панель из Telegram (кнопка WebApp) и проверьте ADMIN_USER_IDS / HTTPS URL.</p></div>`;
    toast(e.message);
  }
}

function initTheme() {
  if (!tg) return;
  const p = tg.themeParams;
  if (p.bg_color) document.documentElement.style.setProperty("--bg", p.bg_color);
  if (p.secondary_bg_color)
    document.documentElement.style.setProperty("--surface", p.secondary_bg_color);
  if (p.text_color) document.documentElement.style.setProperty("--text", p.text_color);
  if (p.hint_color) document.documentElement.style.setProperty("--muted", p.hint_color);
  if (p.link_color) document.documentElement.style.setProperty("--accent", p.link_color);
}

async function boot() {
  initTheme();
  if (!getInitData()) {
    envPill.textContent = "нет initData";
    main.innerHTML =
      '<div class="card empty">Откройте эту страницу через кнопку WebApp в боте (/admin), иначе авторизация невозможна.</div>';
    return;
  }
  envPill.textContent = "Telegram";
  await render();
}

boot();
