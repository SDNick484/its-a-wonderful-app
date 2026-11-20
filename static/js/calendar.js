// It's a Wonderful App: the Calendar (calendar spec §6). A top tab at #/calendar[/YYYY-MM]: one month as a Sunday-first
// grid with a poster on each night we watched a movie; a tap opens that night's list. The month shown is the one the
// server answered for (never the browser clock), and the date math is plain arithmetic, so the browser's time zone
// can't shift a day.
import { APP_NAME, api, esc } from "./core.js";
import { posterHtml, watchPosters } from "./grid.js";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
  "November", "December"];
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

let calShown = 0;          // bumps on every showCalendar, so an answer for a month we've left is dropped
let calSheet = null;
let calOpener = null;

function calMonthKey(year, month) {
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}`;
}

// "2026-12" moved by `by` months, as "YYYY-MM".
function calShift(year, month, by) {
  const total = year * 12 + (month - 1) + by;
  return calMonthKey(Math.floor(total / 12), (total % 12) + 1);
}

function calDaysIn(year, month) {
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

function calWeekday(year, month, day) {
  const d = new Date(0);
  d.setUTCFullYear(year, month - 1, day);   // not Date.UTC, which reads years 0 to 99 as 1900s
  return d.getUTCDay();
}

// ================================================================= the day sheet
function closeCalSheet() {
  if (!calSheet) return;
  calSheet.remove();
  calSheet = null;
  document.removeEventListener("keydown", onCalKey);
  window.removeEventListener("hashchange", closeCalSheet);
  if (calOpener && calOpener.isConnected && !document.getElementById("calendar-view").hidden) calOpener.focus();
  calOpener = null;
}

function onCalKey(e) {
  if (e.key === "Escape") closeCalSheet();
}

function calRowHtml(e) {
  const label = e.year ? `${e.title} (${e.year})` : e.title;
  return `<a class="cal-row" href="#/m/${e.movie_id}">`
    + `<span class="poster-wrap cal-row-poster">${posterHtml(e)}</span>`
    + `<span class="cal-row-text"><span class="cal-row-title">${esc(label)}</span>`
    + (e.finished ? `<span class="cal-row-done">Finished</span>` : "")
    + `</span></a>`;
}

// The same bottom sheet as continue.js's: a title, a close button, Escape, and focus back on the day afterwards.
function openCalSheet(cell, date, entries) {
  closeCalSheet();
  calOpener = cell;
  const [year, month, day] = date.split("-").map(Number);
  const title = `${WEEKDAYS[calWeekday(year, month, day)]}, ${MONTHS[month - 1]} ${day}`;
  calSheet = document.createElement("div");
  calSheet.className = "sheet";
  calSheet.id = "calendar-sheet";
  calSheet.innerHTML = `<div class="sheet-backdrop" data-close></div>`
    + `<div class="sheet-panel" role="dialog" aria-modal="true" aria-labelledby="calendar-sheet-title">`
    + `<div class="sheet-head"><h2 id="calendar-sheet-title" class="sheet-title">${esc(title)}</h2>`
    + `<button type="button" class="icon-btn icon-btn-quiet" data-close aria-label="Close">&times;</button></div>`
    + `<div class="cal-rows">${entries.map(calRowHtml).join("")}</div></div>`;
  document.body.appendChild(calSheet);
  watchPosters(calSheet);
  calSheet.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) closeCalSheet();
  });
  document.addEventListener("keydown", onCalKey);
  window.addEventListener("hashchange", closeCalSheet);   // a row is a link to the movie
  calSheet.querySelector("[data-close]").focus();
}

// ================================================================= the month
function calDayHtml(year, month, day, entries, today) {
  const date = `${calMonthKey(year, month)}-${String(day).padStart(2, "0")}`;
  const ring = date === today ? " cal-today" : "";
  const num = `<span class="cal-num">${day}</span>`;
  if (!entries) return `<div class="cal-day cal-empty${ring}">${num}</div>`;
  const done = entries.some(e => e.finished);
  const label = `${MONTHS[month - 1].slice(0, 3)} ${day}: ${entries.map(e => e.title).join(", ")}.`
    + (done ? " A movie finished." : "");
  return `<button type="button" class="cal-day${ring}" data-date="${date}" aria-label="${esc(label)}">`
    + `<span class="cal-poster">${posterHtml(entries[0])}</span>${num}`
    + (entries.length > 1 ? `<span class="cal-more">+${entries.length - 1}</span>` : "")
    + (done ? `<span class="cal-done" aria-hidden="true">&#10003;&#xFE0E;</span>` : "")
    + `</button>`;
}

function calMonthHtml(year, month, days, today) {
  const heads = ["S", "M", "T", "W", "T", "F", "S"].map(d => `<div class="cal-wd" aria-hidden="true">${d}</div>`);
  const blanks = Array.from({ length: calWeekday(year, month, 1) }, () => `<div class="cal-blank"></div>`);
  const cells = [];
  for (let day = 1; day <= calDaysIn(year, month); day++) {
    cells.push(calDayHtml(year, month, day, days[`${calMonthKey(year, month)}-${String(day).padStart(2, "0")}`], today));
  }
  return heads.concat(blanks, cells).join("");
}

// Asks the server for `month` ("YYYY-MM", or null for this month) and paints the tab. Called each time the tab opens.
async function showCalendar(month) {
  const ticket = ++calShown;
  const box = document.getElementById("calendar-grid");
  const status = document.getElementById("calendar-status");
  document.title = `Calendar · ${APP_NAME}`;
  if (!box.dataset.posters) {   // the poster error fallback is attached once per box element
    watchPosters(box);
    box.dataset.posters = "1";
  }
  box.innerHTML = "";
  status.textContent = "Loading…";
  let data = null;
  try {
    data = await api(month ? `/api/calendar?month=${encodeURIComponent(month)}` : "/api/calendar");
  } catch {
    data = null;
  }
  if (ticket !== calShown) return;
  if (!data) {
    status.textContent = "Couldn't load the calendar right now.";
    return;
  }
  const [year, mon] = data.month.split("-").map(Number);
  document.getElementById("calendar-title").textContent = `${MONTHS[mon - 1]} ${year}`;
  document.getElementById("calendar-prev").href = `#/calendar/${calShift(year, mon, -1)}`;
  document.getElementById("calendar-next").href = `#/calendar/${calShift(year, mon, 1)}`;
  box.innerHTML = calMonthHtml(year, mon, data.days, data.today);
  status.textContent = Object.keys(data.days).length ? "" : `Nothing watched in ${MONTHS[mon - 1]} yet.`;
  for (const cell of box.querySelectorAll("button.cal-day")) {
    cell.addEventListener("click", () => openCalSheet(cell, cell.dataset.date, data.days[cell.dataset.date]));
  }
}

export { showCalendar };
