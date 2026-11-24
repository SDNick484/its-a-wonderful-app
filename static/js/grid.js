// It's a Wonderful App: the poster grid. Loads the list into state.movies and draws a card for each movie.
import { api, esc, state, toast } from "./core.js";
import { starText } from "./rating.js";

// A poster, or (no poster, or one that won't load) a placeholder carrying the movie's title.
function posterHtml(m) {
  const ph = `<div class="poster-ph">${esc(m.title)}</div>`;
  if (!m.poster_url) return ph;
  return `<img class="poster-img" src="${esc(m.poster_url)}" alt="" loading="lazy" decoding="async" data-title="${esc(m.title)}">`;
}

// An <img> that fails to load becomes the titled placeholder. "error" doesn't bubble, so listen while capturing.
function watchPosters(root) {
  root.addEventListener("error", e => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || !img.classList.contains("poster-img")) return;
    const ph = document.createElement("div");
    ph.className = "poster-ph";
    ph.textContent = img.dataset.title || "";
    img.replaceWith(ph);
  }, true);
}

// The star on a poster: the family mean, or Matinee's rating until someone here rates (spec §8.2).
function starHtml(m) {
  const text = starText(m.family_rating);
  return text ? `<span class="star" data-source="${esc(m.rating_source)}" aria-label="Rated ${m.family_rating.toFixed(1)}">${text}</span>` : "";
}

// A movie watched in the last 45 days gets a greyed cover (class `watched`, style.css); the card still opens it.
function cardHtml(m) {
  const label = (m.year ? `${m.title} (${m.year})` : m.title) + (m.watched_recently ? ", watched recently" : "");
  const first = (m.where_to_watch || [])[0];   // the best place to watch it (spec §7.2)
  return `<a class="movie-card${m.watched_recently ? " watched" : ""}" href="#/m/${m.id}" aria-label="${esc(label)}">`
    + `<div class="poster-wrap">${posterHtml(m)}<span class="rating-slot">${starHtml(m)}</span></div>`
    + `<div class="card-title">${esc(m.title)}</div>`
    + (m.year ? `<div class="card-year">${m.year}</div>` : "")
    + (state.whys[m.id] ? `<div class="card-why">${esc(state.whys[m.id])}</div>` : "")
    + (first ? `<div class="card-where" data-kind="${esc(first.kind)}">${esc(first.label)}</div>` : "")
    + `</a>`;
}

// Draws the cards the search left showing (state.shownIds), or all of them.
function renderGrid() {
  const grid = document.getElementById("grid");
  const empty = document.getElementById("grid-empty");
  const shown = state.shownIds ? state.movies.filter(m => state.shownIds.includes(m.id)) : state.movies;
  grid.innerHTML = shown.map(cardHtml).join("");
  empty.hidden = shown.length > 0;
  empty.textContent = state.movies.length ? "Nothing on our list matches that." : "No movies on our list yet.";
}

// Fetch the list again and redraw. A failure leaves what is on screen and says why.
async function loadMovies() {
  let failed = false;
  try {
    state.movies = await api("/api/movies");
  } catch (e) {
    failed = true;
    toast(`Couldn't load the list: ${e.message}`);
  }
  renderGrid();
  if (failed && !state.movies.length) document.getElementById("grid-empty").textContent = "Couldn't load our list. Reload the page to try again.";
}

export { loadMovies, posterHtml, renderGrid, watchPosters };
