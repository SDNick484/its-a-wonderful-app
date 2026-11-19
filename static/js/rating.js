// It's a Wonderful App: ratings. The star on a poster, the dot row on the detail view and the rating sheet (spec §11):
// one row per person, number buttons 1-10 and a ½ button, 44 px or more each. Imports only core.js; the caller says what
// to do with a saved rating (onSaved), so this module never touches the grid.
import { api, esc, toast } from "./core.js";

const NUMBERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
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
// Each row's value is a number from 0 to 10 in 0.5 steps, or null (not rated). The ½ button adds a half to the chosen
// number (8 then ½ is 8.5; ½ alone is 0.5); tapping the same value again clears it, so anyone can be left unrated.
function nextValue(value, button) {
  if (button.dataset.half !== undefined) {
    if (value === null) return 0.5;
    if (value % 1 !== 0) return value === 0.5 ? null : value - 0.5;
    return value < 10 ? value + 0.5 : value;
  }
  const n = Number(button.dataset.n);
  const half = value !== null && value % 1 !== 0;
  const next = half && n < 10 ? n + 0.5 : n;
  return next === value ? null : next;
}

function rowHtml(p) {
  const buttons = NUMBERS.map(n => `<button type="button" class="rate-btn" data-n="${n}" aria-pressed="false">${n}</button>`).join("")
    + `<button type="button" class="rate-btn" data-half aria-pressed="false" aria-label="and a half">½</button>`;
  return `<div class="rate-row" data-person="${p.person_id}"><div class="rate-who">${dotHtml(p)}`
    + `<span class="rate-name">${esc(p.name)}</span><span class="rate-val"></span></div>`
    + `<div class="rate-btns" role="group" aria-label="${esc(p.name)}'s rating">${buttons}</div></div>`;
}

function paintRow(row, value) {
  const half = value !== null && value % 1 !== 0;
  for (const b of row.querySelectorAll(".rate-btn")) {
    const on = b.dataset.half !== undefined ? half : value !== null && Math.floor(value) === Number(b.dataset.n) && value !== 0.5;
    b.setAttribute("aria-pressed", String(on));
  }
  row.querySelector(".rate-val").textContent = ratingText(value);
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
function openRatingSheet(m, from, onSaved) {
  if (rateSheet) return;
  rateOpener = from || null;
  const people = m.family?.by_person || [];
  const before = Object.fromEntries(people.map(p => [p.person_id, p.rating]));
  const now = { ...before };
  rateSheet = document.createElement("div");
  rateSheet.className = "sheet";
  rateSheet.innerHTML = `<div class="sheet-backdrop" data-close></div>`
    + `<div class="sheet-panel" role="dialog" aria-modal="true" aria-labelledby="rate-title">`
    + `<div class="sheet-head"><h2 id="rate-title" class="sheet-title">Rate ${esc(m.title)}</h2>`
    + `<button type="button" class="icon-btn icon-btn-quiet" data-close aria-label="Close">&times;</button></div>`
    + (people.length
      ? `<p class="rate-hint">Tap a number. ½ adds a half. Tap it again to clear. Anyone can be left out.</p>${people.map(rowHtml).join("")}`
        + `<div class="rate-actions"><button type="button" class="btn" id="rate-done">Done</button></div>`
      : `<p class="rate-hint">Nobody to rate yet. <a href="#/settings" data-close>Add the family in Settings</a>.</p>`)
    + `</div>`;
  document.body.appendChild(rateSheet);
  for (const row of rateSheet.querySelectorAll(".rate-row")) paintRow(row, now[row.dataset.person]);
  rateSheet.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) return closeRateSheet();
    const button = e.target.closest(".rate-btn");
    if (button) {
      const row = button.closest(".rate-row");
      const id = row.dataset.person;
      now[id] = nextValue(now[id], button);
      paintRow(row, now[id]);
    } else if (e.target.closest("#rate-done")) {
      saveRatings(m, before, now, onSaved, e.target.closest("#rate-done"));
    }
  });
  document.addEventListener("keydown", onRateKey);
  (rateSheet.querySelector(".rate-btn") || rateSheet.querySelector("[data-close]")).focus();
}

export { dotHtml, dotsHtml, openRatingSheet, starText };
