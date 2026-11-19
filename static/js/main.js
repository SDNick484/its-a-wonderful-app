// It's a Wonderful App: entry point. static/index.html loads this with <script type="module">; app.py's
// render_index() versions every module through an import map, so never hand-edit ?v=.
import { api, APP_NAME, toast } from "./core.js";
import { openAddSheet } from "./add.js";
import { showDetail } from "./detail.js";
import { loadMovies, watchPosters } from "./grid.js";

let gridScroll = 0;

// #/ is the grid, #/m/<id> one movie. The grid keeps its scroll position while a movie is open.
function route() {
  const grid = document.getElementById("grid-view");
  const detail = document.getElementById("detail-view");
  const m = location.hash.match(/^#\/m\/(\d+)$/);
  if (m) {
    if (!grid.hidden) gridScroll = window.scrollY;
    grid.hidden = true;
    detail.hidden = false;
    window.scrollTo(0, 0);
    showDetail(Number(m[1]));
  } else {
    const wasDetail = !detail.hidden;
    detail.hidden = true;
    grid.hidden = false;
    document.title = APP_NAME;
    if (wasDetail) window.scrollTo(0, gridScroll);
  }
}

async function start() {
  document.title = APP_NAME;
  try {
    await api("/api/health");
  } catch (e) {
    toast(`Can't reach the app: ${e.message}`);
  }
  watchPosters(document.getElementById("grid"));
  const add = document.getElementById("add-btn");
  add.addEventListener("click", () => openAddSheet(add));
  window.addEventListener("hashchange", route);
  await loadMovies();
  route();
}

window.addEventListener("DOMContentLoaded", start);
