// It's a Wonderful App: the search box (spec §9, steps 0 and 1). As you type, the grid filters on the page by title,
// year, cast and collection, with no network. Enter asks the app (/api/search), which tries an exact title first.
import { api, state, toast } from "./core.js";
import { renderGrid } from "./grid.js";

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

// Show these ids (null for everything) and say what that is.
function showIds(ids, status) {
  state.shownIds = ids;
  renderGrid();
  setSearchStatus(status);
}

// As you type: the local filter, no request.
function onType(input) {
  const q = input.value.trim();
  if (!q) {
    showIds(null, "");
    return;
  }
  const ids = localIds(q);
  const n = ids.length;
  showIds(ids, n ? `${n} ${n === 1 ? "movie" : "movies"} match "${q}"` : "");
}

// On Enter: the app's answer. Exact title first (one movie), else the local matches in list order.
async function onSubmit(input) {
  const q = input.value.trim();
  if (!q) {
    showIds(null, "");
    return;
  }
  let res;
  try {
    res = await api(`/api/search?q=${encodeURIComponent(q)}`);
  } catch (e) {
    toast(`Search failed: ${e.message}`);
    return;
  }
  if (input.value.trim() !== q) return;   // the box changed while the answer was on its way
  const n = res.matches.length;
  const status = res.mode === "exact" ? `Exact title match for "${q}"`
    : n ? `${n} ${n === 1 ? "movie" : "movies"} match "${q}"` : "";
  showIds(res.matches.map(m => m.id), status);
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
}

export { wireSearch };
