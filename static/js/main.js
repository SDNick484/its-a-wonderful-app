// It's a Wonderful App: entry point. static/index.html loads this with <script type="module">; app.py's
// render_index() versions every module through an import map, so never hand-edit ?v=.
import { api, APP_NAME, esc, state, toast } from "./core.js";

function renderGrid() {
  const grid = document.getElementById("grid");
  const empty = document.getElementById("grid-empty");
  grid.innerHTML = state.movies
    .map(m => `<a class="movie-card" href="#/m/${m.id}"><div class="poster-wrap"><div class="poster-ph">${esc(m.title)}</div></div>`
      + `<div class="card-title">${esc(m.title)}</div></a>`)
    .join("");
  empty.hidden = state.movies.length > 0;
  empty.textContent = "No movies on our list yet.";
}

async function start() {
  document.title = APP_NAME;
  try {
    await api("/api/health");
  } catch (e) {
    toast(`Can't reach the app: ${e.message}`);
  }
  renderGrid();
}

window.addEventListener("DOMContentLoaded", start);
