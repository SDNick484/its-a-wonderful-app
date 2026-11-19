// It's a Wonderful App: the poster grid. Loads the list into state.movies and draws a card for each movie.
import { api, esc, state, toast } from "./core.js";

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

function cardHtml(m) {
  const label = m.year ? `${m.title} (${m.year})` : m.title;
  return `<a class="movie-card" href="#/m/${m.id}" aria-label="${esc(label)}">`
    + `<div class="poster-wrap">${posterHtml(m)}<span class="rating-slot"></span></div>`
    + `<div class="card-title">${esc(m.title)}</div>`
    + (m.year ? `<div class="card-year">${m.year}</div>` : "")
    + `</a>`;
}

function renderGrid() {
  const grid = document.getElementById("grid");
  const empty = document.getElementById("grid-empty");
  grid.innerHTML = state.movies.map(cardHtml).join("");
  empty.hidden = state.movies.length > 0;
  empty.textContent = "No movies on our list yet.";
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

export { loadMovies, posterHtml, watchPosters };
