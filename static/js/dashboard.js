(() => {
  const root = document.getElementById("dash");
  if (!root) return;
  const defaults = JSON.parse(root.dataset.defaults);
  const source = root.dataset.source;
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
  const state = { a: { ...defaults }, b: { ...defaults }, data: null, dataB: null, picked: new Set() };
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
  function query(which) {
    const params = new URLSearchParams({ days: el("window").value });
    Object.entries(readFields(which)).forEach(([k, v]) => params.set(k, v === null ? "off" : v));
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
  function renderTiles(a, b) {
    const hold = last(a.total.hold);
    const items = [["Hold", hold], [b ? "Regel A" : "Regel", last(a.total.rule)]];
    if (b) items.push(["Regel B", last(b.total.rule)]);
    items.push(["Uitgevoerd", last(a.total.executed)], ["Maximum", last(a.total.max)]);
    el("tiles").replaceChildren(...items.map(([name, value]) => {
      const tile = html("div", "tile");
      const text = name === "Hold" ? "start " + euro(a.total.hold[0]) : `${signed(value - hold)} t.o.v. hold`;
      tile.append(html("div", "k", name), html("div", "v", euro(value)), html("div", `d ${name === "Hold" ? "" : tone(value - hold)}`, text));
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
  function renderPrices(a) {
    const n = a.stocks.length;
    const lines = a.stocks
      .map((s, i) => ({ name: s.ticker, color: colorFor(i, n), values: s.price.map((p) => (p / s.price[0]) * 100), width: 1.8 }))
      .filter((l) => state.picked.has(l.name));
    if (!lines.length) { el("price-chart").replaceChildren(html("p", "helper", "Kies een of meer aandelen.")); return; }
    lineChart(el("price-chart"), a.days, lines, [], { height: 300, format: (v) => v.toFixed(0) });
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
    const rows = a.stocks.map((s) => [s.ticker, euro(last(s.hold)), colored(last(s.rule) - last(s.hold)),
      colored(last(s.executed) - last(s.hold)), colored(last(s.max) - last(s.hold))]);
    el("stocks").replaceChildren(table(["Aandeel", "Hold nu", "Regel A t.o.v. hold", "Uitgevoerd t.o.v. hold", "Maximum t.o.v. hold"], rows));
  }
  function render() {
    const a = state.data;
    if (!state.picked.size) a.stocks.slice(0, 5).forEach((s) => state.picked.add(s.ticker));
    renderTiles(a, state.dataB); renderValue(a, state.dataB);
    renderChips(a); renderPrices(a); renderSales(a); renderStocks(a);
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

  buildFields("a"); buildFields("b"); fillFields("a"); fillFields("b");
  el("presets").replaceChildren(...PRESETS.map(([label, patch]) => {
    const button = html("button", "chip", label);
    button.type = "button";
    button.addEventListener("click", () => { applyPreset(patch); run(); });
    return button;
  }));
  el("b-on").addEventListener("change", toggleB);
  el("run").addEventListener("click", run);
  el("max-on").addEventListener("change", () => { if (state.data) render(); });
  run();
})();
