// It's a Wonderful App: the randomizer (spec §12). One button draws three movies from the list through the filter
// chips; Pick Again draws three new ones, skipping what was drawn since the filters last changed. The chips are
// remembered on this device and every one starts off.
import { api, esc, state, toast } from "./core.js";
import { runtimeText } from "./detail.js";
import { posterHtml, watchPosters } from "./grid.js";

const STORAGE_KEY = "wonderful.surprise.filters";
const CAPS = ["G", "PG", "PG-13"];
const PICKS = 3;
const OFF = { animated: null, cap: null, under_90: false, not_watched_this_year: false, ready: false };

let filters = { ...OFF };
let drawn = [];        // the ids drawn since the filters last changed (what Pick Again leaves out)
let busy = false;

// ================================================================= remembered filters
// Private windows and blocked site data make localStorage throw, so every read and write is guarded.
function loadFilters() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
  } catch {
    // unreadable or blocked: start with everything off
  }
  const f = { ...OFF };
  if (saved && typeof saved === "object") {
    if (typeof saved.animated === "boolean") f.animated = saved.animated;
    if (CAPS.includes(saved.cap)) f.cap = saved.cap;
    for (const k of ["under_90", "not_watched_this_year", "ready"]) if (saved[k] === true) f[k] = true;
  }
  return f;
}

function saveFilters() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
  } catch {
    // blocked: the chips still work, they just aren't remembered
  }
}

// ================================================================= chips
// Animated and Live action are two halves of one setting (both off = both); the rating cap is one chip that cycles
// off -> G -> PG -> PG-13 -> off.
const CHIPS = [
  { id: "animated", on: f => f.animated === true, label: () => "Animated" },
  { id: "live", on: f => f.animated === false, label: () => "Live action" },
  { id: "cap", on: f => f.cap !== null, label: f => (f.cap ? `Up to ${f.cap}` : "Any rating") },
  { id: "under_90", on: f => f.under_90, label: () => "Under 90 min" },
  { id: "not_watched_this_year", on: f => f.not_watched_this_year, label: () => "Not watched this year" },
  { id: "ready", on: f => f.ready, label: () => "Ready to watch" },
];

function toggle(id) {
  if (id === "animated") filters.animated = filters.animated === true ? null : true;
  else if (id === "live") filters.animated = filters.animated === false ? null : false;
  else if (id === "cap") filters.cap = filters.cap === null ? CAPS[0] : (CAPS[CAPS.indexOf(filters.cap) + 1] ?? null);
  else filters[id] = !filters[id];
}

function renderChips() {
  document.getElementById("surprise-chips").innerHTML = CHIPS.map(c =>
    `<button type="button" class="chip" data-chip="${c.id}" aria-pressed="${c.on(filters)}">${esc(c.label(filters))}</button>`
  ).join("");
}

function onChip(id) {
  toggle(id);
  saveFilters();
  drawn = [];            // a new filter starts a new round
  renderChips();
  showPicks([], "");
}

// ================================================================= picks
function pickHtml(m) {
  const first = (m.where_to_watch || [])[0];
  const runtime = runtimeText(m.runtime_min);
  const label = m.year ? `${m.title} (${m.year})` : m.title;
  return `<a class="movie-card" href="#/m/${m.id}" aria-label="${esc(label)}">`
    + `<div class="poster-wrap">${posterHtml(m)}</div>`
    + `<div class="card-title">${esc(m.title)}</div>`
    + (runtime ? `<div class="card-year">${esc(runtime)}</div>` : "")
    + (first ? `<div class="card-where" data-kind="${esc(first.kind)}">${esc(first.label)}</div>` : "")
    + `</a>`;
}

function showPicks(ids, status, again = false) {
  const picks = ids.map(id => state.movies.find(m => m.id === id)).filter(Boolean);
  document.getElementById("surprise-picks").innerHTML = picks.map(pickHtml).join("");
  document.getElementById("surprise-status").textContent = status;
  document.getElementById("surprise-again").hidden = !again;
}

function statusFor(res) {
  const n = res.picks.length;
  if (n === 0) return "Nothing matches. Try turning off a filter.";
  if (n < PICKS) return `Only ${n} ${n === 1 ? "matches" : "match"}. Try turning off a filter.`;
  return res.restarted ? "That's all of them. Starting over." : "";
}

async function draw(again) {
  if (busy) return;
  busy = true;
  const buttons = [document.getElementById("surprise-btn"), document.getElementById("surprise-again")];
  buttons.forEach(b => { b.disabled = true; });
  try {
    const res = await api("/api/surprise", { method: "POST", body: { filters, exclude: again ? drawn : [] } });
    drawn = again && !res.restarted ? drawn.concat(res.picks) : [...res.picks];
    // Pick Again only makes sense when there is more than this round to see.
    showPicks(res.picks, statusFor(res), res.pool_size > PICKS);
  } catch (e) {
    toast(`Couldn't pick: ${e.message}`);
  } finally {
    busy = false;
    buttons.forEach(b => { b.disabled = false; });
  }
}

// Wire the section once, at start-up.
function wireSurprise() {
  filters = loadFilters();
  renderChips();
  watchPosters(document.getElementById("surprise-picks"));
  document.getElementById("surprise-chips").addEventListener("click", e => {
    const chip = e.target.closest("[data-chip]");
    if (chip) onChip(chip.dataset.chip);
  });
  document.getElementById("surprise-btn").addEventListener("click", () => draw(false));
  document.getElementById("surprise-again").addEventListener("click", () => draw(true));
}

export { wireSurprise };
