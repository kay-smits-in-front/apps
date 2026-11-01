(() => {
  const root = document.getElementById("dash");
  if (!root) return;
  const defaults = JSON.parse(root.dataset.defaults);
  const source = root.dataset.source;
  const research = root.dataset.research;
  const aiSource = root.dataset.ai;
  const adviceSource = root.dataset.advice;
  const NS = "http://www.w3.org/2000/svg";
  const COLORS = { hold: "#929bad", a: "#7c8cff", b: "#e58cff", max: "#b5f36d", executed: "#ffb454" };
  const RULE_FIELDS = [
    ["lookback_days", "Terugblik (dgn)"], ["up_pct", "Verkoop na stijging %"], ["down_pct", "Terugkoop na daling %"],
    ["stop_pct", "Stop-loss %"], ["floor_pct", "Dieptepunt %"], ["regime_pct", "Extreme trend %"],
    ["turn_pct", "Keer %"], ["review_days", "Check elke (dgn)"],
  ];
  const PRESETS = [
    ["Verkoop +20% / terugkoop -3%", { up_pct: 20, down_pct: 3 }],
    ["Verkoop +2% / terugkoop -15%", { up_pct: 2, down_pct: 15 }],
    ["Nieuws altijd -1", { news: -1 }],
    ["Nieuws en intuïtie uit", { news: null, intuition: null }],
  ];
  const plan = defaults.plan;
  const TREND_FIELDS = [["ma_days", "Gemiddelde (dgn)"], ["band_pct", "Band %"], ["review_days", "Check elke (dgn)"]];
  const state = { a: { ...defaults }, b: { ...defaults }, data: null, dataB: null, picked: new Set(), groups: { ...plan.groups } };
  const el = (id) => document.getElementById(id);
  const euro = (v) => new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(v);
  const signed = (v) => (v >= 0 ? "+" : "") + euro(v);
  const tone = (v) => (v >= 0 ? "pos" : "neg");
  const last = (arr) => arr[arr.length - 1];
  const svg = (name, attrs = {}) => {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    return node;
  };
  const html = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  // ------------------------------------------------------------ form
  function scoreField(key, label) {
    const wrap = html("label");
    wrap.append(label);
    const row = html("div", "score");
    const box = html("input"); box.type = "checkbox"; box.dataset.key = key + "_on";
    const num = html("input"); num.type = "number"; num.min = -5; num.max = 5; num.step = 0.5; num.dataset.key = key;
    row.append(box, num); wrap.append(row);
    return wrap;
  }
  function numberField(key, label) {
    const wrap = html("label");
    wrap.append(label);
    const input = html("input"); input.type = "number"; input.step = "any"; input.dataset.key = key;
    wrap.append(input);
    return wrap;
  }
  const holderOf = (which) => document.querySelector(`fieldset[data-scenario="${which}"] .fields`);
  function buildFields(which) {
    holderOf(which).replaceChildren(...RULE_FIELDS.map(([k, l]) => numberField(k, l)),
      scoreField("news", "Nieuws (-5..5)"), scoreField("intuition", "Intuïtie (-5..5)"));
  }
  function fillFields(which) {
    holderOf(which).querySelectorAll("input[data-key]").forEach((input) => {
      const key = input.dataset.key;
      if (key.endsWith("_on")) input.checked = state[which][key.slice(0, -3)] !== null;
      else input.value = state[which][key] ?? 0;
    });
  }
  function readFields(which) {
    const holder = holderOf(which);
    const out = {};
    holder.querySelectorAll("input[data-key]").forEach((input) => {
      const key = input.dataset.key;
      if (key.endsWith("_on")) return;
      const on = holder.querySelector(`input[data-key="${key}_on"]`);
      out[key] = on && !on.checked ? null : Number(input.value);
    });
    return out;
  }
  // ------------------------------------------------------ my stocks
  const csrf = root.dataset.csrf;
  async function api(method, url, body) {
    const response = await fetch(url, {
      method, credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: body ? JSON.stringify(body) : undefined,
    });
    const type = response.headers.get("content-type") || "";
    const data = type.includes("json") ? await response.json() : {};
    if (!response.ok) throw new Error(data.error || `Fout (status ${response.status})`);
    return data;
  }
  const say = (id, text) => { el(id).textContent = text; };
  async function loadHoldings() {
    const { holdings } = await api("GET", root.dataset.api);
    el("holdings").replaceChildren(table(["Ticker", "Aantal", "Kosten (EUR)", ""], holdings.map((h) => holdingRow(h))));
    holdings.forEach((h) => { if (!(h.ticker in state.groups)) state.groups[h.ticker] = h.group || ""; });
    const known = new Set(holdings.map((h) => h.ticker));
    Object.keys(state.groups).forEach((t) => { if (!known.has(t)) delete state.groups[t]; });
    buildAssignment([...known]);
  }
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
    save.addEventListener("click", () => change(() => api("POST", root.dataset.api, { ticker: h.ticker, quantity: Number(qty.value), cost_eur: Number(cost.value) }), `${h.ticker} opgeslagen.`));
    remove.addEventListener("click", () => change(() => api("DELETE", `${root.dataset.api}/${encodeURIComponent(h.ticker)}`), `${h.ticker} weggehaald.`));
    actions.append(save, remove);
    return [h.ticker, qtyTd, costTd, actions];
  }
  async function change(action, message) {
    say("holdings-status", "Bezig ...");
    try {
      await action();
      await loadHoldings();
      say("holdings-status", message + " Klik op Bereken om het dashboard te verversen.");
    } catch (error) {
      say("holdings-status", error.message);
    }
  }
  async function searchStocks() {
    say("search-status", "Zoeken ...");
    el("search-results").replaceChildren();
    try {
      const { results } = await api("GET", `${root.dataset.search}?q=${encodeURIComponent(el("search-q").value)}`);
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
      await api("POST", root.dataset.api, body);
      ["add-ticker", "add-qty", "add-cost"].forEach((id) => { el(id).value = ""; });
    }, `${ticker} toegevoegd.`);
  }
  async function savePlan() {
    say("plan-status", "Opslaan ...");
    try {
      await api("POST", root.dataset.plan, readPlan());
      say("plan-status", "Opgeslagen.");
    } catch (error) {
      say("plan-status", error.message);
    }
  }

  // ---------------------------------------------------------- groups
  const CUMULATIVE_FIELDS = [["up_pct", "Verkoop boven gemiddelde %"], ["down_pct", "Terugkoop onder gemiddelde %"], ["review_days", "Check elke (dgn)"]];
  const VOLUME_FIELDS = [["spike_x", "Volumepiek (x normaal)"], ["min_move_pct", "Minimale dagbeweging %"], ["review_days", "Check elke (dgn)"]];
  const groupFields = (group) => ({ peak: TREND_FIELDS, cumulative: CUMULATIVE_FIELDS, volume: VOLUME_FIELDS }[group] || RULE_FIELDS);
  function buildGroupFields() {
    el("group-fields").replaceChildren(...Object.keys(plan.labels).map((group) => {
      const box = html("fieldset"); box.dataset.group = group;
      box.append(html("legend", "", plan.labels[group]));
      const fields = html("div", "fields");
      groupFields(group).forEach(([key, label]) => {
        const field = numberField(key, label);
        field.querySelector("input").value = plan.settings[group][key];
        fields.append(field);
      });
      box.append(fields);
      return box;
    }));
  }
  function buildAssignment(tickers) {
    const all = [...new Set([...Object.keys(state.groups), ...tickers])].sort();
    el("group-assign").replaceChildren(...all.map((ticker) => {
      const label = html("label", "", ticker);
      const select = html("select"); select.dataset.ticker = ticker;
      const none = html("option", "", "geen groep"); none.value = "";
      select.append(none, ...Object.entries(plan.labels).map(([g, text]) => {
        const option = html("option", "", text); option.value = g; return option;
      }));
      select.value = state.groups[ticker] || "";
      select.addEventListener("change", () => { state.groups[ticker] = select.value; });
      label.append(select);
      return label;
    }));
  }
  function readPlan() {
    const settings = {};
    document.querySelectorAll("#group-fields fieldset").forEach((box) => {
      settings[box.dataset.group] = {};
      box.querySelectorAll("input[data-key]").forEach((input) => { settings[box.dataset.group][input.dataset.key] = Number(input.value); });
    });
    const groups = Object.fromEntries(Object.entries(state.groups).filter(([, g]) => g));
    return { groups, settings };
  }
  function query(which) {
    const params = new URLSearchParams({ days: el("window").value });
    Object.entries(readFields(which)).forEach(([k, v]) => params.set(k, v === null ? "off" : v));
    if (which === "a" && el("groups-on").checked) params.set("plan", JSON.stringify(readPlan()));
    return params;
  }
  function toggleB() {
    document.querySelector('fieldset[data-scenario="b"]').classList.toggle("off", !el("b-on").checked);
  }
  function applyPreset(patch) {
    state.b = { ...readFields("a"), ...patch };
    el("b-on").checked = true;
    toggleB();
    fillFields("b");
  }

  // ----------------------------------------------------------- chart
  function marker(mk, x, y) {
    const cx = x, cy = y, r = 5;
    if (mk.shape === "dot") {
      const dot = svg("circle", { cx, cy, r: 3.5, fill: mk.color, stroke: "#0b0e14", "stroke-width": 1 });
      const text = svg("title"); text.textContent = mk.title; dot.append(text);
      return dot;
    }
    const points = mk.shape === "diamond"
      ? `${cx},${cy - r - 1} ${cx + r + 1},${cy} ${cx},${cy + r + 1} ${cx - r - 1},${cy}`
      : mk.action === "sell"
        ? `${cx - r},${cy - r} ${cx + r},${cy - r} ${cx},${cy + r}`
        : `${cx - r},${cy + r} ${cx + r},${cy + r} ${cx},${cy - r}`;
    const shape = svg("polygon", { points, fill: mk.color, stroke: "#0b0e14", "stroke-width": 1 });
    const title = svg("title"); title.textContent = mk.title; shape.append(title);
    return shape;
  }
  function lineChart(target, days, lines, markers, opts = {}) {
    const W = 1000, H = opts.height || 340, m = { l: 62, r: 14, t: 12, b: 28 };
    const all = lines.flatMap((s) => s.values);
    let lo = Math.min(...all), hi = Math.max(...all);
    const pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    const x = (i) => m.l + (i / Math.max(days.length - 1, 1)) * (W - m.l - m.r);
    const y = (v) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
    const fmt = opts.format || ((v) => v.toFixed(1));
    const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
    for (let k = 0; k <= 4; k++) {
      const v = lo + ((hi - lo) * k) / 4;
      chart.append(svg("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "grid" }));
      const label = svg("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", class: "axis" });
      label.textContent = fmt(v);
      chart.append(label);
    }
    [0, Math.floor(days.length / 2), days.length - 1].forEach((i) => {
      const anchor = i === 0 ? "start" : i === days.length - 1 ? "end" : "middle";
      const t = svg("text", { x: x(i), y: H - 8, "text-anchor": anchor, class: "axis" });
      t.textContent = days[i];
      chart.append(t);
    });
    lines.forEach((s) => {
      const d = s.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
      const attrs = { d, fill: "none", stroke: s.color, "stroke-width": s.width || 2 };
      if (s.dash) attrs["stroke-dasharray"] = s.dash;
      chart.append(svg("path", attrs));
    });
    (markers || []).forEach((mk) => {
      const i = days.indexOf(mk.day);
      if (i >= 0 && Number.isFinite(mk.value)) chart.append(marker(mk, x(i), y(mk.value)));
    });
    const cross = svg("line", { y1: m.t, y2: H - m.b, stroke: "rgba(255,255,255,.25)", visibility: "hidden" });
    chart.append(cross);
    const tip = html("div", "tip"); tip.hidden = true;
    chart.addEventListener("mousemove", (event) => {
      const box = chart.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * W;
      const i = Math.max(0, Math.min(days.length - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (days.length - 1))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      tip.replaceChildren(html("div", "", days[i]), ...lines.map((s) => {
        const row = html("div", "", `${s.name}: ${fmt(s.values[i])}`);
        row.style.color = s.color;
        return row;
      }));
      tip.hidden = false;
      tip.style.left = Math.min(event.clientX - box.left + 14, box.width - 190) + "px";
      tip.style.top = "8px";
    });
    chart.addEventListener("mouseleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
    target.replaceChildren(chart, tip);
  }

  // ---------------------------------------------------------- render
  function markersFor(stocks, key, color, shape, valueOf) {
    return stocks.flatMap((s) => s[key].map((mk) => ({
      day: mk.day, action: mk.action, color, shape, value: valueOf(mk.day),
      title: `${s.ticker} ${mk.action === "sell" ? "verkocht" : "gekocht"} op ${mk.day} voor ${mk.price}`,
    })));
  }
  const costText = (c) => (c ? `${c.sells + c.buys} transacties, kosten ${euro(c.costs)}` : "");
  function renderTiles(a, b) {
    const hold = last(a.total.hold);
    const items = [["Hold", hold, null], [b ? "Regel A" : "Regel", last(a.total.rule), a.costs.rule]];
    if (b) items.push(["Regel B", last(b.total.rule), b.costs.rule]);
    items.push(["Uitgevoerd", last(a.total.executed), a.costs.executed], ["Maximum", last(a.total.max), a.costs.max]);
    el("tiles").replaceChildren(...items.map(([name, value, costs]) => {
      const tile = html("div", "tile");
      const text = name === "Hold" ? "start " + euro(a.total.hold[0]) : `${signed(value - hold)} t.o.v. hold`;
      tile.append(html("div", "k", name), html("div", "v", euro(value)), html("div", `d ${name === "Hold" ? "" : tone(value - hold)}`, text));
      if (costs) tile.append(html("div", "k", costText(costs)));
      return tile;
    }));
  }
  function renderLegend(hasB) {
    const items = [["Hold", COLORS.hold], ["Regel A", COLORS.a], ["Uitgevoerd", COLORS.executed], ["Maximum (perfect)", COLORS.max]];
    if (hasB) items.splice(2, 0, ["Regel B", COLORS.b]);
    el("legend").replaceChildren(...items.map(([n, c]) => {
      const s = html("span"); const i = html("i"); i.style.background = c; s.append(i, n); return s;
    }));
  }
  function renderValue(a, b) {
    const t = a.total;
    const lines = [
      { name: "Hold", color: COLORS.hold, values: t.hold },
      { name: "Regel A", color: COLORS.a, values: t.rule, width: 2.5 },
      { name: "Uitgevoerd", color: COLORS.executed, values: t.executed, width: 2.5 },
    ];
    if (el("max-on").checked) lines.push({ name: "Maximum", color: COLORS.max, values: t.max, dash: "6 4" });
    if (b) lines.splice(2, 0, { name: "Regel B", color: COLORS.b, values: b.total.rule, width: 2.5 });
    const at = (series) => (day) => series[a.days.indexOf(day)];
    const markers = [
      ...markersFor(a.stocks, "rule_moves", COLORS.a, "tri", at(t.rule)),
      ...markersFor(a.stocks, "executed_moves", COLORS.executed, "diamond", at(t.executed)),
    ];
    renderLegend(Boolean(b));
    lineChart(el("value-chart"), a.days, lines, markers, { format: euro });
  }
  const colorFor = (i, n) => `hsl(${Math.round((i * 360) / n)} 70% 62%)`;
  function renderChips(a) {
    const n = a.stocks.length;
    el("chips").replaceChildren(...a.stocks.map((s, i) => {
      const chip = html("button", "chip" + (state.picked.has(s.ticker) ? " on" : ""));
      chip.type = "button";
      const dot = html("span", "dot"); dot.style.background = colorFor(i, n);
      chip.append(dot, s.ticker);
      chip.addEventListener("click", () => {
        if (state.picked.has(s.ticker)) state.picked.delete(s.ticker); else state.picked.add(s.ticker);
        renderChips(a); renderPrices(a);
      });
      return chip;
    }));
  }
  function spikeMarkers(a, lines) {
    if (!el("spikes-on").checked) return [];
    const shown = new Map(lines.map((l) => [l.name, l]));
    return a.stocks.filter((s) => shown.has(s.ticker)).flatMap((s) => s.daytrade.spikes.map((sp) => {
      const i = a.days.indexOf(sp.day);
      return { day: sp.day, shape: "dot", color: shown.get(s.ticker).color, value: i < 0 ? NaN : shown.get(s.ticker).values[i],
        title: `${s.ticker} ${sp.day}: ${sp.rel}x volume, ${sp.change >= 0 ? "+" : ""}${sp.change}%` };
    }));
  }
  function renderPrices(a) {
    const n = a.stocks.length;
    const lines = a.stocks
      .map((s, i) => ({ name: s.ticker, color: colorFor(i, n), values: s.price.map((p) => (p / s.price[0]) * 100), width: 1.8 }))
      .filter((l) => state.picked.has(l.name));
    if (!lines.length) { el("price-chart").replaceChildren(html("p", "helper", "Kies een of meer aandelen.")); return; }
    lineChart(el("price-chart"), a.days, lines, spikeMarkers(a, lines), { height: 300, format: (v) => v.toFixed(0) });
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
  function renderSales(a) {
    const rows = a.stocks.flatMap((s) => s.effects.map((e) => ({ ticker: s.ticker, ...e })))
      .sort((p, q) => p.day.localeCompare(q.day));
    const total = rows.reduce((t, r) => t + r.euro, 0);
    el("sales").replaceChildren(rows.length
      ? table(["Dag", "Aandeel", "Winst (+) of verlies (-) door de verkoop"],
        [...rows.map((r) => [r.day, r.ticker, colored(r.euro)]), ["Totaal", "", colored(total)]])
      : html("p", "helper", "Regel A verkoopt in deze periode niets."));
  }
  function renderStocks(a) {
    const rows = a.stocks.map((s) => [s.ticker + (s.group ? ` (${plan.labels[s.group]})` : ""), euro(last(s.hold)), colored(last(s.rule) - last(s.hold)),
      `${s.costs.rule.sells + s.costs.rule.buys} / ${euro(s.costs.rule.costs)}`,
      colored(last(s.executed) - last(s.hold)), colored(last(s.max) - last(s.hold))]);
    el("stocks").replaceChildren(table(["Aandeel", "Hold nu", "Regel A t.o.v. hold", "Transacties / kosten A",
      "Uitgevoerd t.o.v. hold", "Maximum t.o.v. hold"], rows));
  }
  const cell = (value, suffix, cls) => html("td", cls || "", value === null || value === undefined ? "-" : `${value}${suffix}`);
  function renderDaytrade(a) {
    const rows = a.stocks.filter((s) => s.daytrade.last).map((s) => {
      const d = s.daytrade.last;
      const flags = html("td");
      d.flags.forEach((f) => flags.append(html("span", "flag", f)));
      return [s.ticker, d.day, cell(d.rel_volume, "x", d.rel_volume >= 2 ? "hot" : ""), cell(d.gap_pct, "%", d.gap_pct > 0 ? "hot" : d.gap_pct < 0 ? "cold" : ""),
        cell(d.range_pct, "%"), cell(d.atr_pct, "%"), cell(d.rsi, "", d.rsi >= 70 ? "cold" : d.rsi <= 30 ? "hot" : ""), flags];
    });
    el("daytrade").replaceChildren(rows.length ? table(["Aandeel", "Laatste dag", "Volume vs normaal", "Gap", "Dagrange", "Gem. range 14d", "RSI 14", "Opvallend"], rows)
      : html("p", "helper", "Nog geen volumegegevens. Klik op Bereken om de koersen opnieuw op te halen."));
  }
  const compact = (v) => new Intl.NumberFormat("nl-NL", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  function playersRow(ticker, p) {
    const flags = html("td");
    p.labels.forEach((f) => flags.append(html("span", "flag", f)));
    const net = p.insiders.net_value;
    const holders = p.holders.map((h) => `${h.holder} ${h.pct ?? "-"}%`).join(", ") || "-";
    const consensus = p.consensus_mean === null ? "-" : `${p.consensus_mean.toFixed(1)} (${p.analysts} analisten${p.target_upside_pct === null ? "" : `, doel ${p.target_upside_pct >= 0 ? "+" : ""}${p.target_upside_pct}%`})`;
    return [ticker, cell(p.institutions_pct, "%"), cell(p.insiders_pct, "%"), cell(p.short_pct_float, "%", p.short_pct_float >= 15 ? "cold" : ""),
      consensus, html("td", net > 0 ? "hot" : net < 0 ? "cold" : "", `${p.insiders.buys} kopen / ${p.insiders.sells} verkopen (${net >= 0 ? "+" : ""}${compact(net)})`), holders, flags];
  }
  async function loadPlayers(a) {
    say("players-status", "Gegevens ophalen bij Yahoo (de eerste keer duurt even) ...");
    try {
      const { players } = await api("GET", root.dataset.players);
      state.players = players;
      renderWhy(a);
      const rows = a.stocks.filter((s) => players[s.ticker]).map((s) => playersRow(s.ticker, players[s.ticker]));
      el("players").replaceChildren(table(["Aandeel", "Institutioneel", "Insiders bezit", "Short (float)", "Analisten (1 = kopen, 5 = verkopen)", "Insiders 6 mnd", "Grootste houders", "Opvallend"], rows));
      say("players-status", "");
    } catch (error) {
      say("players-status", error.message);
    }
  }
  const PLAYER_LEANS = { "veel short": ["Short interest", "negatief"], "analisten: kopen": ["Analisten", "positief"], "analisten: verkopen": ["Analisten", "negatief"],
    "insiders kopen": ["Insiders", "positief"], "insiders verkopen": ["Insiders", "negatief"] };
  function whyFactors(s) {
    const own = s.why.factors.map((f) => ({ ...f }));
    const players = state.players && state.players[s.ticker];
    if (players) players.labels.filter((l) => PLAYER_LEANS[l]).forEach((l) => own.push({ name: PLAYER_LEANS[l][0], lean: PLAYER_LEANS[l][1], text: l }));
    return own;
  }
  function renderWhy(a) {
    el("why").replaceChildren(...a.stocks.map((s) => {
      const factors = whyFactors(s);
      const count = (lean) => factors.filter((f) => f.lean === lean).length;
      const card = html("div", "card");
      const title = html("h3"); title.append(html("span", "", s.ticker), html("span", "", s.group ? plan.labels[s.group] : ""));
      card.append(title, html("div", "sum", `${count("positief")} positief, ${count("negatief")} negatief, ${count("neutraal")} neutraal · ${s.why.day}`));
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
  const lagText = (v) => (v === null ? "-" : `${v > 0 ? "+" : ""}${v}`);
  function timingCells(part) {
    return [`${part.on_time}/${part.signals}`, lagText(part.median_lag_days), part.median_price_pct === null ? "-" : `${part.median_price_pct > 0 ? "+" : ""}${part.median_price_pct}%`];
  }
  function renderTiming(a) {
    const rows = a.stocks.map((s) => [s.ticker, `${s.timing.peaks} pieken, ${s.timing.troughs} dalen`, ...timingCells(s.timing.sell), ...timingCells(s.timing.buy)]);
    el("timing").replaceChildren(table(["Aandeel", "Draaipunten", "Verkopen op tijd", "Vertraging (dgn)", "Koers t.o.v. piek", "Kopen op tijd", "Vertraging (dgn)", "Koers t.o.v. dal"], rows));
  }
  async function loadResearch() {
    el("research-status").textContent = "Perioden doorrekenen ...";
    try {
      const response = await fetch(`${research}?${query("a")}`, { credentials: "same-origin" });
      if (!(response.headers.get("content-type") || "").includes("json")) throw new Error("Geen data (status " + response.status + ").");
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Fout");
      renderResearch(body);
    } catch (error) {
      el("research-status").textContent = error.message;
    }
  }
  const summaryCells = (r) => [`${r.wins}/${r.windows}`, `${r.mean > 0 ? "+" : ""}${r.mean} pp`, `${r.worst} pp`, String(r.trades)];
  function renderResearch(r) {
    el("research-status").textContent = r.total.windows ? "" : "Te weinig geschiedenis voor perioden.";
    const head = ["", "Perioden gewonnen", "Gemiddeld verschil", "Slechtste periode", "Transacties"];
    el("research-total").replaceChildren(table(head, [["Portefeuille", ...summaryCells(r.total)]]));
    const rows = r.stocks.map((s) => [s.ticker, ...summaryCells(s)]);
    el("research-stocks").replaceChildren(table(["Aandeel", ...head.slice(1)], rows));
  }
  async function loadAi() {
    try {
      const response = await fetch(aiSource, { credentials: "same-origin" });
      if (!(response.headers.get("content-type") || "").includes("json")) throw new Error("Geen data (status " + response.status + ").");
      renderAi((await response.json()).run);
    } catch (error) {
      el("ai-status").textContent = error.message;
    }
  }
  function renderAi(run) {
    if (!run) {
      el("ai-status").textContent = "Nog geen run. Draai experiments/three_way_turns/run.py in de ai-lab-map.";
      return;
    }
    const r = run.result, c = run.config;
    el("ai-status").textContent = `Run van ${run.time}. Verkoopsignaal bij kans vanaf ${c.threshold}, daling van minstens ${c.min_drop_pct}% binnen ${c.horizon_days} dagen. Kosten €${c.cost_eur} per transactie.`;
    el("ai-total").replaceChildren(table(["", "Model", "Vasthouden", "Perioden gewonnen", "Transacties"],
      [["Samengesteld over testperiodes", pctText(r.rule_pct), pctText(r.hold_pct), `${r.wins}/${r.total_periods}`, String(r.trades)]]));
    const rows = Object.entries(r.weights_mean).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).map(([name, w]) => [name, `${w > 0 ? "+" : ""}${w}`]);
    el("ai-weights").replaceChildren(table(["Factor", "Gewicht (positief: daling waarschijnlijker)"], rows));
  }
  const pctText = (v) => `${v > 0 ? "+" : ""}${v}%`;
  const ACTIONS = { sell: "VERKOPEN", buy: "KOPEN", hold: "HOUDEN" };
  async function loadAdvice() {
    try {
      const response = await fetch(adviceSource, { credentials: "same-origin" });
      if (!(response.headers.get("content-type") || "").includes("json")) throw new Error("Geen data (status " + response.status + ").");
      renderAdvice((await response.json()).advice);
    } catch (error) {
      el("advice-status").textContent = error.message;
    }
  }
  function renderAdvice(advice) {
    if (!advice) {
      el("advice-status").textContent = "Nog geen advies. Bereken het met de knop op de simpele advies-pagina.";
      return;
    }
    el("advice-status").textContent = `Advies van ${advice.day}. Zwaarste facetten van de forest: ${advice.top_facets.join(", ")}.`;
    const cellOf = (v) => (v === null || v === undefined ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`);
    const rows = advice.rows.map((r) => [r.ticker, r.invested ? "belegd" : "cash", cellOf(r.parts.lstm), cellOf(r.parts.forest),
      cellOf(r.parts.nieuws), cellOf(r.parts.intuitie), cellOf(r.score),
      html("td", r.action === "sell" ? "neg" : r.action === "buy" ? "pos" : "", ACTIONS[r.action]), r.reason]);
    el("advice").replaceChildren(table(["Aandeel", "Status", "LSTM", "Forest", "Nieuws", "Intuïtie", "Score", "Actie", "Reden"], rows));
  }
  function renderGroups(a) {
    const usingGroups = el("groups-on").checked;
    el("group-results").hidden = !usingGroups;
    if (!usingGroups) return;
    const rows = Object.entries(plan.labels).map(([group, text]) => {
      const members = a.stocks.filter((s) => s.group === group);
      const sum = (f) => members.reduce((t, s) => t + f(s), 0);
      const costs = sum((s) => s.costs.rule.costs), moves = sum((s) => s.costs.rule.sells + s.costs.rule.buys);
      return [text, members.map((s) => s.ticker).join(", ") || "-", euro(sum((s) => last(s.hold))),
        colored(sum((s) => last(s.rule) - last(s.hold))), `${moves} / ${euro(costs)}`,
        colored(sum((s) => last(s.max) - last(s.hold)))];
    });
    el("groups").replaceChildren(table(["Groep", "Aandelen", "Hold nu", "Regel t.o.v. hold", "Transacties / kosten", "Maximum t.o.v. hold"], rows));
  }
  function render() {
    const a = state.data;
    if (!state.picked.size) a.stocks.slice(0, 5).forEach((s) => state.picked.add(s.ticker));
    renderTiles(a, state.dataB); renderValue(a, state.dataB);
    renderChips(a); renderPrices(a); renderSales(a); renderStocks(a); renderGroups(a); renderDaytrade(a); renderWhy(a); renderTiming(a); loadResearch();
    if (!state.playersLoaded) { state.playersLoaded = true; loadPlayers(a); }
    buildAssignment(a.stocks.map((s) => s.ticker));
    if (a.failed.length) el("status").textContent = "Geen koersen voor: " + a.failed.join(", ");
  }

  // ------------------------------------------------------------- run
  async function load(which) {
    const response = await fetch(`${source}?${query(which)}`, { credentials: "same-origin" });
    if (response.status === 429) throw new Error("Te veel verzoeken, wacht even en probeer opnieuw.");
    if (response.redirected || !(response.headers.get("content-type") || "").includes("json")) {
      throw new Error("Server gaf geen data terug (status " + response.status + "). Log opnieuw in of kijk in de terminal.");
    }
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Fout");
    return body;
  }
  async function run() {
    el("status").textContent = "Bezig met laden (de eerste keer duurt even) ...";
    el("run").disabled = true;
    try {
      state.data = await load("a");
      state.dataB = el("b-on").checked ? await load("b") : null;
      el("status").textContent = "";
      render();
    } catch (error) {
      el("status").textContent = error.message;
    } finally {
      el("run").disabled = false;
    }
  }

  loadAi();
  loadAdvice();
  buildFields("a"); buildFields("b"); fillFields("a"); fillFields("b");
  el("presets").replaceChildren(...PRESETS.map(([label, patch]) => {
    const button = html("button", "chip", label);
    button.type = "button";
    button.addEventListener("click", () => { applyPreset(patch); run(); });
    return button;
  }));
  buildGroupFields(); buildAssignment([]);
  el("search-go").addEventListener("click", searchStocks);
  el("search-q").addEventListener("keydown", (event) => { if (event.key === "Enter") searchStocks(); });
  el("add-go").addEventListener("click", addStock);
  el("plan-save").addEventListener("click", savePlan);
  loadHoldings().catch((error) => say("holdings-status", error.message));
  el("groups-on").addEventListener("change", () => { el("group-panel").hidden = !el("groups-on").checked; });
  el("b-on").addEventListener("change", toggleB);
  el("run").addEventListener("click", run);
  el("spikes-on").addEventListener("change", () => { if (state.data) renderPrices(state.data); });
  el("max-on").addEventListener("change", () => { if (state.data) render(); });
  run();
})();
