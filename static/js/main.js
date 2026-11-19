// It's a Wonderful App: entry point. static/index.html loads this with <script type="module">; app.py's
// render_index() versions every module through an import map, so never hand-edit ?v=.
import { api, APP_NAME, toast } from "./core.js";
import { openAddSheet } from "./add.js";
import { checkPrompt, loadContinue, wireContinue } from "./continue.js";
import { showDetail } from "./detail.js";
import { loadMovies, watchPosters } from "./grid.js";
import { wireSearch } from "./search.js";
import { showSettings } from "./settings.js";
import { wireSurprise } from "./surprise.js";
import { startTheme } from "./theme.js";

let gridScroll = 0;

// #/ is the grid, #/m/<id> one movie, #/settings the settings. The grid keeps its scroll position while another
// screen is open.
function route() {
  const grid = document.getElementById("grid-view");
  const detail = document.getElementById("detail-view");
  const settings = document.getElementById("settings-view");
  const m = location.hash.match(/^#\/m\/(\d+)$/);
  const other = m || location.hash === "#/settings";
  if (other) {
    if (!grid.hidden) gridScroll = window.scrollY;
    grid.hidden = true;
    detail.hidden = !m;
    settings.hidden = !!m;
    window.scrollTo(0, 0);
    if (m) showDetail(Number(m[1]));
    else showSettings();
  } else {
    const wasOther = grid.hidden;
    detail.hidden = true;
    settings.hidden = true;
    grid.hidden = false;
    document.title = APP_NAME;
    if (wasOther) {
      window.scrollTo(0, gridScroll);
      loadContinue();   // a Watch tonight or a finish on the detail view shows on the row
    }
  }
}

async function start() {
  document.title = APP_NAME;
  await startTheme();   // first, so the list never flashes the wrong light or dark; if it can't load, the plain look stays
  try {
    await api("/api/health");
  } catch (e) {
    toast(`Can't reach the app: ${e.message}`);
  }
  watchPosters(document.getElementById("grid"));
  wireSearch();
  wireSurprise();
  wireContinue();
  const add = document.getElementById("add-btn");
  add.addEventListener("click", () => openAddSheet(add));
  window.addEventListener("hashchange", route);
  await Promise.all([loadMovies(), loadContinue()]);
  route();
  checkPrompt();   // "Did you finish …?" the first time the app opens after the TV stopped a movie
}

window.addEventListener("DOMContentLoaded", start);
