// It's a Wonderful App: the search box (spec §9). As you type, the grid filters on the page by title, year, cast and
// collection, with no network. Enter asks the app (/api/search): an exact title, else smart search, which shows what
// on our list fits with a reason and, under "Not on our list yet", titles to add with a tap (never added on their own).
import { api, esc, state, toast } from "./core.js";
import { loadMovies, renderGrid } from "./grid.js";

// Mirrors normalize() in search.py: casefold, apostrophes dropped, other punctuation a space, runs of spaces
// collapsed, a leading "the " dropped. Change both together.
function normalize(s) {
  const t = String(s ?? "").toLowerCase().replace(/['’]/g, "");
  const u = t.replace(/[^\p{L}\p{N}\s]|_/gu, " ").split(/\s+/).filter(Boolean).join(" ");
  return u.startsWith("the ") ? u.slice(4) : u;
}

// The ids of the movies on the list that match q (the same rule as search.local_matches), in list order.
function localIds(q) {
  const qn = normalize(q);
  if (!qn) return null;
  return state.movies.filter(m =>
    normalize(m.title).includes(qn)
    || (m.year != null && String(m.year).includes(qn))
    || (m.top_cast || []).some(n => normalize(n).includes(qn))
    || (m.collection_name && normalize(m.collection_name).includes(qn))
  ).map(m => m.id);
}

function setSearchStatus(text) {
  document.getElementById("search-status").textContent = text;
}

// Show these ids (null for everything) and say what that is. `whys` maps ids to smart search's reasons.
function showIds(ids, status, whys = {}) {
  state.shownIds = ids;
  state.whys = whys;
  renderGrid();
  setSearchStatus(status);
}

// "Not on our list yet": one row per suggestion with its reason and an Add to our list button. No rows hides it.
function showSuggestions(list) {
  document.getElementById("suggest-list").innerHTML = list.map(s => {
    const what = [s.year, s.tmdb_type === "tv" ? "TV special" : "Movie"].filter(Boolean).join(" · ");
    return `<div class="add-row"><div class="add-what"><div class="add-name">${esc(s.title)}</div>`
      + `<div class="add-kind">${esc(what)}</div>${s.why ? `<div class="add-why">${esc(s.why)}</div>` : ""}</div>`
      + `<button type="button" class="btn" data-add="${s.tmdb_id}" data-type="${esc(s.tmdb_type)}" data-title="${esc(s.title)}">Add to our list</button></div>`;
  }).join("");
  document.getElementById("suggest").hidden = list.length === 0;
}

// The Add to our list button on a suggestion: the one place smart search changes the list, and only on a tap.
async function addSuggestion(btn) {
  const row = btn.closest(".add-row");
  btn.disabled = true;
  btn.textContent = "Adding…";
  try {
    const movie = await api("/api/movies", { method: "POST", body: { tmdb_id: Number(btn.dataset.add), tmdb_type: btn.dataset.type } });
    if (state.shownIds) state.shownIds = [...state.shownIds, movie.id];   // it fits the search, so show it with the rest
    await loadMovies();
    toast(`Added ${btn.dataset.title}.`);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Add to our list";
    toast(e.message);
    return;
  }
  row.remove();
  document.getElementById("suggest").hidden = document.getElementById("suggest-list").children.length === 0;
}

// As you type: the local filter, no request.
function onType(input) {
  showSuggestions([]);
  const q = input.value.trim();
  if (!q) {
    showIds(null, "");
    return;
  }
  const ids = localIds(q);
  const n = ids.length;
  showIds(ids, n ? `${n} ${n === 1 ? "movie" : "movies"} match "${q}"` : "");
}

// What the status line says about an answer: the exact title, or how many on our list fit, then any notice.
function searchStatusFor(res, q) {
  const n = res.matches.length;
  if (res.mode === "exact") return `Exact title match for "${q}"`;
  const count = res.mode === "ai"
    ? (n ? `${n} ${n === 1 ? "movie" : "movies"} on our list fit "${q}"` : `Nothing on our list fits "${q}"`)
    : (n ? `${n} ${n === 1 ? "movie" : "movies"} match "${q}"` : "");
  return [count, res.notice].filter(Boolean).join(". ");
}

// On Enter: the app's answer. An exact title (one movie), else smart search (matches with reasons, and titles to add),
// else the local matches in list order with a notice that smart search is off.
async function onSubmit(input) {
  const q = input.value.trim();
  if (!q) {
    showIds(null, "");
    return;
  }
  setSearchStatus("Searching…");
  let res;
  try {
    res = await api(`/api/search?q=${encodeURIComponent(q)}`);
  } catch (e) {
    setSearchStatus("");
    toast(`Search failed: ${e.message}`);
    return;
  }
  if (input.value.trim() !== q) return;   // the box changed while the answer was on its way
  const whys = {};
  if (res.mode === "ai") for (const m of res.matches) if (m.why) whys[m.id] = m.why;
  showIds(res.matches.map(m => m.id), searchStatusFor(res, q), whys);
  showSuggestions(res.suggestions || []);
}

// Wire the search box once, at start-up.
function wireSearch() {
  const form = document.getElementById("search-form");
  const input = document.getElementById("search-input");
  input.addEventListener("input", () => onType(input));
  form.addEventListener("submit", e => {
    e.preventDefault();
    onSubmit(input);
  });
  document.getElementById("suggest-list").addEventListener("click", e => {
    const btn = e.target.closest("[data-add]");
    if (btn) addSuggestion(btn);
  });
}

export { wireSearch };
