// It's a Wonderful App: one movie's detail view (backdrop, overview, runtime, certification, cast, collection, the
// parent note), Watch tonight / We finished, the family rating (with the notice when Matinee disagrees) and Remove.
import { finishViewing, keepWatching, watchTonight } from "./continue.js";
import { api, esc, state, toast } from "./core.js";
import { loadMovies, posterHtml, renderGrid, watchPosters } from "./grid.js";
import { dotsHtml, openRatingSheet, starText } from "./rating.js";

const CERT_CHOICES = ["G", "PG", "PG-13", "R", "NR"];

function runtimeText(min) {
  if (!min) return "";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? `${h} h${m ? ` ${m} min` : ""}` : `${m} min`;
}

function whereHtml(m) {
  const lines = (m.where_to_watch || []).map(w => `<li class="where-line" data-kind="${esc(w.kind)}">${esc(w.label)}</li>`).join("");
  const source = m.providers_link
    ? `<a href="${esc(m.providers_link)}" target="_blank" rel="noopener">JustWatch</a>` : "JustWatch";
  return `<ul class="where-list" id="detail-where">${lines}</ul>`
    + `<p class="where-credit"><span>Data from ${source}</span> <button type="button" class="btn btn-quiet" id="detail-refresh">Check again</button></p>`;
}

// "Matinee says 9, we say 8.6" with the three answers (spec §8.2), or a line saying Matinee hasn't been told yet.
function syncHtml(m) {
  const c = m.rating_conflict;
  if (c) {
    const ours = typeof c.ours === "number" ? String(c.ours) : "nothing";
    return `<div class="sync-note" id="rating-conflict" role="status"><p class="sync-text">Matinee says ${esc(String(c.matinee))}, we say ${esc(ours)}</p>`
      + `<div class="sync-actions"><button type="button" class="btn" data-choice="ours">Use ours</button>`
      + `<button type="button" class="btn btn-quiet" data-choice="matinee">Use Matinee's</button>`
      + `<button type="button" class="btn btn-quiet" data-choice="dismiss">Dismiss</button></div></div>`;
  }
  return m.rating_pending ? `<p class="sync-hint" id="rating-pending">Not sent to Matinee yet. It tries again tonight.</p>` : "";
}

// "★ 8.6 family" and the dot row (spec §11), or a note that Matinee's rating is showing, with the Rate button.
function ratingsHtml(m) {
  const star = starText(m.family_rating);
  const label = !star ? "Nobody has rated it yet." : m.rating_source === "matinee" ? `${star} family rating from Matinee` : `${star} family`;
  return `<p class="rating-head" id="detail-rating-head">${esc(label)}</p>${dotsHtml(m.family)}${syncHtml(m)}`
    + `<div class="detail-actions"><button type="button" class="btn" id="detail-rate">${m.family?.by_person.some(p => p.rating !== null) ? "Change ratings" : "Rate it"}</button></div>`;
}

// Watch tonight, or where the movie's open viewing stands with Keep watching tonight and We finished (spec §10).
function tonightHtml(m) {
  const v = m.viewing;
  if (!v) return `<div class="detail-actions"><button type="button" class="btn" id="detail-tonight">Watch tonight</button></div>`;
  const where = v.status === "paused" ? `In Continue Watching${v.progress ? `: ${v.progress}` : ""}.`
    : v.status === "watching" ? "Watching now." : "On for tonight.";
  return `<p class="tonight-status" id="detail-tonight-status">${esc(where)}</p><div class="detail-actions">`
    + (v.status === "paused" ? `<button type="button" class="btn" id="detail-keep">Keep watching tonight</button>` : "")
    + `<button type="button" class="btn${v.status === "paused" ? " btn-quiet" : ""}" id="detail-finish">We finished</button></div>`;
}

function detailHtml(m) {
  const meta = [m.year, m.certification, runtimeText(m.runtime_min), m.tmdb_type === "tv" ? "TV special" : ""].filter(Boolean);
  const certs = CERT_CHOICES.includes(m.certification) || !m.certification ? CERT_CHOICES : [...CERT_CHOICES, m.certification];
  return (m.backdrop_url ? `<div class="detail-backdrop"><img src="${esc(m.backdrop_url)}" alt="" decoding="async"></div>` : "")
    + `<div class="detail-head"><div class="detail-poster poster-wrap">${posterHtml(m)}</div><div class="detail-titles">`
    + `<h2 class="detail-title">${esc(m.title)}</h2>`
    + `<p class="detail-meta">${meta.map(esc).join(" · ")}</p>`
    + (m.collection_name ? `<p class="detail-collection">Part of ${esc(m.collection_name)}</p>` : "")
    + `</div></div>`
    + (m.overview ? `<p class="detail-overview">${esc(m.overview)}</p>` : "")
    + `<div id="detail-tonight-box">${tonightHtml(m)}</div>`
    + `<h3 class="detail-label">Ratings</h3><div id="detail-ratings">${ratingsHtml(m)}</div>`
    + `<h3 class="detail-label">Where to watch</h3><div id="detail-where-box">${whereHtml(m)}</div>`
    + (m.top_cast.length ? `<h3 class="detail-label">Cast</h3><p class="detail-cast">${m.top_cast.map(esc).join(", ")}</p>` : "")
    + `<h3 class="detail-label"><label for="detail-cert">Certification</label></h3>`
    + `<select id="detail-cert" class="field">`
    + certs.map(c => `<option${c === m.certification ? " selected" : ""}>${esc(c)}</option>`).join("") + `</select>`
    + `<h3 class="detail-label"><label for="detail-note">Note for parents</label></h3>`
    + `<textarea id="detail-note" class="field" rows="3" maxlength="1000" placeholder="Anything to know before pressing play">${esc(m.parent_note || "")}</textarea>`
    + `<div class="detail-actions"><button type="button" class="btn" id="detail-save">Save note</button>`
    + `<button type="button" class="btn btn-quiet" id="detail-remove">Remove from our list</button></div>`;
}

// Replace the movie in state.movies so the grid is right when the person goes back.
function keepInState(m) {
  state.movies = state.movies.map(x => (x.id === m.id ? { ...x, ...m } : x));
}

// A rating was saved (or a Matinee conflict settled): show it here and on the card behind this screen.
function ratingsSaved(m, saved) {
  const fields = { family_rating: saved.family_rating, rating_source: saved.rating_source, family: saved.family,
    rating_conflict: saved.rating_conflict ?? null, rating_pending: Boolean(saved.rating_pending) };
  Object.assign(m, fields);
  keepInState({ id: m.id, ...fields });
  const box = document.getElementById("detail-ratings");
  if (box && box.isConnected && Number(location.hash.split("/")[2]) === m.id) box.innerHTML = ratingsHtml(m);
  renderGrid();
}

async function saveNote(m, note) {
  try {
    const saved = await api(`/api/movies/${m.id}`, { method: "PUT", body: { parent_note: note } });
    Object.assign(m, saved);
    keepInState(saved);
    toast("Note saved.");
  } catch (e) {
    toast(`Couldn't save: ${e.message}`);
  }
}

async function saveCertification(m, certification, select) {
  try {
    const saved = await api(`/api/movies/${m.id}`, { method: "PUT", body: { certification } });
    Object.assign(m, saved);
    keepInState(saved);
    toast(`Certification is now ${saved.certification}.`);
  } catch (e) {
    select.value = m.certification || "";
    toast(`Couldn't save: ${e.message}`);
  }
}

// Ask TMDB again and redraw the lines. `quiet` (the automatic refresh of an old answer) says nothing when it fails.
async function refreshProviders(m, quiet) {
  const btn = document.getElementById("detail-refresh");
  if (btn) btn.disabled = true;
  try {
    Object.assign(m, await api(`/api/movies/${m.id}/providers/refresh`, { method: "POST" }));
  } catch (e) {
    if (!quiet) toast(`Couldn't check: ${e.message}`);
  }
  const box = document.getElementById("detail-where-box");
  if (box && box.isConnected && Number(location.hash.split("/")[2]) === m.id) box.innerHTML = whereHtml(m);
  keepInState({ id: m.id, where_to_watch: m.where_to_watch });
  renderGrid();   // the card behind this screen shows the new line when the person goes back
}

function redrawTonight(m) {
  const box = document.getElementById("detail-tonight-box");
  if (box && box.isConnected && Number(location.hash.split("/")[2]) === m.id) box.innerHTML = tonightHtml(m);
}

// Watch tonight, Keep watching tonight or We finished, from the detail view.
async function tonightAction(m, which, button) {
  button.disabled = true;
  let v = null;
  if (which === "tonight") v = await watchTonight(m.id);
  else if (which === "keep") v = await keepWatching(m.viewing);
  else v = await finishViewing(m.viewing, saved => ratingsSaved(m, saved));
  if (v) m.viewing = v.status === "finished" || v.status === "abandoned" ? null : v;
  if (button.isConnected) button.disabled = false;
  redrawTonight(m);
}

const SETTLED = { ours: "Sent ours to Matinee.", matinee: "Using Matinee's rating.", dismiss: "Left as it is." };

async function settleConflict(m, choice, button) {
  for (const b of document.querySelectorAll("#rating-conflict button")) b.disabled = true;
  try {
    const saved = await api(`/api/movies/${m.id}/rating-conflict`, { method: "POST", body: { choice } });
    ratingsSaved(m, saved);
    toast(choice === "ours" && saved.rating_pending ? "Matinee didn't answer. Ours goes tonight." : SETTLED[choice]);
  } catch (e) {
    if (button.isConnected) for (const b of document.querySelectorAll("#rating-conflict button")) b.disabled = false;
    toast(`Couldn't save: ${e.message}`);
  }
}

async function removeMovie(m) {
  if (!confirm(`Remove "${m.title}" from our list? Its ratings and viewings go with it.`)) return;
  try {
    await api(`/api/movies/${m.id}`, { method: "DELETE" });
  } catch (e) {
    toast(`Couldn't remove it: ${e.message}`);
    return;
  }
  await loadMovies();
  toast(`Removed ${m.title}.`);
  location.hash = "#/";
}

async function showDetail(id) {
  const box = document.getElementById("detail");
  box.innerHTML = `<p class="empty">Loading…</p>`;
  let m;
  try {
    m = await api(`/api/movies/${id}`);
  } catch (e) {
    box.innerHTML = `<p class="empty">${e.status === 404 ? "That movie isn't on our list." : esc(e.message)}</p>`;
    return;
  }
  if (!m.family?.by_person.length) {
    // Nobody in the family yet: asking for the people copies them from Matinee the first time (spec §8.4).
    try {
      if ((await api("/api/people")).length) m = await api(`/api/movies/${id}`);
    } catch {
      // the movie still shows; the Rate sheet says to add the family in Settings
    }
  }
  box.innerHTML = detailHtml(m);
  watchPosters(box);
  document.title = `${m.title}: It's a Wonderful App`;
  document.getElementById("detail-save").addEventListener("click", () => saveNote(m, document.getElementById("detail-note").value));
  const select = document.getElementById("detail-cert");
  select.addEventListener("change", () => saveCertification(m, select.value, select));
  document.getElementById("detail-remove").addEventListener("click", () => removeMovie(m));
  box.addEventListener("click", e => {
    if (e.target.closest("#detail-refresh")) refreshProviders(m, false);
    const tonight = e.target.closest("#detail-tonight, #detail-keep, #detail-finish");
    if (tonight) tonightAction(m, tonight.id.slice("detail-".length), tonight);
    const rate = e.target.closest("#detail-rate");
    if (rate) openRatingSheet(m, rate, saved => ratingsSaved(m, saved));
    const choice = e.target.closest("[data-choice]");
    if (choice) settleConflict(m, choice.dataset.choice, choice);
  });
  if (m.providers_stale) refreshProviders(m, true);
}

export { runtimeText, showDetail };
