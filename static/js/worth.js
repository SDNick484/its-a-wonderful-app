// It's a Wonderful App: Worth a Month? (spec §13). The home card in November and December, and the same list in Settings.
// The server decides whether the card shows (the host's date, season); a service adding nothing says why.
import { api, esc, state } from "./core.js";
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

// Fills a box with the list. The poster error fallback (a titled placeholder) is attached once per box element.
function paintBox(el, html) {
  el.innerHTML = html;
  if (!el.dataset.posters) {
    watchPosters(el);
    el.dataset.posters = "1";
  }
}

// Asks the server once, then paints the home card (November and December only, and only when a service is being
// considered) and the Settings box when the page has one. A failed call hides the card and says so in Settings.
async function loadWorth() {
  const card = document.getElementById("worth");
  const box = document.getElementById("worth-box");
  let data = null;
  try {
    data = await api("/api/worth");
  } catch {
    data = null;
  }
  if (card) {
    const show = !!data && data.season && data.services.length > 0;
    card.hidden = !show;
    if (show) paintBox(document.getElementById("worth-list"), worthHtml(data.services));
  }
  if (box) {
    if (!data) box.innerHTML = `<p class="empty">Couldn't work out Worth a Month? right now.</p>`;
    else if (!data.services.length) box.innerHTML = `<p class="settings-hint">No service is set to Considering, so there is nothing to add. Set one above to see it here.</p>`;
    else paintBox(box, worthHtml(data.services));
  }
}

export { loadWorth };
