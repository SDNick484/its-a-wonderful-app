// It's a Wonderful App: Continue Watching (spec §10). The row above the grid (only when something is in it), Watch
// tonight, Keep watching tonight, We finished, We gave up on it, the "Did you finish?" sheet with the guess highlighted
// (never answered for you), and the rating sheet after a finish, with the viewing's people first.
import { api, esc, toast } from "./core.js";
import { loadMovies, posterHtml, watchPosters } from "./grid.js";
import { openRatingSheet } from "./rating.js";

let continueRows = [];          // the open viewings, tonight's first (GET /api/continue)
let continueSheet = null;
let continueOpener = null;

// ================================================================= the row
function continueStatus(v) {
  if (v.status === "watching") return "Watching now";
  if (v.status === "tonight") return "Tonight";
  return v.progress || "Paused";
}

function itemHtml(v) {
  return `<button type="button" class="continue-item" data-viewing="${v.viewing_id}" aria-label="${esc(`${v.title}: ${continueStatus(v)}`)}">`
    + `<div class="poster-wrap">${posterHtml(v)}</div>`
    + `<span class="card-title">${esc(v.title)}</span>`
    + `<span class="continue-status" data-status="${esc(v.status)}">${esc(continueStatus(v))}</span></button>`;
}

function renderContinue() {
  const box = document.getElementById("continue");
  if (!box) return;
  box.hidden = continueRows.length === 0;
  document.getElementById("continue-row").innerHTML = continueRows.map(itemHtml).join("");
}

// Fetch the row again and redraw it. A failure leaves what is on screen.
async function loadContinue() {
  try {
    continueRows = (await api("/api/continue")).viewings;
  } catch {
    // keep the last row; the next load tries again
  }
  renderContinue();
}

// ================================================================= sheets
function closeContinueSheet() {
  if (!continueSheet) return;
  continueSheet.remove();
  continueSheet = null;
  document.removeEventListener("keydown", onContinueKey);
  if (continueOpener && continueOpener.isConnected) continueOpener.focus();
  continueOpener = null;
}

function onContinueKey(e) {
  if (e.key === "Escape") closeContinueSheet();
}

// A bottom sheet with a title and `body`; `onClick(target)` gets every click that isn't a close.
function openContinueSheet(id, title, body, from, onClick) {
  closeContinueSheet();
  continueOpener = from || null;
  continueSheet = document.createElement("div");
  continueSheet.className = "sheet";
  continueSheet.id = id;
  continueSheet.innerHTML = `<div class="sheet-backdrop" data-close></div>`
    + `<div class="sheet-panel" role="dialog" aria-modal="true" aria-labelledby="${id}-title">`
    + `<div class="sheet-head"><h2 id="${id}-title" class="sheet-title">${title}</h2>`
    + `<button type="button" class="icon-btn icon-btn-quiet" data-close aria-label="Close">&times;</button></div>`
    + body + `</div>`;
  document.body.appendChild(continueSheet);
  continueSheet.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) return closeContinueSheet();
    onClick(e.target);
  });
  document.addEventListener("keydown", onContinueKey);
  (continueSheet.querySelector(".sheet-actions .btn") || continueSheet.querySelector("[data-close]")).focus();
}

function disableContinueSheet() {
  if (continueSheet) for (const b of continueSheet.querySelectorAll("button")) b.disabled = true;
}

// ================================================================= actions
// Watch tonight on a movie: its viewing (new, or the open one again). Returns the viewing, or null when it failed.
async function watchTonight(movieId) {
  try {
    const v = await api(`/api/movies/${movieId}/tonight`, { method: "POST" });
    toast(`${v.title} is on for tonight.`);
    await loadContinue();
    return v;
  } catch (e) {
    toast(`Couldn't save: ${e.message}`);
    return null;
  }
}

async function keepWatching(v) {
  try {
    const saved = await api(`/api/viewings/${v.viewing_id}/keep`, { method: "POST" });
    toast(`${v.title} is on for tonight.`);
    await loadContinue();
    return saved;
  } catch (e) {
    toast(`Couldn't save: ${e.message}`);
    return null;
  }
}

async function giveUp(v) {
  try {
    const saved = await api(`/api/viewings/${v.viewing_id}/abandon`, { method: "POST" });
    toast(`${v.title} is off the row.`);
    await loadContinue();
    return saved;
  } catch (e) {
    toast(`Couldn't save: ${e.message}`);
    return null;
  }
}

// After a finish (spec §11) the rating sheet opens by itself, with the viewing's people first; closing it rates nobody.
async function rateAfterFinish(v, onRated) {
  closeContinueSheet();
  let m;
  try {
    m = await api(`/api/movies/${v.movie_id}`);
  } catch (e) {
    toast(`Couldn't open the ratings: ${e.message}`);
    return;
  }
  openRatingSheet(m, null, saved => {
    if (onRated) onRated(saved);
    loadMovies();
  }, v.people);
}

// We finished: Matinee gets the watch and Home Assistant the movie log (server side), then the rating sheet.
// `onRated` gets the saved ratings (the detail view redraws with them). Returns the viewing, or null.
async function finishViewing(v, onRated) {
  let saved;
  try {
    saved = await api(`/api/viewings/${v.viewing_id}/finish`, { method: "POST" });
  } catch (e) {
    closeContinueSheet();
    toast(e.status === 409 ? e.message : `Couldn't save: ${e.message}`);
    await loadContinue();
    return null;
  }
  toast(saved.watch_pending ? `${v.title} is finished. Matinee gets it tonight.` : `${v.title} is finished.`);
  await loadContinue();
  rateAfterFinish(saved, onRated);
  return saved;
}

// Tapping a movie in the row: Keep watching tonight (when it is paused), We finished, its details, or give up.
function openActions(v, from) {
  const keep = v.status === "paused" ? `<button type="button" class="btn" data-act="keep">Keep watching tonight</button>` : "";
  openContinueSheet("continue-actions", esc(v.title),
    `<p class="sheet-text">${esc(continueStatus(v))}</p>`
    + `<div class="sheet-actions">${keep}`
    + `<button type="button" class="btn${keep ? " btn-quiet" : ""}" data-act="finish">We finished</button>`
    + `<a class="btn btn-quiet" href="#/m/${v.movie_id}" data-close>Movie details</a></div>`
    + `<button type="button" class="link-btn" data-act="abandon">We gave up on it</button>`,
    from, async target => {
      const act = target.closest("[data-act]")?.dataset.act;
      if (!act) return;
      disableContinueSheet();
      if (act === "keep") {
        await keepWatching(v);
        closeContinueSheet();
      } else if (act === "finish") {
        await finishViewing(v);
      } else if (act === "abandon") {
        await giveUp(v);
        closeContinueSheet();
      }
    });
}

// ================================================================= "Did you finish?" (spec §10.3)
// The guess is highlighted (the filled button, data-guess) but still needs a tap. With no guess neither is.
function openPrompt(p) {
  const yesGuess = p.guess === "finished";
  const noGuess = p.guess === "not_finished";
  const v = { viewing_id: p.viewing_id, title: p.title, movie_id: p.movie_id, people: p.people };
  openContinueSheet("finish-prompt", `Did you finish <em>${esc(p.title)}</em>?`,
    `<div class="sheet-actions prompt-actions">`
    + `<button type="button" class="btn${yesGuess ? "" : " btn-quiet"}" data-ans="yes"${yesGuess ? ' data-guess="true"' : ""}>Yes</button>`
    + `<button type="button" class="btn${noGuess ? "" : " btn-quiet"}" data-ans="not-yet"${noGuess ? ' data-guess="true"' : ""}>Not yet</button></div>`
    + `<button type="button" class="link-btn" data-ans="abandon">We gave up on it</button>`,
    null, async target => {
      const ans = target.closest("[data-ans]")?.dataset.ans;
      if (!ans) return;
      disableContinueSheet();
      if (ans === "yes") {
        await finishViewing(v);
        return;
      }
      if (ans === "abandon") {
        await giveUp(v);
      } else {
        try {
          await api(`/api/viewings/${v.viewing_id}/not-yet`, { method: "POST" });
          await loadContinue();
        } catch (e) {
          toast(`Couldn't save: ${e.message}`);
        }
      }
      closeContinueSheet();
    });
}

// Ask once per app open (and when the phone comes back to it) whether a movie the TV stopped was finished.
async function checkPrompt() {
  if (continueSheet || document.querySelector(".sheet")) return;   // never on top of another sheet
  let p = null;
  try {
    p = (await api("/api/prompt")).prompt;
  } catch {
    return;
  }
  if (!p) return;
  openPrompt(p);
}

function wireContinue() {
  const row = document.getElementById("continue-row");
  watchPosters(row);
  row.addEventListener("click", e => {
    const item = e.target.closest("[data-viewing]");
    const v = item && continueRows.find(r => r.viewing_id === Number(item.dataset.viewing));
    if (v) openActions(v, item);
  });
  document.addEventListener("visibilitychange", async () => {
    if (document.visibilityState !== "visible") return;
    await loadContinue();
    checkPrompt();
  });
}

export { checkPrompt, closeContinueSheet, finishViewing, keepWatching, loadContinue, openContinueSheet, watchTonight, wireContinue };
