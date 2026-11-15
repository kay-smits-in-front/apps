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
  const COLORS = { hold: "#a3acbd", executed: "#ffb454", up: "#b5f36d", down: "#ff8c9a" };
  const euro = (v) => new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(v);
  const signed = (v) => (v >= 0 ? "+" : "") + euro(v);
  const last = (arr) => arr[arr.length - 1];
  const score = (v) => (v === null || v === undefined ? "-" : (v >= 0 ? "+" : "") + Number(v).toFixed(1));
  const compact = (v) => new Intl.NumberFormat("nl-NL", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  const state = { overview: null, advice: null, views: {}, players: null, open: new Set(), news: {} };

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
  const colored = (v) => html("td", v >= 0 ? "pos" : "neg", signed(v));
  function pct(v) {
    if (v === null || v === undefined) return html("td", "dim", "-");
    return html("td", v > 0 ? "pos" : v < 0 ? "neg" : "", `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);
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

  // ------------------------------------------------------------ vandaag
  function rotationItem(advice) {
    // De rotatie hoort bij het begin van de maand: daarbuiten zou hij elke week ruis geven.
    if (Number(advice.day.slice(8, 10)) > 7) return null;
    const moves = (advice.rotation || []).filter((r) => r.action === "sell" || r.action === "buy");
    if (!moves.length) return null;
    const names = (action) => moves.filter((r) => r.action === action).map((r) => r.ticker).join(", ") || "geen";
    return ["Maandelijks", "Rotatie", `eruit: ${names("sell")}. Erin: ${names("buy")}. Ter vergelijking; voer hooguit één keer per maand uit.`];
  }
  function todayItems() {
    const items = [];
    const advice = state.advice;
    if (advice) {
      advice.rows.filter((r) => r.action !== "hold").forEach((r) => items.push(["Advies", r.ticker, `${ACTIONS[r.action]}: ${r.reason}`]));
      const rotation = rotationItem(advice);
      if (rotation) items.push(rotation);
    }
    ((state.overview && state.overview.monitor) || []).forEach((row) => row.signals.forEach((text) => {
      items.push([row.held ? "Signaal" : "Watchlist", row.ticker, text]);
    }));
    return items;
  }
  function renderToday() {
    if (!state.overview) return;
    const items = todayItems();
    const stocks = state.overview.monitor.filter((r) => r.held).length;
    const lead = !stocks ? "Nog geen aandelen. Voeg ze toe onder Beheer."
      : items.length ? `${items.length} ${items.length === 1 ? "punt vraagt" : "punten vragen"} je aandacht.`
        : "Niets vraagt je aandacht. Niets doen is deze week een goede keuze.";
    say("today-lead", lead);
    el("today-list").replaceChildren(...items.map(([kind, ticker, text]) => {
      const li = html("li");
      const what = html("span");
      what.append(html("b", "", ticker), html("br"), html("span", "kind", kind));
      li.append(what, html("span", "", text));
      return li;
    }));
    const advice = state.advice;
    const today = new Date().toISOString().slice(0, 10);
    const notes = [];
    if (!advice) notes.push("Het model en het advies zijn nog niet berekend. Druk op de knop.");
    else if (advice.day !== today) notes.push(`Het model en het advies zijn van ${advice.day}. Druk op de knop om ze bij te werken.`);
    else notes.push(`Model en advies bijgewerkt op ${advice.day}.`);
    if (advice && advice.stale) notes.push(advice.stale);
    if (state.overview.failed.length) notes.push(`Koersen niet ververst voor: ${state.overview.failed.join(", ")}.`);
    say("advice-status", notes.join(" "));
  }
  async function runAdvice(event) {
    event.preventDefault();
    el("run").disabled = true;
    say("advice-status", "Koersen verversen en het model trainen ... ongeveer een halve minuut.");
    try {
      state.advice = await api("POST", data.run, { news: el("news").value, intuition: el("intuition").value });
      await loadOverview();
    } catch (error) {
      say("advice-status", `Niet bijgewerkt: ${error.message}`);
    } finally {
      el("run").disabled = false;
    }
  }

  // ------------------------------------------------------------ monitor
  function sparkline(values) {
    const W = 96, H = 24, lo = Math.min(...values), hi = Math.max(...values);
    const points = values.map((v, i) => `${((i / Math.max(values.length - 1, 1)) * W).toFixed(1)},${(H - 2 - ((v - lo) / (hi - lo || 1)) * (H - 4)).toFixed(1)}`);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "spark", "aria-hidden": "true" });
    chart.append(svg("polyline", { points: points.join(" "), fill: "none", "stroke-width": 1.5, stroke: last(values) >= values[0] ? COLORS.up : COLORS.down }));
    return chart;
  }
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
    if (row.signals.length) { const flag = html("span", "flag", row.signals.length === 1 ? "1 signaal" : `${row.signals.length} signalen`); flag.title = row.signals.join("; "); flags.append(flag); }
    return tableRow([tickerCell(row), row.price.toFixed(2), pct(row.w1), pct(row.m1), pct(row.m3), pct(row.y1), spark,
      html("td", row.above_average === null ? "dim" : row.above_average ? "pos" : "neg", row.above_average === null ? "-" : row.above_average ? "boven" : "onder"),
      row.weight_pct === null ? html("td", "dim", "-") : html("td", row.weight_pct >= 20 ? "neg" : "", `${row.weight_pct.toFixed(0)}%`),
      tomorrow === undefined ? html("td", "dim", "-") : html("td", Math.abs(tomorrow - 50) < 5 ? "dim" : "", `${tomorrow}%`),
      adviceCell(row), html("td", rotation ? "" : "dim", rotation ? ROTATION[rotation.action] : "-"), flags]);
  }
  function renderMonitor() {
    const rows = state.overview.monitor;
    if (!rows.length) { el("monitor").replaceChildren(html("p", "helper", "Nog geen aandelen. Voeg ze toe onder Beheer; daarna zie je hier de trends.")); return; }
    const body = rows.flatMap((row) => (state.open.has(row.ticker) ? [monitorRow(row), detailRow(row)] : [monitorRow(row)]));
    el("monitor").replaceChildren(table(["Aandeel", "Koers", "1 week", "1 maand", "3 maanden", "12 maanden", "3 mnd", "Trend", "Gewicht", "Morgen hoger", "Advies", "Rotatie", "Signalen"], body));
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
    const save = html("button", "secondary-button", "Opslaan"); save.type = "submit";
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
    return block("Jouw beeld (-5 tot +5, leeg is de algemene score)", form);
  }
  function detailRow(row) {
    const stock = state.overview.stocks.find((s) => s.ticker === row.ticker);
    const grid = html("div", "detail-grid");
    grid.append(signalBlock(row), viewBlock(row.ticker), newsBlock(row.ticker));
    if (stock) grid.append(whyBlock(stock));
    if (stock && stock.daytrade.last) grid.append(dayBlock(stock));
    grid.append(playersBlock(row.ticker));
    const td = html("td"); td.colSpan = 13; td.append(grid);
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

  // -------------------------------------------------------- portefeuille
  function lineChart(target, days, lines) {
    const W = 1000, H = 300, m = { l: 70, r: 14, t: 12, b: 28 };
    const all = lines.flatMap((s) => s.values);
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    const x = (i) => m.l + (i / Math.max(days.length - 1, 1)) * (W - m.l - m.r);
    const y = (v) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Waarde van de portefeuille over de gekozen periode" });
    for (let k = 0; k <= 4; k++) {
      const v = lo + ((hi - lo) * k) / 4;
      chart.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "grid" }));
      const label = svg("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", class: "axis" });
      label.textContent = euro(v);
      chart.append(label);
    }
    [0, Math.floor(days.length / 2), days.length - 1].forEach((i) => {
      const t = svg("text", { x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : i === days.length - 1 ? "end" : "middle", class: "axis" });
      t.textContent = days[i];
      chart.append(t);
    });
    lines.forEach((s) => {
      const d = s.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
      chart.append(svg("path", { d, fill: "none", stroke: s.color, "stroke-width": 2 }));
    });
    const tip = html("div", "tip"); tip.hidden = true;
    chart.addEventListener("mousemove", (event) => {
      const box = chart.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * W;
      const i = Math.max(0, Math.min(days.length - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (days.length - 1))));
      tip.replaceChildren(html("div", "", days[i]), ...lines.map((s) => {
        const row = html("div", "", `${s.name}: ${euro(s.values[i])}`);
        row.style.color = s.color;
        return row;
      }));
      tip.hidden = false;
      tip.style.left = Math.min(event.clientX - box.left + 14, box.width - 190) + "px";
      tip.style.top = "8px";
    });
    chart.addEventListener("mouseleave", () => { tip.hidden = true; });
    target.replaceChildren(chart, tip);
  }
  function renderPortfolio(o) {
    if (!o.stocks.length) {
      ["tiles", "legend", "value-chart"].forEach((id) => el(id).replaceChildren());
      el("sales").replaceChildren(html("p", "helper", "Nog geen aandelen."));
      return;
    }
    const hold = last(o.total.hold), done = last(o.total.executed);
    const fromTop = (done / Math.max(...o.total.executed) - 1) * 100;
    const tiles = [["Waarde nu", euro(done)], ["Daling vanaf de top in deze periode", `${fromTop.toFixed(0)}%`],
      ["Als je alles had vastgehouden", euro(hold)], ["Verschil door uitgevoerd advies", signed(done - hold)]];
    el("tiles").replaceChildren(...tiles.map(([k, v]) => { const t = html("div", "tile"); t.append(html("div", "k", k), html("div", "v", v)); return t; }));
    el("legend").replaceChildren(...[["Vasthouden", COLORS.hold], ["Uitgevoerd advies", COLORS.executed]].map(([n, c]) => {
      const s = html("span"); const i = html("i"); i.style.background = c; s.append(i, n); return s;
    }));
    lineChart(el("value-chart"), o.days, [{ name: "Vasthouden", color: COLORS.hold, values: o.total.hold },
      { name: "Uitgevoerd", color: COLORS.executed, values: o.total.executed }]);
    const sales = o.stocks.flatMap((s) => s.effects.map((e) => ({ ticker: s.ticker, ...e }))).sort((p, q) => p.day.localeCompare(q.day));
    const total = sales.reduce((t, r) => t + r.euro, 0);
    el("sales").replaceChildren(sales.length
      ? table(["Dag", "Aandeel", "Winst (+) of verlies (-) door de verkoop"], [...sales.map((r) => [r.day, r.ticker, colored(r.euro)]), ["Totaal", "", colored(total)]])
      : html("p", "helper", "Geen verkopen in deze periode."));
  }
  async function loadOverview() {
    say("overview-status", "Koersen laden ...");
    try {
      state.overview = await api("GET", `${data.overview}?days=${el("window").value}`);
      say("overview-status", "");
      renderToday(); renderMonitor(); renderPortfolio(state.overview);
    } catch (error) {
      say("overview-status", error.message);
      say("today-lead", `De koersen konden niet geladen worden: ${error.message}`);
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
    const [advice, views] = await Promise.all([api("GET", data.advice), api("GET", data.views)]);
    state.advice = advice.advice; state.views = views.views;
    await loadOverview();
    loadPlayers();
  }
  el("advice-form").addEventListener("submit", runAdvice);
  el("watchlist-save").addEventListener("click", saveWatchlist);
  el("search-go").addEventListener("click", searchStocks);
  el("search-q").addEventListener("keydown", (event) => { if (event.key === "Enter") searchStocks(); });
  el("add-go").addEventListener("click", addStock);
  el("window").addEventListener("change", loadOverview);
  start().catch((error) => say("today-lead", error.message));
  loadWatchlist().catch((error) => say("watchlist-status", error.message));
  loadHoldings().catch((error) => say("holdings-status", error.message));
})();
