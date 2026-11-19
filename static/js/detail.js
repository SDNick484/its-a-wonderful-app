// It's a Wonderful App: one movie's detail view (backdrop, overview, runtime, certification, cast, collection, the
// parent note) and Remove.
import { api, esc, state, toast } from "./core.js";
import { loadMovies, posterHtml, renderGrid, watchPosters } from "./grid.js";

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
  box.innerHTML = detailHtml(m);
  watchPosters(box);
  document.title = `${m.title}: It's a Wonderful App`;
  document.getElementById("detail-save").addEventListener("click", () => saveNote(m, document.getElementById("detail-note").value));
  const select = document.getElementById("detail-cert");
  select.addEventListener("change", () => saveCertification(m, select.value, select));
  document.getElementById("detail-remove").addEventListener("click", () => removeMovie(m));
  box.addEventListener("click", e => {
    if (e.target.closest("#detail-refresh")) refreshProviders(m, false);
  });
  if (m.providers_stale) refreshProviders(m, true);
}

export { showDetail };
