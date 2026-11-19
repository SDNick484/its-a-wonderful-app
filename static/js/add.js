// It's a Wonderful App: the add sheet. Search TMDB by title, tap "Add to our list", and the grid gains the poster.
import { api, esc, toast } from "./core.js";
import { loadMovies } from "./grid.js";

const SEARCH_DELAY_MS = 350;
let sheet = null;
let opener = null;
let searchTimer = null;
let searchSeq = 0;

function sheetHtml() {
  return `<div class="sheet-backdrop" data-close></div>`
    + `<div class="sheet-panel" role="dialog" aria-modal="true" aria-labelledby="add-title">`
    + `<div class="sheet-head"><h2 id="add-title" class="sheet-title">Add a movie</h2>`
    + `<button type="button" class="icon-btn icon-btn-quiet" data-close aria-label="Close">&times;</button></div>`
    + `<form id="add-form" role="search"><label class="sr-only" for="add-q">Movie or special title</label>`
    + `<input id="add-q" class="field" type="search" placeholder="Search TMDB by title" autocomplete="off" enterkeyhint="search"></form>`
    + `<div id="add-results" class="add-results" aria-live="polite"></div>`
    + `<p class="tmdb-credit"><img src="/static/tmdb.svg" alt="TMDB" width="64" height="12">`
    + `<span>This product uses the TMDB API but is not endorsed or certified by TMDB.</span></p></div>`;
}

function resultHtml(r) {
  const kind = r.tmdb_type === "tv" ? "TV special" : "Movie";
  const what = [r.year, kind].filter(Boolean).join(" · ");
  const action = r.on_list
    ? `<a class="btn btn-quiet" href="#/m/${r.on_list}" data-close>On our list</a>`
    : `<button type="button" class="btn" data-add="${r.tmdb_id}" data-type="${esc(r.tmdb_type)}" data-title="${esc(r.title)}">Add to our list</button>`;
  return `<div class="add-row"><div class="add-what"><div class="add-name">${esc(r.title)}</div><div class="add-kind">${esc(what)}</div></div>${action}</div>`;
}

function setResults(html) {
  document.getElementById("add-results").innerHTML = html;
}

async function runSearch() {
  const q = document.getElementById("add-q").value.trim();
  const mine = ++searchSeq;
  if (!q) return setResults("");
  setResults(`<p class="add-note">Searching…</p>`);
  let body;
  try {
    body = await api(`/api/tmdb/search?q=${encodeURIComponent(q)}`);
  } catch (e) {
    if (mine === searchSeq) setResults(`<p class="add-note">${esc(e.message)}</p>`);
    return;
  }
  if (mine !== searchSeq) return;   // a newer search is already on its way
  setResults(body.results.length ? body.results.map(resultHtml).join("") : `<p class="add-note">${esc(body.message || "No matches.")}</p>`);
}

async function addMovie(btn) {
  const title = btn.dataset.title;
  btn.disabled = true;
  btn.textContent = "Adding…";
  try {
    await api("/api/movies", { method: "POST", body: { tmdb_id: Number(btn.dataset.add), tmdb_type: btn.dataset.type } });
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Add to our list";
    toast(e.message);
    return;
  }
  await loadMovies();
  closeSheet();
  toast(`Added ${title}.`);
}

function closeSheet() {
  if (!sheet) return;
  clearTimeout(searchTimer);
  searchSeq++;
  sheet.remove();
  sheet = null;
  document.removeEventListener("keydown", onKey);
  if (opener) opener.focus();
}

function onKey(e) {
  if (e.key === "Escape") closeSheet();
}

function openAddSheet(from) {
  if (sheet) return;
  opener = from || null;
  sheet = document.createElement("div");
  sheet.className = "sheet";
  sheet.innerHTML = sheetHtml();
  document.body.appendChild(sheet);
  sheet.addEventListener("click", e => {
    const add = e.target.closest("[data-add]");
    if (add) return addMovie(add);
    if (e.target.closest("[data-close]")) closeSheet();
  });
  sheet.querySelector("#add-form").addEventListener("submit", e => {
    e.preventDefault();
    clearTimeout(searchTimer);
    runSearch();
  });
  sheet.querySelector("#add-q").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, SEARCH_DELAY_MS);
  });
  document.addEventListener("keydown", onKey);
  sheet.querySelector("#add-q").focus();
}

export { openAddSheet };
