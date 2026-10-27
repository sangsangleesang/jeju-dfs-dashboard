/* 제주 지정면세점 수요 대시보드 - 화면 스크립트 (API 키 없음, 서버 /api/data만 호출) */
const S = { d: null, period: 10, charts: {} };
const C = { sea: "#0b5f73", sea2: "#127d96", tang: "#ef7d1a", green: "#1a8a4a", purple: "#6b4fbb", red: "#c8372d", grey: "#a9b3be" };
const PAL = [C.sea, C.tang, C.purple, C.green, C.red];
const $ = (id) => document.getElementById(id);
const fmt = (v, dg = 0) => v == null || isNaN(v) ? "–" : Number(v).toLocaleString("ko-KR", { maximumFractionDigits: dg, minimumFractionDigits: 0 });
const addDays = (s, k) => { const d = new Date(s + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + k); return d.toISOString().slice(0, 10); };
const md = (s) => s ? `${+s.slice(5, 7)}/${+s.slice(8, 10)}` : "";
const lastDate = (o) => { const k = Object.keys(o || {}).filter((x) => o[x] != null).sort(); return k[k.length - 1]; };
function win(o, n, back = 0, end) {
  const L = end || lastDate(o); if (!L) return { dates: [], vals: [] };
  const e = addDays(L, -n * back), dates = [];
  for (let i = n - 1; i >= 0; i--) dates.push(addDays(e, -i));
  return { dates, vals: dates.map((d) => (o && o[d] != null ? o[d] : null)), end: L };
}
const nn = (a) => a.filter((x) => x != null);
const avg = (a) => { const v = nn(a); return v.length ? v.reduce((x, y) => x + y, 0) / v.length : null; };
const sum = (a) => { const v = nn(a); return v.length ? v.reduce((x, y) => x + y, 0) : null; };
const pct = (a, b) => a == null || b == null || b === 0 ? null : ((a - b) / b) * 100;
const hasData = (o) => o && Object.keys(o).length > 0;
function srcMode(id) { const s = (S.d.sources || []).find((x) => x.id === id); return s ? s.mode : "off"; }
function badge(mode) { const t = { live: "실시간", demo: "예시", manual: "입력", empty: "없음", off: "꺼짐" }[mode] || mode; return `<span class="badge ${mode}">${t}</span>`; }
function deltaHtml(p) { if (p == null) return `<span class="delta flat">비교 불가</span>`; const c = p > 0.5 ? "up" : p < -0.5 ? "down" : "flat"; return `<span class="delta ${c}">${p > 0 ? "▲" : p < 0 ? "▼" : "■"} ${Math.abs(p).toFixed(1)}%</span>`; }

function chart(id, cfg) { if (S.charts[id]) S.charts[id].destroy(); const el = $(id); if (!el) return; S.charts[id] = new Chart(el, cfg); }
const baseOpts = (extra = {}) => ({
  responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
  plugins: { legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { size: 11 } } },
    tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y, 1)}` } } },
  scales: { x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, font: { size: 11 } } },
    y: { grid: { color: "#eef1f4" }, ticks: { font: { size: 11 }, callback: (v) => fmt(v) } } }, ...extra });
const line = (label, data, color, o = {}) => ({ label, data, borderColor: color, backgroundColor: color + "22", borderWidth: 2, pointRadius: S.period === 10 ? 2.5 : 0, tension: 0.3, spanGaps: true, ...o });
const prevLine = (data, label = "직전 기간") => line(label, data, C.grey, { borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 });

function compareChart(id, obj, label, color) {
  const n = S.period, cur = win(obj, n), prev = win(obj, n, 1, cur.end);
  chart(id, { type: "line", data: { labels: cur.dates.map(md), datasets: [line(label, cur.vals, color, { fill: true }), prevLine(prev.vals)] }, options: baseOpts() });
}

/* ---------- 지표 정의 ---------- */
function metrics() {
  const d = S.d, nm = d.naver_main || {}, m = d.manual || {}, kto = d.kto || {};
  return [
    { key: "kto", label: "제주 외지인 방문자", unit: "명", obj: kto["외지인"], agg: "sum", mode: srcMode("kto"), color: C.sea },
    { key: "inbound", label: "내국인 입도객", unit: "명", obj: m.inbound_domestic, agg: "sum", mode: srcMode("manual_inbound_domestic"), color: C.sea2 },
    { key: "air", label: "제주항공권 검색", unit: "지수", obj: nm["제주항공권"], agg: "avg", mode: srcMode("naver_main"), color: C.tang },
    { key: "rent", label: "제주렌트카 검색", unit: "지수", obj: nm["제주렌트카"], agg: "avg", mode: srcMode("naver_main"), color: C.purple },
    { key: "dfs", label: "제주면세점 검색", unit: "지수", obj: nm["제주면세점"], agg: "avg", mode: srcMode("naver_main"), color: C.green },
    { key: "udo", label: "우도 방문객", unit: "명", obj: m.udo, agg: "sum", mode: srcMode("manual_udo"), color: C.sea, alt: { label: "우도 검색", obj: nm["우도"], mode: srcMode("naver_main") } },
    { key: "jungmun", label: "중문관광단지 방문객", unit: "명", obj: m.jungmun, agg: "sum", mode: srcMode("manual_jungmun"), color: C.red, alt: { label: "중문관광단지 검색", obj: nm["중문관광단지"], mode: srcMode("naver_main") } },
    { key: "sales", label: "지정면세점 매출", unit: "원", obj: m.sales, agg: "sum", mode: srcMode("manual_sales"), color: C.tang },
  ];
}

function renderKpis() {
  const n = S.period, box = $("kpis"); box.innerHTML = "";
  metrics().forEach((mt, i) => {
    let { label, unit, obj, agg, mode } = mt;
    if (!hasData(obj) && mt.alt && hasData(mt.alt.obj)) { label = mt.alt.label; obj = mt.alt.obj; agg = "avg"; unit = "지수"; mode = mt.alt.mode; }
    const el = document.createElement("div"); el.className = "card kpi";
    if (!hasData(obj)) {
      el.classList.add("empty");
      el.innerHTML = `<div class="k-title">${label} ${badge("empty")}</div><div class="k-val">입력된 값 없음</div><div class="k-sub"><a href="/admin">데이터 입력 화면</a>에서 넣을 수 있습니다.</div>`;
      box.appendChild(el); return;
    }
    const cur = win(obj, n), prev = win(obj, n, 1, cur.end);
    const main = agg === "sum" ? sum(cur.vals) : avg(cur.vals);
    const p = pct(avg(cur.vals), avg(prev.vals));
    const cid = "spark" + i;
    el.innerHTML = `<div class="k-title">${label} ${badge(mode)}</div>
      <div class="k-row"><div class="k-val">${fmt(main, agg === "avg" ? 1 : 0)}<small>${unit}${agg === "avg" ? " (평균)" : ""}</small></div>${deltaHtml(p)}</div>
      <div class="k-sub">${md(cur.dates[0])}~${md(cur.end)} · 일평균 ${fmt(avg(cur.vals), agg === "avg" ? 1 : 0)}</div>
      <div style="height:42px"><canvas id="${cid}"></canvas></div>`;
    box.appendChild(el);
    chart(cid, { type: "line", data: { labels: cur.dates, datasets: [{ data: cur.vals, borderColor: mt.color, backgroundColor: mt.color + "1f", fill: true, borderWidth: 1.6, pointRadius: 0, tension: 0.35, spanGaps: true }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false } } } });
  });
  // 날씨 카드
  const om = S.d.openmeteo, kma = S.d.kma_now;
  const k = kma && kma.find((x) => x.id === "jeju"), o = om && om.jeju && om.jeju.current;
  if (k || o) {
    const el = document.createElement("div"); el.className = "card kpi";
    const t = k ? k.temp : o.temp, wind = k ? k.wind : o.wind;
    el.innerHTML = `<div class="k-title">제주시 현재 날씨 ${badge("live")}</div><div class="k-val">${fmt(t, 1)}<small>℃</small></div>
      <div class="k-sub">${k ? "강수형태 " + k.pty : wxText(o.code)} · 바람 ${fmt(wind, 1)}m/s</div><div class="k-sub">${k ? "기상청 " + k.observed : "Open-Meteo " + (o.time || "").replace("T", " ")}</div>`;
    box.appendChild(el);
  }
}

function renderFlow() {
  const n = S.period, ms = metrics().filter((m) => hasData(m.obj) && m.key !== "sales").slice(0, 5);
  let labels = [];
  const ds = ms.map((m, i) => {
    const w = win(m.obj, n), a = avg(w.vals); if (w.dates.length > labels.length) labels = w.dates;
    return line(m.label, w.vals.map((v) => (v == null || !a ? null : (v / a) * 100)), PAL[i % PAL.length]);
  });
  chart("cFlow", { type: "line", data: { labels: labels.map(md), datasets: ds }, options: baseOpts() });
  const rows = metrics().concat([{ label: "구글 '제주항공권'", obj: (S.d.google || {})["제주항공권"] }, { label: "외국인 방문자", obj: (S.d.kto || {})["외국인"] }])
    .filter((m) => hasData(m.obj)).map((m) => { const c = win(m.obj, n), p = win(m.obj, n, 1, c.end); return { label: m.label, p: pct(avg(c.vals), avg(p.vals)) }; })
    .filter((r) => r.p != null).sort((a, b) => Math.abs(b.p) - Math.abs(a.p)).slice(0, 6);
  $("movers").innerHTML = rows.length ? rows.map((r) => `<li><span class="arrow ${r.p > 0.5 ? "up" : r.p < -0.5 ? "down" : "flat"}">${r.p > 0.5 ? "▲" : r.p < -0.5 ? "▼" : "■"}</span><span><b>${r.label}</b> 일평균이 직전 ${n === 10 ? "10일" : "1개월"}보다 <b>${Math.abs(r.p).toFixed(1)}% ${r.p >= 0 ? "늘었습니다" : "줄었습니다"}</b>.</span></li>`).join("")
    : `<li>비교할 데이터가 아직 없습니다.</li>`;
}

function renderVisitors() {
  const kto = S.d.kto || {}, m = S.d.manual || {};
  $("bKto").innerHTML = badge(srcMode("kto")); $("bKto2").innerHTML = badge(srcMode("kto"));
  compareChart("cKto", kto["외지인"], "외지인 방문자", C.sea);
  compareChart("cKtoFor", kto["외국인"], "외국인 방문자", C.purple);
  if (hasData(m.inbound_domestic)) { $("boxInbound").innerHTML = '<canvas id="cInbound"></canvas>'; compareChart("cInbound", m.inbound_domestic, "내국인 입도객", C.sea2); }
  else $("boxInbound").innerHTML = `<div class="empty-box">입력된 입도객 값이 없습니다.<br><a href="/admin">데이터 입력</a>에서 관광협회 일별 내국인 입도객을 넣어 주세요.</div>`;
  const w = win(kto["외지인"], 28), days = ["일", "월", "화", "수", "목", "금", "토"], acc = days.map(() => []);
  w.dates.forEach((d, i) => { if (w.vals[i] != null) acc[new Date(d + "T00:00:00Z").getUTCDay()].push(w.vals[i]); });
  chart("cDow", { type: "bar", data: { labels: days, datasets: [{ label: "요일 평균", data: acc.map(avg), backgroundColor: days.map((_, i) => (i === 5 || i === 6 || i === 0 ? C.tang : C.sea2)), borderRadius: 6 }] }, options: baseOpts({ plugins: { legend: { display: false } } }) });
}

function multiChart(id, obj, keys) {
  const n = S.period; let labels = [];
  const ds = keys.filter((k) => hasData(obj[k])).map((k, i) => { const w = win(obj[k], n); if (w.dates.length > labels.length) labels = w.dates; return line(k, w.vals, PAL[i % PAL.length]); });
  chart(id, { type: "line", data: { labels: labels.map(md), datasets: ds }, options: baseOpts() });
}

function renderSearch() {
  const nm = S.d.naver_main || {}, g = S.d.google || {}, dfs = S.d.naver_dfs || {};
  $("bNaver").innerHTML = badge(srcMode("naver_main")); $("bGoogle").innerHTML = badge(srcMode("google")); $("bDfs").innerHTML = badge(srcMode("naver_dfs"));
  multiChart("cNaver", nm, ["제주항공권", "제주렌트카", "제주면세점"]);
  multiChart("cGoogle", g, ["제주항공권", "제주렌트카", "제주면세점", "우도", "중문관광단지"]);
  multiChart("cDfs", dfs, Object.keys(dfs));
  const n = S.period, rows = [];
  [["네이버", nm, "naver_main"], ["네이버", dfs, "naver_dfs"], ["구글", g, "google"]].forEach(([src, o, id]) => Object.keys(o).forEach((k) => {
    const c = win(o[k], n), p = win(o[k], n, 1, c.end); rows.push(`<tr><td>${k} <span class="pill">${src}</span> ${badge(srcMode(id))}</td><td>${fmt(avg(c.vals), 1)}</td><td>${fmt(avg(p.vals), 1)}</td><td>${deltaHtml(pct(avg(c.vals), avg(p.vals)))}</td></tr>`);
  }));
  $("tKeywords").innerHTML = `<thead><tr><th>키워드 묶음</th><th>이번 기간</th><th>직전 기간</th><th>변화</th></tr></thead><tbody>${rows.join("")}</tbody>`;
}

function spotChart(id, visitors, search, wxKey, wxField, wxLabel, color) {
  const n = S.period, s = win(search, n), end = s.end, v = win(visitors || {}, n, 0, end);
  const om = S.d.openmeteo && S.d.openmeteo[wxKey], wx = {}; (om ? om.days : []).forEach((d) => (wx[d.date] = d[wxField]));
  const ds = [line("검색 지수", s.vals, color, { yAxisID: "y" })];
  if (hasData(visitors)) ds.unshift(line("방문객(명)", v.vals, C.sea, { yAxisID: "y2", fill: true }));
  if (om) ds.push({ type: "bar", label: wxLabel, data: s.dates.map((d) => wx[d] ?? null), backgroundColor: "#9cc3d055", yAxisID: "y3", borderRadius: 3 });
  const o = baseOpts(); o.scales.y2 = { position: "right", display: hasData(visitors), grid: { display: false }, ticks: { callback: (x) => fmt(x) } }; o.scales.y3 = { display: false };
  chart(id, { type: "line", data: { labels: s.dates.map(md), datasets: ds }, options: o });
}

const WMO = (c) => c == null ? ["–", ""] : c === 0 ? ["맑음", "☀️"] : c <= 2 ? ["구름 조금", "🌤️"] : c === 3 ? ["흐림", "☁️"] : c <= 48 ? ["안개", "🌫️"] : c <= 57 ? ["이슬비", "🌦️"] : c <= 67 ? ["비", "🌧️"] : c <= 77 ? ["눈", "❄️"] : c <= 82 ? ["소나기", "🌧️"] : c <= 86 ? ["눈 소나기", "🌨️"] : ["뇌우", "⛈️"];
const wxText = (c) => WMO(c).join(" ").trim();

function renderWeather() {
  const om = S.d.openmeteo || {}, kma = S.d.kma_now || [], useK = kma.length > 0;
  $("bWx").innerHTML = badge(useK || Object.keys(om).length ? "live" : "off");
  $("wxDesc").textContent = useK ? "기상청 초단기실황(관측) 기준. 하늘 상태 아이콘은 Open-Meteo 모델값입니다." : "Open-Meteo 현재값 기준 (기상청 키를 넣으면 기상청 관측값으로 바뀝니다).";
  const spots = Object.keys(om).length ? Object.keys(om) : kma.map((k) => k.id);
  $("wxNow").innerHTML = spots.map((id) => {
    const o = om[id] || {}, c = o.current || {}, k = kma.find((x) => x.id === id), [t, ic] = WMO(c.code);
    const today = (o.days || []).find((d) => d.date === S.d.today) || {};
    return `<div class="wx"><div class="wx-name"><span>${o.name || (k && k.name)}</span><span class="ico">${ic}</span></div>
      <div class="wx-temp">${fmt(k ? k.temp : c.temp, 1)}℃</div>
      <div class="wx-meta"><span>${k ? "강수형태 " + k.pty : t}</span><span>습도 ${fmt(k ? k.humidity : c.humidity)}%</span><span>바람 ${fmt(k ? k.wind : c.wind, 1)}m/s</span><span>1시간 강수 ${fmt(k ? k.rain1h : c.precip, 1)}mm</span><span>오늘 ${fmt(today.tmin, 0)}~${fmt(today.tmax, 0)}℃</span><span>강수확률 ${fmt(today.pop)}%</span></div>
      <div class="wx-src">${k ? "기상청 관측 " + k.observed : "Open-Meteo " + (c.time || "").replace("T", " ")}</div></div>`;
  }).join("") || `<div class="empty-box">날씨 데이터를 불러오지 못했습니다.</div>`;
  const sel = $("fcSpot"); if (!sel.options.length) { Object.keys(om).forEach((id) => sel.add(new Option(om[id].name, id))); sel.onchange = renderForecast; }
  renderForecast();
  const j = om.jeju; if (j) {
    const past = j.days.filter((d) => d.date < S.d.today).slice(-S.period);
    chart("cWxPast", { type: "bar", data: { labels: past.map((d) => md(d.date)), datasets: [
      { type: "line", label: "최고기온(℃)", data: past.map((d) => d.tmax), borderColor: C.tang, yAxisID: "y", tension: 0.3, pointRadius: 0, borderWidth: 2 },
      { type: "line", label: "최저기온(℃)", data: past.map((d) => d.tmin), borderColor: C.sea2, yAxisID: "y", tension: 0.3, pointRadius: 0, borderWidth: 2 },
      { label: "강수량(mm)", data: past.map((d) => d.precip), backgroundColor: "#5aa9c855", yAxisID: "y2", borderRadius: 3 }] },
      options: (() => { const o = baseOpts(); o.scales.y2 = { position: "right", grid: { display: false } }; return o; })() });
  }
}
function renderForecast() {
  const om = S.d.openmeteo || {}, id = $("fcSpot").value || "jeju", o = om[id]; if (!o) { $("tFc").innerHTML = ""; return; }
  const dn = ["일", "월", "화", "수", "목", "금", "토"];
  const fc = o.days.filter((d) => d.date >= S.d.today).slice(0, 10);
  $("tFc").innerHTML = `<thead><tr><th>날짜</th><th>날씨</th><th>최저/최고</th><th>강수확률</th><th>강수량</th><th>최대풍속</th></tr></thead><tbody>${fc.map((d) => { const [t, ic] = WMO(d.code); return `<tr><td>${md(d.date)} (${dn[new Date(d.date + "T00:00:00Z").getUTCDay()]})</td><td><span class="ico">${ic}</span> ${t}</td><td>${fmt(d.tmin, 0)} / ${fmt(d.tmax, 0)}℃</td><td>${fmt(d.pop)}%</td><td>${fmt(d.precip, 1)}mm</td><td>${fmt(d.wind, 1)}m/s</td></tr>`; }).join("")}</tbody>`;
}

function corr(a, b) {
  const ks = Object.keys(a).filter((k) => b[k] != null && a[k] != null).sort().slice(-90); if (ks.length < 14) return null;
  const x = ks.map((k) => a[k]), y = ks.map((k) => b[k]), mx = avg(x), my = avg(y);
  let sxy = 0, sx = 0, sy = 0; x.forEach((v, i) => { sxy += (v - mx) * (y[i] - my); sx += (v - mx) ** 2; sy += (y[i] - my) ** 2; });
  return sx && sy ? { r: sxy / Math.sqrt(sx * sy), n: ks.length } : null;
}
function renderSales() {
  const m = S.d.manual || {}, box = $("salesCard");
  if (!hasData(m.sales)) { box.innerHTML = `<div class="empty-box">입력된 매출이 없습니다. <a href="/admin">데이터 입력</a>에서 일별 매출을 넣으면 방문·검색 지표와의 상관계수와 추이를 보여 줍니다.</div>`; return; }
  const pairs = [["제주 외지인 방문자", (S.d.kto || {})["외지인"]], ["내국인 입도객", m.inbound_domestic], ["제주면세점 검색", (S.d.naver_main || {})["제주면세점"]], ["제주항공권 검색", (S.d.naver_main || {})["제주항공권"]]];
  const items = pairs.map(([l, o]) => { const c = o ? corr(m.sales, o) : null; return `<div class="c-item"><div class="c-lbl">매출 × ${l}</div><div class="c-val">${c ? c.r.toFixed(2) : "–"}</div><div class="c-lbl">${c ? `${c.n}일 기준 · ${Math.abs(c.r) >= 0.7 ? "강하게" : Math.abs(c.r) >= 0.4 ? "어느 정도" : "약하게"} 함께 움직임` : "겹치는 날이 14일 미만"}</div></div>`; }).join("");
  box.innerHTML = `<h3>매출과 함께 움직이는 정도 (상관계수, 최근 최대 90일)</h3><p class="desc">1에 가까울수록 같이 오르내립니다. 원인·결과를 뜻하지는 않습니다.</p><div class="corr">${items}</div><div class="chart-box" style="margin-top:14px"><canvas id="cSales"></canvas></div>`;
  compareChart("cSales", m.sales, "지정면세점 매출(원)", C.tang);
}

/* ---------- 순별·월간 리포트 ---------- */
let reportRows = [];
function bucket(d, mode) { const y = d.slice(0, 4), mo = +d.slice(5, 7), day = +d.slice(8, 10); return mode === "xun" ? `${y}-${String(mo).padStart(2, "0")}-${day <= 10 ? 1 : day <= 20 ? 2 : 3}` : `${y}-${String(mo).padStart(2, "0")}`; }
function bucketLabel(b, mode) { const p = b.split("-"); return mode === "xun" ? `${+p[1]}월 ${["", "상순", "중순", "하순"][+p[2]]}` : `${p[0]}년 ${+p[1]}월`; }
function renderReport() {
  const d = S.d, nm = d.naver_main || {}, m = d.manual || {}, wj = {}, rj = {};
  ((d.openmeteo && d.openmeteo.jeju && d.openmeteo.jeju.days) || []).filter((x) => x.date < d.today).forEach((x) => { wj[x.date] = (x.tmax + x.tmin) / 2; rj[x.date] = x.precip >= 1 ? 1 : 0; });
  const cols = [["외지인 방문자", (d.kto || {})["외지인"], "sum"], ["내국인 입도객", m.inbound_domestic, "sum"], ["항공권 검색", nm["제주항공권"], "avg"], ["렌트카 검색", nm["제주렌트카"], "avg"], ["면세점 검색", nm["제주면세점"], "avg"], ["우도 방문객", m.udo, "sum"], ["중문 방문객", m.jungmun, "sum"], ["매출(원)", m.sales, "sum"], ["평균기온", wj, "avg"], ["강수일", rj, "sum"]];
  const make = (mode, limit) => {
    const B = {}; cols.forEach(([, o], ci) => Object.keys(o || {}).forEach((dt) => { if (dt >= d.today) return; const b = bucket(dt, mode); (B[b] = B[b] || { n: new Set(), v: cols.map(() => []) }).v[ci].push(o[dt]); B[b].n.add(dt); }));
    const keys = Object.keys(B).sort().reverse().slice(0, limit);
    const rows = keys.map((b) => [bucketLabel(b, mode)].concat(cols.map(([, , a], ci) => (a === "sum" ? sum(B[b].v[ci]) : avg(B[b].v[ci])))));
    return { keys, rows, B };
  };
  const draw = (tid, mode, limit) => {
    const { rows } = make(mode, limit);
    $(tid).innerHTML = `<thead><tr><th>${mode === "xun" ? "순" : "월"}</th>${cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr><td>${r[0]}</td>${r.slice(1).map((v, i) => `<td class="${v == null ? "muted" : ""}">${fmt(v, cols[i][2] === "avg" ? 1 : 0)}</td>`).join("")}</tr>`).join("")}</tbody>`;
    return rows;
  };
  reportRows = [["구분"].concat(cols.map((c) => c[0]))].concat(draw("tXun", "xun", 9)).concat(draw("tMonth", "month", 4));
}
function downloadCsv() {
  const csv = "﻿" + reportRows.map((r) => r.map((v) => (v == null ? "" : typeof v === "number" ? Math.round(v * 10) / 10 : `"${v}"`)).join(",")).join("\n");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = `jeju_report_${S.d.today}.csv`; a.click();
}

function renderSources() {
  $("tSources").innerHTML = `<thead><tr><th>지표</th><th>제공</th><th>주기</th><th>상태</th><th>마지막 갱신</th><th>메모</th></tr></thead><tbody>${S.d.sources.map((s) => `<tr><td>${s.url ? `<a href="${s.url}" target="_blank" rel="noopener">${s.name}</a>` : s.name}</td><td style="text-align:left">${s.provider}</td><td>${s.cadence}</td><td>${badge(s.mode)}</td><td>${s.updated_at || "–"}</td><td style="text-align:left;white-space:normal;min-width:220px;color:var(--ink2)">${s.message || ""}</td></tr>`).join("")}</tbody>`;
  const demo = S.d.sources.filter((s) => s.mode === "demo");
  $("banner").innerHTML = demo.length ? `<div class="banner">⚠️ <div><b>예시 데이터가 섞여 있습니다.</b> ${demo.map((s) => s.name).join(", ")} 은(는) API 키가 없거나 호출에 실패해 화면 구성을 보여주는 가상 값입니다. 배포 화면 환경변수에 키를 넣으면 실제 값으로 바뀝니다. 상세는 <a href="#sources">데이터 출처</a>를 보세요.</div></div>` : "";
}

function renderAll() {
  $("periodText").textContent = `최근 ${S.period === 10 ? "10일" : "1개월(30일)"} · 직전 같은 기간과 비교 · 지표마다 최신 공개일을 기준으로 합니다.`;
  renderKpis(); renderFlow(); renderVisitors(); renderSearch();
  spotChart("cUdo", (S.d.manual || {}).udo, (S.d.naver_main || {})["우도"], "udo", "wind", "최대풍속(m/s)", C.tang);
  spotChart("cJungmun", (S.d.manual || {}).jungmun, (S.d.naver_main || {})["중문관광단지"], "jungmun", "precip", "강수량(mm)", C.red);
  renderWeather(); renderSales(); renderReport(); renderSources();
}

async function load(refresh = 0) {
  $("updated").textContent = "불러오는 중…";
  try {
    const r = await fetch(`/api/data${refresh ? "?refresh=1" : ""}`); if (!r.ok) throw new Error(r.status);
    S.d = await r.json(); $("loading").hidden = true; $("app").hidden = false;
    renderAll(); $("updated").textContent = `갱신 ${S.d.generated_at}`;
  } catch (e) { $("updated").textContent = "불러오기 실패 – 잠시 후 다시 시도"; $("loading").textContent = "데이터를 불러오지 못했습니다. 새로고침해 주세요."; }
}

document.querySelectorAll(".seg button").forEach((b) => b.onclick = () => { document.querySelectorAll(".seg button").forEach((x) => x.classList.toggle("on", x === b)); S.period = +b.dataset.period; if (S.d) renderAll(); });
$("refreshBtn").onclick = () => load(1);
$("csvBtn").onclick = downloadCsv;
// 모바일 탭 & 스크롤 위치 표시
$("mtabs").innerHTML = [...document.querySelectorAll(".side a")].map((a) => `<a href="${a.getAttribute("href")}">${a.textContent}</a>`).join("");
const links = [...document.querySelectorAll(".side a, .mtabs a")];
const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) links.forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + e.target.id)); }), { rootMargin: "-40% 0px -55% 0px" });
document.querySelectorAll("main section").forEach((s) => io.observe(s));
Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
load();
setInterval(() => load(0), 10 * 60 * 1000);
