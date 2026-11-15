"use strict";

(() => {
  const root = document.getElementById("three-way");
  if (!root) return;
  const data = root.dataset;
  const el = (id) => document.getElementById(id);
  const say = (id, text) => { el(id).textContent = text; };
  const NS = "http://www.w3.org/2000/svg";
  const ACTIONS = { sell: "VERKOPEN", buy: "KOPEN", hold: "HOUDEN" };
  const ROTATION = { hold: "erin", buy: "kopen", sell: "eruit", none: "-" };
  const COLORS = { ink: "#161a20", hold: "#8a93a0", executed: "#b45f06", up: "#0f6b3c", down: "#b3261e", ma50: "#1d4ed8", ma200: "#b45f06" };
  const MONTHS = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"];
  const WEIGHT_LIMIT = 20;
  const euro = (v) => new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(v);
  const signed = (v) => (v >= 0 ? "+" : "") + euro(v);
  const last = (arr) => arr[arr.length - 1];
  const score = (v) => (v === null || v === undefined ? "-" : (v >= 0 ? "+" : "") + Number(v).toFixed(1));
  const percent = (v, digits = 1) => (v === null || v === undefined ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`);
  const tone = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
  const compact = (v) => new Intl.NumberFormat("nl-NL", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  const today = () => new Date().toISOString().slice(0, 10);
  const state = { overview: null, advice: null, views: {}, players: null, journal: [], open: new Set(), news: {}, busy: false };

  // ------------------------------------------------------------ helpers
  function html(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function svg(name, attrs = {}) {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    return node;
  }
  function table(headers, rows) {
    const t = html("table", "data");
    const head = t.createTHead().insertRow();
    headers.forEach((h) => { const th = html("th", "", h); th.scope = "col"; head.append(th); });
    const body = t.createTBody();
    rows.forEach((r) => body.append(r instanceof HTMLTableRowElement ? r : tableRow(r)));
    return t;
  }
  function tableRow(cells) {
    const tr = html("tr");
    cells.forEach((c) => tr.append(c instanceof Node ? c : html("td", "", c)));
    return tr;
  }
  function heat(v) {
    // Hoe groter de beweging, hoe sterker de tint; bij 30% is hij vol.
    if (v === null || v === undefined) return html("td", "dim", "-");
    const td = html("td", "", percent(v));
    const strength = Math.min(Math.abs(v) / 30, 1) * 0.26;
    if (v) td.style.backgroundColor = v > 0 ? `rgba(15,107,60,${strength.toFixed(3)})` : `rgba(179,38,30,${strength.toFixed(3)})`;
    return td;
  }
  async function api(method, url, body) {
    const response = await fetch(url, {
      method, credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": data.csrf },
      body: body ? JSON.stringify(body) : undefined,
    });
    const type = response.headers.get("content-type") || "";
    const result = type.includes("json") ? await response.json() : {};
    if (!response.ok) throw new Error(result.error || `Fout (status ${response.status})`);
    return result;
  }
  const adviceRow = (ticker) => state.advice && state.advice.rows.find((r) => r.ticker === ticker);
  const rotationRow = (ticker) => state.advice && (state.advice.rotation || []).find((r) => r.ticker === ticker);
  const held = () => state.overview.monitor.filter((r) => r.held);

  // ------------------------------------------------------------ grafieken
  function lineChart(target, days, lines, opts = {}) {
    const W = opts.width || 1000, H = opts.height || 300, m = { l: 64, r: 10, t: 10, b: 24 };
    const format = opts.format || euro;
    const all = lines.flatMap((s) => s.values).filter((v) => v !== null);
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    const x = (i) => m.l + (i / Math.max(days.length - 1, 1)) * (W - m.l - m.r);
    const y = (v) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "Grafiek" });
    for (let k = 0; k <= 4; k++) {
      const v = lo + ((hi - lo) * k) / 4;
      chart.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "gridline" }));
      const label = svg("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", class: "axis" });
      label.textContent = format(v);
      chart.append(label);
    }
    [0, Math.floor(days.length / 2), days.length - 1].forEach((i) => {
      const t = svg("text", { x: x(i), y: H - 6, "text-anchor": i === 0 ? "start" : i === days.length - 1 ? "end" : "middle", class: "axis" });
      t.textContent = days[i];
      chart.append(t);
    });
    lines.forEach((s) => {
      let d = "", pen = false;
      s.values.forEach((v, i) => {
        if (v === null) { pen = false; return; }
        d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true;
      });
      chart.append(svg("path", { d, fill: "none", stroke: s.color, "stroke-width": s.width || 1.6 }));
    });
    const tip = html("div", "tip"); tip.hidden = true;
    chart.addEventListener("mousemove", (event) => {
      const box = chart.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * W;
      const i = Math.max(0, Math.min(days.length - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (days.length - 1))));
      tip.replaceChildren(html("div", "", days[i]), ...lines.filter((s) => s.values[i] !== null).map((s) => {
        const row = html("div", "", `${s.name}: ${format(s.values[i])}`);
        row.style.color = s.color;
        return row;
      }));
      tip.hidden = false;
      tip.style.left = Math.max(0, Math.min(event.clientX - box.left + 14, box.width - 190)) + "px";
      tip.style.top = "6px";
    });
    chart.addEventListener("mouseleave", () => { tip.hidden = true; });
    target.replaceChildren(chart, tip);
  }
  function legend(items) {
    const box = html("div", "legend");
    box.append(...items.map(([name, color]) => { const s = html("span"); const i = html("i"); i.style.background = color; s.append(i, name); return s; }));
    return box;
  }
  function sparkline(values) {
    const W = 88, H = 20, lo = Math.min(...values), hi = Math.max(...values);
    const points = values.map((v, i) => `${((i / Math.max(values.length - 1, 1)) * W).toFixed(1)},${(H - 2 - ((v - lo) / (hi - lo || 1)) * (H - 4)).toFixed(1)}`);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "spark", "aria-hidden": "true" });
    chart.append(svg("polyline", { points: points.join(" "), fill: "none", "stroke-width": 1.4, stroke: last(values) >= values[0] ? COLORS.up : COLORS.down }));
    return chart;
  }
  function barChart(target, months) {
    const W = 420, H = 190, m = { l: 8, r: 8, t: 16, b: 22 };
    const top = Math.max(...months.map((b) => Math.abs(b.pct)), 1);
    const zero = m.t + (H - m.t - m.b) / 2, scale = (H - m.t - m.b) / 2 / top, step = (W - m.l - m.r) / months.length;
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Rendement van de portefeuille per maand in procenten" });
    chart.append(svg("line", { x1: m.l, x2: W - m.r, y1: zero, y2: zero, class: "gridline" }));
    months.forEach((b, i) => {
      const height = Math.abs(b.pct) * scale, x = m.l + i * step + step * 0.15;
      chart.append(svg("rect", { x, y: b.pct >= 0 ? zero - height : zero, width: step * 0.7, height: Math.max(height, 0.5), fill: b.pct >= 0 ? COLORS.up : COLORS.down }));
      const value = svg("text", { x: x + step * 0.35, y: b.pct >= 0 ? zero - height - 3 : zero + height + 11, "text-anchor": "middle", class: "axis" });
      value.textContent = b.pct.toFixed(0);
      const name = svg("text", { x: x + step * 0.35, y: H - 5, "text-anchor": "middle", class: "axis" });
      name.textContent = MONTHS[Number(b.month.slice(5, 7)) - 1];
      chart.append(value, name);
    });
    target.replaceChildren(chart);
  }

  // ------------------------------------------------- cijferstrook en stempel
  function renderKpis() {
    const s = state.overview.stats;
    if (!s) { el("kpis").replaceChildren(); return; }
    const p = s.periods;
    const items = [["Waarde", euro(s.value), ""], ["Vandaag", percent(p.d1), tone(p.d1)], ["1 week", percent(p.w1), tone(p.w1)], ["1 maand", percent(p.m1), tone(p.m1)],
      ["3 maanden", percent(p.m3), tone(p.m3)], ["12 maanden", percent(p.y1), tone(p.y1)], ["Vanaf de top (2 jaar)", percent(s.from_top_pct, 0), tone(s.from_top_pct)],
      ["Gemiddeld per maand", percent(s.month_average), tone(s.month_average)], ["Gemiddeld per kwartaal", percent(s.quarter_average), tone(s.quarter_average)]];
    el("kpis").replaceChildren(...items.map(([k, v, cls]) => { const box = html("div", "kpi"); box.append(html("div", "k", k), html("div", `v ${cls}`, v)); return box; }));
  }
  function renderStamp(extra) {
    const o = state.overview, advice = state.advice;
    const notes = [];
    if (o && o.stats) notes.push(`Koersen tot en met ${o.stats.day}.`);
    notes.push(extra || (advice ? `Model en advies van ${advice.day}.` : "Model nog niet berekend."));
    if (advice && advice.stale) notes.push(advice.stale);
    if (o && o.failed.length) notes.push(`Niet ververst: ${o.failed.join(", ")}.`);
    say("stamp", notes.join(" "));
  }

  // ------------------------------------------------------------ vandaag
  function rotationItem(advice) {
    // De rotatie hoort bij het begin van de maand: daarbuiten zou hij elke week ruis geven.
    if (Number(advice.day.slice(8, 10)) > 7) return null;
    const moves = (advice.rotation || []).filter((r) => r.action === "sell" || r.action === "buy");
    if (!moves.length) return null;
    const names = (action) => moves.filter((r) => r.action === action).map((r) => r.ticker).join(", ") || "geen";
    return ["Maandelijks", "Rotatie", `eruit: ${names("sell")}. Erin: ${names("buy")}. Ter vergelijking; hooguit één keer per maand.`];
  }
  function todayItems() {
    const items = [];
    if (state.advice) {
      state.advice.rows.filter((r) => r.action !== "hold").forEach((r) => items.push(["Advies", r.ticker, `${ACTIONS[r.action]}: ${r.reason}`]));
      const rotation = rotationItem(state.advice);
      if (rotation) items.push(rotation);
    }
    state.overview.monitor.forEach((row) => row.signals.forEach((text) => items.push([row.held ? "Signaal" : "Watchlist", row.ticker, text])));
    return items;
  }
  function renderToday() {
    const items = todayItems();
    say("today-lead", !held().length ? "Nog geen aandelen. Voeg ze toe onder Beheer."
      : items.length ? `${items.length} ${items.length === 1 ? "punt vraagt" : "punten vragen"} je aandacht.`
        : "Niets vraagt je aandacht. Niets doen is een goede keuze.");
    el("today-list").replaceChildren(...items.map(([kind, ticker, text]) => {
      const li = html("li");
      li.append(html("span", "kind", kind), html("b", "", ticker), text);
      return li;
    }));
  }

  // --------------------------------------------------- regels die werken
  function rule(title, value, ok, why) {
    const li = html("li");
    const line = html("span", "state");
    line.append(html("span", "", title), html("span", ok ? "ok" : "watch", value));
    li.append(line, html("span", "why", why));
    return li;
  }
  function renderRules() {
    const rows = held(), stats = state.overview.stats;
    if (!rows.length || !stats) { el("rules").replaceChildren(html("li", "dim", "Voeg eerst je aandelen toe.")); return; }
    const weights = rows.map((r) => r.weight_pct).sort((a, b) => b - a);
    const top3 = weights.slice(0, 3).reduce((t, w) => t + w, 0);
    const known = rows.filter((r) => r.above_average !== null), above = known.filter((r) => r.above_average).length;
    const since = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
    const trades = state.journal.filter((e) => e.day >= since && (e.action === "gekocht" || e.action === "verkocht")).length;
    el("rules").replaceChildren(
      rule("Grootste positie", `${weights[0].toFixed(0)}%`, weights[0] < WEIGHT_LIMIT, `Houd één aandeel onder ${WEIGHT_LIMIT}%: dan kan geen enkele misser je portefeuille breken.`),
      rule("Grootste drie samen", `${top3.toFixed(0)}%`, top3 <= 60, "Boven 60% hangt je resultaat aan drie namen. Spreiden verlaagt het risico zonder rendement te kosten."),
      rule("Boven lange gemiddelde", `${above} van ${known.length}`, above * 2 >= known.length, "Aandelen onder hun gemiddelde van 200 dagen dalen vaker door. Koop daar niet bij zonder reden."),
      rule("Daling vanaf de top", percent(stats.from_top_pct, 0), stats.from_top_pct > -20, "Bepaal vooraf bij welke daling je iets doet. Wie het pas in de daling bedenkt, verkoopt meestal op het dieptepunt."),
      rule("Handelingen in 30 dagen", String(trades), trades <= 4, "Veel handelen is de duurste gewoonte van particuliere beleggers. Elke handeling kost geld en zelden levert hij iets op."),
    );
  }

  // ------------------------------------------------------------ monitor
  function tickerCell(row) {
    const td = html("td");
    const button = html("button", "ticker", row.ticker);
    button.type = "button";
    button.setAttribute("aria-expanded", String(state.open.has(row.ticker)));
    if (!row.held) button.append(html("small", "", "watchlist"));
    button.addEventListener("click", () => toggle(row.ticker));
    td.append(button);
    return td;
  }
  function adviceCell(row) {
    const found = adviceRow(row.ticker);
    if (!found) return html("td", "dim", "-");
    return html("td", `action ${found.action === "sell" ? "neg" : found.action === "buy" ? "pos" : ""}`, `${ACTIONS[found.action]} ${score(found.score)}`);
  }
  function monitorRow(row) {
    const tomorrow = state.advice && state.advice.tomorrow ? state.advice.tomorrow[row.ticker] : undefined;
    const rotation = rotationRow(row.ticker);
    const spark = html("td"); spark.append(sparkline(row.spark));
    const flags = html("td", row.signals.length ? "" : "dim", row.signals.length ? "" : "-");
    if (row.signals.length) { const flag = html("span", "flag", String(row.signals.length)); flag.title = row.signals.join("; "); flags.append(flag); }
    return tableRow([tickerCell(row), row.price.toFixed(2), heat(row.d1), heat(row.w1), heat(row.m1), heat(row.m3), heat(row.y1), spark,
      html("td", row.above_average === null ? "dim" : row.above_average ? "pos" : "neg", row.above_average === null ? "-" : row.above_average ? "boven" : "onder"),
      row.weight_pct === null ? html("td", "dim", "-") : html("td", row.weight_pct >= WEIGHT_LIMIT ? "neg" : "", `${row.weight_pct.toFixed(0)}%`),
      tomorrow === undefined ? html("td", "dim", "-") : html("td", Math.abs(tomorrow - 50) < 5 ? "dim" : "", `${tomorrow}%`),
      adviceCell(row), html("td", rotation ? "" : "dim", rotation ? ROTATION[rotation.action] : "-"), flags]);
  }
  const MONITOR_HEAD = ["Aandeel", "Koers", "Dag", "1 week", "1 maand", "3 maanden", "12 maanden", "3 mnd", "Trend", "Gewicht", "Morgen", "Advies", "Rotatie", "Signalen"];
  function renderMonitor() {
    const rows = state.overview.monitor;
    if (!rows.length) { el("monitor").replaceChildren(html("p", "helper", "Nog geen aandelen. Open Beheer onderaan en voeg je eerste aandeel toe; daarna zie je hier de trends.")); return; }
    const body = rows.flatMap((row) => (state.open.has(row.ticker) ? [monitorRow(row), detailRow(row)] : [monitorRow(row)]));
    el("monitor").replaceChildren(table(MONITOR_HEAD, body));
  }
  function toggle(ticker) {
    if (state.open.has(ticker)) state.open.delete(ticker); else state.open.add(ticker);
    renderMonitor();
    if (state.open.has(ticker) && !state.news[ticker]) loadNews(ticker);
  }

  // ---------------------------------------------------- detail per aandeel
  function block(title, content) {
    const box = html("div");
    box.append(html("h4", "", title), content);
    return box;
  }
  function list(items) {
    const ul = html("ul");
    items.forEach((item) => { const li = html("li"); li.append(...[].concat(item)); ul.append(li); });
    return ul;
  }
  function priceChart(row) {
    const box = html("div");
    const chart = html("div", "chart");
    const c = row.chart;
    lineChart(chart, c.days, [{ name: "Koers", color: COLORS.ink, values: c.closes, width: 1.8 }, { name: "Gemiddelde 50 dagen", color: COLORS.ma50, values: c.ma50, width: 1.2 },
      { name: "Gemiddelde 200 dagen", color: COLORS.ma200, values: c.ma200, width: 1.2 }], { height: 240, width: 1200, format: (v) => v.toFixed(2), label: `Koers van ${row.ticker} over een jaar met de gemiddelden van 50 en 200 dagen` });
    box.append(legend([["Koers", COLORS.ink], ["Gemiddelde 50 dagen", COLORS.ma50], ["Gemiddelde 200 dagen", COLORS.ma200]]), chart);
    return box;
  }
  function signalBlock(row) {
    const found = adviceRow(row.ticker);
    const lines = row.signals.map((text) => [html("b", "", "Signaal: "), text]);
    lines.push([html("b", "", "Onder de top van 3 maanden: "), `${row.from_high_pct.toFixed(0)}%`]);
    if (found) lines.push([html("b", "", "Advies: "), `${found.reason} (model ${score(found.parts.forest)}, nieuws ${score(found.parts.nieuws)}, intuïtie ${score(found.parts.intuitie)})`]);
    return block("Stand van zaken", list(lines));
  }
  const PLAYER_LEANS = { "veel short": ["Short interest", "negatief"], "analisten: kopen": ["Analisten", "positief"], "analisten: verkopen": ["Analisten", "negatief"],
    "insiders kopen": ["Insiders", "positief"], "insiders verkopen": ["Insiders", "negatief"] };
  function whyBlock(stock) {
    const factors = stock.why.factors.map((f) => ({ ...f }));
    const players = state.players && state.players[stock.ticker];
    if (players) players.labels.filter((l) => PLAYER_LEANS[l]).forEach((l) => factors.push({ name: PLAYER_LEANS[l][0], lean: PLAYER_LEANS[l][1], text: l }));
    return block("Waarom nu", list(factors.map((f) => [html("span", `lean ${f.lean}`), html("b", "", `${f.name}: `), f.text])));
  }
  function dayBlock(stock) {
    const d = stock.daytrade.last;
    const value = (v, suffix) => (v === null || v === undefined ? "-" : `${v}${suffix}`);
    return block(`Laatste handelsdag (${d.day})`, list([
      [html("b", "", "Volume: "), `${value(d.rel_volume, "x")} normaal`], [html("b", "", "Gap bij opening: "), value(d.gap_pct, "%")],
      [html("b", "", "Dagrange: "), `${value(d.range_pct, "%")} (gemiddeld ${value(d.atr_pct, "%")})`], [html("b", "", "RSI 14: "), value(d.rsi, "")],
    ]));
  }
  function playersBlock(ticker) {
    const p = state.players && state.players[ticker];
    if (!p) return block("Wie zit erin", html("p", "helper", state.players ? "Geen gegevens bij Yahoo." : "Gegevens ophalen ..."));
    const value = (v, suffix) => (v === null || v === undefined ? "-" : `${v}${suffix}`);
    const net = p.insiders.net_value;
    return block("Wie zit erin", list([
      [html("b", "", "Institutioneel: "), value(p.institutions_pct, "%")], [html("b", "", "Insiders: "), `${value(p.insiders_pct, "%")} in bezit, 6 maanden ${p.insiders.buys} kopen en ${p.insiders.sells} verkopen (${net >= 0 ? "+" : ""}${compact(net)})`],
      [html("b", "", "Short: "), `${value(p.short_pct_float, "%")} van de vrij verhandelbare aandelen`],
      [html("b", "", "Analisten: "), p.consensus_mean === null ? "-" : `${p.consensus_mean.toFixed(1)} op een schaal van 1 (kopen) tot 5 (verkopen), ${p.analysts} analisten${p.target_upside_pct === null ? "" : `, koersdoel ${p.target_upside_pct >= 0 ? "+" : ""}${p.target_upside_pct}%`}`],
    ]));
  }
  function newsBlock(ticker) {
    const found = state.news[ticker];
    if (!found) return block("Nieuws", html("p", "helper", "Nieuws ophalen ..."));
    if (found.error) return block("Nieuws", html("p", "helper", found.error));
    if (!found.items.length) return block("Nieuws", html("p", "helper", "Geen recente koppen bij Yahoo."));
    return block("Nieuws", list(found.items.map((n) => {
      const title = n.url ? html("a", "", n.title) : html("span", "", n.title);
      if (n.url) { title.href = n.url; title.target = "_blank"; title.rel = "noopener noreferrer"; }
      return [title, ` · ${n.source}${/^\d{4}-/.test(n.time) ? ` · ${n.time.slice(0, 10)}` : ""}`];
    })));
  }
  function viewBlock(ticker) {
    const view = state.views[ticker] || {};
    const form = html("form", "view-form");
    const field = (label, value) => {
      const wrap = html("label", "", label); const input = html("input");
      input.type = "number"; input.min = -5; input.max = 5; input.step = 0.5; input.placeholder = "algemeen";
      input.value = value === null || value === undefined ? "" : value;
      wrap.append(input);
      return [wrap, input];
    };
    const [newsLabel, news] = field("Nieuws", view.news), [intuitionLabel, intuition] = field("Intuïtie", view.intuition);
    const note = html("textarea"); note.maxLength = 500; note.placeholder = "Notitie: waarom denk je dit?"; note.value = view.note || "";
    note.setAttribute("aria-label", `Notitie bij ${ticker}`);
    const save = html("button", "button quiet", "Opslaan"); save.type = "submit";
    const status = html("span", "helper"); status.setAttribute("role", "status");
    form.append(newsLabel, intuitionLabel, save, status, note);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        state.views = (await api("POST", data.views, { ticker, news: news.value, intuition: intuition.value, note: note.value })).views;
        status.textContent = "Opgeslagen. Telt mee bij de volgende keer bijwerken.";
      } catch (error) {
        status.textContent = error.message;
      }
    });
    return block("Jouw beeld (-5 tot +5, leeg is je algemene score)", form);
  }
  function detailRow(row) {
    const stock = state.overview.stocks.find((s) => s.ticker === row.ticker);
    const grid = html("div", "detail-grid");
    grid.append(signalBlock(row), viewBlock(row.ticker), newsBlock(row.ticker));
    if (stock) grid.append(whyBlock(stock));
    if (stock && stock.daytrade.last) grid.append(dayBlock(stock));
    grid.append(playersBlock(row.ticker));
    const box = html("div", "detail-box"); box.append(priceChart(row), grid);
    const td = html("td"); td.colSpan = MONITOR_HEAD.length; td.append(box);
    const tr = html("tr", "detail"); tr.append(td);
    return tr;
  }
  async function loadNews(ticker) {
    try {
      state.news[ticker] = { items: (await api("GET", data.news.replace(/_$/, encodeURIComponent(ticker)))).news };
    } catch (error) {
      state.news[ticker] = { error: error.message };
    }
    if (state.open.has(ticker)) renderMonitor();
  }
  async function loadPlayers() {
    try {
      state.players = (await api("GET", data.players)).players;
    } catch (error) {
      state.players = {};
    }
    if (state.open.size) renderMonitor();
  }

  // -------------------------------------------- waarde, maanden, verdeling
  function renderValue() {
    const o = state.overview;
    if (!o.stocks.length) { ["legend", "value-chart", "sales"].forEach((id) => el(id).replaceChildren()); return; }
    const traded = o.total.hold.some((v, i) => v !== o.total.executed[i]);
    const lines = [{ name: "Waarde bij vasthouden", color: COLORS.ink, values: o.total.hold, width: 1.8 }];
    if (traded) lines.push({ name: "Met uitgevoerd advies", color: COLORS.executed, values: o.total.executed });
    el("legend").replaceChildren(...legend(lines.map((l) => [l.name, l.color])).children);
    lineChart(el("value-chart"), o.days, lines, { height: 300, width: 760, label: "Waarde van de portefeuille over de gekozen periode" });
    const sales = o.stocks.flatMap((s) => s.effects.map((e) => ({ ticker: s.ticker, ...e }))).sort((p, q) => p.day.localeCompare(q.day));
    if (!sales.length) { el("sales").replaceChildren(); return; }
    const cell = (v) => html("td", tone(v), signed(v));
    el("sales").replaceChildren(html("h3", "", "Wat de verkopen van het advies opleverden"),
      table(["Dag", "Aandeel", "Resultaat"], [...sales.map((r) => [r.day, r.ticker, cell(r.euro)]), ["Totaal", "", cell(sales.reduce((t, r) => t + r.euro, 0))]]));
  }
  function renderMonths() {
    const s = state.overview.stats;
    if (!s || !s.months.length) { el("months").replaceChildren(html("p", "helper", "Nog te weinig historie.")); el("month-facts").replaceChildren(); return; }
    barChart(el("months"), s.months);
    const name = (m) => `${MONTHS[Number(m.month.slice(5, 7)) - 1]} ${m.month.slice(0, 4)}`;
    const facts = [["Gemiddeld per maand", percent(s.month_average)], ["Gemiddeld per kwartaal", percent(s.quarter_average)],
      ["Maanden met winst", `${s.positive_months} van ${s.months.length}`], ["Beste maand", `${percent(s.best.pct)} (${name(s.best)})`], ["Slechtste maand", `${percent(s.worst.pct)} (${name(s.worst)})`]];
    el("month-facts").replaceChildren(...facts.flatMap(([k, v]) => [html("dt", "", k), html("dd", "", v)]));
  }
  function renderAllocation() {
    const rows = held();
    el("allocation").replaceChildren(...(rows.length ? rows.map((r) => {
      const line = html("div", "alloc-row"); const bar = html("span", "bar"); const fill = html("i", r.weight_pct >= WEIGHT_LIMIT ? "over" : "");
      fill.style.width = `${Math.min(r.weight_pct / Math.max(rows[0].weight_pct, WEIGHT_LIMIT) * 100, 100)}%`;
      bar.append(fill);
      line.append(html("span", "", r.ticker), bar, html("span", "", `${r.weight_pct.toFixed(0)}%`));
      return line;
    }) : [html("p", "helper", "Nog geen aandelen.")]));
    if (rows.length) el("allocation").append(html("p", "helper", `Oranje is ${WEIGHT_LIMIT}% of meer van je portefeuille.`));
  }

  // ------------------------------------------------------------ logboek
  function fillJournalTickers() {
    const select = el("journal-ticker"), chosen = select.value;
    select.replaceChildren(...state.overview.monitor.map((r) => { const o = html("option", "", r.ticker); o.value = r.ticker; return o; }));
    if (chosen) select.value = chosen;
  }
  function renderJournal() {
    if (!state.journal.length) { el("journal").replaceChildren(html("p", "helper", "Nog niets vastgelegd. Leg je eerstvolgende beslissing vast, ook als je besluit niets te doen.")); return; }
    const price = Object.fromEntries(((state.overview && state.overview.monitor) || []).map((r) => [r.ticker, r.price]));
    el("journal").replaceChildren(table(["Dag", "Aandeel", "Wat", "Waarom", "Koers toen", "Sindsdien", ""], state.journal.map((e) => {
      const remove = html("button", "", "Wis"); remove.type = "button"; remove.setAttribute("aria-label", `Wis de regel van ${e.day} over ${e.ticker}`);
      remove.addEventListener("click", async () => { state.journal = (await api("DELETE", `${data.journal}/${e.id}`)).journal; renderJournal(); renderRules(); });
      const cell = html("td"); cell.append(remove);
      const since = e.price && price[e.ticker] ? (price[e.ticker] / e.price - 1) * 100 : null;
      return [e.day, e.ticker, e.action, html("td", "text", e.note), e.price ? e.price.toFixed(2) : "-", heat(since === null ? null : Math.round(since * 10) / 10), cell];
    })));
  }
  async function addJournal(event) {
    event.preventDefault();
    try {
      state.journal = (await api("POST", data.journal, { ticker: el("journal-ticker").value, action: el("journal-action").value, note: el("journal-note").value })).journal;
      el("journal-note").value = "";
      say("journal-status", "Vastgelegd.");
      renderJournal(); renderRules();
    } catch (error) {
      say("journal-status", error.message);
    }
  }

  // ------------------------------------------------ laden en bijwerken
  function renderAll() {
    renderStamp(); renderKpis(); renderToday(); renderRules(); renderMonitor(); renderValue(); renderMonths(); renderAllocation(); fillJournalTickers(); renderJournal();
  }
  async function loadOverview() {
    try {
      state.overview = await api("GET", `${data.overview}?days=${el("window").value}`);
      renderAll();
    } catch (error) {
      say("stamp", `De koersen konden niet geladen worden: ${error.message}`);
    }
  }
  async function runModel() {
    if (state.busy) return;
    state.busy = true; el("run").disabled = true;
    renderStamp("Model bijwerken ... ongeveer een halve minuut.");
    try {
      state.advice = await api("POST", data.run, { news: el("news").value, intuition: el("intuition").value });
      await loadOverview();
    } catch (error) {
      renderStamp(`Model niet bijgewerkt: ${error.message}`);
    } finally {
      state.busy = false; el("run").disabled = false;
    }
  }

  // ------------------------------------------------------------- beheer
  function numberCell(value, label) {
    const td = html("td"); const input = html("input");
    input.type = "number"; input.step = "any"; input.min = 0; input.value = value; input.setAttribute("aria-label", label);
    td.append(input);
    return [td, input];
  }
  function holdingRow(h) {
    const [qtyTd, qty] = numberCell(h.quantity, `Aantal ${h.ticker}`), [costTd, cost] = numberCell(h.cost_eur, `Kosten ${h.ticker}`);
    const actions = html("td");
    const save = html("button", "", "Opslaan"), remove = html("button", "", "Weghalen");
    save.type = remove.type = "button";
    save.addEventListener("click", () => change(() => api("POST", data.holdings, { ticker: h.ticker, quantity: Number(qty.value), cost_eur: Number(cost.value) }), `${h.ticker} opgeslagen.`));
    remove.addEventListener("click", () => change(() => api("DELETE", `${data.holdings}/${encodeURIComponent(h.ticker)}`), `${h.ticker} weggehaald.`));
    actions.append(save, remove);
    return [h.ticker, qtyTd, costTd, actions];
  }
  async function loadHoldings() {
    const { holdings } = await api("GET", data.holdings);
    el("holdings").replaceChildren(holdings.length ? table(["Ticker", "Aantal", "Kosten (EUR)", ""], holdings.map(holdingRow))
      : html("p", "helper", "Nog geen aandelen. Voeg je eerste aandeel hierboven toe."));
    if (!holdings.length) document.querySelector(".area-manage details").open = true;
  }
  async function change(action, message) {
    say("holdings-status", "Bezig ...");
    try {
      await action();
      await loadHoldings();
      say("holdings-status", message);
      loadOverview();
    } catch (error) {
      say("holdings-status", error.message);
    }
  }
  async function searchStocks() {
    say("search-status", "Zoeken ...");
    el("search-results").replaceChildren();
    try {
      const { results } = await api("GET", `${data.search}?q=${encodeURIComponent(el("search-q").value)}`);
      say("search-status", results.length ? "" : "Niets gevonden. Vul de ticker zelf in.");
      el("search-results").replaceChildren(...results.map((r) => {
        const button = html("button", "result"); button.type = "button";
        button.append(html("span", "", `${r.symbol} · ${r.name}`), html("span", "", `${r.exchange} ${r.type}`));
        button.addEventListener("click", () => { el("add-ticker").value = r.symbol; el("add-qty").focus(); });
        return button;
      }));
    } catch (error) {
      say("search-status", error.message);
    }
  }
  function addStock() {
    const ticker = el("add-ticker").value.trim().toUpperCase();
    const body = { ticker, quantity: Number(el("add-qty").value), cost_eur: Number(el("add-cost").value || 0) };
    change(async () => {
      await api("POST", data.holdings, body);
      ["add-ticker", "add-qty", "add-cost"].forEach((id) => { el(id).value = ""; });
    }, `${ticker} toegevoegd.`);
  }
  async function loadWatchlist() {
    el("watchlist").value = (await api("GET", data.watchlist)).watchlist.join(" ");
  }
  async function saveWatchlist() {
    say("watchlist-status", "Opslaan en koersen ophalen ...");
    try {
      const { watchlist } = await api("POST", data.watchlist, { tickers: el("watchlist").value });
      el("watchlist").value = watchlist.join(" ");
      say("watchlist-status", `${watchlist.length} aandelen opgeslagen.`);
      loadOverview();
    } catch (error) {
      say("watchlist-status", error.message);
    }
  }

  // -------------------------------------------------------------- start
  async function start() {
    const [advice, views, journal] = await Promise.all([api("GET", data.advice), api("GET", data.views), api("GET", data.journal)]);
    state.advice = advice.advice; state.views = views.views; state.journal = journal.journal;
    await loadOverview();
    loadPlayers();
    // Het model werkt zichzelf één keer per dag bij, zodat je niets hoeft in te vullen om informatie te zien.
    if (state.overview && held().length && (!state.advice || state.advice.day !== today())) runModel();
  }
  el("advice-form").addEventListener("submit", (event) => { event.preventDefault(); runModel(); });
  el("journal-form").addEventListener("submit", addJournal);
  el("watchlist-save").addEventListener("click", saveWatchlist);
  el("search-go").addEventListener("click", searchStocks);
  el("search-q").addEventListener("keydown", (event) => { if (event.key === "Enter") searchStocks(); });
  el("add-go").addEventListener("click", addStock);
  el("window").addEventListener("change", loadOverview);
  start().catch((error) => say("stamp", error.message));
  loadWatchlist().catch((error) => say("watchlist-status", error.message));
  loadHoldings().catch((error) => say("holdings-status", error.message));
})();
