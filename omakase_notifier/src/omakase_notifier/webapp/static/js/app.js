/* Omakase Notifier — SPA front-end */

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

const api = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : null,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async put(url, body) {
    const r = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async del(url) {
    const r = await fetch(url, { method: "DELETE" });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
};

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 1800);
}

/* ---------------- Routing ---------------- */
const TITLES = {
  home: "ホーム",
  restaurants: "店舗",
  users: "ユーザー",
};

function activateView(view) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  $("#navTitle").textContent = TITLES[view] || "Omakase";
  if (view === "home") loadCalendar();
  if (view === "restaurants") loadRestaurants();
  if (view === "users") loadUsers();
}

window.addEventListener("hashchange", () => {
  const v = (location.hash || "#home").slice(1);
  activateView(v);
});

/* ---------------- Calendar ---------------- */
const cal = {
  year: 0,
  month: 0,
  selected: null,
  data: null,
};

function ymdToday() {
  const d = new Date();
  return [d.getFullYear(), d.getMonth() + 1, d.getDate()];
}

async function loadCalendar() {
  if (!cal.year) {
    const [y, m] = ymdToday();
    cal.year = y;
    cal.month = m;
  }
  $("#calTitle").textContent = `${cal.year}年${cal.month}月`;
  cal.data = await api.get(`/api/calendar/${cal.year}/${cal.month}`);
  renderCalendar();
}

function renderCalendar() {
  const grid = $("#calGrid");
  grid.innerHTML = "";
  const fw = cal.data.first_weekday; // Mon=0..Sun=6
  for (let i = 0; i < fw; i++) {
    const e = document.createElement("div");
    e.className = "cal-cell empty";
    grid.appendChild(e);
  }
  const [ty, tm, td] = ymdToday();
  for (let day = 1; day <= cal.data.days_in_month; day++) {
    const dateStr = `${cal.year}-${String(cal.month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const count = cal.data.availability[dateStr] || 0;
    const btn = document.createElement("button");
    btn.className = "cal-cell";
    if (count > 0) btn.classList.add("has-slots");
    if (cal.year === ty && cal.month === tm && day === td) btn.classList.add("today");
    if (cal.selected === dateStr) btn.classList.add("selected");
    btn.innerHTML = `<span>${day}</span>` + (count > 0 ? `<span class="dot" title="${count}店舗"></span>` : "");
    btn.addEventListener("click", () => selectDay(dateStr));
    grid.appendChild(btn);
  }
}

async function selectDay(dateStr) {
  cal.selected = dateStr;
  renderCalendar();
  $("#dayTitle").textContent = `${dateStr} の空席`;
  const slots = await api.get(`/api/calendar/day/${dateStr}`);
  const list = $("#slotList");
  const empty = $("#dayEmpty");
  list.innerHTML = "";
  if (!slots.length) {
    empty.style.display = "block";
    empty.textContent = "この日に空席はありません。";
    return;
  }
  empty.style.display = "none";
  for (const s of slots) {
    const dt = new Date(s.datetime);
    const time = `${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
    const li = document.createElement("li");
    const meta = [`${time}`, `${s.party_size}名`];
    if (s.price_jpy != null) meta.push(`¥${s.price_jpy.toLocaleString()}`);
    li.innerHTML = `
      <div class="name">${escapeHtml(s.restaurant.name)}</div>
      <div class="meta">${meta.map((m) => `<span>${escapeHtml(m)}</span>`).join("")}<a href="${escapeHtml(s.restaurant.url)}" target="_blank">店舗ページ</a></div>
      ${s.cancellation_policy ? `<div class="cancel">${escapeHtml(s.cancellation_policy)}</div>` : ""}
    `;
    list.appendChild(li);
  }
}

$("#calPrev").addEventListener("click", () => {
  cal.month--;
  if (cal.month < 1) { cal.month = 12; cal.year--; }
  cal.selected = null;
  loadCalendar();
});
$("#calNext").addEventListener("click", () => {
  cal.month++;
  if (cal.month > 12) { cal.month = 1; cal.year++; }
  cal.selected = null;
  loadCalendar();
});

/* ---------------- Restaurants ---------------- */
let restaurantsCache = [];

async function loadRestaurants(q = "") {
  const list = $("#restList");
  list.innerHTML = `<div class="list-empty">読み込み中…</div>`;
  restaurantsCache = await api.get(`/api/restaurants${q ? `?q=${encodeURIComponent(q)}` : ""}`);
  renderRestaurants();
}

function renderRestaurants() {
  const list = $("#restList");
  list.innerHTML = "";
  if (!restaurantsCache.length) {
    list.innerHTML = `<div class="list-empty">店舗が見つかりません。「リスト更新」を押してください。</div>`;
    return;
  }
  for (const r of restaurantsCache) {
    const row = document.createElement("div");
    row.className = "row";
    const subInfo = [r.area, r.genre].filter(Boolean).join(" · ");
    row.innerHTML = `
      <div class="left">
        <div class="name">${escapeHtml(r.name)}</div>
        <div class="sub">${escapeHtml(subInfo || r.omakase_id)} · 購読 ${r.subscribers}人</div>
      </div>
      <div style="display:flex; align-items:center; gap:8px;">
        ${r.has_open_slots ? `<span class="badge">空席</span>` : ""}
        <span class="chevron">›</span>
      </div>
    `;
    row.addEventListener("click", () => openRestaurantSheet(r));
    list.appendChild(row);
  }
}

$("#restSearch").addEventListener("input", (e) => loadRestaurants(e.target.value));
$("#refreshListBtn").addEventListener("click", async () => {
  const btn = $("#refreshListBtn");
  btn.disabled = true; btn.textContent = "更新中…";
  try {
    const r = await api.post("/api/restaurants/refresh");
    toast(`掲載店リスト更新: ${r.count} 件`);
    await loadRestaurants($("#restSearch").value);
  } catch (e) {
    toast("更新失敗: " + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "リスト更新";
  }
});

async function openRestaurantSheet(r) {
  const users = await api.get("/api/users");
  const usersWithSub = await Promise.all(
    users.map(async (u) => {
      const det = await api.get(`/api/users/${u.id}`);
      const sub = det.subscriptions.find((s) => s.restaurant_id === r.id);
      return { ...u, subscription: sub };
    })
  );
  openSheet(`購読 — ${r.name}`, () => {
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div class="muted" style="margin-bottom:12px">${escapeHtml([r.area, r.genre].filter(Boolean).join(" · "))}</div>
    `;
    const card = document.createElement("div");
    card.className = "card";
    if (!usersWithSub.length) {
      card.innerHTML = `<div class="list-empty">先に「ユーザー」タブでユーザーを作成してください。</div>`;
    } else {
      for (const u of usersWithSub) {
        const id = `usw_${u.id}`;
        const subbed = !!u.subscription;
        card.insertAdjacentHTML("beforeend", `
          <div class="toggle-row">
            <label>${escapeHtml(u.name)}<div class="muted" style="font-size:12px">${escapeHtml(u.email || u.line_user_id || "—")}</div></label>
            <label class="switch"><input type="checkbox" id="${id}" ${subbed ? "checked" : ""}/><span class="slider"></span></label>
          </div>
        `);
      }
    }
    wrap.appendChild(card);
    return wrap;
  }, async () => {
    for (const u of usersWithSub) {
      const checked = $(`#usw_${u.id}`)?.checked;
      const subbed = !!u.subscription;
      if (checked && !subbed) {
        await api.post(`/api/users/${u.id}/subscriptions`, { restaurant_id: r.id });
      } else if (!checked && subbed) {
        await api.del(`/api/subscriptions/${u.subscription.id}`);
      }
    }
    toast("購読を更新しました");
    await loadRestaurants($("#restSearch").value);
  });
}

/* ---------------- Users ---------------- */
let usersCache = [];
let activeUserId = null;

async function loadUsers() {
  usersCache = await api.get("/api/users");
  renderUserList();
  if (activeUserId && usersCache.some((u) => u.id === activeUserId)) {
    showUserDetail(activeUserId);
  } else if (usersCache.length) {
    showUserDetail(usersCache[0].id);
  } else {
    $("#userDetail").innerHTML = `<div class="muted" style="padding:24px">＋ 追加 でユーザーを作成してください。</div>`;
    activeUserId = null;
  }
}

function renderUserList() {
  const list = $("#userList");
  list.innerHTML = "";
  if (!usersCache.length) {
    list.innerHTML = `<div class="list-empty">ユーザーがありません</div>`;
    return;
  }
  for (const u of usersCache) {
    const row = document.createElement("div");
    row.className = "row";
    if (u.id === activeUserId) row.style.background = "var(--separator-soft)";
    row.innerHTML = `
      <div class="left">
        <div class="name">${escapeHtml(u.name)} ${u.enabled ? "" : `<span class="muted" style="font-size:12px">（無効）</span>`}</div>
        <div class="sub">${escapeHtml(u.email || u.line_user_id || "—")} · 購読 ${u.subscriptions}件</div>
      </div>
      <span class="chevron">›</span>
    `;
    row.addEventListener("click", () => showUserDetail(u.id));
    list.appendChild(row);
  }
}

async function showUserDetail(userId) {
  activeUserId = userId;
  renderUserList();
  const u = await api.get(`/api/users/${userId}`);
  const detail = $("#userDetail");
  detail.innerHTML = `
    <div class="card">
      <h2 class="section-title">基本情報</h2>
      <div class="field"><label>名前</label><input type="text" id="uName" value="${escapeAttr(u.name)}"/></div>
      <div class="field"><label>メールアドレス</label><input type="email" id="uEmail" value="${escapeAttr(u.email || "")}"/></div>
      <div class="field"><label>LINE User ID</label><input type="text" id="uLine" value="${escapeAttr(u.line_user_id || "")}"/></div>
      <div class="toggle-row">
        <label>通知を有効にする</label>
        <label class="switch"><input type="checkbox" id="uEnabled" ${u.enabled ? "checked" : ""}/><span class="slider"></span></label>
      </div>
      <div style="display:flex; gap:8px; padding:12px 16px; justify-content:flex-end;">
        <button class="danger" id="uDeleteBtn">削除</button>
        <button class="primary" id="uSaveBtn">保存</button>
      </div>
    </div>
    <div class="card">
      <h2 class="section-title" style="display:flex; justify-content:space-between; align-items:center; padding-right:8px">
        購読店舗
        <button class="btn-text" id="addSubBtn">＋ 追加</button>
      </h2>
      <div id="userSubs"></div>
    </div>
  `;

  const subsBox = $("#userSubs");
  if (!u.subscriptions.length) {
    subsBox.innerHTML = `<div class="list-empty">購読がありません</div>`;
  } else {
    subsBox.innerHTML = "";
    for (const s of u.subscriptions) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `
        <div class="left">
          <div class="name">${escapeHtml(s.restaurant_name)}</div>
          <div class="sub">${s.notify_email ? "メール" : ""}${s.notify_email && s.notify_line ? "・" : ""}${s.notify_line ? "LINE" : ""} · ${s.party_size_min}〜${s.party_size_max}名</div>
        </div>
        <button class="btn-text" data-sub-id="${s.id}" style="color:var(--red)">解除</button>
      `;
      row.querySelector("button").addEventListener("click", async (ev) => {
        ev.stopPropagation();
        if (!confirm(`${s.restaurant_name} の購読を解除しますか？`)) return;
        await api.del(`/api/subscriptions/${s.id}`);
        toast("購読を解除しました");
        await showUserDetail(userId);
        await loadUsers();
      });
      subsBox.appendChild(row);
    }
  }

  $("#uSaveBtn").addEventListener("click", async () => {
    await api.put(`/api/users/${userId}`, {
      name: $("#uName").value.trim(),
      email: $("#uEmail").value.trim() || null,
      line_user_id: $("#uLine").value.trim() || null,
      enabled: $("#uEnabled").checked,
    });
    toast("保存しました");
    await loadUsers();
  });
  $("#uDeleteBtn").addEventListener("click", async () => {
    if (!confirm(`${u.name} を削除しますか？（購読も全削除）`)) return;
    await api.del(`/api/users/${userId}`);
    activeUserId = null;
    await loadUsers();
  });
  $("#addSubBtn").addEventListener("click", () => addSubscriptionSheet(userId));
}

function addSubscriptionSheet(userId) {
  openSheet("購読を追加", () => {
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <input type="search" id="subSearch" placeholder="店舗を検索…" style="margin-bottom:12px"/>
      <div class="card list" id="subPickList" style="max-height:50vh; overflow-y:auto;"></div>
    `;
    return wrap;
  }, null);
  let q = "";
  const render = async () => {
    const list = $("#subPickList");
    const restaurants = await api.get(`/api/restaurants${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    list.innerHTML = "";
    if (!restaurants.length) {
      list.innerHTML = `<div class="list-empty">該当なし</div>`;
      return;
    }
    for (const r of restaurants) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = `
        <div class="left">
          <div class="name">${escapeHtml(r.name)}</div>
          <div class="sub">${escapeHtml([r.area, r.genre].filter(Boolean).join(" · ") || r.omakase_id)}</div>
        </div>
        <span class="chevron">＋</span>
      `;
      row.addEventListener("click", async () => {
        await api.post(`/api/users/${userId}/subscriptions`, { restaurant_id: r.id });
        toast(`${r.name} を購読しました`);
        closeSheet();
        await showUserDetail(userId);
        await loadUsers();
      });
      list.appendChild(row);
    }
  };
  setTimeout(() => {
    const search = $("#subSearch");
    search.addEventListener("input", (e) => {
      q = e.target.value;
      render();
    });
    render();
  }, 0);
}

$("#addUserBtn").addEventListener("click", () => {
  openSheet("新しいユーザー", () => {
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div class="card">
        <div class="field"><label>名前</label><input type="text" id="newName" placeholder="例: Taro"/></div>
        <div class="field"><label>メールアドレス</label><input type="email" id="newEmail" placeholder="taro@example.com"/></div>
        <div class="field"><label>LINE User ID（任意）</label><input type="text" id="newLine" placeholder="Uxxxxxxxxxxxxxxxx"/></div>
      </div>
    `;
    return wrap;
  }, async () => {
    const name = $("#newName").value.trim();
    if (!name) throw new Error("名前は必須です");
    const r = await api.post("/api/users", {
      name,
      email: $("#newEmail").value.trim() || null,
      line_user_id: $("#newLine").value.trim() || null,
    });
    toast("ユーザーを作成しました");
    activeUserId = r.id;
    await loadUsers();
  });
});

/* ---------------- Settings ---------------- */
$("#settingsBtn").addEventListener("click", async () => {
  const s = await api.get("/api/settings");
  openSheet("設定", () => {
    const wrap = document.createElement("div");
    wrap.innerHTML = `
      <div class="card">
        <h2 class="section-title">ポーリング</h2>
        <div class="field"><label>間隔 (秒, 0.1 単位)</label><input type="number" id="setInterval" min="0.1" step="0.1" value="${s.poll_interval_seconds}"/></div>
        <div class="field"><label>掲載店リスト更新時刻</label><input type="time" id="setListTime" value="${escapeAttr(s.list_refresh_time)}"/></div>
      </div>
      <div class="card">
        <h2 class="section-title">SMTP（メール送信）</h2>
        <div class="field"><label>ホスト</label><input type="text" id="setSmtpHost" value="${escapeAttr(s.smtp_host)}"/></div>
        <div class="field"><label>ポート</label><input type="number" id="setSmtpPort" value="${s.smtp_port}"/></div>
        <div class="field"><label>ユーザー</label><input type="text" id="setSmtpUser" value="${escapeAttr(s.smtp_user)}"/></div>
        <div class="field"><label>パスワード${s.smtp_password_set ? "（設定済み・変更時のみ入力）" : ""}</label><input type="password" id="setSmtpPass" placeholder=""/></div>
        <div class="field"><label>From アドレス</label><input type="text" id="setSmtpFrom" value="${escapeAttr(s.smtp_from)}"/></div>
        <div class="toggle-row"><label>STARTTLS を使う</label>
          <label class="switch"><input type="checkbox" id="setSmtpTls" ${s.smtp_use_starttls ? "checked" : ""}/><span class="slider"></span></label>
        </div>
      </div>
      <div class="card">
        <h2 class="section-title">LINE Messaging API</h2>
        <div class="field"><label>Channel access token${s.line_token_set ? "（設定済み・変更時のみ入力）" : ""}</label><input type="password" id="setLineToken" placeholder=""/></div>
      </div>
    `;
    return wrap;
  }, async () => {
    const payload = {
      poll_interval_seconds: parseFloat($("#setInterval").value),
      list_refresh_time: $("#setListTime").value,
      smtp_host: $("#setSmtpHost").value,
      smtp_port: parseInt($("#setSmtpPort").value, 10),
      smtp_user: $("#setSmtpUser").value,
      smtp_password: $("#setSmtpPass").value,
      smtp_from: $("#setSmtpFrom").value,
      smtp_use_starttls: $("#setSmtpTls").checked,
      line_token: $("#setLineToken").value,
    };
    await api.put("/api/settings", payload);
    toast("設定を保存しました");
  });
});

/* ---------------- Modal sheet helpers ---------------- */
let sheetOnSave = null;
function openSheet(title, bodyFactory, onSave) {
  $("#sheetTitle").textContent = title;
  const body = $("#sheetBody");
  body.innerHTML = "";
  body.appendChild(bodyFactory());
  $("#modalRoot").classList.remove("hidden");
  sheetOnSave = onSave;
  $("#sheetSave").style.display = onSave ? "" : "none";
}
function closeSheet() {
  $("#modalRoot").classList.add("hidden");
  sheetOnSave = null;
}
$("#sheetCancel").addEventListener("click", closeSheet);
$("#sheetSave").addEventListener("click", async () => {
  if (!sheetOnSave) return closeSheet();
  try {
    await sheetOnSave();
    closeSheet();
  } catch (e) {
    toast("エラー: " + e.message);
  }
});
$("#modalRoot").addEventListener("click", (e) => {
  if (e.target.id === "modalRoot") closeSheet();
});

/* ---------------- Helpers ---------------- */
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}
function escapeAttr(s) { return escapeHtml(s); }

/* ---------------- Init ---------------- */
const initialView = (location.hash || "#home").slice(1);
activateView(initialView);
