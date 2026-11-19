// It's a Wonderful App: Worth a Month? (spec §13). A top tab reached from the header, always open. The server returns
// the considering services; a service adding nothing says why.
import { APP_NAME, api, esc, state } from "./core.js";
import { posterHtml, watchPosters } from "./grid.js";

// One poster card per movie a service would add; ids the grid no longer has are skipped.
function posterCardHtml(m) {
  const label = m.year ? `${m.title} (${m.year})` : m.title;
  return `<a class="movie-card" href="#/m/${m.id}" aria-label="${esc(label)}">`
    + `<div class="poster-wrap">${posterHtml(m)}</div>`
    + `<div class="card-title">${esc(m.title)}</div>`
    + `</a>`;
}

function workRowHtml(s, byId) {
  const posters = s.movies.map(id => byId.get(id)).filter(Boolean);
  const head = `<p class="worth-line"><span class="worth-name">${esc(s.name)}</span> adds <strong>${s.count}</strong>`
    + (s.count === 0 && s.reason ? `. <span class="worth-reason">${esc(s.reason)}</span>` : "")
    + `</p>`;
  const grid = posters.length ? `<div class="grid worth-posters">${posters.map(posterCardHtml).join("")}</div>` : "";
  return `<li class="worth-service" data-service="${esc(s.service)}">${head}${grid}</li>`;
}

function worthHtml(services) {
  const byId = new Map(state.movies.map(m => [m.id, m]));
  return `<ul class="worth-list">${services.map(s => workRowHtml(s, byId)).join("")}</ul>`;
}

// Asks the server and paints the tab. Called each time #/worth opens, so a Settings change shows at once.
async function showWorth() {
  const box = document.getElementById("worth-list");
  document.title = `Worth a Month? · ${APP_NAME}`;
  box.innerHTML = `<p class="empty">Loading…</p>`;
  let data = null;
  try {
    data = await api("/api/worth");
  } catch {
    data = null;
  }
  if (!data) box.innerHTML = `<p class="empty">Couldn't work out Worth a Month? right now.</p>`;
  else if (!data.services.length) box.innerHTML = `<p class="settings-hint">No service is set to Considering, so there is nothing to add. Set one in Settings to see it here.</p>`;
  else {
    box.innerHTML = worthHtml(data.services);
    if (!box.dataset.posters) {   // the poster error fallback is attached once per box element
      watchPosters(box);
      box.dataset.posters = "1";
    }
  }
}

export { showWorth };
