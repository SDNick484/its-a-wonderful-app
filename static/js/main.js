// It's a Wonderful App: entry point. static/index.html loads this with <script type="module">; app.py's
// render_index() versions every module through an import map, so never hand-edit ?v=.
import { api, APP_NAME, toast } from "./core.js";
import { openAddSheet } from "./add.js";
import { showCalendar } from "./calendar.js";
import { checkPrompt, loadContinue, wireContinue } from "./continue.js";
import { showDetail } from "./detail.js";
import { loadMovies, watchPosters } from "./grid.js";
import { wireSearch } from "./search.js";
import { showSettings } from "./settings.js";
import { wireSurprise } from "./surprise.js";
import { startTheme } from "./theme.js";
import { showWorth } from "./worth.js";

let gridScroll = 0;

// #/ is the grid, #/m/<id> one movie, #/settings the settings, #/worth Worth a Month?, #/calendar[/YYYY-MM] the
// Calendar. A hash that matches none of them (#/calendar/2026-13 too) is the grid. The grid keeps its scroll position
// while another screen is open.
function route() {
  const grid = document.getElementById("grid-view");
  const views = {
    detail: document.getElementById("detail-view"),
    settings: document.getElementById("settings-view"),
    worth: document.getElementById("worth-view"),
    calendar: document.getElementById("calendar-view"),
  };
  const m = location.hash.match(/^#\/m\/(\d+)$/);
  const cal = location.hash.match(/^#\/calendar(?:\/(\d{4}-(?:0[1-9]|1[0-2])))?$/);
  const view = m ? "detail" : cal ? "calendar" : location.hash === "#/settings" ? "settings"
    : location.hash === "#/worth" ? "worth" : "grid";
  const worthBtn = document.getElementById("worth-btn");
  if (view === "worth") worthBtn.setAttribute("aria-current", "page");
  else worthBtn.removeAttribute("aria-current");
  if (view !== "grid") {
    if (!grid.hidden) gridScroll = window.scrollY;
    grid.hidden = true;
    for (const [name, el] of Object.entries(views)) el.hidden = name !== view;
    window.scrollTo(0, 0);
    if (m) showDetail(Number(m[1]));
    else if (view === "settings") showSettings();
    else if (view === "calendar") showCalendar(cal[1] || null);
    else showWorth();
  } else {
    const wasOther = grid.hidden;
    for (const el of Object.values(views)) el.hidden = true;
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
