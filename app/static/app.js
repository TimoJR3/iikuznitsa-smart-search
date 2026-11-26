"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rub = (v) => (v ? Math.round(v).toLocaleString("ru-RU") + " ₽" : "цена по запросу");

let session = "s" + Math.random().toString(36).slice(2);
try {
  session = localStorage.getItem("ss-session") || session;
  localStorage.setItem("ss-session", session);
} catch (e) { /* без хранилища — новая сессия на каждую загрузку */ }

const EXAMPLES = ["astra linux", "сервер", "по для сервера", "антивирь", "винда", "мдаемон", "fcnhf kbyerc", "крипта про", "программа для чертежей", "бесперебойник"];

let lastEvent = null;

// ---------- вкладки ----------
document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", x === b));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.hidden = p.id !== "tab-" + b.dataset.tab));
    if (b.dataset.tab === "analytics") loadAnalytics();
  })
);

// ---------- поиск ----------
const form = $("#search-form");
const input = $("#q");
const sug = $("#suggest");

$("#examples").innerHTML = EXAMPLES.map((q) => `<button type="button">${esc(q)}</button>`).join("");
$("#examples").addEventListener("click", (e) => {
  if (e.target.tagName === "BUTTON") { input.value = e.target.textContent; runSearch(input.value); }
});

form.addEventListener("submit", (e) => { e.preventDefault(); runSearch(input.value); });

async function runSearch(q) {
  q = q.trim();
  if (!q) return;
  hideSuggest();
  history.replaceState(null, "", "?q=" + encodeURIComponent(q));
  $("#results").innerHTML = `<li class="empty">Ищем…</li>`;
  const r = await fetch(`/api/search?q=${encodeURIComponent(q)}&session=${session}`).then((x) => x.json());
  lastEvent = r.event_id;
  renderUnderstanding(r);
  const st = $("#status");
  if (r.status === "no_match") {
    st.hidden = false;
    st.textContent = "Точного совпадения нет. Показываем самые близкие товары, а запрос передан команде каталога.";
  } else if (r.status === "weak") {
    st.hidden = false;
    st.textContent = "Поиск не уверен в ответе. Уточните запрос или выберите из близких товаров ниже.";
  } else st.hidden = true;
  $("#results").innerHTML = r.items.map((it, i) => card(it, i)).join("");
  renderSide(r);
}

function renderUnderstanding(r) {
  const u = r.understanding;
  const steps = [`<span class="step">Вы ввели <b>${esc(r.query)}</b></span>`];
  if (u.layout_fixed) steps.push(`<span class="step">Раскладка → <b>${esc(u.normalized)}</b></span>`);
  for (const [a, b] of Object.entries(u.corrections || {})) steps.push(`<span class="step">Исправлено <b>${esc(a)}</b> → <b>${esc(b)}</b></span>`);
  if (u.expansions?.length) steps.push(`<span class="step">Синонимы <b>${esc(u.expansions.join(", "))}</b></span>`);
  if (u.rewritten_by_llm) steps.push(`<span class="step llm">GigaChat понял как <b>${esc(u.rewritten_by_llm)}</b></span>`);
  if (u.intent !== "any") {
    const t = u.intent === "hardware" ? "Ищем оборудование" : "Ищем программное обеспечение";
    steps.push(`<span class="step intent-${u.intent}"><b>${t}</b>${u.intent_reason ? ": " + esc(u.intent_reason) : ""}</span>`);
  }
  const el = $("#understanding");
  el.hidden = false;
  el.innerHTML = steps.join('<span class="arrow" aria-hidden="true">›</span>') +
    `<span class="meta">${r.items.length} товаров за ${Math.round(r.latency_ms)} мс</span>`;
}

function tags(it) {
  const t = [`<span class="tag kind-${esc(it.kind)}">${esc(it.kind)}</span>`];
  for (const b of it.badges || []) t.push(`<span class="tag ${b.type === "promo" ? "promo" : ""}">${esc(b.text)}</span>`);
  return `<div class="tags">${t.join("")}</div>`;
}

function card(it, i) {
  return `<li class="card">
    <img src="${esc(it.picture)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
    <div>
      <a class="title" href="${esc(it.url)}" target="_blank" rel="noopener" data-pid="${it.product_id}" data-pos="${i}" data-block="results">${esc(it.title)}</a>
      <div class="sub">${esc(it.vendor)} · ${esc(it.category)}</div>
      ${tags(it)}
    </div>
    <div class="price"><small>от</small><b>${rub(it.price_from)}</b></div>
  </li>`;
}

function mini(it, block) {
  return `<div class="mini"><img src="${esc(it.picture)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
    <div><a href="${esc(it.url)}" target="_blank" rel="noopener" data-pid="${it.product_id}" data-block="${esc(block)}">${esc(it.title)}</a>
    <small>${esc(it.vendor)}, от ${rub(it.price_from)}</small></div></div>`;
}

function renderSide(r) {
  const parts = [];
  for (const b of r.bundles || []) {
    parts.push(`<section class="block"><h3>${esc(b.title)}</h3><p class="reason">${esc(b.reason)}</p>${b.items.map((x) => mini(x, "bundle")).join("")}</section>`);
  }
  if (r.alternatives?.length) {
    parts.push(`<section class="block"><h3>Аналоги других производителей</h3><p class="reason">та же категория каталога, по возрастанию цены</p>${r.alternatives.map((x) => mini(x, "alternative")).join("")}</section>`);
  }
  $("#side").innerHTML = parts.join("");
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-pid]");
  if (a && lastEvent) {
    navigator.sendBeacon?.("/api/click", new Blob([JSON.stringify({
      event_id: lastEvent, product_id: +a.dataset.pid, position: +(a.dataset.pos || 0), block: a.dataset.block,
    })], { type: "application/json" }));
  }
});

// ---------- подсказки при вводе ----------
let timer = null, seq = 0, active = -1;
input.addEventListener("input", () => {
  clearTimeout(timer);
  const q = input.value;
  if (q.trim().length < 2) return hideSuggest();
  timer = setTimeout(async () => {
    const my = ++seq;
    const r = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`).then((x) => x.json());
    if (my === seq) renderSuggest(r);
  }, 160);
});
input.addEventListener("keydown", (e) => {
  const items = [...sug.querySelectorAll(".s-item")];
  if (sug.hidden || !items.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((x, i) => x.classList.toggle("active", i === active));
  } else if (e.key === "Enter" && active >= 0) {
    e.preventDefault();
    items[active].click();
  } else if (e.key === "Escape") hideSuggest();
});
document.addEventListener("click", (e) => { if (!form.contains(e.target)) hideSuggest(); });

function renderSuggest(r) {
  active = -1;
  if (!r.completions.length && !r.products.length) return hideSuggest();
  const fix = r.did_you_mean ? `<p class="fix">Возможно, вы искали <b>${esc(r.did_you_mean)}</b></p>` : "";
  const comps = r.completions.map((c) => `<button type="button" class="s-item" data-q="${esc(c)}">${esc(c)}</button>`).join("");
  const prods = r.products.map((p) => `<button type="button" class="s-item" data-url="${esc(p.url)}" data-pid="${p.product_id}">
      <span class="s-prod"><span>${esc(p.title)}</span><small>от ${rub(p.price_from)}</small></span></button>`).join("");
  sug.innerHTML = `<div class="col"><h3>Запросы</h3>${fix}${comps || '<p class="fix muted">Продолжайте ввод</p>'}</div>
    <div class="col"><h3>Товары</h3>${prods}</div>`;
  sug.hidden = false;
}
sug.addEventListener("click", (e) => {
  const b = e.target.closest(".s-item");
  if (!b) return;
  if (b.dataset.q) { input.value = b.dataset.q; runSearch(b.dataset.q); }
  else if (b.dataset.url) { window.open(b.dataset.url, "_blank", "noopener"); hideSuggest(); }
});
function hideSuggest() { sug.hidden = true; active = -1; }

// ---------- аналитика ----------
$("#an-refresh").addEventListener("click", loadAnalytics);
$("#an-source").addEventListener("change", loadAnalytics);

const pct = (v) => (v == null ? "—" : Math.round(v * 100) + "%");
const STATUS = { ok: "найдено", weak: "неуверенно", no_match: "не найдено" };

async function loadAnalytics() {
  const src = $("#an-source").value;
  const a = await fetch("/api/analytics" + (src ? "?source=" + src : "")).then((x) => x.json());
  const t = a.totals;
  $("#an-period").textContent = t.searches
    ? `Период: ${t.first_ts} — ${t.last_ts}. Доли считаются от числа поисков в выбранном источнике (${t.searches}).`
    : "Пока нет поисков. Выполните несколько запросов на вкладке «Поиск».";
  const kpi = [
    [t.searches ?? 0, "поисков"],
    [t.unique_queries ?? 0, "разных запросов"],
    [pct(t.understood_share), "поиск уверенно ответил"],
    [pct(t.no_match_share), "без подходящего товара"],
    [t.llm_used ?? 0, "запросов разобрала GigaChat"],
    [t.corrected ?? 0, "исправлено опечаток"],
    [pct(t.ctr), "поисков с переходом в товар"],
    [t.avg_latency_ms ? Math.round(t.avg_latency_ms) + " мс" : "—", "среднее время ответа"],
  ];
  $("#an-kpi").innerHTML = kpi.map(([v, l]) => `<div class="kpi"><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("");

  $("#an-gaps").innerHTML = a.gaps.length
    ? `<tr><th>Запрос</th><th class="num">Раз</th><th>Что показали</th><th>Причина</th></tr>` +
      a.gaps.map((g) => `<tr><td><b>${esc(g.query)}</b>${g.llm_rewrite ? `<br><small class="muted">GigaChat: ${esc(g.llm_rewrite)}</small>` : ""}</td>
        <td class="num">${g.n}</td><td>${esc(g.top_title)}<br><small class="muted">уверенность ${g.confidence}</small></td>
        <td><div class="label-btns" data-q="${esc(g.query)}">${Object.entries(a.gap_labels).map(([k, v]) =>
          `<button type="button" data-label="${k}" class="${g.label === k ? "on" : ""}">${esc(v)}</button>`).join("")}</div></td></tr>`).join("")
    : `<tr><td class="empty">Все запросы получили уверенный ответ</td></tr>`;

  $("#an-top").innerHTML = `<tr><th>Запрос</th><th class="num">Раз</th><th>Итог</th></tr>` +
    a.top_queries.map((q) => `<tr><td>${esc(q.query)}</td><td class="num">${q.n}</td><td><span class="pill ${q.status}">${STATUS[q.status] || q.status}</span></td></tr>`).join("");

  const max = Math.max(1, ...a.categories.map((c) => c.n));
  $("#an-cats").innerHTML = a.categories.map((c) => `<div class="bar"><span>${esc(c.category.split(" > ").slice(-2).join(" › "))}</span>
    <span class="num">${c.n}</span><div class="track"><div class="fill" style="width:${(c.n / max) * 100}%"></div></div></div>`).join("") || '<p class="empty">Нет данных</p>';

  $("#an-recent").innerHTML = `<tr><th>Время</th><th>Запрос</th><th>Итог</th><th>Первый товар</th><th class="num">мс</th></tr>` +
    a.recent.map((e) => `<tr><td>${esc(e.ts.slice(11))}</td><td>${esc(e.query)}</td><td><span class="pill ${e.status}">${STATUS[e.status]}</span></td>
      <td>${esc(e.top_title)}</td><td class="num">${Math.round(e.latency_ms)}</td></tr>`).join("");
}

$("#an-gaps").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-label]");
  if (!b) return;
  const q = b.parentElement.dataset.q;
  await fetch("/api/gaps/label", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q, label: b.dataset.label }) });
  b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
});

// Открытие по ссылке ?q=...
const initial = new URLSearchParams(location.search).get("q");
if (initial) { input.value = initial; runSearch(initial); }
