// It's a Wonderful App: ratings. The star on a poster, the dot row on the detail view and the rating sheet (spec §11):
// one row per person with a 0-10 slider in half steps, as in Matinee. Imports only core.js; the caller says what
// to do with a saved rating (onSaved), so this module never touches the grid.
import { api, esc, toast } from "./core.js";

let rateSheet = null;
let rateOpener = null;

// "★ 8.6" for a poster, or "" when there is no rating to show.
function starText(rating) {
  return typeof rating === "number" ? `★ ${rating.toFixed(1)}` : "";
}

// 8 stays "8", 8.5 stays "8.5".
function ratingText(rating) {
  return typeof rating === "number" ? String(rating) : "–";
}

// The coloured dot with a person's initial. `color` is one of Matinee's palette keys (green, blue, red, pink, purple).
function dotHtml(person) {
  const initial = Array.from(person.name.trim())[0] || "?";
  return `<span class="dot" data-color="${esc(person.color)}" aria-hidden="true">${esc(initial.toUpperCase())}</span>`;
}

// The detail view's dot row: "● N 8  ● L 9 …". An unrated person shows a dash.
function dotsHtml(family) {
  const items = (family?.by_person || []).map(p => {
    const said = typeof p.rating === "number" ? `${p.name} rated it ${p.rating}` : `${p.name} hasn't rated it`;
    return `<li class="rating-dot" aria-label="${esc(said)}">${dotHtml(p)}<span class="dot-val">${ratingText(p.rating)}</span></li>`;
  });
  return items.length ? `<ul class="rating-dots">${items.join("")}</ul>` : "";
}

// ================================================================= the rating sheet
// One slider per person, 0 to 10 in 0.5 steps (as in Matinee). Each value is a number or null (not rated): an unrated
// row shows "–" and a dimmed slider resting on 7 until someone touches it, and Clear makes it unrated again.
const RESTING = 7;

function rowHtml(p, dim) {
  return `<div class="rate-row${dim ? " rate-row-dim" : ""}" data-person="${p.person_id}"><div class="rate-who">${dotHtml(p)}`
    + `<span class="rate-name">${esc(p.name)}</span><span class="rate-val"></span>`
    + `<button type="button" class="btn btn-quiet rate-clear">Clear</button></div>`
    + `<input type="range" class="rate-slider" min="0" max="10" step="0.5" aria-label="${esc(p.name)}'s rating"></div>`;
}

function paintRow(row, value) {
  const slider = row.querySelector(".rate-slider");
  const unset = value === null || value === undefined;
  slider.value = String(unset ? RESTING : value);
  slider.setAttribute("aria-valuetext", unset ? "Not rated" : String(value));
  if (unset) row.classList.add("rate-row-unset");
  else row.classList.remove("rate-row-unset");
  row.querySelector(".rate-clear").hidden = unset;
  row.querySelector(".rate-val").textContent = ratingText(unset ? null : value);
}

function closeRateSheet() {
  if (!rateSheet) return;
  rateSheet.remove();
  rateSheet = null;
  document.removeEventListener("keydown", onRateKey);
  // the button that opened the sheet may have been redrawn with the new rating: find it again by id
  const back = rateOpener && (rateOpener.isConnected ? rateOpener : rateOpener.id && document.getElementById(rateOpener.id));
  if (back) back.focus();
}

function onRateKey(e) {
  if (e.key === "Escape") closeRateSheet();
}

// Save what changed, one person at a time, then hand the last answer (the movie's new family rating) to onSaved.
async function saveRatings(m, before, now, onSaved, done) {
  const changed = Object.keys(now).filter(id => now[id] !== before[id]);
  if (!changed.length) return closeRateSheet();
  done.disabled = true;
  let last = null;
  try {
    for (const id of changed) last = await api(`/api/movies/${m.id}/ratings/${id}`, { method: "PUT", body: { rating: now[id] } });
  } catch (e) {
    done.disabled = false;
    toast(`Couldn't save: ${e.message}`);
    if (last) onSaved(last);   // what did save is still saved
    return;
  }
  onSaved(last);
  closeRateSheet();
  toast("Ratings saved.");
}

// Opens the sheet for movie `m` (its `family.by_person` is who can rate). onSaved gets {family_rating, rating_source, family}.
// `first` (person ids, after a finish: the viewing's people) puts those rows first and dims the rest (spec §11).
function openRatingSheet(m, from, onSaved, first = null) {
  if (rateSheet) return;
  rateOpener = from || null;
  const all = m.family?.by_person || [];
  const lead = Array.isArray(first) ? first : null;
  const people = lead ? [...all.filter(p => lead.includes(p.person_id)), ...all.filter(p => !lead.includes(p.person_id))] : all;
  const dim = p => Boolean(lead) && !lead.includes(p.person_id);
  const before = Object.fromEntries(people.map(p => [p.person_id, p.rating]));
  const now = { ...before };
  rateSheet = document.createElement("div");
  rateSheet.className = "sheet";
  rateSheet.innerHTML = `<div class="sheet-backdrop" data-close></div>`
    + `<div class="sheet-panel" role="dialog" aria-modal="true" aria-labelledby="rate-title">`
    + `<div class="sheet-head"><h2 id="rate-title" class="sheet-title">Rate ${esc(m.title)}</h2>`
    + `<button type="button" class="icon-btn icon-btn-quiet" data-close aria-label="Close">&times;</button></div>`
    + (people.length
      ? `<p class="rate-hint">Slide to rate. Clear leaves someone out.</p>${people.map(p => rowHtml(p, dim(p))).join("")}`
        + `<div class="rate-actions"><button type="button" class="btn" id="rate-done">Done</button></div>`
      : `<p class="rate-hint">Nobody to rate yet. <a href="#/settings" data-close>Add the family in Settings</a>.</p>`)
    + `</div>`;
  document.body.appendChild(rateSheet);
  for (const row of rateSheet.querySelectorAll(".rate-row")) paintRow(row, now[row.dataset.person]);
  // a tap on the slider counts even where it already rests (no input event then), so 7 can be given in one tap
  const slid = e => {
    const slider = e.target.closest(".rate-slider");
    if (!slider) return;
    const row = slider.closest(".rate-row");
    now[row.dataset.person] = Number(slider.value);
    paintRow(row, now[row.dataset.person]);
  };
  rateSheet.addEventListener("input", slid);
  rateSheet.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) return closeRateSheet();
    const clear = e.target.closest(".rate-clear");
    if (clear) {
      const row = clear.closest(".rate-row");
      now[row.dataset.person] = null;
      paintRow(row, null);
      row.querySelector(".rate-slider").focus();
    } else if (e.target.closest(".rate-slider")) {
      slid(e);
    } else if (e.target.closest("#rate-done")) {
      saveRatings(m, before, now, onSaved, e.target.closest("#rate-done"));
    }
  });
  document.addEventListener("keydown", onRateKey);
  (rateSheet.querySelector(".rate-slider") || rateSheet.querySelector("[data-close]")).focus();
}

export { dotHtml, dotsHtml, openRatingSheet, starText };
