// It's a Wonderful App: one movie's detail view (backdrop, overview, runtime, certification, cast, collection, the
// parent note), Watch tonight / We finished, Play on the Family Room TV (play.js), the family rating (with the notice
// when Matinee disagrees), Log date (a night nobody logged at the time, with who watched, as in Matinee), the Watched
// list (each finished viewing, deletable when it was logged by mistake) and Remove.
import { closeContinueSheet, finishViewing, keepWatching, loadContinue, openContinueSheet, rateAfterFinish, watchTonight } from "./continue.js";
import { api, esc, state, toast } from "./core.js";
import { loadMovies, posterHtml, renderGrid, watchPosters } from "./grid.js";
import { playHtml, startPlay } from "./play.js";
import { dotHtml, dotsHtml, initialOf, openRatingSheet, starText } from "./rating.js";

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

// "2026-11-20" -> a local Date at midnight, so the day never shifts with the time zone.
function localDay(iso) {
  const [y, mo, d] = iso.split("-").map(Number);
  return new Date(y, mo - 1, d);
}

function readableDay(iso) {
  return localDay(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

// "today", "yesterday", "5 days ago", "3 weeks ago", "2 months ago", "1 year ago", counted from `today`: the host's
// date (the movie's `today`), never this phone's clock, which may be in another time zone.
function agoText(iso, today) {
  const days = Math.round((localDay(today) - localDay(iso)) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  const [n, unit] = days < 14 ? [days, "day"] : days < 60 ? [Math.floor(days / 7), "week"]
    : days < 365 ? [Math.floor(days / 30), "month"] : [Math.floor(days / 365), "year"];
  return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
}

// Log date, as in Matinee: Who watched (everyone on until someone is tapped off), a date (the host's today or
// earlier) and the button. With no family yet there is no Who watched row and the night is logged for nobody.
function logHtml(m) {
  const people = m.family?.by_person || [];
  const who = people.length
    ? `<div class="who-row" id="detail-who" role="group" aria-labelledby="detail-who-label">`
      + `<span class="who-label" id="detail-who-label">Who watched</span><span class="who-btns">`
      + people.map(p => `<button type="button" class="who-btn" data-person="${p.person_id}" data-color="${esc(p.color)}"`
        + ` aria-pressed="true" aria-label="${esc(p.name)}" title="${esc(p.name)}">${esc(initialOf(p))}</button>`).join("") + `</span></div>`
    : "";
  return who + `<div class="log-row"><input type="date" id="detail-log-date" class="field" max="${esc(m.today)}" aria-label="Date watched">`
    + `<button type="button" class="btn btn-quiet" id="detail-log">Log date</button></div>`;
}

// Each finished viewing, newest first: the date, how long ago, who watched, and ✕ to delete it.
function watchedHtml(m) {
  const list = m.watched || [];
  if (!list.length) return `<p class="watched-none">Not watched yet.</p>`;
  const people = new Map((m.family?.by_person || []).map(p => [p.person_id, p]));
  return `<ul class="watched-list">` + list.map(w => {
    const who = w.people.map(id => people.get(id)).filter(Boolean);
    const names = who.map(p => p.name).join(", ");
    return `<li class="watched-row" data-viewing="${w.viewing_id}">`
      + `<span class="watched-when"><span class="watched-date">${esc(readableDay(w.finished_on))}</span>`
      + ` <span class="watched-ago">(${esc(agoText(w.finished_on, m.today))})</span></span>`
      + (who.length ? `<span class="watched-who" aria-label="${esc(`Watched by ${names}`)}">${who.map(dotHtml).join("")}</span>` : "")
      + `<button type="button" class="icon-btn icon-btn-quiet watched-delete" data-viewing="${w.viewing_id}"`
      + ` aria-label="${esc(`Delete the viewing on ${readableDay(w.finished_on)}`)}">&times;</button></li>`;
  }).join("") + `</ul>`;
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
    + `<h3 class="detail-label">Watched</h3><div id="detail-log-box">${logHtml(m)}</div><div id="detail-watched">${watchedHtml(m)}</div>`
    + playHtml(m)
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

function redrawWatched(m) {
  const box = document.getElementById("detail-watched");
  if (box && box.isConnected && Number(location.hash.split("/")[2]) === m.id) box.innerHTML = watchedHtml(m);
}

// The Watched list changed (a night logged, finished or deleted; `saved` has the new `watched` and
// `watched_recently`): redraw it, and grey or clear the cover on the card behind this screen.
function watchedSaved(m, saved) {
  m.watched = saved.watched;
  m.watched_recently = saved.watched_recently;
  keepInState({ id: m.id, watched_recently: saved.watched_recently });
  redrawWatched(m);
  renderGrid();
}

// ✕ on a Watched row: "Delete this viewing?", then it goes here and in Matinee (the server refuses when Matinee
// can't be reached, so the two never disagree). The Calendar and "Not watched this year" read the same rows.
function confirmDelete(m, viewingId, from) {
  const w = (m.watched || []).find(x => x.viewing_id === viewingId);
  if (!w) return;
  openContinueSheet("watched-delete", "Delete this viewing?",
    `<p class="sheet-text">${esc(m.title)} on ${esc(readableDay(w.finished_on))}. It's deleted in Matinee too.</p>`
    + `<div class="sheet-actions"><button type="button" class="btn" data-act="delete">Delete</button>`
    + `<button type="button" class="btn btn-quiet" data-act="cancel">Cancel</button></div>`,
    from, async target => {
      const act = target.closest("[data-act]")?.dataset.act;
      if (act === "cancel") return closeContinueSheet();
      if (act !== "delete") return;
      for (const b of document.querySelectorAll("#watched-delete button")) b.disabled = true;
      let saved;
      try {
        saved = await api(`/api/viewings/${viewingId}`, { method: "DELETE" });
      } catch (e) {
        closeContinueSheet();
        toast(`Couldn't delete it: ${e.message}`);
        return;
      }
      closeContinueSheet();
      watchedSaved(m, saved);
      toast("Viewing deleted.");
      const back = document.querySelector("#detail-watched .watched-delete") || document.getElementById("detail-rate");
      if (back) back.focus();
    });
}

// After a finish the new viewing joins the Watched list.
async function reloadWatched(m) {
  let fresh;
  try {
    fresh = await api(`/api/movies/${m.id}`);
  } catch {
    return;   // the list is right again on the next visit
  }
  m.today = fresh.today;
  watchedSaved(m, fresh);
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
  if (v?.status === "finished") reloadWatched(m);
}

// A Play on the Family Room TV line, on this movie's page while it is open; when the person has gone elsewhere it
// comes as a toast instead (a disc's stays until tapped), so the answer isn't lost.
function sayOnPage(m) {
  return (text, sticky) => {
    const line = document.getElementById("detail-play-status");
    if (line && line.isConnected && detailMovie === m && Number(location.hash.split("/")[2]) === m.id) line.textContent = text;
    else toast(text, sticky ? 0 : undefined);
  };
}

// Start the disc or Stream it: every Play button is off until the server answers, so a second tap sends nothing; then
// the tonight box shows the viewing the play made (or, when the play failed, the one it made before Home Assistant
// didn't answer), and Continue Watching follows.
async function playAction(m, button) {
  const buttons = [...document.querySelectorAll("#detail-play-box [data-play]")];
  for (const b of buttons) b.disabled = true;
  const body = button.dataset.play === "disc" ? { mode: "disc" } : { mode: "stream", service: button.dataset.service };
  const answer = await startPlay(m, body, sayOnPage(m));
  for (const b of buttons) b.disabled = false;
  if (answer) {
    m.viewing = answer.viewing;
  } else {
    try {
      m.viewing = (await api(`/api/movies/${m.id}`)).viewing;
    } catch {
      // the box is right again on the next visit
    }
  }
  redrawTonight(m);
  loadContinue();
}

// With every Who watched toggle off there is nobody to log, so the button is off too.
function syncLog() {
  const button = document.getElementById("detail-log");
  const who = document.getElementById("detail-who");
  if (button) button.disabled = Boolean(who) && !who.querySelector('.who-btn[aria-pressed="true"]');
}

function toggleWho(who) {
  who.setAttribute("aria-pressed", who.getAttribute("aria-pressed") === "true" ? "false" : "true");
  syncLog();
}

// Log date: the night joins the Watched list (Matinee gets the watch, server side), a viewing of it that was waiting
// in Continue Watching is the one finished, the form goes back to everyone and no date, and the rating sheet opens
// with the people who watched first.
async function logDate(m, button) {
  const input = document.getElementById("detail-log-date");
  const day = input.value;
  if (!day) {
    toast("Choose a date first.");
    input.focus();
    return;
  }
  const who = document.getElementById("detail-who");
  const body = { finished_on: day };
  if (who) body.people = [...who.querySelectorAll('.who-btn[aria-pressed="true"]')].map(t => Number(t.dataset.person));
  button.disabled = true;
  let saved;
  try {
    saved = await api(`/api/movies/${m.id}/watched`, { method: "POST", body });
  } catch (e) {
    toast(`Couldn't log it: ${e.message}`);
    syncLog();
    return;
  }
  watchedSaved(m, saved);
  if (m.viewing?.viewing_id === saved.viewing_id) {
    m.viewing = null;
    redrawTonight(m);
    loadContinue();
  }
  const box = document.getElementById("detail-log-box");
  if (box && box.isConnected && Number(location.hash.split("/")[2]) === m.id) box.innerHTML = logHtml(m);
  toast(`Logged for ${readableDay(day)}.${saved.watch_pending ? " Matinee gets it tonight." : ""}`);
  rateAfterFinish(saved, rated => ratingsSaved(m, rated));
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

// The movie on screen: the one the view's click handler acts on. showDetail sets it with the page it draws.
let detailMovie = null;

function onDetailClick(e) {
  const m = detailMovie;
  if (!m) return;
  if (e.target.closest("#detail-refresh")) refreshProviders(m, false);
  const tonight = e.target.closest("#detail-tonight, #detail-keep, #detail-finish");
  if (tonight) tonightAction(m, tonight.id.slice("detail-".length), tonight);
  const play = e.target.closest("[data-play]");
  if (play && !play.disabled) playAction(m, play);
  const rate = e.target.closest("#detail-rate");
  if (rate) openRatingSheet(m, rate, saved => ratingsSaved(m, saved));
  const who = e.target.closest(".who-btn");
  if (who) toggleWho(who);
  const log = e.target.closest("#detail-log");
  if (log) logDate(m, log);
  const del = e.target.closest(".watched-delete");
  if (del) confirmDelete(m, Number(del.dataset.viewing), del);
  const choice = e.target.closest("[data-choice]");
  if (choice) settleConflict(m, choice.dataset.choice, choice);
}

// Once, at start (main.js): the detail view's one click handler and its poster fallback. #detail outlives every
// movie shown in it, so a handler added per visit would pile up: each tap would then also act on the movies opened
// earlier (initials toggled back, a date logged for them too).
function wireDetail() {
  const box = document.getElementById("detail");
  watchPosters(box);
  box.addEventListener("click", onDetailClick);
}

async function showDetail(id) {
  const box = document.getElementById("detail");
  detailMovie = null;
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
  detailMovie = m;
  document.title = `${m.title}: It's a Wonderful App`;
  document.getElementById("detail-save").addEventListener("click", () => saveNote(m, document.getElementById("detail-note").value));
  const select = document.getElementById("detail-cert");
  select.addEventListener("change", () => saveCertification(m, select.value, select));
  document.getElementById("detail-remove").addEventListener("click", () => removeMovie(m));
  if (m.providers_stale) refreshProviders(m, true);
}

export { runtimeText, showDetail, wireDetail };
