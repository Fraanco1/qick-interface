"use strict";
// One page for the whole instrument. The server owns all measurement logic;
// this file renders forms from parameter schemas and plots live updates.

const $ = (id) => document.getElementById(id);

// ---- per-browser conveniences (may be unavailable, e.g. private windows) ----
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem("qi." + key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem("qi." + key, JSON.stringify(value)); } catch {} },
  remove(key) { try { localStorage.removeItem("qi." + key); } catch {} },
};

const clientId = store.get("client", null) || (() => {
  const id = Math.random().toString(36).slice(2) + Date.now().toString(36);
  store.set("client", id);
  return id;
})();

const state = {
  measurements: {},      // key -> {name, params (JSON schema), x_axis, marker_sets}
  measurement: store.get("measurement", "resonator_sweep"),
  get schema() { return this.measurements[this.measurement].params; },
  profiles: {},          // chip name -> setup profile
  parameters: {},        // chip parameters of the selected chip
  controller: null, controllerName: null, running: false, tone: null,
  setupOpen: false, setupTab: "Setup",  // the chip's setup panel
  helpOpen: false,  // the help panel; it and the setup take turns over the screen
  menu: store.get("menu", "Sweep"),
  data: null,            // last update {measurement, x, traces, x_axis, info}
  xAxis: null,           // {title, unit} of what is on screen
  plotsFor: null,        // measurement whose plot layout is on screen
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

// Tick label for the x axis: frequencies in GHz/MHz, anything else as a plain number,
// with just enough decimals for one division.
function xTick(v, div, ghz) {
  const val = ghz ? v / 1000 : v, d = ghz ? div / 1000 : div;
  return minus(val.toFixed(Math.max(0, Math.ceil(-Math.log10(d) + 0.001))));
}

const xUnit = () => state.xAxis?.unit ?? "MHz";

// A value on the x axis with its unit, e.g. "7.012 500 GHz" or "0.412 µs".
function formatX(v) {
  if (xUnit() === "MHz") return formatFreq(v);
  return `${minus(String(+v.toPrecision(4)))}${xUnit() ? " " + xUnit() : ""}`;
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
  return [...groups, "Scale", "Marker"];
}

// Measurements this chip's setup can run (e.g. RX I/Q calibration needs an I/Q return path).
function renderMeasurementList() {
  const profile = state.profiles[$("chip").value] ?? {};
  const usable = Object.entries(state.measurements).filter(([, m]) =>
    Object.entries(m.setup_requires).every(([key, value]) => profile[key] === value));
  if (!usable.some(([k]) => k === state.measurement)) state.measurement = "resonator_sweep";
  $("measurement").replaceChildren(...usable.map(([k, m]) => new Option(m.name, k)));
  $("measurement").value = state.measurement;
  const runKey = state.measurements[state.measurement].run_key;
  $("run").textContent = runKey;
  $("empty").textContent = `Choose a chip, set the measurement and press ${runKey}.`;
}

function renderMenus() {
  renderMeasurementList();
  const names = menuNames();
  if (!names.includes(state.menu)) state.menu = names[0];
  const keys = names.map((name) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "key"; b.textContent = name; b.role = "tab";
    b.setAttribute("aria-selected", String(name === state.menu));
    b.onclick = () => { state.menu = name; store.set("menu", name); renderMenus(); };
    return b;
  });
  const divider = document.createElement("hr"); divider.className = "menu-divider";
  keys.splice(names.indexOf("Scale"), 0, divider);  // measurement settings above, display below
  $("menus").replaceChildren(...keys);
  renderMenuBody();
}

function renderMenuBody() {
  const body = $("menu-body");
  if (state.menu === "Marker") body.replaceChildren(...markerMenu());
  else if (state.menu === "Scale") body.replaceChildren(...scaleMenu());
  else {
    const saved = store.get(paramsKey(), {});
    // shown_when: {field: value} or {field: [values]}
    const applies = (p) => Object.entries(p.shown_when ?? {}).every(([key, value]) =>
      [value].flat().includes(paramValue(key, state.schema.properties[key], saved).value));
    const fields = Object.entries(state.schema.properties).filter(([, p]) => p.group === state.menu && applies(p));
    body.replaceChildren(...fields.map(([key, p]) => paramField(key, p)));
    if (state.menu === "Output" && state.measurements[state.measurement].sequence) body.append(...sequenceKeys());
    updateDriveHints();
  }
  applyControl();
}

// Under each gain field, its drive power at the DAC from the board calibration (server: /api/drive-power).
let driveHintsPending;
function updateDriveHints() {
  clearTimeout(driveHintsPending);
  driveHintsPending = setTimeout(async () => {
    if (!$("chip").value) return;
    const hints = await api("POST", "/api/drive-power",
      { measurement: state.measurement, chip: $("chip").value, params: collectParams() }).catch(() => ({}));
    for (const el of document.querySelectorAll("#menu-body [data-drive]")) el.textContent = hints[el.dataset.drive] ?? "";
  }, 150);
}

// Values typed by the user, per measurement and chip.
const paramsKey = (measurement = state.measurement) => `params.${measurement}.${$("chip").value}`;

// What a field holds: what the user typed, else the chip parameter it starts from, else its default.
function paramValue(key, p, saved = store.get(paramsKey(), {})) {
  if (saved[key] !== undefined) return { value: saved[key], fromChip: false };
  const chipValue = p.from_chip ? state.parameters[p.from_chip] : undefined;
  if (chipValue !== undefined) return { value: chipValue, fromChip: true };
  return { value: p.default, fromChip: false };
}

function paramField(key, p) {
  let input;
  if (p.enum) {
    input = document.createElement("select");
    const label = (v) => ({ cw: "CW" })[v] ?? v[0].toUpperCase() + v.slice(1);
    input.append(...p.enum.map((v) => new Option(label(v), v)));
  } else {
    input = document.createElement("input");
    input.type = "number"; input.inputMode = "decimal";
    input.step = p.type === "integer" ? "1" : "any";
    if (p.minimum !== undefined) input.min = p.minimum;
    if (p.maximum !== undefined) input.max = p.maximum;
  }
  input.name = key;
  const { value, fromChip } = paramValue(key, p);
  input.value = typeof value === "number" ? +value.toFixed(6) : value ?? "";
  input.dataset.param = "1";
  input.onchange = () => {
    const params = store.get(paramsKey(), {});
    params[key] = input.value === "" ? undefined : p.enum ? input.value : Number(input.value);
    store.set(paramsKey(), params);
    if (p.enum) renderMenuBody();  // a mode change shows that mode's fields
    if (state.tone?.mode === "sequence") playSequence();  // a playing sequence follows every edit
    updateDriveHints();
  };
  const box = field(p.title, input, p.unit, fromChip ? "From the chip parameters." : p.description);
  const drive = document.createElement("span"); drive.className = "hint drive"; drive.dataset.drive = key;
  box.append(drive);
  return box;
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
  const main = () => state.data?.traces[plotDefs()[0].traces[0]];
  const nodes = [
    button("Marker → Min", () => setMarker(argMin(main()))),
    button("Marker → Max", () => setMarker(argMax(main()))),
    button("Marker off", () => setMarker(null)),
  ];
  for (const [name, value] of Object.entries(state.data?.info ?? {})) {
    const target = state.measurements[state.data.measurement]?.info_sets?.[name];
    if (!target) continue;
    const keep = button(`Store ${name} (${+value.toPrecision(4)})`, () => saveParameters({ [target]: value }));
    keep.dataset.control = "1";
    nodes.push(keep);
  }
  const shown = state.measurements[state.data?.measurement], setupSets = shown?.setup_sets ?? {};
  const results = Object.entries(setupSets).filter(([name]) => state.data?.info?.[name] !== undefined);
  if (results.length) {
    const keep = button(`Store in setup: ${shown.setup_label}`, () => saveSetup(state.data.chip,
      Object.fromEntries(results.map(([name, key]) => [key, +state.data.info[name].toPrecision(6)]))));
    keep.dataset.control = "1";
    nodes.push(keep);
  }
  const target = state.measurements[state.data?.measurement ?? state.measurement]?.marker_sets;
  if (target) {
    const label = PARAMETER_LABELS[target]?.[0] ?? target;
    const keep = button(`Marker → ${label}`, () => {
      if (state.marker === null) return message("Place the marker first.", true);
      saveParameters({ [target]: state.data.x[state.marker] });
    });
    keep.dataset.control = "1";
    nodes.push(keep, hint(`Click on a trace to place the marker. ${label} is stored in the chip parameters.`));
  }
  return nodes;
}

// ---- Scale: like the PNA-X Scale hardkey. Display only, so per browser, per measurement and window. ----
// Manual: Scale per division, Reference level, and the division it sits on (Reference position, 0 = bottom).
const scaleKey = (k) => {
  const def = plotDefs()[k];  // a view other than the window's first keeps its own scale
  return `scale.${state.data?.measurement ?? state.measurement}.${def?.unit ?? ""}.${k}${def?.view ? `.v${def.view}` : ""}`;
};
const scaleOf = (k) => store.get(scaleKey(k), { auto: true });

function yRange(k, min, max) {
  const s = scaleOf(k);
  return s.auto ? tenDivisionRange(min, max) : [s.ref - s.pos * s.perDiv, s.ref + (10 - s.pos) * s.perDiv];
}

// Where the autoscale would put the data, as manual settings with the reference in the middle (PNA default).
function fittedScale(k) {
  const vals = (plots[k]?.data ?? []).slice(1).flat().filter(Number.isFinite);
  if (!vals.length) return { auto: false, perDiv: 1, ref: 0, pos: 5 };
  const [lo, hi] = tenDivisionRange(vals.reduce((a, b) => Math.min(a, b)), vals.reduce((a, b) => Math.max(a, b)));
  return { auto: false, perDiv: (hi - lo) / 10, ref: lo + 5 * (hi - lo) / 10, pos: 5 };
}

function setScale(k, s) {
  store.set(scaleKey(k), s);
  if (plots[k]) plots[k].setData(plots[k].data);  // recomputes the y range
  traceLines();
}

// Horizontal scale, for measurements that offer one (the Oscilloscope): like a scope's time/div and position.
// Display only, per browser and measurement; Autoscale shows the whole record.
const xScaleKey = () => `xscale.${state.data?.measurement ?? state.measurement}`;
const xScaleOf = () => store.get(xScaleKey(), { auto: true });
const hasXScale = () => !!state.measurements[state.data?.measurement ?? state.measurement]?.x_scale;

function xRange(min, max) {
  const s = xScaleOf();
  return !hasXScale() || s.auto ? [min, max] : [s.centre - 5 * s.perDiv, s.centre + 5 * s.perDiv];
}

function setXScale(s) {
  store.set(xScaleKey(), s);
  for (const k of [0, 1]) if (plots[k]?.data) plots[k].setData(plots[k].data);  // recomputes the x range
  traceLines();
}

function horizontalMenu() {
  if (!hasXScale()) return [];
  const s = xScaleOf(), title = document.createElement("h3"), unit = xUnit();
  title.className = "subhead"; title.textContent = "Horizontal";
  const mode = document.createElement("select");
  mode.append(new Option("On (whole record)", "auto"), new Option("Off (fixed)", "fixed"));
  mode.value = s.auto ? "auto" : "fixed";
  mode.onchange = () => {
    const x = state.data?.x ?? [0, 1], lo = x[0], hi = x[x.length - 1];
    setXScale(mode.value === "auto" ? { ...s, auto: true } : { auto: false, perDiv: (hi - lo) / 10, centre: (lo + hi) / 2 });
    renderMenuBody();
  };
  const number = (key, check) => {
    const input = document.createElement("input");
    input.type = "number"; input.inputMode = "decimal"; input.step = "any"; input.disabled = s.auto;
    input.value = s[key] === undefined ? "" : +(+s[key]).toPrecision(6);
    input.onchange = () => {
      const v = Number(input.value);
      if (input.value === "" || !check(v)) { input.value = +(+s[key]).toPrecision(6); return; }
      setXScale({ ...xScaleOf(), [key]: v });
    };
    return input;
  };
  return [title, field("Autoscale", mode),
    field("Time per division", number("perDiv", (v) => v > 0), `${unit}/div`),
    field("Centre", number("centre", Number.isFinite), unit, "The time at the middle of the screen.")];
}

function scaleMenu() {
  const units = document.createElement("select");
  units.append(new Option("Relative (dB, a.u.)", "relative"), new Option("Absolute at the ADC (dBm, mV)", "absolute"));
  units.value = store.get("units", "relative");
  units.onchange = () => setUnits(units.value);
  const head = [field("Units", units, null,
    "Absolute: power at the ADC input, from the calibration the chip's Setup picks for it (dBFS and % of full " +
    "scale with no calibration). Phase is unchanged."),
    ...horizontalMenu()];
  return [...head, ...plotDefs().flatMap((def, k) => {
    const s = scaleOf(k), title = document.createElement("h3");
    title.className = "subhead"; title.textContent = `Tr${k + 1} ${def.title}`;
    const views = windowViews(k), show = [];
    if (views) {
      const pick = document.createElement("select");
      views.forEach((v, i) => pick.append(new Option(v.title, i)));
      pick.value = def.view ?? 0;
      pick.onchange = () => setView(k, Number(pick.value));
      show.push(field("Show", pick));
    }
    if (def.iq) return [title, ...show, hint("Q against I, one point per sweep step, with the fit along the "
      + "direction the points move. Autoscaled, with the same scale on I and Q.")];
    const mode = document.createElement("select");
    mode.append(new Option("On", "auto"), new Option("Off (fixed)", "fixed"));
    mode.value = s.auto ? "auto" : "fixed";
    mode.onchange = () => { setScale(k, mode.value === "auto" ? { ...s, auto: true } : fittedScale(k)); renderMenuBody(); };
    const number = (key, check) => {
      const input = document.createElement("input");
      input.type = "number"; input.inputMode = "decimal"; input.step = "any"; input.disabled = s.auto;
      input.value = s[key] === undefined ? "" : +(+s[key]).toPrecision(6);
      input.onchange = () => {
        const v = Number(input.value);
        if (input.value === "" || !check(v)) { input.value = +(+s[key]).toPrecision(6); return; }
        setScale(k, { ...scaleOf(k), [key]: v });  // fresh: other fields may have changed since
      };
      return input;
    };
    return [title, ...show, field("Autoscale", mode),
      field("Scale", number("perDiv", (v) => v > 0), `${def.unit}/div`),
      field("Reference level", number("ref", Number.isFinite), def.unit, "Value at the reference line (▶)."),
      field("Reference position", number("pos", (v) => v >= 0 && v <= 10), "div", "0 = bottom, 10 = top."),
      button("Autoscale once", () => { setScale(k, fittedScale(k)); renderMenuBody(); })];
  })];
}

// Overwrite some fields of a chip's setup profile, e.g. with a calibration result.
async function saveSetup(chip, changes) {
  try {
    await api("PUT", `/api/profiles/${encodeURIComponent(chip)}`, { ...state.profiles[chip], ...changes });
    await loadProfiles($("chip").value);
    message(`Stored in the setup of ${chip}.`);
  } catch (e) { message(e.message, true); }
}

const PARAMETER_LABELS = {
  readout_freq_mhz: ["Readout frequency", formatFreq], readout_gain: ["Readout gain", String],
  qubit_freq_mhz: ["Qubit frequency", formatFreq], qubit_gain: ["Qubit gain", String],
  pi_gain: ["π-pulse gain", String], pi_sigma_us: ["π-pulse σ", (v) => `${v} µs`],
};

function parameterList() {
  const box = document.createElement("dl"); box.className = "parameters";
  const entries = Object.entries(state.parameters);
  if (!entries.length) { box.append(hint("No chip parameters yet. They are filled from measurement results.")); }
  for (const [key, value] of entries) {
    const [label, fmt] = PARAMETER_LABELS[key] || [key, String];
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = fmt(value);
    box.append(dt, dd);
  }
  return box;
}

async function loadParameters() {
  const chip = $("chip").value;
  state.parameters = chip ? await api("GET", `/api/parameters/${encodeURIComponent(chip)}`).catch(() => ({})) : {};
}

async function saveParameters(changes) {
  try {
    state.parameters = await api("PATCH", `/api/parameters/${encodeURIComponent($("chip").value)}`, changes);
    // a new chip parameter replaces what was typed into the fields that start from it
    for (const [key, m] of Object.entries(state.measurements)) {
      const saved = store.get(paramsKey(key), {});
      for (const [name, p] of Object.entries(m.params.properties)) if (p.from_chip in changes) delete saved[name];
      store.set(paramsKey(key), saved);
    }
    message("Saved to the chip parameters.");
  } catch (e) { message(e.message, true); }
}

function hint(text) {
  const p = document.createElement("p"); p.className = "hint"; p.textContent = text; p.style.margin = "0";
  return p;
}

// ---- setup profiles ------------------------------------------------------
// [key, title, kind, unit, hint, shown only for this output path, or in the "I/Q cal" menu]
const PROFILE_FIELDS = [
  ["chip", "Chip name", "text"],
  ["lo_mhz", "LO frequency", "number", "MHz", "Leave empty when there is no mixer (RF = IF)."],
  ["lo_power_dbm", "LO power", "number", "dBm", "Set on the LO when the app controls it (started with --lo). The MMIQ wants 7–16 dBm, 13 nominal; at most 16 dBm.", "lo"],
  ["sideband", "Sideband", ["upper", "lower"], null, "Upper: RF = LO + IF. Lower: RF = LO − IF.", "lo"],
  ["output_path", "Output path", ["real", "iq"], null, "I/Q: the tone goes out on two DACs into an I/Q mixer."],
  ["readout_dac", "Readout output", ["DAC_A", "DAC_B"], null, null, "real"],
  ["i_dac", "I output", ["DAC_A", "DAC_B"], null, null, "iq"],
  ["q_dac", "Q output", ["DAC_A", "DAC_B"], null, null, "iq"],
  ["iq_phase_deg", "Q phase offset", "number", "°", "90 for an ideal mixer.", "I/Q cal"],
  ["iq_gain_ratio", "Q / I gain", "number", null, "1 for an ideal mixer.", "I/Q cal"],
  ["iq_delay_ps", "Q delay", "number", "ps",
    "How far the Q DAC runs ahead of the I DAC. It changes at every power-up of the board: Measure it with both DACs cabled to the oscilloscope (equal cables).", "I/Q cal"],
  ["electrical_delay_ns", "Electrical delay", "number", "ns",
    "Subtracted from the resonator sweep's phase. Empty: fitted on each sweep. Store it from a wide sweep (Marker menu)."],
  ["time_of_flight_us", "Time of flight", "number", "µs",
    "From the trigger to when the signal reaches the ADC; the readout window opens this late. Measure sends a test pulse and finds it."],
  ["control_dac", "Control line", ["", "DAC_A", "DAC_B"], null,
    "A DAC of its own for the qubit tone, with no mixer: the qubit frequency is the DAC frequency."],
  ["return_path", "Return path", ["real", "iq"], null, "I/Q: an I/Q mixer into two ADCs, combined in software."],
  ["readout_adc", "Readout input", ["ADC_B", "ADC_C", "ADC_D"], null, null, "return:real"],
  ["i_adc", "I input", ["ADC_B", "ADC_C", "ADC_D"], null, null, "return:iq"],
  ["q_adc", "Q input", ["ADC_B", "ADC_C", "ADC_D"], null, null, "return:iq"],
  ["rx_gain_ratio", "RX Q / I gain", "number", null, "From the RX I/Q calibration; 1 for an ideal mixer.", "return:iq"],
  ["rx_phase_deg", "RX Q phase", "number", "°", "0 for an ideal mixer.", "return:iq"],
  ["rx_delay_ps", "RX I/Q delay", "number", "ps", "About 48 ps per cm of I/Q cable difference.", "return:iq"],
];
const NUMBER_FIELDS = ["lo_power_dbm", "time_of_flight_us", "iq_phase_deg", "iq_gain_ratio", "iq_delay_ps", "rx_gain_ratio", "rx_phase_deg", "rx_delay_ps"];

const NEW_PROFILE = { chip: "", lo_mhz: null, lo_power_dbm: 13, sideband: "upper", output_path: "real",
  readout_dac: "DAC_B", i_dac: "DAC_A", q_dac: "DAC_B", iq_phase_deg: 90, iq_gain_ratio: 1, iq_delay_ps: 0, readout_adc: "ADC_D",
  electrical_delay_ns: null, time_of_flight_us: 0.3, control_dac: null, return_path: "real", i_adc: "ADC_D", q_adc: "ADC_C", rx_gain_ratio: 1, rx_phase_deg: 0, rx_delay_ps: 0, calibrations: {} };

// ---- the chip's setup: a panel over the screen, apart from the measurement's menus ----
function renderSetupPanel() {
  const open = !!state.setupOpen, chip = $("chip").value;
  $("setup-panel").hidden = !open;
  $("setup-key").setAttribute("aria-expanded", String(open));
  if (!open) { applyControl(); return; }
  const iq = state.profiles[chip]?.output_path === "iq";
  const tabs = ["Setup", ...(iq ? ["I/Q cal"] : []), "Board"];
  if (!tabs.includes(state.setupTab)) state.setupTab = "Setup";
  $("setup-title").textContent = state.setupTab === "Board" ? "Board calibration tables (every chip)"
    : chip ? `Setup of ${chip}` : "New chip";
  $("setup-tabs").replaceChildren(...(tabs.length > 1 ? tabs : []).map((name) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "key"; b.textContent = name; b.role = "tab";
    b.setAttribute("aria-selected", String(name === state.setupTab));
    b.onclick = () => { state.setupTab = name; renderSetupPanel(); };
    return b;
  }));
  $("setup-body").replaceChildren(...(state.setupTab === "Board" ? boardMenu() : setupMenu(state.setupTab)));
  applyControl();
}

// ---- the board's power calibration: shared by every chip (profiles/board/calibration.json, see power.py) ----
async function loadBoard() {
  state.board = await api("GET", "/api/board").catch(() => null);
  state.instruments = await api("GET", "/api/instruments").catch(() => ({ analyzer: null, lo: false }));
}

const pointsText = (table) => table.points.map(([f, dbm]) => `${f} ${dbm}`).join("\n");
function parsePoints(text) {
  const points = text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split(/[\s,;]+/).map(Number));
  if (!points.length || points.some((p) => p.length !== 2 || p.some((v) => !Number.isFinite(v))))
    throw new Error("Each line needs a frequency in MHz and a power in dBm, e.g. 550 -1.0");
  return points.sort((a, b) => a[0] - b[0]);
}

const PORTS = { dac: ["DAC_A", "DAC_B"], adc: ["ADC_B", "ADC_C", "ADC_D"] };
const DATASHEET = "data sheet", UNCALIBRATED = "none";

// The Setup tab's "Power calibration": the board table each port uses. "" (left out of the setup) is the newest.
function calibrationChoices(chosen) {
  const selects = {};
  const rows = [...PORTS.dac, ...PORTS.adc].map((port) => {
    const tables = state.board?.[port.startsWith("DAC") ? "dac" : "adc"][port] ?? [];
    const c = document.createElement("select"); c.dataset.control = "1";
    const newest = tables.length ? tables[tables.length - 1].source : "data sheet";
    c.append(new Option(`Newest (${newest})`, ""), new Option("Data sheet", DATASHEET),
      ...tables.slice().reverse().map((t) => new Option(t.source, t.source)), new Option("None (dBFS)", UNCALIBRATED));
    const value = chosen[port] ?? "";
    if (![...c.options].some((o) => o.value === value)) c.append(new Option(`${value} (deleted)`, value));
    c.value = value;
    selects[port] = c;
    return field(port, c);
  });
  const title = document.createElement("h3"); title.className = "subhead"; title.textContent = "Power calibration";
  const box = document.createElement("div"); box.className = "setup-fields"; box.append(...rows);
  return {
    nodes: [title, box, hint("The board calibration table each port uses for dBm and mV (Board tab). " +
      "None: powers relative to the converter's full scale (dBFS, % FS).")],
    value: () => Object.fromEntries(Object.entries(selects).filter(([, c]) => c.value).map(([p, c]) => [p, c.value])),
  };
}

// A measured table is selected in the chip's setup on arrival (Newest already follows it).
async function selectNewTable(added) {
  const chip = $("chip").value;
  if (!chip || !state.profiles[chip] || !added) return;
  const calibrations = { ...(state.profiles[chip].calibrations ?? {}) };
  if (!(added.port in calibrations)) return;
  calibrations[added.port] = added.name;
  await saveSetup(chip, { calibrations });
}

function boardMenu() {
  if (!state.board) return [hint("The board calibration could not be loaded.")];
  const heading = (text) => { const h = document.createElement("h3"); h.className = "subhead"; h.textContent = text; return h; };
  const setup = state.profiles[$("chip").value] ?? NEW_PROFILE;
  const select = (options, value) => {
    const c = document.createElement("select"); c.append(...options.map((o) => new Option(o, o)));
    c.value = value; c.dataset.control = "1"; return c;
  };
  const put = async (next, done) => {
    try {
      state.board = await api("PUT", "/api/board", next);
      renderSetupPanel(); updateDriveHints(); message(done);
    } catch (e) { message(e.message, true); }
  };
  // one box per port: its tables, newest first; the data sheet's is built in and read-only
  const portBox = (kind, port, label) => {
    const tables = state.board[kind][port];
    const pick = document.createElement("select"); pick.dataset.control = "1";
    pick.append(...tables.map((t, i) => new Option(t.source, i)).reverse(), new Option("Data sheet", "datasheet"),
      new Option("New table (type it in)", "new"));
    const area = document.createElement("textarea");
    area.rows = 5; area.spellcheck = false; area.dataset.control = "1";
    const name = document.createElement("input"); name.type = "text"; name.dataset.control = "1";
    const save = button("Save table", async () => {
      let points;
      try { points = parsePoints(area.value); } catch (e) { message(e.message, true); return; }
      const next = structuredClone(state.board), list = next[kind][port];
      const entry = { points, source: name.value.trim() || `entered by hand, ${new Date().toISOString().slice(0, 10)}` };
      if (pick.value === "new" || pick.value === "datasheet") list.push(entry); else list[Number(pick.value)] = entry;
      await put(next, `Saved ${port}'s table “${entry.source}”.`);
    });
    const remove = button("Delete", async () => {
      const t = tables[Number(pick.value)];
      if (!confirm(`Delete ${port}'s table “${t.source}”? Chips that use it must pick another.`)) return;
      const next = structuredClone(state.board);
      next[kind][port].splice(Number(pick.value), 1);
      await put(next, `Deleted ${port}'s table “${t.source}”.`);
    }, "key-danger");
    save.dataset.control = remove.dataset.control = "1";
    const show = () => {
      const i = pick.value, builtIn = i === "datasheet";
      area.value = i === "new" ? "" : pointsText(builtIn ? { points: state.board.datasheet[kind] } : tables[Number(i)]);
      name.value = i === "new" || builtIn ? "" : tables[Number(i)].source;
      name.placeholder = builtIn ? "a new table's name" : "entered by hand";
      remove.hidden = i === "new" || builtIn;
    };
    pick.onchange = show; show();
    const keys = document.createElement("div"); keys.className = "setup-keys"; keys.append(save, remove);
    const box = document.createElement("div"); box.className = "board-table";
    box.append(field(label, pick), field("Points", area, "MHz dBm"), field("Name", name), keys);
    return box;
  };
  const dac = select(PORTS.dac, setup.readout_dac ?? "DAC_B");
  const adc = select(PORTS.adc, setup.readout_adc ?? "ADC_D");
  const loopback = button("Calibrate ADC from loopback", async () => {
    loopback.disabled = true; message("Measuring the loopback…");
    try {
      const calibrations = (state.profiles[$("chip").value] ?? NEW_PROFILE).calibrations ?? {};
      state.board = await api("POST", "/api/board/adc-from-loopback", { dac: dac.value, adc: adc.value, calibrations });
      await selectNewTable(state.board.added);
      renderSetupPanel();
      message(`${adc.value} calibrated from ${dac.value}: added as “${state.board.added.name}”.`);
    } catch (e) { message(e.message, true); }
    finally { loopback.disabled = false; applyControl(); }
  });
  loopback.dataset.control = "1";
  // a DAC's table measured on the signal analyzer (only when the app was started with --analyzer)
  const analyzer = state.instruments?.analyzer;
  const calDac = select(PORTS.dac, setup.control_dac || setup.i_dac || "DAC_A");
  const loss = document.createElement("input");
  loss.type = "number"; loss.step = "0.1"; loss.min = "0"; loss.max = "20"; loss.value = "0.5"; loss.dataset.control = "1";
  const measureDac = button("Calibrate DAC with analyzer", async () => {
    measureDac.disabled = true; message(`Measuring ${calDac.value} on the ${analyzer}, every 50 MHz (about a minute)…`);
    try {
      state.board = await api("POST", "/api/board/dac-from-analyzer", { dac: calDac.value, cable_loss_db: Number(loss.value) });
      await selectNewTable(state.board.added);
      renderSetupPanel();
      updateDriveHints();
      message(`${calDac.value} calibrated on the ${analyzer}: added as “${state.board.added.name}”.`);
    } catch (e) { message(e.message, true); }
    finally { measureDac.disabled = false; applyControl(); }
  });
  measureDac.dataset.control = "1";
  const fields = document.createElement("div"); fields.className = "setup-fields";
  fields.append(...PORTS.dac.map((p) => portBox("dac", p, `${p} output at gain 1`)),
    ...PORTS.adc.map((p) => portBox("adc", p, `${p} full scale`)));
  const loop = document.createElement("div"); loop.className = "setup-fields";
  loop.append(field("From DAC", dac), field("To ADC", adc));
  const keys = document.createElement("div"); keys.className = "setup-keys"; keys.append(loopback);
  const analyzerPart = [];
  if (analyzer) {
    const row = document.createElement("div"); row.className = "setup-fields";
    row.append(field("DAC", calDac), field("Cable loss", loss, "dB"));
    const k = document.createElement("div"); k.className = "setup-keys"; k.append(measureDac);
    analyzerPart.push(heading(`Signal analyzer (${analyzer})`), row, k,
      hint("Cable the DAC to the analyzer's RF input. The app plays a full-scale tone every 50 MHz from 50 to " +
        "4900 MHz, reads each peak, adds the cable loss and adds the result as a new table."));
  }
  return [fields, ...analyzerPart, heading("Loopback"), loop, keys,
    hint("Every port keeps all its tables: powers at the board's SMA connectors, 50 Ω, against frequency (MHz, dBm " +
      "per line). DAC: output at gain 1 (flat pulse). ADC: the input that reads full scale. The data sheet's are " +
      "built in. A new measurement is added, never replacing one; each chip's Setup picks the table every port " +
      "uses. Calibrate ADC from loopback needs a short cable from the DAC to the ADC: it trusts the DAC's table " +
      "this chip uses and measures the ADC's.")];
}

function toggleSetup(open = !state.setupOpen) {
  if (open && state.helpOpen) toggleHelp(false);
  state.setupOpen = open;
  renderSetupPanel();
  if (open) $("setup-body").querySelector("input, select")?.focus();
  else $("setup-key").focus();
}

// ---- help: static text in index.html ----
function toggleHelp(open = !state.helpOpen) {
  if (open && state.setupOpen) toggleSetup(false);
  state.helpOpen = open;
  $("help-panel").hidden = !open;
  $("help-key").setAttribute("aria-expanded", String(open));
  if (open) $("help-close").focus();
  else $("help-key").focus();
}

async function deleteChip(chip) {
  if (!confirm(`Delete chip "${chip}"? Its setup and chip parameters are removed. Saved runs stay in data/.`)) return;
  try {
    await api("DELETE", `/api/profiles/${encodeURIComponent(chip)}`);
    for (const key of Object.keys(state.measurements)) store.remove(`params.${key}.${chip}`);
    store.remove("chip");
    await loadProfiles();
    message(`Deleted chip ${chip}.`);
  } catch (e) { message(e.message, true); }
}

// The Setup and I/Q cal tabs edit the same profile; each shows its own fields and saves all of them.
function setupMenu(menu) {
  const current = { ...NEW_PROFILE, ...(state.profiles[$("chip").value] || {}) };
  const controls = {}, rows = {};
  const nodes = PROFILE_FIELDS.map(([key, title, kind, unit, help, onlyFor]) => {
    let c;
    if (Array.isArray(kind)) {
      c = document.createElement("select");
      c.append(...kind.map((v) => new Option(v === "iq" ? "I/Q" : v === "" ? "None" : v, v)));
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
  // onlyFor: "I/Q cal" (that menu only), "real"/"iq" (output path), "return:real"/"return:iq" (return path),
  // "lo" (only with an LO frequency)
  const shown = (only) => {
    if (menu === "I/Q cal") return only === "I/Q cal";
    if (!only) return true;
    if (only === "lo") return controls.lo_mhz.value !== "";
    if (only.startsWith("return:")) return only.slice(7) === controls.return_path.value;
    return only === controls.output_path.value;
  };
  const showFields = () => { for (const row of Object.values(rows)) row.hidden = !shown(row.dataset.onlyFor); };
  controls.output_path.onchange = showFields;
  controls.lo_mhz.oninput = showFields;
  controls.return_path.onchange = showFields;
  showFields();
  controls.iq_phase_deg.step = "0.1";
  controls.iq_gain_ratio.step = "0.005";
  const extra = menu === "I/Q cal" ? [toneBlock(controls)] : [];
  const choices = menu === "Setup" ? calibrationChoices(current.calibrations ?? {}) : null;

  const formProfile = () => {
    const profile = Object.fromEntries(Object.entries(controls).map(([k, c]) => [k, c.value]));
    profile.calibrations = choices ? choices.value() : (current.calibrations ?? {});
    profile.lo_mhz = profile.lo_mhz === "" ? null : Number(profile.lo_mhz);
    profile.control_dac = profile.control_dac || null;
    profile.electrical_delay_ns = profile.electrical_delay_ns === "" ? null : Number(profile.electrical_delay_ns);
    for (const k of NUMBER_FIELDS) profile[k] = Number(profile[k]);
    return profile;
  };
  // Measure keys: a value of the setup as edited, measured on the board; it waits in the field for Save setup
  const measureKey = (key, path, describe) => {
    const measure = button("Measure", async () => {
      measure.disabled = true;
      message("Measuring…");
      try {
        const result = await api("POST", path, formProfile());
        controls[key].value = result[key];
        message(`${describe(result)} Press Save setup to keep it.`);
      } catch (e) { message(e.message, true); }
      finally { measure.disabled = false; applyControl(); }
    });
    measure.dataset.control = "1";
    rows[key].querySelector(".input-row").append(measure);
  };
  measureKey("time_of_flight_us", "/api/time-of-flight", (r) => `Time of flight measured: ${r.time_of_flight_us} µs.`);
  measureKey("iq_delay_ps", "/api/iq-delay", (r) =>
    `Q delay measured: ${r.iq_delay_ps} ps (I on ${r.i_channel}, Q on ${r.q_channel}).`);

  const save = button("Save setup", async () => {
    const profile = formProfile();
    try {
      await api("PUT", `/api/profiles/${encodeURIComponent(profile.chip)}`, profile);
      await loadProfiles(profile.chip);
      message(`Saved setup for ${profile.chip}.`);
    } catch (e) { message(e.message, true); }
  }, "key-strong");
  save.dataset.control = "1";
  const help = menu === "I/Q cal"
    ? "Play a tone, watch the image on a spectrum analyzer, adjust until it is smallest, then save."
    : "Shared by every measurement on this chip. Change the chip name to save a new chip.";
  const chip = $("chip").value;
  const keys = document.createElement("div"); keys.className = "setup-keys"; keys.append(save);
  if (chip && menu === "Setup") {
    const remove = button("Delete chip", () => deleteChip(chip), "key-danger");
    remove.dataset.control = "1";
    keys.append(remove);
  }
  const fields = document.createElement("div"); fields.className = "setup-fields"; fields.append(...nodes, ...extra);
  const footer = [keys, hint(help)];
  if (menu === "Setup") {
    const title = document.createElement("h3"); title.className = "subhead"; title.textContent = "Chip parameters";
    footer.push(title, parameterList());
  }
  return [fields, ...(choices ? choices.nodes : []), ...footer];
}

// The Output menu of a pulsed measurement: its own shot at one point, repeated for an oscilloscope.
function sequenceKeys() {
  const play = button("Play sequence", playSequence, "key-strong"); play.dataset.control = "1";
  const off = button("Off", () => {
    clearTimeout(sequencePending);  // an edit committed by this click must not restart it
    api("POST", "/api/tone/off").catch((e) => message(e.message, true));
  });
  off.dataset.control = "1";
  const keys = document.createElement("div"); keys.className = "run-keys"; keys.append(play, off);
  return [keys, hint("Plays this measurement's shot (qubit pulse, then readout pulse) at the value above, " +
    "with the settings of the other menus, until Off. PMOD0_0 is high while the qubit pulse plays: " +
    "trigger the oscilloscope on it.")];
}

let sequencePending;
function playSequence() {
  clearTimeout(sequencePending);
  sequencePending = setTimeout(async () => {
    try {
      await api("POST", "/api/sequence", { measurement: state.measurement, chip: $("chip").value, params: collectParams() });
      message("Sequence playing. Off or starting a run stops it.");
    } catch (e) { message(e.message, true); }
  }, 120);
}

// The I/Q calibration tone: continuous, on the chip's output path. While it plays, every edit is sent
// at once, including the Q phase offset and gain being tuned (`calibration`: the I/Q cal tab's controls).
function toneBlock(calibration) {
  const box = document.createElement("fieldset");
  box.className = "tone";
  const legend = document.createElement("legend");
  legend.textContent = "Calibration tone";
  const number = (key, fallback, step) => {
    const c = document.createElement("input"); c.type = "number"; c.step = step; c.inputMode = "decimal";
    c.value = store.get(key, fallback); c.dataset.control = "1"; return c;
  };
  const rf = number("toneRf", "", "any"), gain = number("toneGain", 0.3, "0.05");
  gain.min = 0; gain.max = 1;

  const send = async () => {
    for (const [k, c] of [["toneRf", rf], ["toneGain", gain]]) store.set(k, c.value);
    const body = { chip: $("chip").value, rf_mhz: Number(rf.value), gain: Number(gain.value),
                   iq_phase_deg: Number(calibration.iq_phase_deg.value), iq_gain_ratio: Number(calibration.iq_gain_ratio.value) };
    try {
      await api("POST", "/api/tone", body);
      message("Tone playing. Adjust the Q phase offset and Q / I gain until the image is smallest.");
    } catch (e) { message(e.message, true); }
  };
  const on = button("Tone on", send); on.dataset.control = "1";
  const off = button("Tone off", () => api("POST", "/api/tone/off").catch((e) => message(e.message, true)));
  off.dataset.control = "1";
  const keys = document.createElement("div"); keys.className = "run-keys"; keys.append(on, off);

  let pending;
  const live = () => { if (state.tone?.rf_mhz !== undefined) { clearTimeout(pending); pending = setTimeout(send, 120); } };
  for (const c of [rf, gain, calibration.iq_phase_deg, calibration.iq_gain_ratio]) c.addEventListener("input", live);

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
  await loadParameters();
  renderMenus();
  if (!chips.length) state.setupOpen = true;
  renderSetupPanel();
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
  led.textContent = state.running ? "Measuring"
    : state.tone?.mode === "sequence" ? `Sequence (${state.tone.measurement})`
    : state.tone ? `Tone ${formatFreq(state.tone.rf_mhz)}` : "Hold";
  led.classList.toggle("on", state.running || !!state.tone);
  const lo = $("st-lo");  // what the LO read back the last time the app set it
  lo.hidden = !state.lo;
  if (state.lo) lo.textContent = `LO ${formatFreq(state.lo.freq_mhz)} ${state.lo.power_dbm} dBm${state.lo.on ? "" : " (RF off)"}`;
}

function collectParams() {
  const saved = store.get(paramsKey(), {}), params = {};
  for (const [key, p] of Object.entries(state.schema.properties)) {
    const { value } = paramValue(key, p, saved);
    if (value !== undefined && value !== null && value !== "") params[key] = p.enum ? value : Number(value);
  }
  return params;
}

async function run() {
  try {
    message("");
    await api("POST", "/api/runs", { measurement: state.measurement, chip: $("chip").value, params: collectParams() });
  } catch (e) { message(e.message, true); }
}

// ---- plots ----------------------------------------------------------------
const plots = {};

const COLORS = () => {
  const css = getComputedStyle(document.documentElement);
  return [css.getPropertyValue("--tr1").trim(), css.getPropertyValue("--tr2").trim()];
};

// Units (Scale menu): relative (dB, a.u.) or absolute at the ADC (dBm, mV), from the board calibration.
// A plot shows its absolute version when it has one and the data carries those traces (older runs may not).
// Views (Scale → Show): a window may offer other traces, e.g. Rabi's raw I, Q, |S21| or the I/Q plane.
function plotDefs(measurement = state.data?.measurement ?? state.measurement) {
  const has = (d) => !state.data || d.traces.every((t) => t in (state.data.traces ?? {}));
  const defs = state.measurements[measurement].plots.map((d, k) => {
    if (!d.views) return d;
    const i = store.get(`view.${measurement}.${k}`, 0);
    return d.views[i] && has(d.views[i]) ? { ...d.views[i], view: i } : { ...d.views[0], view: 0 };
  });
  if (store.get("units", "relative") !== "absolute") return defs;
  const units = absoluteUnits();
  return defs.map((d) => (d.absolute && has(d.absolute)
    ? { ...d.absolute, unit: units[d.absolute.unit] ?? d.absolute.unit, view: d.view } : d));
}

// The absolute traces' units: a run says them; before one, the chip's setup decides (its input with no
// calibration: dBFS and % of full scale instead of dBm and mV).
function absoluteUnits() {
  if (state.data) return state.data.units ?? { dBm: "dBm", mV: "mV" };
  const p = state.profiles[$("chip").value] ?? NEW_PROFILE;
  const adc = p.return_path === "iq" ? p.i_adc : p.readout_adc;
  return p.calibrations?.[adc] === "none" ? { dBm: "dBFS", mV: "% FS" } : { dBm: "dBm", mV: "mV" };
}

const windowViews = (k) => state.measurements[state.data?.measurement ?? state.measurement].plots[k]?.views;

function setView(k, i) {
  store.set(`view.${state.data?.measurement ?? state.measurement}.${k}`, i);
  state.plotsFor = null;  // rebuild: the trace count, and for the I/Q plane the plot kind, change
  if (state.data) showUpdate(state.data); else { buildPlots(state.measurement); traceLines(); }
  renderMenuBody();
}

function setUnits(units) {
  store.set("units", units);
  state.plotsFor = null;  // rebuild the plots with the other traces
  if (state.data) showUpdate(state.data); else traceLines();
  renderMenuBody();
}

// Rebuild both plot windows for a measurement's layout (trace count and names differ).
function buildPlots(measurement) {
  if (state.plotsFor === measurement) return;
  state.plotsFor = measurement;
  plotDefs(measurement).forEach((def, k) => {
    const el = $(k === 0 ? "plot-mag" : "plot-phase");
    plots[k]?.destroy();
    plots[k] = def.iq ? new IqPlot(el, COLORS()[k]) : makePlot(el, COLORS()[k], def.traces.length, k);
  });
  plots.mag = plots[0]; plots.phase = plots[1];
}

function makePlot(el, color, nTraces, k) {
  const axis = { stroke: "#9aa1aa", grid: { stroke: "#3b4148", width: 1, dash: [2, 3] },
                 ticks: { show: false }, font: "12px " + getComputedStyle(document.body).fontFamily };
  const tenDivisions = (u, i, min, max) => Array.from({ length: 11 }, (_, k) => min + (k * (max - min)) / 10);
  const opts = {
    width: el.clientWidth, height: el.clientHeight,
    legend: { show: false },
    cursor: { sync: { key: "screen" }, points: { show: false }, drag: { x: false, y: false } },
    scales: { x: { time: false, range: (u, min, max) => xRange(min, max) }, y: { range: (u, min, max) => yRange(k, min, max) } },
    axes: [
      { ...axis, splits: tenDivisions, size: 30, values: (u, vals) => {
          const every = u.width < 500 ? 5 : 2, div = (vals[10] - vals[0]) / 10;
          const ghz = xUnit() === "MHz" && Math.max(...vals.map(Math.abs)) >= 1000;  // one unit for the whole axis
          return vals.map((v, k) => (k % every ? "" : xTick(v, div, ghz)));
        } },
      { ...axis, splits: tenDivisions, size: 56,
        values: (u, vals) => vals.map((v) => minus(v.toFixed(decimalsFor((vals[10] - vals[0]) / 10)))) },
    ],
    series: [{}, { stroke: color, width: 1.5, points: { show: false } },
             ...(nTraces > 1 ? [{ stroke: "#ffffff", width: 1, dash: [6, 4], points: { show: false } }] : [])],
    hooks: { draw: [(u) => drawMarker(u, color), (u) => drawReference(u, k, color)], setScale: [() => traceLines()], ready: [(u) => u.over.addEventListener("click", () => setMarker(u.cursor.idx))] },
  };
  return new uPlot(opts, [[], ...Array.from({ length: nTraces }, () => [])], el);
}

// The I/Q plane: Q against I, one dot per sweep point, the fit as a dashed line. Same scale on both axes,
// so the direction the points move is drawn true. Offers what the page uses of a uPlot plot.
class IqPlot {
  constructor(el, color) {
    this.el = el; this.color = color; this.data = [];
    this.canvas = document.createElement("canvas");
    this.canvas.style.display = "block";
    this.canvas.addEventListener("click", (e) => setMarker(this.nearest(e)));
    el.append(this.canvas);
    this.setSize({ width: el.clientWidth, height: el.clientHeight });
  }
  destroy() { this.canvas.remove(); }
  setSize({ width, height }) {
    this.w = width; this.h = height;
    this.canvas.width = width * devicePixelRatio; this.canvas.height = height * devicePixelRatio;
    this.canvas.style.width = `${width}px`; this.canvas.style.height = `${height}px`;
    this.redraw();
  }
  setData(data) { this.data = data; this.redraw(); }
  // one step for both axes, a square grid; [x0, y0] is the data value at the plot's lower left
  layout() {
    const [, i, q, fi, fq] = this.data, box = { left: 56, top: 4, right: this.w - 8, bottom: this.h - 30 };
    const all = (a, b) => [...(a ?? []), ...(b ?? [])].filter(Number.isFinite);
    const xs = all(i, fi), ys = all(q, fq);
    if (!xs.length || box.right <= box.left || box.bottom <= box.top) return null;
    const lo = (v) => Math.min(...v), hi = (v) => Math.max(...v);
    const bw = box.right - box.left, bh = box.bottom - box.top;
    const span = Math.max((hi(xs) - lo(xs)) / bw, (hi(ys) - lo(ys)) / bh) * 1.1 || 1e-9;  // data per pixel
    const step = niceDiv(span * Math.min(bw, bh));
    const perPx = Math.max(span, step / (Math.min(bw, bh) / 10));
    const cx = (lo(xs) + hi(xs)) / 2, cy = (lo(ys) + hi(ys)) / 2;
    return { box, step, perPx, x0: cx - perPx * bw / 2, y0: cy - perPx * bh / 2 };
  }
  get scales() { const l = this.layout(); return { y: l ? { min: l.y0, max: l.y0 + 10 * l.step } : {} }; }
  get div() { return this.layout()?.step; }
  nearest(e) {
    const l = this.layout(), [, i, q] = this.data;
    if (!l) return null;
    const r = this.canvas.getBoundingClientRect();
    const x = l.x0 + (e.clientX - r.left - l.box.left) * l.perPx, y = l.y0 + (l.box.bottom - (e.clientY - r.top)) * l.perPx;
    return argMin(i.map((v, k) => (v - x) ** 2 + (q[k] - y) ** 2));
  }
  redraw() {
    const ctx = this.canvas.getContext("2d"), d = devicePixelRatio, l = this.layout();
    ctx.setTransform(d, 0, 0, d, 0, 0);
    ctx.clearRect(0, 0, this.w, this.h);
    if (!l) return;
    const { box, step, perPx, x0, y0 } = l, X = (v) => box.left + (v - x0) / perPx, Y = (v) => box.bottom - (v - y0) / perPx;
    const font = "12px " + getComputedStyle(document.body).fontFamily, digits = decimalsFor(step);
    ctx.save();
    ctx.strokeStyle = "#3b4148"; ctx.setLineDash([2, 3]); ctx.lineWidth = 1;
    ctx.fillStyle = "#9aa1aa"; ctx.font = font;
    ctx.beginPath(); ctx.rect(box.left, box.top, box.right - box.left, box.bottom - box.top); ctx.clip();
    for (let v = Math.ceil(x0 / step) * step; X(v) <= box.right; v += step) { ctx.moveTo(X(v), box.top); ctx.lineTo(X(v), box.bottom); }
    for (let v = Math.ceil(y0 / step) * step; Y(v) >= box.top; v += step) { ctx.moveTo(box.left, Y(v)); ctx.lineTo(box.right, Y(v)); }
    ctx.stroke(); ctx.setLineDash([]);
    const [, i, q, fi, fq] = this.data;
    if (fi?.some(Number.isFinite)) {
      ctx.strokeStyle = "#ffffff"; ctx.setLineDash([6, 4]); ctx.beginPath();
      fi.forEach((v, k) => (k ? ctx.lineTo(X(v), Y(fq[k])) : ctx.moveTo(X(v), Y(fq[k]))));
      ctx.stroke(); ctx.setLineDash([]);
    }
    ctx.fillStyle = this.color;
    i.forEach((v, k) => { ctx.beginPath(); ctx.arc(X(v), Y(q[k]), 2.5, 0, 2 * Math.PI); ctx.fill(); });
    if (state.marker !== null && i[state.marker] !== undefined) {
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.beginPath();
      ctx.arc(X(i[state.marker]), Y(q[state.marker]), 6, 0, 2 * Math.PI); ctx.stroke();
    }
    ctx.restore();
    ctx.fillStyle = "#9aa1aa"; ctx.font = font; ctx.textAlign = "center";
    for (let v = Math.ceil(x0 / step) * step, n = 0; X(v) <= box.right; v += step, n++)
      if (n % 2 === 0 && X(v) < box.right - 40) ctx.fillText(minus(v.toFixed(digits)), X(v), box.bottom + 16);  // clear of "I →"
    ctx.textAlign = "right";
    for (let v = Math.ceil(y0 / step) * step, n = 0; Y(v) >= box.top; v += step, n++)
      if (n % 2 === 0) ctx.fillText(minus(v.toFixed(digits)), box.left - 6, Y(v) + 4);
    ctx.textAlign = "left"; ctx.fillText("I →", box.right - 28, box.bottom + 16);
    ctx.save(); ctx.translate(12, box.top + 24); ctx.fillText("Q ↑", 0, 0); ctx.restore();
  }
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

// The PNA-X's reference arrow: ▶ on the left edge at the reference line.
function drawReference(u, k, color) {
  const s = scaleOf(k), y = u.scales.y;
  if (y.min === undefined || y.min === null) return;
  const pos = s.auto ? 5 : s.pos, cy = u.bbox.top + u.bbox.height * (1 - pos / 10), r = 5 * devicePixelRatio;
  const ctx = u.ctx;
  ctx.save();
  ctx.fillStyle = color;
  ctx.beginPath(); ctx.moveTo(u.bbox.left, cy - r); ctx.lineTo(u.bbox.left + 1.4 * r, cy); ctx.lineTo(u.bbox.left, cy + r); ctx.closePath(); ctx.fill();
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
  box.append(`Mkr 1  ${formatX(state.data.x[i])}`, document.createElement("br"));
  const num = (txt) => { const s = document.createElement("span"); s.className = "num"; s.textContent = txt; return s; };
  const fmt = (v, digits) => (v === null || v === undefined ? "—" : minus(v.toFixed(digits)));
  plotDefs().forEach((def, k) => {
    if (k) box.append("   ");
    if (def.iq) box.append(num(`I ${fmt(t[def.traces[0]][i], 2)}, Q ${fmt(t[def.traces[1]][i], 2)} ${def.unit}`));
    else box.append(num(`${fmt(t[def.traces[0]][i], 2)}${def.unit === "°" ? "°" : " " + def.unit}`));
  });
}

const argMin = (a) => (a && a.length ? a.reduce((best, v, i) => (v < a[best] ? i : best), 0) : null);
const argMax = (a) => (a && a.length ? a.reduce((best, v, i) => (v > a[best] ? i : best), 0) : null);

function showUpdate(u) {
  const newLayout = state.plotsFor !== u.measurement;
  if (newLayout || (state.marker !== null && state.marker >= u.x.length)) state.marker = null;
  const hadInfo = JSON.stringify(state.data?.info ?? {}) !== JSON.stringify(u.info ?? {});
  state.data = u;
  state.xAxis = u.x_axis;
  buildPlots(u.measurement);
  $("empty").hidden = true;
  plotDefs().forEach((def, k) => plots[k].setData([u.x, ...def.traces.map((name) => u.traces[name])]));
  renderMarkerReadout();
  renderInfo();
  if (state.menu === "Marker" && hadInfo) renderMenuBody();
  $("st-meas").textContent = state.measurements[u.measurement]?.name ?? "";
  $("st-start").textContent = `Start ${formatX(u.x[0])}`;
  $("st-stop").textContent = `Stop ${formatX(u.x[u.x.length - 1])}`;
  $("st-points").textContent = `${u.x.length} points`;
  $("st-round").textContent = u.rounds == null ? `Sweep ${u.round}` : `Round ${u.round} of ${u.rounds}`;
}

function traceLines() {
  plotDefs().forEach((def, k) => {
    const line = $(k === 0 ? "tr1-line" : "tr2-line"), label = `Tr${k + 1} ${def.title}`;
    const s = plots[k]?.scales.y;
    if (!state.data || s?.min === undefined || s.min === null) { line.textContent = label; return; }
    if (def.iq) { line.textContent = `${label}   ${+plots[k].div.toPrecision(3)} ${def.unit}/div on I and Q`; return; }
    const div = (s.max - s.min) / 10, sc = scaleOf(k), ref = sc.auto ? s.min + 5 * div : sc.ref;
    const refText = minus(String(+ref.toFixed(decimalsFor(div) + 1)));
    const xs = plots[k].scales.x, horizontal = hasXScale() && k === 0 && xs?.min !== undefined
      ? `   │   ${+((xs.max - xs.min) / 10).toPrecision(3)} ${xUnit()}/div` : "";
    line.textContent = `${label}   ${+div.toPrecision(3)} ${def.unit}/div   Ref ${refText} ${def.unit}${sc.auto ? "" : "   Fixed"}${horizontal}`;
  });
}

// Fit results (e.g. the π-pulse gain) under the marker readout.
function renderInfo() {
  const box = $("fit-readout"), info = Object.entries(state.data?.info ?? {});
  box.hidden = !info.length;
  box.textContent = info.map(([name, v]) => `${name}  ${+v.toPrecision(4)}`).join("\n");
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
      Object.assign(state, { controller: m.controller, controllerName: m.controller_name, running: m.running, tone: m.tone, lo: m.lo });
      applyControl();
    } else if (m.type === "update") {
      showUpdate(m);
    } else if (m.type === "parameters") {
      if (m.chip === $("chip").value) {
        state.parameters = m.parameters; renderMenuBody();
        document.querySelector("#setup-body .parameters")?.replaceWith(parameterList());
      }
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
  $("chip").onchange = async () => { store.set("chip", $("chip").value); await loadParameters(); renderMenus(); renderSetupPanel(); };
  $("setup-key").onclick = () => toggleSetup();
  $("setup-close").onclick = () => toggleSetup(false);
  $("help-key").onclick = () => toggleHelp();
  $("help-close").onclick = () => toggleHelp(false);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (state.setupOpen) toggleSetup(false);
    if (state.helpOpen) toggleHelp(false);
  });
  $("take-control").onclick = async () => {
    if (!$("name").value.trim()) { $("name").focus(); message("Type your name first, so others know who controls the board.", true); return; }
    try { await api("POST", "/api/control"); } catch (e) { message(e.message, true); }
  };
  $("run").onclick = run;
  $("stop").onclick = () => api("POST", "/api/runs/stop").catch((e) => message(e.message, true));

  state.measurements = await api("GET", "/api/measurements");
  if (!state.measurements[state.measurement]) state.measurement = "resonator_sweep";
  const select = $("measurement");  // its options depend on the chip; renderMenus() fills them
  select.onchange = () => {
    state.measurement = select.value; store.set("measurement", select.value);
    if (!state.data) { buildPlots(state.measurement); traceLines(); }
    renderMenus();
  };
  buildPlots(state.measurement);
  traceLines();
  new ResizeObserver(() => {
    for (const [k, el] of [[0, "plot-mag"], [1, "plot-phase"]]) plots[k].setSize({ width: $(el).clientWidth, height: $(el).clientHeight });
    traceLines();
  }).observe($("plot-mag").parentElement.parentElement);

  await loadBoard();
  await loadProfiles();  // draws the menus, which depend on the chip's output path
  applyControl();
  connect();
}

main().catch((e) => message(e.message, true));
