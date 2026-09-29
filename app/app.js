// Vagnvåg – enkel webbapp. Ingen byggprocess, bara vanlig JavaScript.
"use strict";

const REFRESH_MS = 3000;
const CORNERS = ["VL", "VR", "HL", "HR"];
const CORNER_NAMES = { VL: "Fram vänster", VR: "Fram höger", HL: "Bak vänster", HR: "Bak höger" };
const FLAG_TEXT = {
  corner_missing: ["Hörn saknas", "bad"],
  not_calibrated: ["Ej nollställd", "warn"],
  no_tare: ["Tomvikt saknas", "warn"],
  overload: ["Överlast", "bad"],
  imbalance_long: ["Snedlast fram/bak", "bad"],
  imbalance_lat: ["Snedlast sida", "bad"],
  imbalance_diag: ["Snedlast diagonalt", "bad"],
  low_battery: ["Lågt batteri", "warn"],
  sensor_fault: ["Givarfel", "bad"],
  simulated: ["Simulerade värden", "warn"],
  laser_ok: ["Laser", "ok"],
  ultrasonic_ok: ["Ultraljud", "ok"],
  moving: ["Rör sig", "warn"],
};

const $view = document.getElementById("view");
const $conn = document.getElementById("conn");
let timer = null;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtKg(kg) {
  if (kg === null || kg === undefined) return "–";
  return kg >= 1000 ? `${(kg / 1000).toFixed(1).replace(".", ",")} t` : `${Math.round(kg)} kg`;
}

function fmtAge(s) {
  if (s === null || s === undefined) return "aldrig";
  if (s < 60) return `${Math.round(s)} s sedan`;
  if (s < 3600) return `${Math.round(s / 60)} min sedan`;
  return `${Math.round(s / 3600)} h sedan`;
}

function fmtMm(mm) {
  return mm === null || mm === undefined ? "–" : `${mm.toFixed(1).replace(".", ",")} mm`;
}

function chips(flags) {
  if (!flags || !flags.length) return `<div class="chips"><span class="chip ok">OK</span></div>`;
  return `<div class="chips">${flags.map((f) => {
    const [text, cls] = FLAG_TEXT[f] || [f, ""];
    return `<span class="chip ${cls}">${esc(text)}</span>`;
  }).join("")}</div>`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* tomt svar */ }
  if (!res.ok) throw new Error((data && data.detail) ? JSON.stringify(data.detail).replace(/^"|"$/g, "") : `HTTP ${res.status}`);
  $conn.textContent = `Ansluten · uppdaterad ${new Date().toLocaleTimeString("sv-SE")}`;
  return data;
}

function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach((a) =>
    a.classList.toggle("active", a.dataset.nav === name));
}

function every(fn) {
  clearInterval(timer);
  const run = () => fn().catch((e) => { $conn.textContent = `Ingen kontakt med servern: ${e.message}`; });
  run();
  timer = setInterval(run, REFRESH_MS);
}

// ---- Vagnar ----

function renderWagonList() {
  setNav("wagons");
  $view.innerHTML = `<h1>Vagnar</h1><div id="list" class="grid"></div>
    <p class="muted small">Registrera hörnenheter under <a href="#/enheter">Enheter</a> för att lägga till en vagn.</p>`;
  every(async () => {
    const wagons = await api("/api/v1/wagons");
    const el = document.getElementById("list");
    if (!el) return;
    el.innerHTML = wagons.length ? wagons.map((w) => `
      <a class="card" href="#/vagn/${encodeURIComponent(w.wagon)}" style="color:inherit">
        <div class="row spread"><strong class="mono">${esc(w.wagon)}</strong>
          <span class="muted small">${fmtAge(w.last_age_s)}</span></div>
        <div class="big">${fmtKg(w.total_kg)}</div>
        ${chips(w.flags)}
      </a>`).join("") : `<div class="card muted">Inga vagnar än.</div>`;
  });
}

function cornerGrid(w) {
  // Sett uppifrån med färdriktningen åt vänster: höger sida överst, vänster sida nederst.
  const cell = (c) => {
    const d = w.corners[c];
    const missing = d.distance_mm === null;
    const batt = d.battery_mv ? (d.battery_mv / 1000).toFixed(2).replace(".", ",") + " V" : "– V";
    return `<div class="corner-cell${missing ? " missing" : ""}">
      <div class="small muted">${c} · ${esc(CORNER_NAMES[c])}</div>
      <div class="corner-kg">${fmtKg(d.kg)}</div>
      <div class="small muted">${fmtMm(d.distance_mm)} · ${batt}</div>
      <div class="small muted">${d.mac ? fmtAge(d.age_s) : "ingen enhet registrerad"}</div>
    </div>`;
  };
  return `<div class="corner-grid">
    ${cell("VR")}${cell("HR")}
    <div class="wagon-line"><span>◀ färdriktning · boggi 1</span><span>boggi 2</span></div>
    ${cell("VL")}${cell("HL")}
  </div>`;
}

function imbalanceRow(label, pct) {
  const v = Math.max(-30, Math.min(30, pct || 0));
  const left = v < 0 ? 50 + (v / 30) * 50 : 50;
  const width = Math.abs(v / 30) * 50;
  const color = Math.abs(pct) > 10 ? "var(--bad)" : "var(--accent)";
  return `<div class="imb"><span class="small">${label}</span>
    <div class="bar"><i></i><span style="left:${left}%;width:${width}%;background:${color}"></span></div>
    <span class="small">${pct === null || pct === undefined ? "–" : pct.toFixed(1).replace(".", ",") + " %"}</span></div>`;
}

function sparkline(points) {
  const vals = points.filter((p) => p.total_kg !== null);
  if (vals.length < 2) return `<p class="muted small">För lite data för en kurva än.</p>`;
  const xs = vals.map((p) => p.ts), ys = vals.map((p) => p.total_kg);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.1 || 500;
  const sx = (x) => ((x - x0) / (x1 - x0 || 1)) * 600;
  const sy = (y) => 80 - ((y - (y0 - pad)) / (y1 - y0 + 2 * pad)) * 80;
  const pts = vals.map((p) => `${sx(p.ts).toFixed(1)},${sy(p.total_kg).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 600 80" preserveAspectRatio="none">
    <line x1="0" y1="79.5" x2="600" y2="79.5"/><polyline points="${pts}"/></svg>
    <div class="row spread small muted"><span>${fmtKg(y0)} – ${fmtKg(y1)}</span><span>senaste timmen</span></div>`;
}

function renderWagon(id) {
  setNav("wagons");
  $view.innerHTML = `
    <p><a href="#/">← Vagnar</a></p>
    <h1 class="mono">${esc(id)}</h1>
    <div id="summary" class="card"></div>
    <div class="card" id="svg"></div>
    <div class="card"><h2 style="margin-top:0">Snedlastning</h2><div id="imb"></div></div>
    <div class="card"><h2 style="margin-top:0">Totalvikt över tid</h2><div id="hist"></div></div>
    <div class="card">
      <h2 style="margin-top:0">Tom vagn</h2>
      <p class="small muted">Bekräfta när vagnen är tom. Nollpunkten justeras bara om ändringen är rimlig (högst 3 mm).
        Välj "efter ommontering" första gången eller om en enhet eller målplåt har flyttats.</p>
      <div class="field"><label for="who">Ditt namn</label><input id="who" autocomplete="name"></div>
      <div class="row">
        <button id="empty">Bekräfta tom vagn</button>
        <button id="emptyForce" class="secondary">Efter ommontering</button>
      </div>
      <div id="emptyMsg"></div>
    </div>
    <div class="card">
      <h2 style="margin-top:0">Inställningar</h2>
      <form id="settings">
        <div class="field"><label for="tare">Tomvikt (kg, står på vagnen)</label><input id="tare" type="number" inputmode="decimal" min="0"></div>
        <div class="field"><label for="max">Max totalvikt (kg)</label><input id="max" type="number" inputmode="decimal" min="0"></div>
        <button type="submit">Spara</button>
        <div id="setMsg"></div>
      </form>
    </div>`;

  let filled = false;
  const confirmEmpty = async (force) => {
    const msg = document.getElementById("emptyMsg");
    try {
      await api(`/api/v1/wagons/${encodeURIComponent(id)}/empty`, {
        method: "POST", body: { who: document.getElementById("who").value || null, force },
      });
      msg.innerHTML = `<div class="msg ok">Nollställd.</div>`;
    } catch (e) {
      msg.innerHTML = `<div class="msg bad">${esc(e.message)}</div>`;
    }
  };
  document.getElementById("empty").onclick = () => confirmEmpty(false);
  document.getElementById("emptyForce").onclick = () => {
    if (confirm("Sätta nya nollpunkter utan rimlighetskontroll? Gör bara detta när vagnen är tom och efter montering.")) confirmEmpty(true);
  };
  document.getElementById("settings").onsubmit = async (ev) => {
    ev.preventDefault();
    const num = (v) => (v === "" ? null : Number(v));
    const msg = document.getElementById("setMsg");
    try {
      await api(`/api/v1/wagons/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: { tare_kg: num(document.getElementById("tare").value), max_total_kg: num(document.getElementById("max").value) },
      });
      msg.innerHTML = `<div class="msg ok">Sparat.</div>`;
    } catch (e) {
      msg.innerHTML = `<div class="msg bad">${esc(e.message)}</div>`;
    }
  };

  every(async () => {
    const [w, h] = await Promise.all([
      api(`/api/v1/wagons/${encodeURIComponent(id)}`),
      api(`/api/v1/wagons/${encodeURIComponent(id)}/history?minutes=60&bucket_s=30`),
    ]);
    if (!document.getElementById("summary")) return;
    document.getElementById("summary").innerHTML = `
      <div class="row spread"><span class="muted">Totalvikt</span><span class="muted small">${fmtAge(w.last_age_s)}</span></div>
      <div class="big">${fmtKg(w.total_kg)}</div>
      <div class="small muted">Tomvikt ${fmtKg(w.tare_kg)}${w.max_total_kg ? ` · max ${fmtKg(w.max_total_kg)}` : ""}</div>
      ${chips(w.flags)}`;
    document.getElementById("svg").innerHTML = cornerGrid(w);
    const imb = w.imbalance || {};
    document.getElementById("imb").innerHTML =
      imbalanceRow("Fram – bak", imb.long_pct) +
      imbalanceRow("Vänster – höger", imb.lat_pct) +
      imbalanceRow("Diagonalt", imb.diag_pct);
    document.getElementById("hist").innerHTML = sparkline(h.points || []);
    if (!filled) {
      document.getElementById("tare").value = w.tare_kg ?? "";
      document.getElementById("max").value = w.max_total_kg ?? "";
      filled = true;
    }
  });
}

// ---- Enheter ----

function renderDevices() {
  setNav("devices");
  $view.innerHTML = `
    <h1>Enheter</h1>
    <div class="card">
      <h2 style="margin-top:0">Registrera hörnenhet</h2>
      <form id="reg">
        <div class="field"><label for="mac">Enhet (MAC)</label><select id="mac"></select></div>
        <div class="field"><label for="wagon">Vagnsnummer</label>
          <input id="wagon" placeholder="t.ex. 318045671234" autocapitalize="characters" required pattern="[A-Za-z0-9\\-]{1,32}"></div>
        <div class="field"><label for="corner">Hörn</label>
          <select id="corner">${CORNERS.map((c) => `<option value="${c}">${c} – ${CORNER_NAMES[c]}</option>`).join("")}</select></div>
        <button type="submit">Registrera</button>
        <div id="regMsg"></div>
      </form>
    </div>
    <div class="card scroll"><table>
      <thead><tr><th>MAC</th><th>Vagn</th><th>Hörn</th><th>Avstånd</th><th>Batteri</th><th>RSSI</th><th>Senast</th></tr></thead>
      <tbody id="devs"></tbody></table></div>`;

  document.getElementById("reg").onsubmit = async (ev) => {
    ev.preventDefault();
    const msg = document.getElementById("regMsg");
    const wagon = document.getElementById("wagon").value.trim();
    try {
      await api("/api/v1/devices", {
        method: "POST",
        body: { mac: document.getElementById("mac").value, wagon, corner: document.getElementById("corner").value },
      });
      msg.innerHTML = `<div class="msg ok">Registrerad. <a href="#/vagn/${encodeURIComponent(wagon)}">Öppna vagnen</a></div>`;
    } catch (e) {
      msg.innerHTML = `<div class="msg bad">${esc(e.message)}</div>`;
    }
  };

  let lastMacs = "";
  every(async () => {
    const devs = await api("/api/v1/devices");
    const tbody = document.getElementById("devs");
    if (!tbody) return;
    tbody.innerHTML = devs.length ? devs.map((d) => `<tr>
      <td class="mono">${esc(d.mac)}</td>
      <td class="mono">${d.wagon ? `<a href="#/vagn/${encodeURIComponent(d.wagon)}">${esc(d.wagon)}</a>` : `<span class="muted">ej registrerad</span>`}</td>
      <td>${esc(d.corner || d.reported_corner || "–")}</td>
      <td>${fmtMm(d.distance_mm)}</td>
      <td>${d.battery_mv ? (d.battery_mv / 1000).toFixed(2).replace(".", ",") + " V" : "–"}</td>
      <td>${d.rssi ?? "–"}</td>
      <td class="small">${fmtAge(d.age_s)}</td></tr>`).join("")
      : `<tr><td colspan="7" class="muted">Inga enheter hörda än. Starta en hörnenhet och en gateway.</td></tr>`;

    // Uppdatera listan i formuläret bara när enheterna ändrats, så att valet inte nollställs.
    const macs = devs.map((d) => d.mac + (d.wagon || "")).join(",");
    if (macs !== lastMacs) {
      const sel = document.getElementById("mac");
      const prev = sel.value;
      sel.innerHTML = devs.map((d) =>
        `<option value="${esc(d.mac)}">${esc(d.mac)}${d.wagon ? ` (${esc(d.wagon)} ${esc(d.corner)})` : " – ny"}</option>`).join("");
      if (prev) sel.value = prev;
      lastMacs = macs;
    }
  });
}

// ---- Gateways ----

function renderGateways() {
  setNav("gateways");
  $view.innerHTML = `<h1>Gateways</h1><div class="card scroll"><table>
    <thead><tr><th>Id</th><th>Firmware</th><th>Wifi RSSI</th><th>Drifttid</th><th>Senast</th></tr></thead>
    <tbody id="gws"></tbody></table></div>`;
  every(async () => {
    const gws = await api("/api/v1/gateways");
    const tbody = document.getElementById("gws");
    if (!tbody) return;
    tbody.innerHTML = gws.length ? gws.map((g) => `<tr>
      <td class="mono">${esc(g.id)}</td><td>${esc(g.fw || "–")}</td><td>${g.wifi_rssi ?? "–"}</td>
      <td>${g.uptime_s != null ? Math.round(g.uptime_s / 60) + " min" : "–"}</td>
      <td class="small">${fmtAge(g.age_s)}</td></tr>`).join("")
      : `<tr><td colspan="5" class="muted">Ingen gateway har hörts av än.</td></tr>`;
  });
}

// ---- Routing ----

function route() {
  const h = location.hash.replace(/^#/, "") || "/";
  const m = h.match(/^\/vagn\/(.+)$/);
  if (m) return renderWagon(decodeURIComponent(m[1]));
  if (h === "/enheter") return renderDevices();
  if (h === "/gateways") return renderGateways();
  return renderWagonList();
}

window.addEventListener("hashchange", route);
route();
