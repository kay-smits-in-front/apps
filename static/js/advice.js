"use strict";

(function () {
  const root = document.getElementById("advice-page");
  if (!root) return;

  const LABELS = { sell: "VERKOPEN", buy: "KOPEN", hold: "HOUDEN" };
  const CLASSES = { sell: "neg", buy: "pos", hold: "" };
  const el = (id) => document.getElementById(id);

  function cell(text, className) {
    const td = document.createElement("td");
    td.textContent = text;
    if (className) td.className = className;
    return td;
  }

  function score(value) {
    return value === null || value === undefined ? "-" : (value >= 0 ? "+" : "") + Number(value).toFixed(1);
  }

  function table(headers, rows) {
    const t = document.createElement("table");
    t.className = "data";
    const head = t.createTHead().insertRow();
    headers.forEach((h) => {
      const th = document.createElement("th");
      th.textContent = h;
      head.appendChild(th);
    });
    const body = t.createTBody();
    rows.forEach((cells) => {
      const tr = body.insertRow();
      cells.forEach((c) => tr.appendChild(c));
    });
    return t;
  }

  function renderActions(advice) {
    el("actions-title").textContent = `Acties van ${advice.day} voor de komende 2,5 dag`;
    const rows = advice.rows.map((r) => [cell(r.ticker), cell(LABELS[r.action], CLASSES[r.action]), cell(r.reason)]);
    el("actions").replaceChildren(table(["Aandeel", "Actie", "Reden"], rows));
    el("actions-panel").hidden = false;
  }

  function renderDetails(advice) {
    const top = advice.top_facets.join(", ");
    el("details-note").textContent =
      `Zwaarste facetten volgens de forest: ${top}. Scores lopen van -5 tot +5; verkopen vanaf -1,5, terugkopen vanaf +1,5.`;
    const rows = advice.rows.map((r) => [
      cell(r.ticker), cell(r.invested ? "belegd" : "cash"), cell(score(r.parts.forest)), cell(score(r.parts.logistisch)),
      cell(score(r.parts.boosted)), cell(score(r.parts.gam)), cell(score(r.parts.nieuws)), cell(score(r.parts.intuitie)),
      cell(score(r.score)),
    ]);
    el("details").replaceChildren(table(
      ["Aandeel", "Status", "Forest 25%", "Logistisch 10%", "Boosted 10%", "GAM 10%", "Nieuws 25%", "Intuïtie 20%", "Score"], rows));
    el("details-panel").hidden = false;
  }

  function show(advice) {
    renderActions(advice);
    renderDetails(advice);
    const notes = [];
    if (advice.stale) notes.push(advice.stale);
    if (advice.failed && advice.failed.length) notes.push(`Koersen niet ververst voor: ${advice.failed.join(", ")}.`);
    el("advice-status").textContent = notes.length ? notes.join(" ") : `Advies van ${advice.day} berekend.`;
  }

  function setBusy(busy, text) {
    ["run", "retrain"].forEach((id) => { el(id).disabled = busy; });
    if (text) el("advice-status").textContent = text;
  }

  async function post(retrain) {
    const response = await fetch(root.dataset.run, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": root.dataset.csrf },
      body: JSON.stringify({ news: el("news").value, intuition: el("intuition").value, retrain }),
    });
    const body = await response.json().catch(() => ({ error: "Onverwacht antwoord van de server." }));
    if (!response.ok) throw new Error(body.error || "Het advies kon niet worden berekend.");
    return body;
  }

  async function run(retrain) {
    setBusy(true, retrain
      ? "Trainen en toetsen... dit kan een paar minuten duren. Sluit deze pagina niet."
      : "Koersen verversen en AI draaien... dit duurt even.");
    try {
      show(await post(retrain));
    } catch (error) {
      el("advice-status").textContent = `Geen advies: ${error.message}`;
    } finally {
      setBusy(false);
    }
  }

  async function loadSaved() {
    try {
      const response = await fetch(root.dataset.saved, { credentials: "same-origin" });
      const { advice } = await response.json();
      if (advice) {
        show(advice);
        el("advice-status").textContent = `Laatste advies, van ${advice.day}. Druk op de knop voor een nieuw advies.`;
      }
    } catch (error) {
      /* geen eerder advies is geen fout */
    }
  }

  el("advice-form").addEventListener("submit", (event) => { event.preventDefault(); run(false); });
  el("retrain").addEventListener("click", () => run(true));
  loadSaved();
})();
