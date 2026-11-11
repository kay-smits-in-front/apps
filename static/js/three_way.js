"use strict";

(() => {
  const root = document.getElementById("three-way");
  if (!root) return;
  const data = root.dataset;
  const el = (id) => document.getElementById(id);
  const say = (id, text) => { el(id).textContent = text; };
  const NS = "http://www.w3.org/2000/svg";
  const LABELS = { sell: "VERKOPEN", buy: "KOPEN", hold: "HOUDEN" };
  const COLORS = { hold: "#929bad", executed: "#ffb454" };
  const euro = (v) => new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(v);
  const signed = (v) => (v >= 0 ? "+" : "") + euro(v);
  const tone = (v) => (v >= 0 ? "pos" : "neg");
  const last = (arr) => arr[arr.length - 1];
  const score = (v) => (v === null || v === undefined ? "-" : (v >= 0 ? "+" : "") + Number(v).toFixed(1));
  const compact = (v) => new Intl.NumberFormat("nl-NL", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  const state = { overview: null, players: null };

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
    const head = html("tr");
    headers.forEach((h) => head.append(html("th", "", h)));
    t.append(head);
    rows.forEach((r) => {
      const tr = html("tr");
      r.forEach((c) => tr.append(typeof c === "object" ? c : html("td", "", c)));
      t.append(tr);
    });
    return t;
  }
  const colored = (v) => html("td", tone(v), signed(v));
  const cell = (value, suffix, cls) => html("td", cls || "", value === null || value === undefined ? "-" : `${value}${suffix}`);
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

  // ------------------------------------------------------------- advice
  function renderAdvice(advice) {
    const rows = advice.rows.map((r) => [r.ticker, html("td", `action ${r.action === "sell" ? "neg" : r.action === "buy" ? "pos" : ""}`, LABELS[r.action]),
      html("td", "", score(r.score)), html("td", "", r.reason)]);
    el("actions").replaceChildren(table(["Aandeel", "Actie", "Score", "Reden"], rows));
    say("details-note", `Zwaarste facetten van de forest: ${advice.top_facets.join(", ")}. Alle scores lopen van -5 tot +5.`);
    el("details").replaceChildren(table(["Aandeel", "Status", "Forest", "Nieuws", "Intuïtie", "Score"], advice.rows.map((r) => [
      r.ticker, r.invested ? "belegd" : "cash", score(r.parts.forest), score(r.parts.nieuws), score(r.parts.intuitie), score(r.score)])));
    el("details-box").hidden = false;
    renderCandidates(advice.candidates || []);
    const notes = [`Advies van ${advice.day}.`];
    if (advice.stale) notes.push(advice.stale);
    if (advice.failed && advice.failed.length) notes.push(`Koersen niet ververst voor: ${advice.failed.join(", ")}.`);
    say("advice-status", notes.join(" "));
  }
  function renderCandidates(candidates) {
    el("candidates").replaceChildren(candidates.length
      ? table(["Aandeel", "Verwachting forest", ""], candidates.map((c) => [c.ticker, html("td", c.score >= 1.5 ? "pos" : c.score <= -1.5 ? "neg" : "", score(c.score)),
        c.score >= 1.5 ? "kandidaat" : ""]))
      : html("p", "helper", "Nog geen kandidaten. Vul je watchlist in en bereken het advies."));
  }
  async function runAdvice(event) {
    event.preventDefault();
    el("run").disabled = true;
    say("advice-status", "Koersen verversen en de forest trainen ... ongeveer een halve minuut.");
    try {
      renderAdvice(await api("POST", data.run, { news: el("news").value, intuition: el("intuition").value }));
      loadOverview();
    } catch (error) {
      say("advice-status", `Geen advies: ${error.message}`);
    } finally {
      el("run").disabled = false;
    }
  }
  async function loadAdvice() {
    const { advice } = await api("GET", data.advice);
    if (advice) {
      renderAdvice(advice);
      say("advice-status", `Laatste advies, van ${advice.day}. Druk op de knop voor een nieuw advies.`);
    }
  }

  // ---------------------------------------------------------- watchlist
  async function loadWatchlist() {
    const { watchlist } = await api("GET", data.watchlist);
    el("watchlist").value = watchlist.join(" ");
  }
  async function saveWatchlist() {
    try {
      const { watchlist } = await api("POST", data.watchlist, { tickers: el("watchlist").value });
      el("watchlist").value = watchlist.join(" ");
      say("watchlist-status", `${watchlist.length} aandelen opgeslagen. Ze worden meegenomen bij het volgende advies.`);
    } catch (error) {
      say("watchlist-status", error.message);
    }
  }

  // ----------------------------------------------------------- holdings
  function numberCell(value) {
    const td = html("td"); const input = html("input");
    input.type = "number"; input.step = "any"; input.min = 0; input.value = value;
    td.append(input);
    return [td, input];
  }
  function holdingRow(h) {
    const [qtyTd, qty] = numberCell(h.quantity), [costTd, cost] = numberCell(h.cost_eur);
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
      : html("p", "helper", "Nog geen aandelen. Voeg ze hierboven toe."));
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

  // ----------------------------------------------------------- overview
  function lineChart(target, days, lines) {
    const W = 1000, H = 300, m = { l: 70, r: 14, t: 12, b: 28 };
    const all = lines.flatMap((s) => s.values);
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    const x = (i) => m.l + (i / Math.max(days.length - 1, 1)) * (W - m.l - m.r);
    const y = (v) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Waarde van de portefeuille" });
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
    const hold = last(o.total.hold), done = last(o.total.executed);
    const tiles = [["Waarde nu (uitgevoerd)", euro(done)], ["Als je had vastgehouden", euro(hold)], ["Verschil door het advies", signed(done - hold)]];
    el("tiles").replaceChildren(...tiles.map(([k, v]) => { const t = html("div", "tile"); t.append(html("div", "k", k), html("div", "v", v)); return t; }));
    el("legend").replaceChildren(...[["Vasthouden", COLORS.hold], ["Uitgevoerd advies", COLORS.executed]].map(([n, c]) => {
      const s = html("span"); const i = html("i"); i.style.background = c; s.append(i, n); return s;
    }));
    lineChart(el("value-chart"), o.days, [{ name: "Vasthouden", color: COLORS.hold, values: o.total.hold },
      { name: "Uitgevoerd", color: COLORS.executed, values: o.total.executed }]);
    el("stocks").replaceChildren(table(["Aandeel", "Waarde nu", "Vasthouden", "Verschil", "Kosten"], o.stocks.map((s) => [
      s.ticker, euro(last(s.executed)), euro(last(s.hold)), colored(last(s.executed) - last(s.hold)), euro(s.costs)])));
    const sales = o.stocks.flatMap((s) => s.effects.map((e) => ({ ticker: s.ticker, ...e }))).sort((p, q) => p.day.localeCompare(q.day));
    const total = sales.reduce((t, r) => t + r.euro, 0);
    el("sales").replaceChildren(sales.length
      ? table(["Dag", "Aandeel", "Winst (+) of verlies (-) door de verkoop"], [...sales.map((r) => [r.day, r.ticker, colored(r.euro)]), ["Totaal", "", colored(total)]])
      : html("p", "helper", "Geen verkopen in deze periode."));
  }
  function renderDaytrade(o) {
    const rows = o.stocks.filter((s) => s.daytrade.last).map((s) => {
      const d = s.daytrade.last;
      const flags = html("td");
      d.flags.forEach((f) => flags.append(html("span", "flag", f)));
      return [s.ticker, d.day, cell(d.rel_volume, "x", d.rel_volume >= 2 ? "hot" : ""), cell(d.gap_pct, "%", d.gap_pct > 0 ? "hot" : d.gap_pct < 0 ? "cold" : ""),
        cell(d.range_pct, "%"), cell(d.atr_pct, "%"), cell(d.rsi, "", d.rsi >= 70 ? "cold" : d.rsi <= 30 ? "hot" : ""), flags];
    });
    el("daytrade").replaceChildren(rows.length ? table(["Aandeel", "Laatste dag", "Volume vs normaal", "Gap", "Dagrange", "Gem. range 14d", "RSI 14", "Opvallend"], rows)
      : html("p", "helper", "Nog geen volumegegevens."));
  }
  const PLAYER_LEANS = { "veel short": ["Short interest", "negatief"], "analisten: kopen": ["Analisten", "positief"], "analisten: verkopen": ["Analisten", "negatief"],
    "insiders kopen": ["Insiders", "positief"], "insiders verkopen": ["Insiders", "negatief"] };
  function whyFactors(s) {
    const own = s.why.factors.map((f) => ({ ...f }));
    const players = state.players && state.players[s.ticker];
    if (players) players.labels.filter((l) => PLAYER_LEANS[l]).forEach((l) => own.push({ name: PLAYER_LEANS[l][0], lean: PLAYER_LEANS[l][1], text: l }));
    return own;
  }
  function renderWhy(o) {
    el("why").replaceChildren(...o.stocks.map((s) => {
      const factors = whyFactors(s);
      const count = (lean) => factors.filter((f) => f.lean === lean).length;
      const card = html("div", "card");
      card.append(html("h3", "", s.ticker), html("div", "sum", `${count("positief")} positief, ${count("negatief")} negatief, ${count("neutraal")} neutraal · ${s.why.day}`));
      const list = html("ul");
      factors.forEach((f) => {
        const item = html("li"); item.append(html("span", `dot2 ${f.lean}`));
        const text = html("span"); text.append(html("b", "", f.name + ": "), f.text);
        item.append(text); list.append(item);
      });
      card.append(list);
      return card;
    }));
  }
  function playersRow(ticker, p) {
    const flags = html("td");
    p.labels.forEach((f) => flags.append(html("span", "flag", f)));
    const net = p.insiders.net_value;
    const holders = p.holders.map((h) => `${h.holder} ${h.pct ?? "-"}%`).join(", ") || "-";
    const consensus = p.consensus_mean === null ? "-" : `${p.consensus_mean.toFixed(1)} (${p.analysts} analisten${p.target_upside_pct === null ? "" : `, doel ${p.target_upside_pct >= 0 ? "+" : ""}${p.target_upside_pct}%`})`;
    return [ticker, cell(p.institutions_pct, "%"), cell(p.insiders_pct, "%"), cell(p.short_pct_float, "%", p.short_pct_float >= 15 ? "cold" : ""),
      consensus, html("td", net > 0 ? "hot" : net < 0 ? "cold" : "", `${p.insiders.buys} kopen / ${p.insiders.sells} verkopen (${net >= 0 ? "+" : ""}${compact(net)})`), holders, flags];
  }
  async function loadPlayers() {
    say("players-status", "Gegevens ophalen bij Yahoo (de eerste keer duurt even) ...");
    try {
      const { players } = await api("GET", data.players);
      state.players = players;
      if (state.overview) renderWhy(state.overview);
      el("players").replaceChildren(table(["Aandeel", "Institutioneel", "Insiders bezit", "Short (float)", "Analisten (1 = kopen, 5 = verkopen)", "Insiders 6 mnd", "Grootste houders", "Opvallend"],
        Object.entries(players).map(([ticker, p]) => playersRow(ticker, p))));
      say("players-status", "");
    } catch (error) {
      say("players-status", error.message);
    }
  }
  async function loadOverview() {
    say("overview-status", "Koersen laden ...");
    try {
      const o = await api("GET", `${data.overview}?days=${el("window").value}`);
      state.overview = o;
      say("overview-status", o.failed.length ? `Koersen niet ververst voor: ${o.failed.join(", ")}.` : "");
      if (!o.stocks.length) { say("overview-status", "Nog geen aandelen. Voeg ze toe bij 4. Mijn aandelen."); return; }
      renderPortfolio(o); renderDaytrade(o); renderWhy(o);
    } catch (error) {
      say("overview-status", error.message);
    }
  }

  // -------------------------------------------------------------- start
  el("advice-form").addEventListener("submit", runAdvice);
  el("watchlist-save").addEventListener("click", saveWatchlist);
  el("search-go").addEventListener("click", searchStocks);
  el("search-q").addEventListener("keydown", (event) => { if (event.key === "Enter") searchStocks(); });
  el("add-go").addEventListener("click", addStock);
  el("window").addEventListener("change", loadOverview);
  loadAdvice().catch((error) => say("advice-status", error.message));
  loadWatchlist().catch((error) => say("watchlist-status", error.message));
  loadHoldings().catch((error) => say("holdings-status", error.message));
  loadOverview().then(loadPlayers);
})();
