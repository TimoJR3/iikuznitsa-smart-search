"use strict";

/* ===================== общие помощники ===================== */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rub = (v) => (v ? Math.round(v).toLocaleString("ru-RU") + " ₽" : "по запросу");
const plural = (n, a, b, c) => { const m = n % 10, h = n % 100; return m === 1 && h !== 11 ? a : m >= 2 && m <= 4 && (h < 12 || h > 14) ? b : c; };
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const COLORS = {
  os: "#6ea8ff", security: "#ff6f91", office: "#6ee0c0", design: "#c69cff",
  business: "#a6da6a", infra: "#48d0e6", dev: "#ff9f68", hardware: "#e6eaf5",
};
const BEACON = "#ffb547";
const STATUS_COLOR = { ok: "#6ee0c0", weak: "#ffb547", no_match: "#ff6f6f", absent: "#c69cff" };
const STATUS_TEXT = { ok: "найдено", weak: "неуверенно", no_match: "не найдено", absent: "нет в каталоге" };
const ROUTES = ["astra linux", "сервер", "по для сервера", "антивирь", "винда", "мдаемон", "fcnhf kbyerc", "teamviewer", "российский антивирус", "программа для чертежей"];

let session = "s" + Math.random().toString(36).slice(2);
try { session = localStorage.getItem("atlas-session") || session; localStorage.setItem("atlas-session", session); } catch (e) { /* без хранилища */ }

/* ===================== состояние ===================== */
const S = {
  n: 0, xs: null, ys: null, gi: null, ids: [], titles: [], vendors: [], prices: [], groupKeys: [], groupNames: {}, byGroup: [],
  grid: null, G: 64, labels: [],
  cam: { x: 0.5, y: 0.5, k: 1 }, W: 0, H: 0, dpr: 1, base: 1,
  hover: -1, hot: -1, selected: -1,
  results: [], query: null, queryText: "", raysT0: 0,
  links: [], suggest: [], off: new Set(),
  mode: "search", demand: [], demandHover: -1, focusQuery: null,
  tween: null, dirty: true, lastEvent: null, filters: {}, lastLlm: false,
};

/* ===================== карта ===================== */
const canvas = $("#map");
const ctx = canvas.getContext("2d");
let bgGrad = null;

function resize() {
  S.dpr = Math.min(window.devicePixelRatio || 1, 2);
  S.W = window.innerWidth; S.H = window.innerHeight;
  canvas.width = S.W * S.dpr; canvas.height = S.H * S.dpr;
  S.base = Math.min(S.W, S.H) * 0.92;
  bgGrad = ctx.createRadialGradient(S.W * 0.5, S.H * 0.45, 0, S.W * 0.5, S.H * 0.45, Math.max(S.W, S.H) * 0.75);
  bgGrad.addColorStop(0, "#1b2a5c"); bgGrad.addColorStop(1, "#0e1838");
  S.dirty = true;
}

function view() {
  // Свободная часть экрана, не закрытая панелями: туда направляем камеру.
  let l = 0, t = 64, r = S.W, b = S.H;
  const panels = [];
  if (document.body.dataset.stage === "results" || S.mode === "analytics") panels.push($("#rail"));
  if (!$("#drawer").hidden) panels.push($("#drawer"));
  for (const el of panels) {
    const rc = el.getBoundingClientRect();
    if (rc.width < S.W * 0.6) { if (rc.left < S.W / 2) l = Math.max(l, rc.right); else r = Math.min(r, rc.left); }
    else b = Math.min(b, rc.top);
  }
  if (document.body.dataset.stage === "results" && S.mode === "search") t = Math.max(t, S.W > 900 ? 180 : 130);
  // На вступлении слева текст, карта смотрит в правую часть экрана.
  if (document.body.dataset.stage === "intro" && S.mode === "search" && S.W > 900) l = Math.max(l, Math.min(S.W * 0.46, 720));
  return { l, t, r, b, cx: (l + r) / 2, cy: (t + b) / 2, w: r - l, h: b - t };
}
const scale = () => S.base * S.cam.k;
function toScreen(x, y, v = S.v) { const s = scale(); return [(x - S.cam.x) * s + v.cx, (y - S.cam.y) * s + v.cy]; }
function toWorld(sx, sy, v = S.v) { const s = scale(); return [(sx - v.cx) / s + S.cam.x, (sy - v.cy) / s + S.cam.y]; }

function buildGrid() {
  const G = S.G; S.grid = Array.from({ length: G * G }, () => []);
  for (let i = 0; i < S.n; i++) {
    const cx = Math.min(G - 1, Math.floor(S.xs[i] * G)), cy = Math.min(G - 1, Math.floor(S.ys[i] * G));
    S.grid[cy * G + cx].push(i);
  }
  // Подписи разделов: в самой плотной клетке 16×16 каждого раздела.
  const C = 16, counts = {};
  for (let i = 0; i < S.n; i++) {
    const g = S.groupKeys[S.gi[i]], key = g + ":" + Math.min(C - 1, Math.floor(S.xs[i] * C)) + ":" + Math.min(C - 1, Math.floor(S.ys[i] * C));
    counts[key] = (counts[key] || 0) + 1;
  }
  const best = {};
  for (const [key, c] of Object.entries(counts)) {
    const [g, x, y] = key.split(":");
    if (!best[g] || c > best[g].c) best[g] = { c, x: (+x + 0.5) / C, y: (+y + 0.5) / C };
  }
  S.labels = Object.entries(best).map(([g, p]) => ({ g, x: p.x, y: p.y }));
}

function nearest(sx, sy, radius = 10) {
  const [wx, wy] = toWorld(sx, sy), rw = radius / scale(), G = S.G;
  const x0 = Math.max(0, Math.floor((wx - rw) * G)), x1 = Math.min(G - 1, Math.floor((wx + rw) * G));
  const y0 = Math.max(0, Math.floor((wy - rw) * G)), y1 = Math.min(G - 1, Math.floor((wy + rw) * G));
  let best = -1, bd = rw * rw;
  for (let gy = y0; gy <= y1; gy++) for (let gx = x0; gx <= x1; gx++) for (const i of S.grid[gy * G + gx]) {
    if (S.off.has(S.gi[i])) continue;
    const d = (S.xs[i] - wx) ** 2 + (S.ys[i] - wy) ** 2;
    if (d < bd) { bd = d; best = i; }
  }
  return best;
}

const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
function flyTo(x, y, k, ms = 1000) {
  k = Math.max(0.8, Math.min(60, k));
  if (REDUCED || ms === 0) { S.cam = { x, y, k }; S.dirty = true; return; }
  S.tween = { from: { ...S.cam }, to: { x, y, k }, t0: performance.now(), ms };
}
function fit(points, pad = 0.16, maxK = 18) {
  if (!points.length) return flyTo(0.5, 0.5, 1);
  const v = view();
  let x0 = 1, x1 = 0, y0 = 1, y1 = 0;
  for (const [x, y] of points) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  const bw = Math.max(x1 - x0, 0.02) * (1 + pad * 2), bh = Math.max(y1 - y0, 0.02) * (1 + pad * 2);
  const k = Math.min(v.w / (bw * S.base), v.h / (bh * S.base), maxK);
  flyTo((x0 + x1) / 2, (y0 + y1) / 2, k);
}

function draw(now) {
  if (S.tween) {
    const t = Math.min(1, (now - S.tween.t0) / S.tween.ms), e = ease(t), a = S.tween.from, b = S.tween.to;
    // Логарифмическая интерполяция масштаба: полёт выглядит равномерным.
    S.cam = { x: a.x + (b.x - a.x) * e, y: a.y + (b.y - a.y) * e, k: Math.exp(Math.log(a.k) + (Math.log(b.k) - Math.log(a.k)) * e) };
    if (t >= 1) S.tween = null;
    S.dirty = true;
  }
  const raysAge = now - S.raysT0;
  const animating = S.tween || (S.results.length && raysAge < 2600) || (S.selected >= 0 && now - S.linksT0 < 1400);
  if (!S.dirty && !animating) return requestAnimationFrame(draw);
  S.dirty = false;
  S.v = view();
  const { W, H } = S, s = scale();
  ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
  ctx.fillStyle = bgGrad; ctx.fillRect(0, 0, W, H);

  // Координатная сетка: шаг 0,1 карты.
  ctx.strokeStyle = "rgba(255,255,255,0.045)"; ctx.lineWidth = 1; ctx.beginPath();
  for (let g = 0; g <= 10; g++) {
    const [sx] = toScreen(g / 10, 0), [, sy] = toScreen(0, g / 10);
    ctx.moveTo(sx, 0); ctx.lineTo(sx, H); ctx.moveTo(0, sy); ctx.lineTo(W, sy);
  }
  ctx.stroke();
  if (!S.n) return requestAnimationFrame(draw);

  const focus = S.results.length || S.selected >= 0 || S.mode === "analytics";
  const r = Math.max(1.2, Math.min(4.2, 1.1 + Math.log2(S.cam.k + 1) * 0.9));
  for (let g = 0; g < S.groupKeys.length; g++) {
    const off = S.off.has(g);
    ctx.globalAlpha = off ? 0.05 : focus ? 0.32 : 0.78;
    ctx.fillStyle = COLORS[S.groupKeys[g]] || "#fff";
    ctx.beginPath();
    for (const i of S.byGroup[g]) {
      const sx = (S.xs[i] - S.cam.x) * s + S.v.cx, sy = (S.ys[i] - S.cam.y) * s + S.v.cy;
      if (sx < -5 || sy < -5 || sx > W + 5 || sy > H + 5) continue;
      ctx.moveTo(sx + r, sy); ctx.arc(sx, sy, r, 0, 6.2832);
    }
    ctx.fill();
  }
  ctx.globalAlpha = 1;

  // Материки карты: программы и оборудование.
  if (S.cam.k < 2.6) {
    ctx.font = "700 22px Unbounded, Onest, sans-serif"; ctx.fillStyle = "rgba(255,255,255,0.22)"; ctx.textAlign = "left";
    for (const [name, x, y] of [["Программы", 0.0, -0.035], ["Оборудование", 0.66, 0.045]]) {
      const [sx, sy] = toScreen(x, y); ctx.fillText(name, sx, sy);
    }
  }
  // Подписи разделов видны на общем плане.
  if (S.cam.k < 3.2) {
    ctx.font = `500 ${S.W > 900 ? 13 : 11}px Unbounded, Onest, sans-serif`; ctx.textAlign = "center";
    const placed = [];
    for (const lb of S.labels) {
      const gIdx = S.groupKeys.indexOf(lb.g);
      if (S.off.has(gIdx)) continue;
      let [sx, sy] = toScreen(lb.x, lb.y);
      const text = S.groupNames[lb.g] || lb.g, w = ctx.measureText(text).width;
      // Подписи не налезают друг на друга: сдвигаем вниз, пока не найдётся свободное место.
      for (let tries = 0; tries < 8 && placed.some((p) => Math.abs(p.x - sx) < (p.w + w) / 2 + 12 && Math.abs(p.y - sy) < 26); tries++) sy += 26;
      placed.push({ x: sx, y: sy, w });
      ctx.globalAlpha = focus ? 0.45 : 0.9;
      ctx.fillStyle = "rgba(14,24,56,0.75)";
      ctx.fillRect(sx - w / 2 - 8, sy - 12, w + 16, 22);
      ctx.fillStyle = COLORS[lb.g]; ctx.fillText(text, sx, sy + 4);
    }
    ctx.globalAlpha = 1; ctx.textAlign = "left";
  }

  // Товары из подсказок, пока человек печатает.
  for (const id of S.suggest) ring(id, r + 4, BEACON, 1.5, 0.8);

  if (S.mode === "analytics") drawDemand(now);
  else drawSearch(now, r);

  if (S.hover >= 0) ring(S.hover, r + 6, "#fff", 2, 1);
  requestAnimationFrame(draw);
}

function ring(i, rad, color, lw = 2, alpha = 1, fill = null) {
  const [sx, sy] = toScreen(S.xs[i], S.ys[i]);
  ctx.globalAlpha = alpha; ctx.beginPath(); ctx.arc(sx, sy, rad, 0, 6.2832);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.stroke(); ctx.globalAlpha = 1;
  return [sx, sy];
}

function drawSearch(now, r) {
  const age = now - S.raysT0;
  // Связи выбранного продукта с сопутствующими решениями: дуги через карту.
  if (S.selected >= 0) {
    const [ax, ay] = toScreen(S.xs[S.selected], S.ys[S.selected]);
    const p = Math.min(1, (now - S.linksT0) / 900);
    for (const ln of S.links) {
      const [bx, by] = toScreen(S.xs[ln.i], S.ys[ln.i]);
      const mx = (ax + bx) / 2 - (by - ay) * 0.25, my = (ay + by) / 2 + (bx - ax) * 0.25;
      ctx.setLineDash([5, 6]); ctx.strokeStyle = COLORS[ln.g] || "#fff"; ctx.lineWidth = 1.6; ctx.globalAlpha = 0.9;
      ctx.beginPath(); ctx.moveTo(ax, ay);
      const steps = 24, n = Math.ceil(steps * ease(p));
      for (let k = 1; k <= n; k++) { const t = k / steps; ctx.lineTo((1 - t) ** 2 * ax + 2 * (1 - t) * t * mx + t * t * bx, (1 - t) ** 2 * ay + 2 * (1 - t) * t * my + t * t * by); }
      ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
      if (p >= 1) ring(ln.i, r + 5, COLORS[ln.g], 2, 1, "rgba(14,24,56,0.6)");
    }
  }
  if (!S.results.length || !S.query) return;
  const [qx, qy] = toScreen(S.query[0], S.query[1]);
  // Лучи от запроса к найденным товарам, по очереди.
  S.results.forEach((it, k) => {
    const t = Math.max(0, Math.min(1, (age - 250 - k * 70) / 550));
    if (t <= 0) return;
    const [bx, by] = toScreen(S.xs[it.product_id], S.ys[it.product_id]);
    const e = ease(t);
    ctx.strokeStyle = it.product_id === S.hot ? "#fff" : "rgba(255,181,71,0.55)";
    ctx.lineWidth = it.product_id === S.hot ? 2 : 1.2;
    ctx.beginPath(); ctx.moveTo(qx, qy); ctx.lineTo(qx + (bx - qx) * e, qy + (by - qy) * e); ctx.stroke();
  });
  const badges = [];
  S.results.forEach((it, k) => {
    const t = Math.max(0, Math.min(1, (age - 650 - k * 70) / 300));
    if (t <= 0) return;
    const id = it.product_id, hot = id === S.hot || id === S.selected;
    const [sx, sy] = ring(id, (r + 3) * (0.6 + 0.4 * ease(t)) + (hot ? 3 : 0), hot ? "#fff" : BEACON, hot ? 3 : 2, t, COLORS[it.group]);
    // Номер в выдаче рядом с точкой; соседние номера раскладываются веером, а не стопкой.
    let bx = sx + r + 12, by = sy - r - 10;
    for (let tries = 0; tries < 12 && badges.some((b) => Math.hypot(b[0] - bx, b[1] - by) < 21); tries++) {
      const ang = -Math.PI / 2 + (tries + 1) * 0.7; bx = sx + Math.cos(ang) * (26 + tries * 4); by = sy + Math.sin(ang) * (26 + tries * 4);
    }
    badges.push([bx, by]);
    ctx.globalAlpha = t;
    if (Math.hypot(bx - sx, by - sy) > 22) { ctx.strokeStyle = "rgba(255,181,71,0.5)"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(bx, by); ctx.stroke(); }
    ctx.fillStyle = "#131a33"; ctx.beginPath(); ctx.arc(bx, by, 10, 0, 6.2832); ctx.fill();
    ctx.strokeStyle = BEACON; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.fillStyle = BEACON; ctx.font = "700 10px Unbounded, Onest, sans-serif"; ctx.textAlign = "center";
    ctx.fillText(String(k + 1), bx, by + 3.5); ctx.textAlign = "left"; ctx.globalAlpha = 1;
  });
  // Точка запроса: «вы здесь».
  const pulse = REDUCED ? 0 : Math.max(0, 1 - age / 1600);
  if (pulse > 0) {
    ctx.globalAlpha = pulse * 0.6; ctx.strokeStyle = BEACON; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(qx, qy, 12 + (1 - pulse) * 60, 0, 6.2832); ctx.stroke(); ctx.globalAlpha = 1;
  }
  ctx.fillStyle = BEACON; ctx.beginPath();
  ctx.moveTo(qx, qy - 11); ctx.lineTo(qx + 8, qy); ctx.lineTo(qx, qy + 11); ctx.lineTo(qx - 8, qy); ctx.closePath(); ctx.fill();
  ctx.font = "600 13px Onest, sans-serif";
  const label = "«" + S.queryText + "»", w = ctx.measureText(label).width;
  ctx.fillStyle = "rgba(14,24,56,0.85)"; ctx.fillRect(qx + 14, qy - 12, w + 14, 24);
  ctx.fillStyle = BEACON; ctx.fillText(label, qx + 21, qy + 5);
}

function drawDemand(now) {
  S.demand.forEach((d, k) => {
    const [sx, sy] = toScreen(d.xy[0], d.xy[1]);
    const rad = 5 + Math.sqrt(d.n) * 4, c = STATUS_COLOR[d.status] || BEACON, hot = k === S.demandHover || d.query === S.focusQuery;
    ctx.globalAlpha = 0.22; ctx.fillStyle = c; ctx.beginPath(); ctx.arc(sx, sy, rad * 2.2, 0, 6.2832); ctx.fill();
    ctx.globalAlpha = 1; ctx.strokeStyle = hot ? "#fff" : c; ctx.lineWidth = hot ? 3 : 2;
    ctx.beginPath(); ctx.arc(sx, sy, rad, 0, 6.2832); ctx.stroke();
    if (hot || S.cam.k > 4) {
      ctx.font = "600 12px Onest, sans-serif";
      const w = ctx.measureText(d.query).width;
      ctx.fillStyle = "rgba(14,24,56,0.85)"; ctx.fillRect(sx + rad + 6, sy - 11, w + 12, 22);
      ctx.fillStyle = c; ctx.fillText(d.query, sx + rad + 12, sy + 4);
    }
  });
}

/* ---------- управление картой ---------- */
let drag = null;
canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, cx: S.cam.x, cy: S.cam.y, moved: false }; canvas.setPointerCapture(e.pointerId); });
canvas.addEventListener("pointermove", (e) => {
  if (drag) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) { drag.moved = true; canvas.classList.add("dragging"); }
    if (drag.moved) { S.tween = null; S.cam.x = drag.cx - dx / scale(); S.cam.y = drag.cy - dy / scale(); S.dirty = true; hideTip(); return; }
  }
  hoverAt(e.clientX, e.clientY);
});
canvas.addEventListener("pointerup", (e) => {
  const click = drag && !drag.moved;
  drag = null; canvas.classList.remove("dragging");
  if (!click) return;
  if (S.mode === "analytics" && S.demandHover >= 0) return focusDemand(S.demand[S.demandHover].query);
  const i = nearest(e.clientX, e.clientY, 12);
  if (i >= 0) openProduct(i, true);
});
canvas.addEventListener("pointerleave", () => { S.hover = -1; S.demandHover = -1; hideTip(); S.dirty = true; });
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  S.tween = null;
  const [wx, wy] = toWorld(e.clientX, e.clientY, view());
  const k = Math.max(0.8, Math.min(60, S.cam.k * Math.exp(-e.deltaY * 0.0015)));
  S.cam.k = k;
  const v = view(), s = scale();
  S.cam.x = wx - (e.clientX - v.cx) / s; S.cam.y = wy - (e.clientY - v.cy) / s;
  S.dirty = true;
}, { passive: false });
$("#zoom-in").onclick = () => flyTo(S.cam.x, S.cam.y, S.cam.k * 1.8, 400);
$("#zoom-out").onclick = () => flyTo(S.cam.x, S.cam.y, S.cam.k / 1.8, 400);
$("#zoom-reset").onclick = () => fitAll(700);
function fitAll(ms = 900) { const v = view(); flyTo(0.5, 0.5, Math.min(v.w / (S.base * 1.06), v.h / (S.base * 1.06)), ms); }

const tip = $("#tooltip");
function hoverAt(x, y) {
  S.v = view();
  if (S.mode === "analytics") {
    let best = -1, bd = 1e9;
    S.demand.forEach((d, k) => {
      const [sx, sy] = toScreen(d.xy[0], d.xy[1]), dd = Math.hypot(sx - x, sy - y), rad = 5 + Math.sqrt(d.n) * 4 + 6;
      if (dd < rad && dd < bd) { bd = dd; best = k; }
    });
    if (best !== S.demandHover) { S.demandHover = best; S.dirty = true; }
    if (best >= 0) {
      const d = S.demand[best];
      showTip(x, y, `<b>«${esc(d.query)}»</b><span>${d.n} ${plural(d.n, "поиск", "поиска", "поисков")}, ${STATUS_TEXT[d.status]}, уверенность ${d.confidence}</span>`);
      canvas.classList.add("pointing"); return;
    }
  }
  const i = nearest(x, y, 10);
  if (i !== S.hover) { S.hover = i; S.dirty = true; }
  canvas.classList.toggle("pointing", i >= 0);
  if (i < 0) return hideTip();
  showTip(x, y, `<b>${esc(S.titles[i])}</b><span>${esc(S.vendors[i])}, от ${rub(S.prices[i])}</span><br><span>${esc(S.groupNames[S.groupKeys[S.gi[i]]])}</span>`);
}
function showTip(x, y, html) {
  tip.innerHTML = html; tip.hidden = false;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(S.W - w - 8, x + 16) + "px"; tip.style.top = Math.min(S.H - h - 8, y + 16) + "px";
}
function hideTip() { tip.hidden = true; }

/* ===================== легенда ===================== */
function renderLegend() {
  $("#legend").innerHTML = S.groupKeys.map((g, k) =>
    `<button type="button" data-g="${k}" aria-pressed="${!S.off.has(k)}"><span class="sw" style="background:${COLORS[g]}"></span>${esc(S.groupNames[g])}</button>`).join("");
}
$("#legend").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-g]");
  if (!b) return;
  const k = +b.dataset.g;
  // Клик с Alt (или второй клик по единственному включённому) — показать только этот раздел.
  if (e.altKey) { S.off = new Set(S.groupKeys.map((_, j) => j).filter((j) => j !== k)); }
  else if (S.off.has(k)) S.off.delete(k); else S.off.add(k);
  renderLegend(); S.dirty = true;
});

/* ===================== поиск ===================== */
const form = $("#search-form"), input = $("#q"), sug = $("#suggest");
$("#routes").innerHTML = `<p class="hint">Попробуйте запросы с жаргоном, опечаткой или в другой раскладке</p>` +
  ROUTES.map((q) => `<button type="button">${esc(q)}</button>`).join("");
$("#routes").addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") { input.value = e.target.textContent; runSearch(input.value); } });
form.addEventListener("submit", (e) => { e.preventDefault(); runSearch(input.value); });

async function runSearch(q) {
  q = q.trim();
  if (!q) return;
  clearTimeout(timer); seq++;
  hideSuggest(); closeDrawer(false); input.blur();
  S.filters = {};
  history.replaceState(null, "", "?q=" + encodeURIComponent(q));
  setStage("results");
  $("#rail-search").innerHTML = `<div class="rail-head"><h2>Ищем…</h2></div>`;
  let r;
  const my = ++searchSeq;
  try { r = await fetch(`/api/search?q=${encodeURIComponent(q)}&session=${session}&llm=0`).then((x) => x.json()); }
  catch (e) { $("#rail-search").innerHTML = `<div class="rail-head"><h2>Поиск недоступен</h2><p>Сервер не ответил. Повторите запрос через несколько секунд.</p></div>`; return; }
  if (my !== searchSeq) return;
  showResults(r, q);
  // Неуверенный ответ: выдача уже на экране, GigaChat уточняет запрос вторым шагом.
  if (r.can_refine) {
    const r2 = await fetch(`/api/search?q=${encodeURIComponent(q)}&session=${session}&llm=1&event=${r.event_id}`).then((x) => x.json()).catch(() => null);
    if (my !== searchSeq) return;
    if (r2 && r2.understanding.rewritten_by_llm) showResults(r2, q, true);
    else renderTrace(r, "none");
  }
}
let searchSeq = 0;

function filterQs(f) {
  return Object.entries(f).filter(([, v]) => v !== "" && v != null && v !== false).map(([k, v]) => `&${k}=${encodeURIComponent(v === true ? 1 : v)}`).join("");
}
async function applyFilters() {
  const q = S.queryText, my = ++searchSeq;
  const r = await fetch(`/api/search?q=${encodeURIComponent(q)}&session=${session}&llm=${S.lastLlm ? 1 : 0}&event=${S.lastEvent || ""}${filterQs(S.filters)}`).then((x) => x.json()).catch(() => null);
  if (r && my === searchSeq) showResults({ ...r, can_refine: false }, q, r.llm_used);
}

function showResults(r, q, refined = false) {
  S.lastEvent = r.event_id; S.lastLlm = !!r.llm_used;
  S.results = r.items; S.query = r.query_xy; S.queryText = q; S.raysT0 = performance.now(); S.hot = -1;
  renderTrace(r, r.can_refine ? "pending" : refined ? "done" : "");
  renderResults(r);
  setTimeout(() => fit([...r.items.slice(0, 8).map((it) => it.xy), r.query_xy], 0.18, 14), 60);
}

function renderTrace(r, llmState = "") {
  const u = r.understanding, steps = [`<li>Запрос <b>${esc(r.query)}</b></li>`];
  if (u.absent) steps.push(`<li class="absent"><b>${esc(u.absent.name)}</b> нет в каталоге, ищем: ${esc(u.absent.task)}</li>`);
  if (u.domestic) steps.push(`<li class="intent"><b>Российское ПО</b>: реестр, импортозамещение, российские вендоры</li>`);
  if (u.layout_fixed) steps.push(`<li>Раскладка <b>${esc(u.normalized)}</b></li>`);
  for (const [a, b] of Object.entries(u.corrections || {})) steps.push(`<li><s>${esc(a)}</s> <b>${esc(b)}</b></li>`);
  if (u.expansions?.length && !u.absent) steps.push(`<li>Синонимы <b>${esc(u.expansions.join(", "))}</b></li>`);
  if (u.rewritten_by_llm) steps.push(`<li class="llm">GigaChat понял как <b>${esc(u.rewritten_by_llm)}</b></li>`);
  else if (llmState === "pending") steps.push(`<li class="llm pending">GigaChat уточняет запрос…</li>`);
  else if (llmState === "none") steps.push(`<li class="llm">GigaChat не нашёл лучшего толкования</li>`);
  if (u.intent !== "any") steps.push(`<li class="intent"><b>${u.intent === "hardware" ? "Оборудование" : "Программы"}</b>${u.intent_reason ? ", " + esc(u.intent_reason) : ""}</li>`);
  const el = $("#trace");
  el.innerHTML = steps.map((s, k) => s.replace("<li", `<li style="animation-delay:${k * 90}ms"`)).join("");
  el.hidden = false;
}

function chips(it) {
  const c = [`<span class="chip"><span class="sw" style="background:${COLORS[it.group]}"></span>${esc(it.kind)}</span>`];
  for (const b of it.badges || []) c.push(`<span class="chip ${["promo", "deal", "registry", "cert"].includes(b.type) ? b.type : ""}">${esc(b.text)}</span>`);
  return `<div class="chips">${c.join("")}</div>`;
}

function renderResults(r) {
  const n = r.items.length;
  let notice = "";
  if (r.status === "absent") notice = `<p class="notice absent">«${esc(r.understanding.absent.name)}» нет в каталоге магазина. Показываем решения той же задачи: ${esc(r.understanding.absent.task)}. Запрос учтён в аналитике спроса.</p>`;
  else if (r.status === "no_match") notice = `<p class="notice miss">Точного совпадения нет. Показываем ближайшие по смыслу товары, запрос передан команде каталога.</p>`;
  else if (r.status === "weak") notice = `<p class="notice">Поиск не уверен в ответе. Уточните запрос или выберите из близких товаров.</p>`;
  const items = r.items.map((it, k) => `<li class="result" data-pid="${it.product_id}" data-pos="${k}" tabindex="0">
      <span class="rank">${k + 1}</span>
      <div><h3>${esc(it.title)}</h3><div class="vendor">${esc(it.vendor)}</div>
      <div class="row">${chips(it)}<span class="price"><small>от</small>${rub(it.price_from)}</span></div>
      ${it.why?.length ? `<p class="why-line">Почему здесь: ${esc(it.why.join(", "))}</p>` : ""}</div></li>`).join("");
  const blocks = (r.bundles || []).map((b) => `<section><h4>${esc(b.title)}</h4><p class="why">${esc(b.reason)}</p>
      ${b.items.map((x) => mini(x, "bundle")).join("")}</section>`).join("");
  const alts = r.alternatives?.length ? `<section><h4>Аналоги других производителей</h4><p class="why">тот же раздел каталога, от дешёвых к дорогим</p>
      ${r.alternatives.map((x) => mini(x, "alternative")).join("")}</section>` : "";
  $("#rail-search").innerHTML = `<div class="rail-head"><h2>${n} ${plural(n, "товар", "товара", "товаров")}</h2>
      <p>за ${Math.round(r.latency_ms)} мс${r.llm_used ? ", запрос уточнила GigaChat" : ""}${r.can_refine ? ". GigaChat ищет точнее, выдача обновится" : ""}. Номера совпадают с метками на карте.</p></div>
      ${facetsBar(r)}${notice}<ol class="results">${items}</ol>
      ${blocks || alts ? `<div class="side-blocks">${blocks}${alts}</div>` : ""}`;
}
function facetsBar(r) {
  const f = r.facets || {}, cur = S.filters;
  if (!f.pool) return "";
  const kinds = f.kind || {};
  const seg = (kinds.software && kinds.hardware) || cur.kind ? `<div class="seg" role="group" aria-label="Тип товара">
      <button type="button" data-f="kind" data-v="" aria-pressed="${!cur.kind}">Все</button>
      <button type="button" data-f="kind" data-v="software" aria-pressed="${cur.kind === "software"}">Программы ${kinds.software || ""}</button>
      <button type="button" data-f="kind" data-v="hardware" aria-pressed="${cur.kind === "hardware"}">Оборудование ${kinds.hardware || ""}</button></div>` : "";
  const dom = f.domestic || cur.domestic ? `<button type="button" class="toggle" data-f="domestic" aria-pressed="${!!cur.domestic}">Российское ПО ${f.domestic || ""}</button>` : "";
  const vendors = `<select data-f="vendor" aria-label="Производитель"><option value="">Все производители</option>
      ${(f.vendors || []).map((v) => `<option value="${esc(v.name)}" ${cur.vendor === v.name ? "selected" : ""}>${esc(v.name)} (${v.n})</option>`).join("")}
      ${cur.vendor && !(f.vendors || []).some((v) => v.name === cur.vendor) ? `<option selected value="${esc(cur.vendor)}">${esc(cur.vendor)}</option>` : ""}</select>`;
  const sort = `<select data-f="sort" aria-label="Сортировка"><option value="">По релевантности</option>
      <option value="price_asc" ${cur.sort === "price_asc" ? "selected" : ""}>Сначала дешевле</option>
      <option value="price_desc" ${cur.sort === "price_desc" ? "selected" : ""}>Сначала дороже</option></select>`;
  return `<div class="facets">${seg}<div class="facet-row">${dom}${vendors}${sort}</div></div>`;
}

function mini(x, block) {
  return `<button type="button" class="mini" data-pid="${x.product_id}" data-block="${block}">
    <span><span class="sw" style="background:${COLORS[x.group]}"></span>${esc(x.title)}</span><small>от ${rub(x.price_from)}</small></button>${fact(x)}`;
}
function fact(x) {
  if (!x.fact) return "";
  return `<p class="fact"><span aria-hidden="true">✓</span> ${esc(x.fact.text)}. <a href="${esc(x.fact.url)}" target="_blank" rel="noopener">${esc(x.fact.source)}</a></p>`;
}

$("#rail").addEventListener("pointerover", (e) => {
  const el = e.target.closest("[data-pid]");
  const id = el ? +el.dataset.pid : -1;
  if (id !== S.hot) { S.hot = id; S.dirty = true; }
  document.querySelectorAll(".result.hot").forEach((x) => x.classList.remove("hot"));
});
$("#rail").addEventListener("click", (e) => {
  const el = e.target.closest("[data-pid]");
  if (!el) return;
  track(+el.dataset.pid, +(el.dataset.pos || 0), el.dataset.block || "results");
  openProduct(+el.dataset.pid, true);
});
$("#rail-search").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-f]");
  if (!b) return;
  e.stopPropagation();
  if (b.dataset.f === "domestic") S.filters.domestic = !S.filters.domestic;
  else S.filters[b.dataset.f] = b.dataset.v;
  applyFilters();
}, true);
$("#rail-search").addEventListener("change", (e) => {
  const s = e.target.closest("select[data-f]");
  if (!s) return;
  S.filters[s.dataset.f] = s.value;
  applyFilters();
});
$("#rail").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches(".result")) e.target.click(); });

function track(pid, pos, block) {
  if (!S.lastEvent) return;
  navigator.sendBeacon?.("/api/click", new Blob([JSON.stringify({ event_id: S.lastEvent, product_id: pid, position: pos, block })], { type: "application/json" }));
}

/* ===================== карточка продукта ===================== */
async function openProduct(id, fly) {
  const p = await fetch(`/api/product/${id}`).then((x) => x.json());
  S.selected = id; S.linksT0 = performance.now();
  S.links = (p.bundles || []).flatMap((b) => b.items.map((x) => ({ i: x.product_id, g: x.group })));
  document.querySelectorAll(".result").forEach((el) => el.classList.toggle("selected", +el.dataset.pid === id));
  const drawer = $("#drawer");
  drawer.hidden = false;
  drawer.style.setProperty("--accent", COLORS[p.group]);
  const crumbs = esc(p.category.split(" > ").join(" / "));
  $("#drawer-body").innerHTML = `
    <div class="d-top" style="--accent:${COLORS[p.group]}">
      <p class="crumbs">${crumbs}</p><h2>${esc(p.title)}</h2><div class="vendor">${esc(p.vendor)}</div>
    </div>
    <div class="d-buy">
      <div><span class="price"><small>от</small>${rub(p.price_from)}</span>${chips(p)}</div>
      <a class="cta" href="${esc(p.url)}" target="_blank" rel="noopener">Открыть в магазине</a>
    </div>
    ${p.price_note ? `<p class="price-note">${esc(p.price_note)}</p>` : ""}
    ${p.bundles?.length ? `<div class="d-section"><h3>С этим продуктом берут</h3>
      <p class="why">Сопутствующие решения из каталога: экосистема вендора и разделы, которые нужны вместе. На карте показаны пунктиром.</p>
      ${orbit(p)}${sources(p)}</div>` : ""}
    ${p.alternatives?.length ? `<div class="d-section"><h3>Аналоги</h3><p class="why">тот же раздел, другие производители</p>
      ${p.alternatives.map((x) => mini(x, "alternative")).join("")}</div>` : ""}
    <div class="d-section"><h3>Варианты лицензий</h3><p class="desc">${p.variants} ${plural(p.variants, "вариант", "варианта", "вариантов")} в каталоге: сроки, число мест и тип лицензии. Цена указана для самого доступного.</p></div>`;
  if (fly) fit([p.xy, ...S.links.map((l) => [S.xs[l.i], S.ys[l.i]])], 0.25, 10);
  S.dirty = true;
}

function sources(p) {
  const items = p.bundles.flatMap((b) => b.items).filter((x) => x.fact);
  if (!items.length) return "";
  return `<div class="sources"><h4>Проверено у вендоров</h4>${items.map((x) => `<p class="fact"><span aria-hidden="true">✓</span>
    <button type="button" class="linklike" data-pid="${x.product_id}" data-block="verified">${esc(x.title)}</button>: ${esc(x.fact.text)}.
    <a href="${esc(x.fact.url)}" target="_blank" rel="noopener">${esc(x.fact.source)}</a></p>`).join("")}</div>`;
}

function orbit(p) {
  const items = p.bundles.flatMap((b) => b.items.map((x) => ({ ...x, block: b.title }))).slice(0, 6);
  const W = 380, H = 270, cx = W / 2, cy = H / 2, RX = 74, RY = 84;
  const nodes = items.map((x, k) => {
    const a = -Math.PI / 2 + ((k + 0.5) / items.length) * Math.PI * 2;
    return { ...x, a, x: cx + Math.cos(a) * RX, y: cy + Math.sin(a) * RY };
  });
  const short = (t, n = 20) => (t.length > n ? t.slice(0, n - 1) + "…" : t);
  const label = (n) => {
    const right = Math.cos(n.a) > 0.15, left = Math.cos(n.a) < -0.15;
    const anchor = right ? "start" : left ? "end" : "middle";
    const tx = n.x + (right ? 18 : left ? -18 : 0), ty = n.y + (right || left ? 4 : Math.sin(n.a) > 0 ? 30 : -20);
    const len = anchor === "middle" ? 30 : 14;
    return `<text x="${tx}" y="${ty}" text-anchor="${anchor}">${esc(short(n.title, len))}</text>
      <text class="cap" x="${tx}" y="${ty + 13}" text-anchor="${anchor}">${esc(short(n.block, len + 2))}</text>`;
  };
  return `<svg class="orbit" viewBox="0 0 ${W} ${H}" role="list" aria-label="Сопутствующие решения">
    <ellipse cx="${cx}" cy="${cy}" rx="${RX}" ry="${RY}" fill="none" stroke="#dfe4f0" stroke-dasharray="3 5"/>
    ${nodes.map((n) => `<line x1="${cx}" y1="${cy}" x2="${n.x}" y2="${n.y}" stroke="${COLORS[n.group]}" stroke-width="2" opacity=".8"/>`).join("")}
    <circle cx="${cx}" cy="${cy}" r="28" fill="#131a33" stroke="${BEACON}" stroke-width="2"/>
    <path d="M${cx} ${cy - 11} L${cx + 8} ${cy} L${cx} ${cy + 11} L${cx - 8} ${cy} Z" fill="${BEACON}"/>
    ${nodes.map((n) => `<g class="node" role="listitem" tabindex="0" data-pid="${n.product_id}" data-block="bundle">
      <circle class="ring" cx="${n.x}" cy="${n.y}" r="12" fill="${COLORS[n.group]}" stroke="#fff" stroke-width="2"/>
      ${label(n)}<title>${esc(n.title)}, от ${rub(n.price_from)}</title></g>`).join("")}
  </svg>`;
}

$("#drawer").addEventListener("click", (e) => {
  const el = e.target.closest("[data-pid]");
  if (el) { track(+el.dataset.pid, 0, el.dataset.block || "drawer"); openProduct(+el.dataset.pid, true); }
});
$("#drawer").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.closest("[data-pid]")) e.target.closest("[data-pid]").dispatchEvent(new MouseEvent("click", { bubbles: true })); });
$("#drawer-close").onclick = () => closeDrawer(true);
function closeDrawer(refit) {
  $("#drawer").hidden = true; S.selected = -1; S.links = [];
  document.querySelectorAll(".result.selected").forEach((x) => x.classList.remove("selected"));
  if (refit && S.results.length) fit([...S.results.slice(0, 8).map((it) => it.xy), S.query], 0.18, 14);
  S.dirty = true;
}

/* ===================== подсказки при вводе ===================== */
let timer = null, seq = 0, active = -1;
input.addEventListener("input", () => {
  clearTimeout(timer);
  const q = input.value;
  if (q.trim().length < 2) return hideSuggest();
  timer = setTimeout(async () => {
    const my = ++seq;
    const r = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`).then((x) => x.json());
    if (my === seq) renderSuggest(r);
  }, 140);
});
input.addEventListener("keydown", (e) => {
  const items = [...sug.querySelectorAll(".s-item")];
  if (e.key === "Escape") return hideSuggest();
  if (sug.hidden || !items.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
    items.forEach((x, i) => x.classList.toggle("active", i === active));
  } else if (e.key === "Enter" && active >= 0) { e.preventDefault(); items[active].click(); }
});
document.addEventListener("click", (e) => { if (!form.contains(e.target)) hideSuggest(); });
function renderSuggest(r) {
  active = -1;
  if (!r.completions.length && !r.products.length) return hideSuggest();
  const fix = r.did_you_mean ? `<p class="fix">Возможно, вы ищете <b>${esc(r.did_you_mean)}</b></p>` : "";
  sug.innerHTML = `<div class="col"><h3>Запросы</h3>${fix}${r.completions.map((c) => `<button type="button" class="s-item" data-q="${esc(c)}">${esc(c)}</button>`).join("") || (fix ? "" : '<p class="fix">Продолжайте ввод</p>')}</div>
    <div class="col"><h3>Товары</h3>${r.products.map((p) => `<button type="button" class="s-item" data-pid="${p.product_id}">
      <span class="grow"><span class="sw" style="background:${COLORS[p.group]}"></span><span>${esc(p.title)}</span></span><small>от ${rub(p.price_from)}</small></button>`).join("")}</div>`;
  sug.hidden = false; input.setAttribute("aria-expanded", "true");
  S.suggest = r.products.map((p) => p.product_id); S.dirty = true;
}
sug.addEventListener("click", (e) => {
  const b = e.target.closest(".s-item");
  if (!b) return;
  if (b.dataset.q) { input.value = b.dataset.q; runSearch(b.dataset.q); }
  else { hideSuggest(); setStage("results"); openProduct(+b.dataset.pid, true); }
});
function hideSuggest() { sug.hidden = true; active = -1; input.setAttribute("aria-expanded", "false"); S.suggest = []; S.dirty = true; }

/* ===================== аналитика спроса ===================== */
document.querySelectorAll(".modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
function setMode(mode) {
  S.mode = mode; document.body.dataset.mode = mode;
  document.querySelectorAll(".modes button").forEach((x) => x.setAttribute("aria-selected", x.dataset.mode === mode));
  $("#rail-search").hidden = mode !== "search"; $("#rail-analytics").hidden = mode !== "analytics";
  $("#trace").hidden = mode !== "search" || !S.results.length;
  closeDrawer(false); hideSuggest();
  if (mode === "analytics") loadAnalytics();
  else if (S.results.length) fit([...S.results.slice(0, 8).map((it) => it.xy), S.query], 0.18, 14);
  else fitAll(700);
  S.dirty = true;
}

const pct = (v) => (v == null ? "—" : Math.round(v * 100) + "%");
async function loadAnalytics(src = $("#an-source")?.value || "") {
  const qs = src ? "?source=" + src : "";
  const [a, dm, syn] = await Promise.all([fetch("/api/analytics" + qs).then((x) => x.json()), fetch("/api/analytics/map" + qs).then((x) => x.json()), fetch("/api/synonyms").then((x) => x.json())]);
  S.demand = dm; S.focusQuery = null;
  const t = a.totals, n = t.searches || 0;
  const cats = a.categories, max = Math.max(1, ...cats.map((c) => c.n));
  $("#rail-analytics").innerHTML = `
    <div class="rail-head"><h2>Карта спроса</h2>
      <p>${n ? `${n} ${plural(n, "поиск", "поиска", "поисков")} с ${esc(t.first_ts)} по ${esc(t.last_ts)}. Кольца на карте — запросы: где ищут и где не находят.` : "Пока нет поисков. Выполните несколько запросов в режиме «Поиск»."}</p></div>
    <div class="an-tools"><select id="an-source" aria-label="Источник событий">
        <option value="" ${!src ? "selected" : ""}>Все события</option>
        <option value="demo" ${src === "demo" ? "selected" : ""}>Поиски на стенде</option>
        <option value="replay" ${src === "replay" ? "selected" : ""}>Выборка запросов магазина</option></select>
      <button type="button" id="an-refresh">Обновить</button></div>
    <div class="kpis">
      <div class="kpi accent"><b>${pct(t.understood_share)}</b><span>запросов поиск понял уверенно</span></div>
      <div class="kpi"><b>${pct(t.no_match_share)}</b><span>без подходящего товара</span></div>
      <div class="kpi"><b>${t.absent ?? 0}</b><span>запросов о продуктах, которых нет в каталоге</span></div>
      <div class="kpi"><b>${t.corrected ?? 0}</b><span>исправлено опечаток и раскладок</span></div>
      <div class="kpi"><b>${t.llm_used ?? 0}</b><span>запросов уточнила GigaChat</span></div>
      <div class="kpi"><b>${pct(t.ctr)}</b><span>поисков с переходом в товар</span></div>
      <div class="kpi"><b>${t.avg_latency_ms ? Math.round(t.avg_latency_ms) + " мс" : "—"}</b><span>среднее время ответа</span></div>
    </div>
    <div class="an-sec"><h3>Экономический эффект</h3>
      <p class="why">Сколько заказов возвращает поиск, который понимает запрос. Значения по умолчанию взяты из ТЗ, доля неудачных поисков после внедрения — из журнала стенда. Средний чек — допущение, поставьте свой.</p>
      <form class="calc" id="calc">
        <label>Поисков в месяц<input name="s" type="number" min="0" step="500" value="15000"></label>
        <label>Неудачных сейчас, %<input name="f0" type="number" min="0" max="100" step="1" value="40"></label>
        <label>Неудачных с умным поиском, %<input name="f1" type="number" min="0" max="100" step="1" value="${Math.max(0, Math.round((1 - (t.understood_share ?? 0.95)) * 100))}"></label>
        <label>Уходят после неудачи, %<input name="leave" type="number" min="0" max="100" step="1" value="40"></label>
        <label>Конверсия поиска в заказ, %<input name="conv" type="number" min="0" max="100" step="0.5" value="7.5"></label>
        <label>Средний чек, ₽<input name="check" type="number" min="0" step="1000" value="50000"></label>
      </form>
      <div class="calc-out" id="calc-out" aria-live="polite"></div></div>
    <div class="an-sec"><h3>Запросы без уверенного ответа</h3>
      <p class="why">Нажмите, чтобы увидеть место на карте. Отметьте причину, чтобы запрос ушёл в работу каталогу или поиску.</p>
      ${a.gaps.length ? a.gaps.map((g) => `<div class="gap" data-q="${esc(g.query)}">
        <div class="q"><span>«${esc(g.query)}»</span><small>${g.n} ${plural(g.n, "раз", "раза", "раз")}, уверенность ${g.confidence}</small></div>
        <div class="shown">Показали: ${esc(g.top_title)}</div>
        ${g.llm_rewrite ? `<div class="llm">GigaChat: ${esc(g.llm_rewrite)}</div>` : ""}
        <div class="labels">${Object.entries(a.gap_labels).map(([k, v]) => `<button type="button" data-label="${k}" class="${g.label === k ? "on" : ""}">${esc(v)}</button>`).join("")}</div>
      </div>`).join("") : `<p class="why">Все запросы получили уверенный ответ.</p>`}</div>
    <div class="an-sec"><h3>Пополнение словаря</h3>
      <p class="why">Эти запросы поиск понял только с помощью GigaChat. Добавьте толкование в словарь, и запрос будет находиться сразу, без вызова модели.</p>
      ${(a.suggestions || []).map((s) => `<div class="sug" data-term="${esc(s.query)}" data-exp="${esc(s.rewrite)}">
        <div><b>«${esc(s.query)}»</b> → ${esc(s.rewrite)}</div>
        <button type="button" class="add-syn" ${syn.custom[s.query] ? "disabled" : ""}>${syn.custom[s.query] ? "В словаре" : "Добавить в словарь"}</button></div>`).join("") || `<p class="why">Пока нет запросов, которые понадобилось уточнять.</p>`}
      <form class="syn-form" id="syn-form">
        <input name="term" placeholder="Запрос клиента: касперыч" aria-label="Запрос клиента" required>
        <input name="exp" placeholder="Как в каталоге: kaspersky" aria-label="Термин каталога" required>
        <button type="submit">Добавить</button>
      </form></div>
    <div class="an-sec"><h3>Частые запросы</h3>
      ${a.top_queries.map((q) => `<div class="qrow" data-q="${esc(q.query)}"><span>${esc(q.query)}</span><span>${q.n}</span><span class="pill ${q.status}">${STATUS_TEXT[q.status]}</span></div>`).join("")}</div>
    <div class="an-sec"><h3>Разделы, где находят товар</h3>
      ${cats.map((c) => `<div class="bar"><div class="lbl"><span>${esc(c.category.split(" > ").slice(-2).join(" / "))}</span><span>${c.n}</span></div>
        <div class="track"><div class="fill" style="width:${(c.n / max) * 100}%;background:${BEACON}"></div></div></div>`).join("") || `<p class="why">Нет данных</p>`}</div>`;
  $("#an-source").onchange = (e) => loadAnalytics(e.target.value);
  $("#calc").oninput = calc; calc();
  $("#syn-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target, term = f.term.value.trim(), exp = f.exp.value.trim();
    if (!term || !exp) return;
    await addSynonym(term, exp.split(",").map((x) => x.trim()));
    f.reset(); loadAnalytics($("#an-source").value);
  };
  $("#an-refresh").onclick = () => loadAnalytics($("#an-source").value);
  fit(dm.map((d) => d.xy), 0.12, 3);
  S.dirty = true;
}
async function addSynonym(term, expansions) {
  return fetch("/api/synonyms", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ term, expansions }) }).then((x) => x.json());
}
$("#rail-analytics").addEventListener("click", async (e) => {
  const add = e.target.closest(".add-syn");
  if (add) {
    e.stopPropagation();
    const row = add.closest(".sug");
    await addSynonym(row.dataset.term, [row.dataset.exp]);
    add.textContent = "В словаре"; add.disabled = true;
    return;
  }
  const lb = e.target.closest("button[data-label]");
  if (lb) {
    e.stopPropagation();
    const q = lb.closest(".gap").dataset.q;
    await fetch("/api/gaps/label", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q, label: lb.dataset.label }) });
    lb.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === lb));
    return;
  }
  const row = e.target.closest("[data-q]");
  if (row) focusDemand(row.dataset.q);
});
function calc() {
  const f = Object.fromEntries([...new FormData($("#calc")).entries()].map(([k, v]) => [k, +v || 0]));
  const orders = f.s * Math.max(0, f.f0 - f.f1) / 100 * f.leave / 100 * f.conv / 100;
  const month = orders * f.check;
  const mln = (v) => (v / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 });
  $("#calc-out").innerHTML = `<b>+${Math.round(orders).toLocaleString("ru-RU")}</b> ${plural(Math.round(orders), "заказ", "заказа", "заказов")} в месяц,
    около <b>${mln(month)} млн ₽</b> в месяц и <b>${mln(month * 12)} млн ₽</b> в год.
    <small>Поиски × (неудачные сейчас − с умным поиском) × доля ушедших × конверсия × средний чек. Это оценка, а не измерение: рост продаж подтверждает A/B-тест после внедрения.</small>`;
}

function focusDemand(q) {
  const d = S.demand.find((x) => x.query === q);
  if (!d) return;
  S.focusQuery = q; flyTo(d.xy[0], d.xy[1], 7, 900); S.dirty = true;
}

/* ===================== запуск ===================== */
function setStage(stage) { document.body.dataset.stage = stage; layoutIntro(); S.dirty = true; }
function layoutIntro() {
  // На вступлении строка поиска стоит под заголовком, высота которого зависит от ширины экрана.
  const cap = $("#search-form"), routes = $("#routes");
  if (document.body.dataset.stage === "intro" && S.W > 900) {
    const hb = $("#hero").getBoundingClientRect();
    cap.style.top = hb.bottom + 32 + "px";
    routes.style.top = hb.bottom + 32 + cap.offsetHeight + 18 + "px";
  } else { cap.style.top = ""; routes.style.top = ""; }
}
window.addEventListener("resize", () => { resize(); layoutIntro(); S.dirty = true; });
document.fonts?.ready.then(layoutIntro);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden) closeDrawer(true); });

async function boot() {
  resize(); layoutIntro();
  requestAnimationFrame(draw);
  const [m, h] = await Promise.all([fetch("/api/map?v=" + Date.now()).then((x) => x.json()), fetch("/health").then((x) => x.json()).catch(() => ({}))]);
  S.groupNames = m.groups; S.groupKeys = Object.keys(m.groups);
  S.n = m.points.length;
  S.xs = new Float32Array(S.n); S.ys = new Float32Array(S.n); S.gi = new Uint8Array(S.n);
  S.byGroup = S.groupKeys.map(() => []);
  m.points.forEach(([id, x, y, g, t, v, p], i) => {
    // Индекс массива совпадает с product_id: сервер отдаёт точки по порядку.
    S.xs[i] = x; S.ys[i] = y; S.gi[i] = S.groupKeys.indexOf(g); S.titles[i] = t; S.vendors[i] = v; S.prices[i] = p;
    S.byGroup[S.gi[i]].push(i);
  });
  buildGrid(); renderLegend(); fitAll(0);
  $("#status-line").innerHTML = `<span class="dot" aria-hidden="true"></span>${S.n.toLocaleString("ru-RU")} продуктов на карте${h.llm ? ", GigaChat подключена" : ""}`;
  S.dirty = true;
  const initial = new URLSearchParams(location.search).get("q");
  if (initial) { input.value = initial; runSearch(initial); }
}
boot();
