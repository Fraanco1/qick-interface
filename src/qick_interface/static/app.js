"use strict";
// One page for the whole instrument. The server owns all measurement logic;
// this file renders forms from parameter schemas and plots live updates.

const MEASUREMENT = "resonator_sweep";
const $ = (id) => document.getElementById(id);

// ---- per-browser conveniences (may be unavailable, e.g. private windows) ----
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem("qi." + key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem("qi." + key, JSON.stringify(value)); } catch {} },
};

const clientId = store.get("client", null) || (() => {
  const id = Math.random().toString(36).slice(2) + Date.now().toString(36);
  store.set("client", id);
  return id;
})();

const state = {
  schema: null,          // parameter JSON schema of the measurement
  profiles: {},          // chip name -> setup profile
  controller: null, controllerName: null, running: false, tone: null,
  menu: store.get("menu", "Sweep"),
  data: null,            // last update {x, traces}
  marker: null,          // index into x
};

// ---- server calls -----------------------------------------------------
async function api(method, path, body) {
  const headers = { "X-Client-Id": clientId, "X-Client-Name": encodeURIComponent($("name").value.trim()) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const payload = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(describeError(payload.detail) || `Request failed (${r.status}).`);
  return payload;
}

function describeError(detail) {
  if (!Array.isArray(detail)) return detail;
  return detail.map((d) => `${fieldTitle(d.field || (d.loc || []).slice(-1)[0])}: ${d.message || d.msg}`).join("; ");
}

function fieldTitle(key) {
  return state.schema?.properties?.[key]?.title || key;
}

// ---- formatting ---------------------------------------------------------
function formatFreq(mhz) {
  if (Math.abs(mhz) >= 1000) return (mhz / 1000).toFixed(6).replace(/(\.\d{3})(\d{3})$/, "$1 $2") + " GHz";
  return mhz.toFixed(3) + " MHz";
}

// Tick label for a frequency axis: GHz/MHz with just enough decimals for one division.
function freqTick(v, div) {
  const ghz = Math.abs(v) >= 1000, val = ghz ? v / 1000 : v, d = ghz ? div / 1000 : div;
  return val.toFixed(Math.max(0, Math.ceil(-Math.log10(d) + 0.001)));
}

const minus = (text) => text.replace(/^-/, "\u2212");

function decimalsFor(div) { return Math.max(0, -Math.floor(Math.log10(div) + 1e-9)); }

// 10 divisions with a round step, starting on a division and always containing [min, max].
function tenDivisionRange(min, max) {
  let d = niceDiv((max - min) || 1), lo = Math.floor(min / d) * d;
  while (lo + 10 * d < max) { d = niceDiv(d * 10.1); lo = Math.floor(min / d) * d; }
  return [lo, lo + 10 * d];
}

function niceDiv(range) {
  const raw = range / 10, p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].map((m) => m * p).find((v) => v >= raw);
}

// ---- soft-key menus -------------------------------------------------------
function menuNames() {
  const groups = [];
  for (const p of Object.values(state.schema.properties)) {
    if (p.group && !groups.includes(p.group)) groups.push(p.group);
  }
  const iq = state.profiles[$("chip").value]?.output_path === "iq";
  return [...groups, "Marker", "Setup", ...(iq ? ["I/Q cal"] : [])];
}

function renderMenus() {
  const names = menuNames();
  if (!names.includes(state.menu)) state.menu = names[0];
  $("menus").replaceChildren(...names.map((name) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "key"; b.textContent = name; b.role = "tab";
    b.setAttribute("aria-selected", String(name === state.menu));
    b.onclick = () => { state.menu = name; store.set("menu", name); renderMenus(); };
    return b;
  }));
  renderMenuBody();
}

function renderMenuBody() {
  const body = $("menu-body");
  if (state.menu === "Marker") body.replaceChildren(...markerMenu());
  else if (state.menu === "Setup") body.replaceChildren(...setupMenu("Setup"));
  else if (state.menu === "I/Q cal") body.replaceChildren(...setupMenu("I/Q cal"));
  else {
    const saved = store.get("params", {});
    const fields = Object.entries(state.schema.properties).filter(([, p]) => p.group === state.menu);
    body.replaceChildren(...fields.map(([key, p]) => paramField(key, p, saved[key])));
  }
  applyControl();
}

function paramField(key, p, savedValue) {
  const input = document.createElement("input");
  input.name = key; input.type = "number"; input.inputMode = "decimal";
  input.step = p.type === "integer" ? "1" : "any";
  if (p.minimum !== undefined) input.min = p.minimum;
  if (p.maximum !== undefined) input.max = p.maximum;
  input.value = savedValue ?? p.default ?? "";
  input.dataset.param = "1";
  input.onchange = () => {
    const params = store.get("params", {});
    params[key] = input.value === "" ? undefined : Number(input.value);
    store.set("params", params);
    input.removeAttribute("aria-invalid");
  };
  return field(p.title, input, p.unit);
}

function field(title, control, unit, hint) {
  const label = document.createElement("label");
  label.className = "field";
  const span = document.createElement("span"); span.textContent = title;
  const row = document.createElement("div"); row.className = "input-row";
  row.append(control);
  if (unit) { const u = document.createElement("span"); u.className = "unit"; u.textContent = unit; row.append(u); }
  label.append(span, row);
  if (hint) { const h = document.createElement("span"); h.className = "hint"; h.textContent = hint; label.append(h); }
  return label;
}

function button(text, onclick, extraClass = "") {
  const b = document.createElement("button");
  b.type = "button"; b.className = "key " + extraClass; b.textContent = text; b.onclick = onclick;
  return b;
}

function markerMenu() {
  return [
    button("Marker → Min", () => setMarker(argMin(state.data?.traces["|S21| (dB)"]))),
    button("Marker → Max", () => setMarker(argMax(state.data?.traces["|S21| (dB)"]))),
    button("Marker off", () => setMarker(null)),
    hint("Click on a trace to place the marker."),
  ];
}

function hint(text) {
  const p = document.createElement("p"); p.className = "hint"; p.textContent = text; p.style.margin = "0";
  return p;
}

// ---- setup profiles ------------------------------------------------------
// [key, title, kind, unit, hint, shown only for this output path, or in the "I/Q cal" menu]
const PROFILE_FIELDS = [
  ["chip", "Chip name", "text"],
  ["chip_type", "Chip type", ["transmon", "fluxonium"]],
  ["lo_mhz", "LO frequency", "number", "MHz", "Leave empty when there is no mixer (RF = IF)."],
  ["sideband", "Sideband", ["upper", "lower"], null, "Upper: RF = LO + IF. Lower: RF = LO − IF."],
  ["output_path", "Output path", ["real", "iq"], null, "I/Q: the tone goes out on two DACs into an I/Q mixer."],
  ["readout_dac", "Readout output", ["DAC_A", "DAC_B"], null, null, "real"],
  ["i_dac", "I output", ["DAC_A", "DAC_B"], null, null, "iq"],
  ["q_dac", "Q output", ["DAC_A", "DAC_B"], null, null, "iq"],
  ["iq_phase_deg", "Q phase offset", "number", "°", "90 for an ideal mixer.", "I/Q cal"],
  ["iq_gain_ratio", "Q / I gain", "number", null, "1 for an ideal mixer.", "I/Q cal"],
  ["readout_adc", "Readout input", ["ADC_B", "ADC_C", "ADC_D"]],
];

const NEW_PROFILE = { chip: "", chip_type: "transmon", lo_mhz: null, sideband: "upper", output_path: "real",
  readout_dac: "DAC_B", i_dac: "DAC_A", q_dac: "DAC_B", iq_phase_deg: 90, iq_gain_ratio: 1, readout_adc: "ADC_D" };

// The Setup and I/Q cal menus edit the same profile; each shows its own fields and saves all of them.
function setupMenu(menu) {
  const current = { ...NEW_PROFILE, ...(state.profiles[$("chip").value] || {}) };
  const controls = {}, rows = {};
  const nodes = PROFILE_FIELDS.map(([key, title, kind, unit, help, onlyFor]) => {
    let c;
    if (Array.isArray(kind)) {
      c = document.createElement("select");
      c.append(...kind.map((v) => new Option(v === "iq" ? "I/Q" : v, v)));
    } else {
      c = document.createElement("input"); c.type = kind;
      if (kind === "number") { c.step = "any"; c.inputMode = "decimal"; }
    }
    c.value = current[key] ?? "";
    c.dataset.control = "1";
    controls[key] = c;
    rows[key] = field(title, c, unit, help);
    rows[key].dataset.onlyFor = onlyFor || "";
    return rows[key];
  });
  const showFields = () => {
    for (const row of Object.values(rows)) {
      const only = row.dataset.onlyFor;
      row.hidden = menu === "I/Q cal" ? only !== "I/Q cal" : only === "I/Q cal" || (!!only && only !== controls.output_path.value);
    }
  };
  controls.output_path.onchange = showFields;
  showFields();
  controls.iq_phase_deg.step = "0.1";
  controls.iq_gain_ratio.step = "0.005";
  const extra = menu === "I/Q cal" ? [calibrationTone(controls)] : [];

  const save = button("Save setup", async () => {
    const profile = Object.fromEntries(Object.entries(controls).map(([k, c]) => [k, c.value]));
    profile.lo_mhz = profile.lo_mhz === "" ? null : Number(profile.lo_mhz);
    profile.iq_phase_deg = Number(profile.iq_phase_deg);
    profile.iq_gain_ratio = Number(profile.iq_gain_ratio);
    try {
      await api("PUT", `/api/profiles/${encodeURIComponent(profile.chip)}`, profile);
      await loadProfiles(profile.chip);
      message(`Saved setup for ${profile.chip}.`);
    } catch (e) { message(e.message, true); }
  }, "key-strong");
  save.dataset.control = "1";
  const help = menu === "I/Q cal"
    ? "Play a tone, watch the image on a spectrum analyzer, adjust until it is smallest, then save."
    : "Each chip keeps its own wiring. Change the chip name to save a new one.";
  return [...nodes, ...extra, save, hint(help)];
}

// A continuous tone on the I/Q pair. While it plays, phase and gain edits apply at once,
// so the image can be nulled on a spectrum analyzer before saving the setup.
function calibrationTone(controls) {
  const box = document.createElement("fieldset");
  box.className = "tone";
  const legend = document.createElement("legend"); legend.textContent = "Calibration tone";
  const rf = document.createElement("input"); rf.type = "number"; rf.step = "any"; rf.inputMode = "decimal";
  rf.value = store.get("toneRf", ""); rf.dataset.control = "1";
  const gain = document.createElement("input"); gain.type = "number"; gain.step = "0.05"; gain.min = 0; gain.max = 1;
  gain.value = store.get("toneGain", 0.3); gain.dataset.control = "1";

  const send = async () => {
    store.set("toneRf", rf.value); store.set("toneGain", gain.value);
    try {
      await api("POST", "/api/tone", { chip: controls.chip.value, rf_mhz: Number(rf.value), gain: Number(gain.value),
        iq_phase_deg: Number(controls.iq_phase_deg.value), iq_gain_ratio: Number(controls.iq_gain_ratio.value) });
      message("Tone playing. Adjust the Q phase offset and Q / I gain until the image is smallest.");
    } catch (e) { message(e.message, true); }
  };
  const on = button("Tone on", send); on.dataset.control = "1";
  const off = button("Tone off", () => api("POST", "/api/tone/off").catch((e) => message(e.message, true)));
  off.dataset.control = "1";
  const keys = document.createElement("div"); keys.className = "run-keys"; keys.append(on, off);

  let pending;
  const live = () => { if (state.tone) { clearTimeout(pending); pending = setTimeout(send, 120); } };
  for (const c of [controls.iq_phase_deg, controls.iq_gain_ratio, rf, gain]) c.addEventListener("input", live);

  box.append(legend, field("Frequency", rf, "MHz"), field("Tone gain", gain), keys);
  return box;
}

async function loadProfiles(select) {
  state.profiles = await api("GET", "/api/profiles");
  const chips = Object.keys(state.profiles);
  const chosen = select ?? store.get("chip", chips[0]);
  $("chip").replaceChildren(...(chips.length ? chips.map((c) => new Option(c, c)) : [new Option("No chips yet", "")]));
  if (chips.includes(chosen)) $("chip").value = chosen;
  store.set("chip", $("chip").value);
  if (!chips.length) state.menu = "Setup";
  renderMenus();
}

// ---- control ------------------------------------------------------------
function isController() { return state.controller === clientId; }

function applyControl() {
  const mine = isController();
  const status = $("control-status");
  status.classList.toggle("mine", mine);
  status.textContent = mine ? "You control the board"
    : state.controller ? `Viewing. ${state.controllerName || "Someone"} controls the board`
    : "Nobody controls the board";
  $("take-control").hidden = mine;
  document.querySelectorAll("[data-param], [data-control]").forEach((el) => { el.disabled = !mine; });
  $("run").disabled = !mine || state.running || !$("chip").value;
  $("stop").disabled = !mine || !state.running;
  const led = $("st-state");
  led.textContent = state.running ? "Measuring" : state.tone ? `Tone ${formatFreq(state.tone.rf_mhz)}` : "Hold";
  led.classList.toggle("on", state.running || !!state.tone);
}

function collectParams() {
  const saved = store.get("params", {});
  const params = {};
  for (const [key, p] of Object.entries(state.schema.properties)) {
    const v = saved[key] ?? p.default;
    if (v !== undefined && v !== null && v !== "") params[key] = Number(v);
  }
  return params;
}

async function run() {
  try {
    message("");
    await api("POST", "/api/runs", { measurement: MEASUREMENT, chip: $("chip").value, params: collectParams() });
  } catch (e) { message(e.message, true); }
}

// ---- plots ----------------------------------------------------------------
const plots = {};

function makePlot(el, color, unit) {
  const axis = { stroke: "#9aa1aa", grid: { stroke: "#3b4148", width: 1, dash: [2, 3] },
                 ticks: { show: false }, font: "12px " + getComputedStyle(document.body).fontFamily };
  const tenDivisions = (u, i, min, max) => Array.from({ length: 11 }, (_, k) => min + (k * (max - min)) / 10);
  const opts = {
    width: el.clientWidth, height: el.clientHeight,
    legend: { show: false },
    cursor: { sync: { key: "screen" }, points: { show: false }, drag: { x: false, y: false } },
    scales: { x: { time: false }, y: { range: (u, min, max) => tenDivisionRange(min, max) } },
    axes: [
      { ...axis, splits: tenDivisions, size: 30, values: (u, vals) => {
          const every = u.width < 500 ? 5 : 2, div = (vals[10] - vals[0]) / 10;
          return vals.map((v, k) => (k % every ? "" : freqTick(v, div)));
        } },
      { ...axis, splits: tenDivisions, size: 56,
        values: (u, vals) => vals.map((v) => minus(v.toFixed(decimalsFor((vals[10] - vals[0]) / 10)))) },
    ],
    series: [{}, { stroke: color, width: 1.5, points: { show: false } }],
    hooks: { draw: [(u) => drawMarker(u, color)], setScale: [() => traceLines()], ready: [(u) => u.over.addEventListener("click", () => setMarker(u.cursor.idx))] },
  };
  return new uPlot(opts, [[], []], el);
}

function drawMarker(u, color) {
  if (state.marker === null || !state.data) return;
  const x = state.data.x[state.marker], y = u.data[1][state.marker];
  if (x === undefined || y === undefined) return;
  const cx = u.valToPos(x, "x", true), cy = u.valToPos(y, "y", true), ctx = u.ctx, r = 6 * devicePixelRatio;
  ctx.save();
  ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5 * devicePixelRatio;
  ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx - r, cy - 1.7 * r); ctx.lineTo(cx + r, cy - 1.7 * r); ctx.closePath(); ctx.stroke();
  ctx.fillStyle = color; ctx.font = `${11 * devicePixelRatio}px sans-serif`; ctx.textAlign = "center";
  ctx.fillText("1", cx, cy - 2.2 * r);
  ctx.restore();
}

function setMarker(idx) {
  state.marker = idx ?? null;
  plots.mag.redraw(false); plots.phase.redraw(false);
  renderMarkerReadout();
}

function renderMarkerReadout() {
  const box = $("marker-readout");
  if (state.marker === null || !state.data) { box.hidden = true; return; }
  const i = state.marker, t = state.data.traces;
  box.hidden = false;
  box.innerHTML = "";
  box.append(`Mkr 1  ${formatFreq(state.data.x[i])}`, document.createElement("br"));
  const num = (txt) => { const s = document.createElement("span"); s.className = "num"; s.textContent = txt; return s; };
  const fmt = (v, digits) => (v === null ? "—" : minus(v.toFixed(digits)));
  box.append(num(`${fmt(t["|S21| (dB)"][i], 2)} dB`), "   ", num(`${fmt(t["Phase (°)"][i], 2)}°`));
}

const argMin = (a) => (a && a.length ? a.reduce((best, v, i) => (v < a[best] ? i : best), 0) : null);
const argMax = (a) => (a && a.length ? a.reduce((best, v, i) => (v > a[best] ? i : best), 0) : null);

function showUpdate(u) {
  if (state.marker !== null && state.marker >= u.x.length) state.marker = null;
  state.data = u;
  $("empty").hidden = true;
  plots.mag.setData([u.x, u.traces["|S21| (dB)"]]);
  plots.phase.setData([u.x, u.traces["Phase (°)"]]);
  renderMarkerReadout();
  $("st-start").textContent = `Start ${formatFreq(u.x[0])}`;
  $("st-stop").textContent = `Stop ${formatFreq(u.x[u.x.length - 1])}`;
  $("st-points").textContent = `${u.x.length} points`;
  $("st-round").textContent = `Round ${u.round} of ${u.rounds}`;
}

function traceLines() {
  if (!state.data) return;
  for (const [key, line, label, unit] of [["mag", "tr1-line", "Tr1 S21 LogMag", "dB"], ["phase", "tr2-line", "Tr2 S21 Phase", "°"]]) {
    const s = plots[key]?.scales.y;
    if (s.min === undefined || s.min === null) continue;
    const div = (s.max - s.min) / 10;
    $(line).textContent = `${label}   ${+div.toPrecision(3)} ${unit}/div   Ref ${minus(s.min.toFixed(decimalsFor(div)))} ${unit}`;
  }
}

function message(text, isError = false) {
  const m = $("st-message");
  m.textContent = text;
  m.classList.toggle("error", isError);
}

// ---- live connection ------------------------------------------------------
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "state") {
      Object.assign(state, { controller: m.controller, controllerName: m.controller_name, running: m.running, tone: m.tone });
      applyControl();
    } else if (m.type === "update") {
      showUpdate(m);
    } else if (m.type === "saved") {
      message(`Saved to data/${m.file}`);
    } else if (m.type === "error") {
      message(m.message, true);
    }
  };
  ws.onclose = () => { message("Connection to the instrument lost. Reconnecting…", true); setTimeout(connect, 2000); };
  ws.onopen = () => { if ($("st-message").textContent.startsWith("Connection")) message(""); };
}

// ---- start --------------------------------------------------------------
async function main() {
  $("name").value = store.get("name", "");
  $("name").onchange = () => store.set("name", $("name").value.trim());
  $("chip").onchange = () => { store.set("chip", $("chip").value); renderMenus(); };
  $("take-control").onclick = async () => {
    if (!$("name").value.trim()) { $("name").focus(); message("Type your name first, so others know who controls the board.", true); return; }
    try { await api("POST", "/api/control"); } catch (e) { message(e.message, true); }
  };
  $("run").onclick = run;
  $("stop").onclick = () => api("POST", "/api/runs/stop").catch((e) => message(e.message, true));

  state.schema = (await api("GET", "/api/measurements"))[MEASUREMENT].params;
  plots.mag = makePlot($("plot-mag"), getComputedStyle(document.documentElement).getPropertyValue("--tr1").trim());
  plots.phase = makePlot($("plot-phase"), getComputedStyle(document.documentElement).getPropertyValue("--tr2").trim());
  new ResizeObserver(() => {
    for (const [k, el] of [["mag", "plot-mag"], ["phase", "plot-phase"]]) plots[k].setSize({ width: $(el).clientWidth, height: $(el).clientHeight });
    traceLines();
  }).observe($("plot-mag").parentElement.parentElement);

  await loadProfiles();  // draws the menus, which depend on the chip's output path
  applyControl();
  connect();
}

main().catch((e) => message(e.message, true));
