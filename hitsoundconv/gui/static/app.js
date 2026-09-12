"use strict";

const $ = (selector) => document.querySelector(selector);
let app = null;        // what the server knows: open project, available configs
let selected = null;   // file name of the sample shown in the details panel
let showStart = false; // "Project…" was pressed while a project is open
let busy = false;
let saveTimer = null;

const project = () => app && app.project;

// --- language -------------------------------------------------------------------------------------

const STRINGS = {
  en: {
    project_button: "Project…",
    edit_title: "Mapset holds only the source samples – while hitsounding",
    listen_title: "Convert and install the generated files into the mapset",
    convert: "Convert",
    start: "Project",
    start_intro: "A config holds the roles of a map: which sample belongs in which slot.",
    open_label: "Path to a config (.toml) or to an osu!mania difficulty (.osu)",
    open_button: "Open / create",
    no_configs: "No config yet.",
    configs_hint: "New configs are written to {dir}.",
    pool: "Samples without a role",
    pool_hint: "Samples dropped here use the fallback slot {slot}.",
    slots: "Slots",
    slots_hint: "Drag samples into a slot. Click a sample for its details, ▶ plays it.",
    details: "Details",
    settings: "Settings",
    result: "Result",
    detail_empty: "Click a sample to set priority, lock, anchor and overflow slot.",
    head_fill: "greenlines + fill",
    head_silence: "silence",
    fill: "fill",
    sample_meta: "{count}× in the chart · volumes {volumes}",
    play: "Play",
    slot: "Slot",
    fallback_option: "— fallback ({slot}) —",
    priority: "Priority",
    priority_hint: "Decides the bank when several samples land in the same channel.",
    anchor: "Anchor (kick focus)",
    anchor_hint: "When this sample plays, everything else on that timestamp is mixed into its slot.",
    lock: "Lock",
    lock_hint: "Never move to another bank, never move away.",
    overflow: "Overflow slot",
    overflow_hint: "Where it goes if the mix in its own slot would clip.",
    gain: "Gain (dB)",
    set_bank_mode: "Bank mode",
    set_bank_mode_hint: "prefer: another bank when that saves an index",
    set_volume_mode: "Volume mode",
    set_volume_mode_hint: "relative: greenline = loudest sample",
    set_on_clip: "On clipping",
    set_on_clip_hint: "roles: move to the role or overflow slot",
    set_duplicates: "Duplicate samples",
    set_duplicates_hint: "loudest: once, at its loudest volume",
    set_silent_bank: "Bank for silence",
    set_silent_bank_hint: "with skin hitsounds you hear that bank's skin hitnormal",
    set_fill_sample: "Fill sound",
    set_fill_sample_hint: "what objects without a mania sound play",
    set_fill_bank: "Fill / greenline bank",
    set_fill_bank_hint: "must differ from the bank for silence",
    set_fill_gain: "Fill gain (dB)",
    mapset_line: "Mapset: {path} – {mode}, {count} installed files.",
    mapset_unknown: " {count} files look like an old export copied by hand.",
    stat_indices: "indices",
    stat_wavs: "WAVs",
    stat_distinct: "distinct sounds",
    stat_slides: "sliderslides",
    stat_combinations: "combinations",
    stat_moved: "moved",
    stat_limited: "mixed quieter",
    stat_off_role: "other bank",
    fill_line: "Fill: {fill}",
    not_converted: "Not converted yet – press Convert or LISTEN.",
    index_line: "Index {index} · {objects} objects · {files} files",
    ready: "Ready.",
    pick_project: "Open or create a project.",
    busy_convert: "Converting",
    busy_listen: "Converting and installing into the mapset",
    busy_edit: "Removing the installed files from the mapset",
    busy_routes: "Saving roles",
    busy_setting: "Saving setting",
    busy_open: "Opening project",
    busy_create: "Creating config",
    play_failed: "Playback failed: {error}",
  },
  de: {
    project_button: "Projekt…",
    edit_title: "Mapset enthält nur die Quell-Samples – währenddessen hitsoundest du",
    listen_title: "Konvertieren und die erzeugten Dateien in den Mapset installieren",
    convert: "Konvertieren",
    start: "Projekt",
    start_intro: "Eine Config hält die Rollen einer Map fest: welches Sample in welchen Slot gehört.",
    open_label: "Pfad zu einer Config (.toml) oder zu einer osu!mania-Difficulty (.osu)",
    open_button: "Öffnen bzw. anlegen",
    no_configs: "Noch keine Config vorhanden.",
    configs_hint: "Neue Configs landen in {dir}.",
    pool: "Samples ohne Rolle",
    pool_hint: "Hier abgelegte Samples landen auf dem Fallback-Slot {slot}.",
    slots: "Slots",
    slots_hint: "Samples in einen Slot ziehen. Klick auf ein Sample zeigt die Details, ▶ spielt es ab.",
    details: "Details",
    settings: "Einstellungen",
    result: "Ergebnis",
    detail_empty: "Ein Sample anklicken, um Priorität, Lock, Anchor und Ausweich-Slot einzustellen.",
    head_fill: "Greenlines + Fill",
    head_silence: "Stille",
    fill: "Fill",
    sample_meta: "{count}× im Chart · Volumes {volumes}",
    play: "Anhören",
    slot: "Slot",
    fallback_option: "— Fallback ({slot}) —",
    priority: "Priorität",
    priority_hint: "Bestimmt die Bank, wenn mehrere Samples im selben Kanal landen.",
    anchor: "Anchor (Kick-Fokus)",
    anchor_hint: "Spielt dieses Sample, wird alles andere des Zeitstempels in seinen Slot gemischt.",
    lock: "Lock",
    lock_hint: "Nie in eine andere Bank verschieben, nie ausweichen.",
    overflow: "Ausweich-Slot",
    overflow_hint: "Wohin es ausweicht, falls der Mix im eigenen Slot übersteuern würde.",
    gain: "Gain (dB)",
    set_bank_mode: "Bank-Modus",
    set_bank_mode_hint: "prefer: andere Bank, wenn das einen Index spart",
    set_volume_mode: "Volume-Modus",
    set_volume_mode_hint: "relative: Greenline = lautestes Sample",
    set_on_clip: "Bei Übersteuern",
    set_on_clip_hint: "roles: in Rollen- oder Ausweich-Slot ausweichen",
    set_duplicates: "Doppelte Samples",
    set_duplicates_hint: "loudest: einmal, in der lautesten Lautstärke",
    set_silent_bank: "Bank für Stille",
    set_silent_bank_hint: "mit Skin-Hitsounds hört man hier den Skin-hitnormal",
    set_fill_sample: "Fill-Sound",
    set_fill_sample_hint: "was Objekte ohne Mania-Sound spielen",
    set_fill_bank: "Fill-/Greenline-Bank",
    set_fill_bank_hint: "muss sich von der Bank für Stille unterscheiden",
    set_fill_gain: "Fill-Gain (dB)",
    mapset_line: "Mapset: {path} – {mode}, {count} installierte Dateien.",
    mapset_unknown: " {count} Dateien sehen nach einem alten, von Hand kopierten Export aus.",
    stat_indices: "Indizes",
    stat_wavs: "WAVs",
    stat_distinct: "verschiedene Klänge",
    stat_slides: "sliderslides",
    stat_combinations: "Kombinationen",
    stat_moved: "ausgewichen",
    stat_limited: "leiser gemischt",
    stat_off_role: "andere Bank",
    fill_line: "Fill: {fill}",
    not_converted: "Noch nicht konvertiert – „Konvertieren“ oder LISTEN drücken.",
    index_line: "Index {index} · {objects} Objekte · {files} Dateien",
    ready: "Bereit.",
    pick_project: "Projekt öffnen oder anlegen.",
    busy_convert: "Konvertiere",
    busy_listen: "Konvertiere und installiere in den Mapset",
    busy_edit: "Entferne die installierten Dateien aus dem Mapset",
    busy_routes: "Speichere Rollen",
    busy_setting: "Speichere Einstellung",
    busy_open: "Öffne Projekt",
    busy_create: "Lege Config an",
    play_failed: "Abspielen fehlgeschlagen: {error}",
  },
};

function storedLang() {
  try {
    return localStorage.getItem("lang");
  } catch {
    return null;
  }
}

let lang = STRINGS[storedLang()] ? storedLang() : "en";

function T(key, params = {}) {
  const text = (STRINGS[lang] || STRINGS.en)[key] ?? STRINGS.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => params[name] ?? "");
}

function setLang(next) {
  lang = next;
  try {
    localStorage.setItem("lang", next);
  } catch { /* private mode: keep it for this page only */ }
  document.documentElement.lang = next;
  render();
}

// --- server ---------------------------------------------------------------------------------------

async function api(path, body) {
  const options = body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(`${path}?lang=${lang}`, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function setStatus(text, kind = "") {
  const el = $("#status");
  el.textContent = text;
  el.className = kind;
}

async function run(label, task) {
  if (busy) return;
  busy = true;
  document.body.classList.add("busy");
  setStatus(label + " …");
  try {
    const result = await task();
    app = result.state;
    render();
    setStatus(result.message, "ok");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    busy = false;
    document.body.classList.remove("busy");
  }
}

function saveRoutes() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => run(T("busy_routes"), () => api("/api/routes", { samples: project().samples })), 250);
}

function saveSetting(section, key, value) {
  run(T("busy_setting"), () => api("/api/settings", { [section]: { [key]: value } }));
}

function playAudio(kind, name) {
  const player = $("#player");
  player.src = `/audio/${kind}/${encodeURIComponent(name)}`;
  player.play().catch((error) => setStatus(T("play_failed", { error: error.message }), "error"));
}

// --- small DOM helpers ----------------------------------------------------------------------------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  node.append(...children.filter((child) => child !== null && child !== undefined));
  return node;
}

function allSlots() {
  return project().sounds.flatMap((sound) => project().banks.map((bank) => `${bank}-${sound}`));
}

function volumeRange(volumes) {
  if (!volumes.length) return "";
  const lo = volumes[0], hi = volumes[volumes.length - 1];
  return lo === hi ? `${lo}` : `${lo}–${hi}`;
}

function select(options, value, onChange, placeholder) {
  const node = el("select", { onchange: (e) => onChange(e.target.value) });
  if (placeholder !== undefined) node.append(el("option", { value: "", textContent: placeholder }));
  for (const option of options) node.append(el("option", { value: option, textContent: option }));
  node.value = value ?? "";
  return node;
}

function field(label, control, hint) {
  return el("label", { class: "field" },
    el("span", { class: "label", textContent: label }), control,
    hint ? el("small", { class: "muted", textContent: hint }) : null);
}

// --- start screen ---------------------------------------------------------------------------------

function renderStart() {
  const list = $("#project-list");
  list.replaceChildren(...app.projects.map((entry) => el("li", {},
    el("button", { type: "button", textContent: entry.name, onclick: () => openPath(entry.path) }),
    el("small", { class: "muted", textContent: entry.path }))));
  if (!app.projects.length) {
    list.replaceChildren(el("li", { class: "muted", textContent: T("no_configs") }));
  }
  $("#start-hint").textContent = T("configs_hint", { dir: app.configs_dir });
}

function openPath(path) {
  const isConfig = path.toLowerCase().endsWith(".toml");
  run(isConfig ? T("busy_open") : T("busy_create"), () =>
    api(isConfig ? "/api/open" : "/api/create", isConfig ? { path } : { beatmap: path }))
    .then(() => { showStart = false; render(); });
}

// --- sample cards and drop zones --------------------------------------------------------------------

function card(sample) {
  const r = sample.route;
  const badges = el("span", { class: "badges" },
    r.anchor ? el("span", { class: "badge", textContent: "anchor" }) : null,
    r.lock ? el("span", { class: "badge", textContent: "lock" }) : null,
    r.overflow ? el("span", { class: "badge", textContent: `→ ${r.overflow}` }) : null,
    r.gain_db ? el("span", { class: "badge", textContent: `${r.gain_db > 0 ? "+" : ""}${r.gain_db} dB` }) : null);
  const node = el("div", {
    class: "card" + (sample.file === selected ? " selected" : ""),
    draggable: true,
    title: sample.file,
    onclick: () => { selected = sample.file; render(); },
    ondragstart: (e) => {
      e.dataTransfer.setData("text/plain", sample.file);
      e.dataTransfer.effectAllowed = "move";
      node.classList.add("dragging");
    },
    ondragend: () => node.classList.remove("dragging"),
  },
    el("button", {
      type: "button", class: "play", title: T("play"), textContent: "▶",
      onclick: (e) => { e.stopPropagation(); playAudio("source", sample.file); },
    }),
    el("span", { class: "name", textContent: sample.file }),
    el("small", { class: "muted", textContent: `${sample.count}× · ${volumeRange(sample.volumes)}` }),
    badges);
  return node;
}

function makeDropZone(node, slot) {
  node.addEventListener("dragover", (e) => { e.preventDefault(); node.classList.add("over"); });
  node.addEventListener("dragleave", () => node.classList.remove("over"));
  node.addEventListener("drop", (e) => {
    e.preventDefault();
    node.classList.remove("over");
    const sample = project().samples.find((s) => s.file === e.dataTransfer.getData("text/plain"));
    if (!sample) return;
    if (slot) {
      sample.route.slot = slot;
      sample.route.fallback = false;
    } else {
      sample.route.fallback = true;
    }
    selected = sample.file;
    render();
    saveRoutes();
  });
}

// --- panels -------------------------------------------------------------------------------------------

function renderChrome() {
  for (const [key, id] of [["start", "t-start"], ["start_intro", "t-start-intro"], ["open_label", "t-open-label"],
                           ["open_button", "t-open-button"], ["pool", "t-pool"], ["slots", "t-slots"],
                           ["slots_hint", "t-slots-hint"], ["details", "t-details"], ["settings", "t-settings"],
                           ["result", "t-result"]]) {
    $("#" + id).textContent = T(key);
  }
  $("#switch").textContent = T("project_button");
  $("#convert").textContent = T("convert");
  $("[data-mode=edit]").title = T("edit_title");
  $("[data-mode=listen]").title = T("listen_title");
  for (const button of document.querySelectorAll("[data-lang]")) {
    button.classList.toggle("active", button.dataset.lang === lang);
  }
  const p = project();
  $("#map").textContent = p ? `${p.title} · ${p.config}` : "";
  $("#project-actions").hidden = !p;
  if (!p) return;
  for (const button of document.querySelectorAll("[data-mode]")) {
    const active = button.dataset.mode === p.mode.mode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function renderPool() {
  const p = project();
  $("#pool").replaceChildren(...p.samples.filter((s) => s.route.fallback).map(card));
  $("#pool-hint").textContent = T("pool_hint", { slot: p.fallback });
}

function renderBoard() {
  const p = project();
  const fillBank = p.settings.fill.bank;
  const silentBank = p.settings.mix.silent_bank;
  const board = $("#board");
  board.replaceChildren(el("div", { class: "corner" }));
  for (const bank of p.banks) {
    const notes = [bank === fillBank ? T("head_fill") : null, bank === silentBank ? T("head_silence") : null].filter(Boolean);
    board.append(el("div", { class: "head" }, el("strong", { textContent: bank }),
      notes.length ? el("small", { class: "muted", textContent: notes.join(" · ") }) : null));
  }
  for (const sound of p.sounds) {
    board.append(el("div", { class: "rowhead", textContent: sound }));
    for (const bank of p.banks) {
      const slot = `${bank}-${sound}`;
      const isFill = sound === "hitnormal" && bank === fillBank;
      const zone = el("div", { class: "drop slot" + (isFill ? " fill" : "") },
        el("div", { class: "slot-label", textContent: isFill ? `${slot} · ${T("fill")}` : slot }),
        ...p.samples.filter((s) => !s.route.fallback && s.route.slot === slot).map(card));
      makeDropZone(zone, slot);
      board.append(zone);
    }
  }
}

function renderDetail() {
  const box = $("#detail");
  const sample = project().samples.find((s) => s.file === selected);
  if (!sample) {
    box.replaceChildren(el("p", { class: "muted", textContent: T("detail_empty") }));
    return;
  }
  const r = sample.route;
  const change = (apply) => (value) => { apply(value); render(); saveRoutes(); };
  box.replaceChildren(
    el("h3", { textContent: sample.file }),
    el("p", { class: "muted", textContent: T("sample_meta", { count: sample.count, volumes: sample.volumes.join(", ") }) }),
    el("button", { type: "button", textContent: "▶ " + T("play"), onclick: () => playAudio("source", sample.file) }),
    field(T("slot"), select(allSlots(), r.fallback ? "" : r.slot, change((v) => {
      if (v) { r.slot = v; r.fallback = false; } else { r.fallback = true; }
    }), T("fallback_option", { slot: project().fallback }))),
    field(T("priority"), el("input", {
      type: "number", step: 1, value: r.priority,
      onchange: (e) => change((v) => { r.priority = v; })(parseInt(e.target.value || "0", 10)),
    }), T("priority_hint")),
    field(T("anchor"), el("input", {
      type: "checkbox", checked: r.anchor, onchange: (e) => change((v) => { r.anchor = v; })(e.target.checked),
    }), T("anchor_hint")),
    field(T("lock"), el("input", {
      type: "checkbox", checked: r.lock, onchange: (e) => change((v) => { r.lock = v; })(e.target.checked),
    }), T("lock_hint")),
    field(T("overflow"), select(allSlots(), r.overflow, change((v) => { r.overflow = v; }), "—"), T("overflow_hint")),
    field(T("gain"), el("input", {
      type: "number", step: 0.5, value: r.gain_db,
      onchange: (e) => change((v) => { r.gain_db = v; })(parseFloat(e.target.value || "0")),
    })),
  );
}

const SETTINGS = [
  ["mix", "bank_mode", ["prefer", "strict"]],
  ["mix", "volume_mode", ["relative", "absolute", "auto"]],
  ["mix", "on_clip", ["roles", "limit", "spread"]],
  ["mix", "duplicates", ["loudest", "sum"]],
  ["mix", "silent_bank", null],
  ["fill", "sample", null],
  ["fill", "bank", null],
];

function renderSettings() {
  const p = project();
  const box = $("#settings");
  box.replaceChildren();
  for (const [section, key, choices] of SETTINGS) {
    const options = choices ?? (key === "sample" ? ["auto", "none", ...p.samples.map((s) => s.file)] : p.banks);
    const name = section === "fill" ? `set_fill_${key === "sample" ? "sample" : "bank"}` : `set_${key}`;
    box.append(field(T(name), select(options, p.settings[section][key], (v) => saveSetting(section, key, v)), T(name + "_hint")));
  }
  box.append(field(T("set_fill_gain"), el("input", {
    type: "number", step: 0.5, value: p.settings.fill.gain_db,
    onchange: (e) => saveSetting("fill", "gain_db", parseFloat(e.target.value || "0")),
  })));
  box.append(el("p", { class: "muted" },
    T("mapset_line", { path: p.mode.mapset, mode: p.mode.mode.toUpperCase(), count: p.mode.installed }),
    p.mode.unknown.length
      ? el("span", { class: "warn", textContent: T("mapset_unknown", { count: p.mode.unknown.length }) })
      : null));
}

function renderResult() {
  const summary = project().summary;
  const stats = $("#stats");
  $("#messages").replaceChildren();
  $("#indices").replaceChildren();
  if (!summary) {
    stats.replaceChildren(el("p", { class: "muted", textContent: T("not_converted") }));
    return;
  }
  const numbers = [
    ["stat_indices", `${summary.indices}/${summary.index_limit}`, summary.over_limit ? "bad" : ""],
    ["stat_wavs", `${summary.wavs}`, ""],
    ["stat_distinct", `${summary.distinct}`, ""],
    ["stat_slides", `${summary.slides}`, ""],
    ["stat_combinations", `${summary.combinations}`, ""],
    ["stat_moved", `${summary.moved}`, ""],
    ["stat_limited", `${summary.limited}`, summary.limited ? "warn" : ""],
    ["stat_off_role", `${summary.off_role}`, ""],
  ];
  stats.replaceChildren(
    el("p", { class: "numbers" }, ...numbers.map(([key, value, kind]) => el("span", { class: `num ${kind}` },
      el("b", { textContent: value }), el("span", { class: "label", textContent: " " + T(key) })))),
    el("p", { class: "muted", textContent: T("fill_line", { fill: summary.fill }) }));
  $("#messages").replaceChildren(...summary.messages.map((message) => el("li", { textContent: message })));
  $("#indices").replaceChildren(...summary.index_table.map((idx) => el("details", {},
    el("summary", { textContent: T("index_line", { index: idx.index, objects: idx.objects, files: idx.slots.length }) }),
    el("table", {}, el("tbody", {}, ...idx.slots.map((slot) => el("tr", { class: slot.fill ? "fill" : "" },
      el("td", {}, el("button", {
        type: "button", class: "play", title: T("play"), textContent: "▶",
        onclick: () => playAudio("export", slot.file),
      })),
      el("td", { class: "file", textContent: slot.file + (slot.fill ? ` (${T("fill")})` : "") }),
      el("td", { textContent: slot.content }))))))));
}

function render() {
  const open = Boolean(project()) && !showStart;
  $("#start-panel").hidden = open;
  document.querySelector("main").hidden = !open;
  $("#result-panel").hidden = !open;
  renderChrome();
  if (!open) {
    renderStart();
    return;
  }
  renderPool();
  renderBoard();
  renderDetail();
  renderSettings();
  renderResult();
}

// --- start --------------------------------------------------------------------------------------------

makeDropZone($("#pool"), null);
$("#convert").addEventListener("click", () => run(T("busy_convert"), () => api("/api/convert", {})));
$("#switch").addEventListener("click", () => { showStart = true; render(); });
$("#open-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const path = $("#open-path").value.trim().replace(/^"|"$/g, "");
  if (path) openPath(path);
});
for (const button of document.querySelectorAll("[data-lang]")) {
  button.addEventListener("click", () => setLang(button.dataset.lang));
}
for (const button of document.querySelectorAll("[data-mode]")) {
  button.addEventListener("click", () => {
    const listen = button.dataset.mode === "listen";
    run(listen ? T("busy_listen") : T("busy_edit"), () => api("/api/mode", { mode: button.dataset.mode }));
  });
}
document.documentElement.lang = lang;
api("/api/state")
  .then((data) => {
    app = data;
    render();
    setStatus(project() ? T("ready") : T("pick_project"), "ok");
  })
  .catch((error) => setStatus(error.message, "error"));
