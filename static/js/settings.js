// It's a Wonderful App: the settings screen. Subscriptions: each streaming service is Subscribed, Considering or Ignore,
// and where-to-watch lines everywhere follow it (spec §7.2, decision 15). People: who rates (spec §8.4), copied from
// Matinee or added here. Look: Advent themes on or off, Light or Dark, and a preview of each theme (spec §14.2).
import { api, esc, toast } from "./core.js";
import { loadMovies } from "./grid.js";
import { dotHtml } from "./rating.js";
import { THEME_NAMES, previewTheme, savePrefs, themeInfo } from "./theme.js";

const CHOICES = [["subscribed", "Subscribed"], ["considering", "Considering"], ["ignore", "Ignore"]];

function serviceHtml(s) {
  const buttons = CHOICES.map(([value, label]) =>
    `<button type="button" class="seg-btn" data-status="${value}" aria-pressed="${s.status === value}">${label}</button>`).join("");
  return `<li class="svc" data-key="${esc(s.key)}"><span class="svc-name">${esc(s.name)}</span>`
    + `<div class="seg" role="group" aria-label="${esc(s.name)}">${buttons}</div></li>`;
}

function personHtml(p) {
  return `<li class="person">${dotHtml(p)}<span class="person-name">${esc(p.name)}</span><span class="person-kind">${p.kind === "kid" ? "Kid" : "Adult"}</span></li>`;
}

function peopleHtml(people) {
  const list = people.length ? `<ul class="people-list" id="people-list">${people.map(personHtml).join("")}</ul>`
    : `<p class="settings-hint" id="people-list">Nobody yet. Sync from Matinee or add someone below.</p>`;
  return `<h3 class="detail-label">People</h3>`
    + `<p class="settings-hint">The family who rate movies. Matinee's people are copied here by name; someone added here `
    + `(a visitor, say) rates too but isn't sent to Matinee.</p>`
    + list
    + `<div class="detail-actions"><button type="button" class="btn btn-quiet" id="people-sync">Sync people from Matinee</button></div>`
    + `<form id="person-form" class="person-form"><label class="sr-only" for="person-name">Name</label>`
    + `<input id="person-name" class="field" maxlength="40" autocomplete="off" placeholder="Add someone">`
    + `<label class="sr-only" for="person-kind">Adult or kid</label>`
    + `<select id="person-kind" class="field"><option value="adult">Adult</option><option value="kid">Kid</option></select>`
    + `<button type="submit" class="btn">Add</button></form>`;
}

const MODES = [["light", "Light"], ["dark", "Dark"], ["system", "System"]];
const PREVIEWS = [[null, "Today's"], ...Object.entries(THEME_NAMES), ["plain", "No theme"]];

function segHtml(label, name, choices, current) {
  const buttons = choices.map(([value, text]) =>
    `<button type="button" class="seg-btn" data-${name}="${esc(String(value))}" aria-pressed="${value === current}">${esc(text)}</button>`).join("");
  return `<div class="seg" role="group" aria-label="${esc(label)}">${buttons}</div>`;
}

// "January 6" from "2027-01-06" (a plain calendar date, so no time zone shifts it).
function longDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

function themeHint(info) {
  if (!info.today) return "Couldn't ask what today's theme is.";
  const name = THEME_NAMES[info.today.theme];
  if (name) return `Today it's the ${name.toLowerCase()} scene, through ${longDate(info.today.until)}.`;
  const [y, m, d] = info.today.until.split("-").map(Number);
  return `No theme today. The next one comes on ${new Date(y, m - 1, d + 1).toLocaleDateString(undefined, { month: "long", day: "numeric" })}.`;
}

function lookHtml() {
  const info = themeInfo();
  return `<h3 class="detail-label">Advent themes</h3>`
    + `<p class="settings-hint" id="theme-hint">${esc(themeHint(info))}</p>`
    + segHtml("Advent themes", "enabled", [[true, "On"], [false, "Off"]], info.prefs.enabled)
    + `<h3 class="detail-label">Light or dark</h3>`
    + `<p class="settings-hint">For the rest of the year. The Advent scenes are always dark.</p>`
    + segHtml("Light or dark", "mode", MODES, info.prefs.mode)
    + `<h3 class="detail-label">Preview themes</h3>`
    + `<p class="settings-hint">See a scene on this phone. It goes back to normal when you close the app.</p>`
    + `<div class="chips" role="group" aria-label="Preview themes">${PREVIEWS.map(([value, text]) =>
      `<button type="button" class="chip" data-preview="${esc(String(value))}" aria-pressed="${(value ?? null) === info.preview}">${esc(text)}</button>`).join("")}</div>`;
}

// Redraws the Look section, and puts keyboard focus back on the button that was just pressed.
function showLook(pressed) {
  const box = document.getElementById("look-box");
  if (!box) return;
  box.innerHTML = lookHtml();
  if (pressed) box.querySelector(`[${pressed.name}="${pressed.value}"]`)?.focus();
}

async function lookClick(e) {
  const pref = e.target.closest("[data-enabled], [data-mode]");
  if (pref) {
    const isOnOff = pref.dataset.enabled !== undefined;
    try {
      await savePrefs(isOnOff ? { enabled: pref.dataset.enabled === "true" } : { mode: pref.dataset.mode });
    } catch (err) {
      toast(`Couldn't save: ${err.message}`);
    }
    return showLook(isOnOff ? { name: "data-enabled", value: pref.dataset.enabled } : { name: "data-mode", value: pref.dataset.mode });
  }
  const preview = e.target.closest("[data-preview]");
  if (preview) {
    previewTheme(preview.dataset.preview === "null" ? null : preview.dataset.preview);
    showLook({ name: "data-preview", value: preview.dataset.preview });
  }
}

function settingsHtml(services) {
  return `<h2 class="section-title">Settings</h2>`
    + `<div id="look-box" class="look-box"></div>`
    + `<h3 class="detail-label">Subscriptions</h3>`
    + `<p class="settings-hint">Subscribed services make a movie ready to watch. Considering ones show "(you don't have it)". `
    + `Ignore hides a service everywhere.</p>`
    + `<ul class="svc-list">${services.map(serviceHtml).join("")}</ul>`
    + `<div id="people-box"></div>`;
}

// Redraws the People section from the server's list.
function showPeople(people) {
  document.getElementById("people-box").innerHTML = peopleHtml(people);
}

async function syncPeople(button) {
  button.disabled = true;
  try {
    const done = await api("/api/people/sync", { method: "POST" });
    showPeople(done.people);
    toast(done.added || done.updated ? `Added ${done.added}, updated ${done.updated}.` : "Already up to date.");
  } catch (e) {
    button.disabled = false;
    toast(`Couldn't sync: ${e.message}`);
  }
}

async function addPerson(form) {
  const name = form.querySelector("#person-name").value.trim();
  if (!name) return toast("Type a name.");
  try {
    await api("/api/people", { method: "POST", body: { name, kind: form.querySelector("#person-kind").value } });
    showPeople(await api("/api/people"));
    toast(`Added ${name}.`);
  } catch (e) {
    toast(`Couldn't add: ${e.message}`);
  }
}

function markPressed(li, status) {
  for (const b of li.querySelectorAll(".seg-btn")) b.setAttribute("aria-pressed", String(b.dataset.status === status));
}

async function setStatus(li, button) {
  const was = li.querySelector('.seg-btn[aria-pressed="true"]')?.dataset.status;
  const status = button.dataset.status;
  if (status === was) return;
  markPressed(li, status);
  try {
    await api("/api/services", { method: "PUT", body: { key: li.dataset.key, status } });
  } catch (e) {
    markPressed(li, was);
    toast(`Couldn't save: ${e.message}`);
    return;
  }
  await loadMovies();   // the cards' where-to-watch lines follow the new status
}

async function showSettings() {
  const box = document.getElementById("settings");
  box.innerHTML = `<p class="empty">Loading…</p>`;
  document.title = "Settings: It's a Wonderful App";
  let services;
  let people = null;
  try {
    [services, people] = await Promise.all([api("/api/services"), api("/api/people").catch(() => null)]);
  } catch (e) {
    box.innerHTML = `<p class="empty">${esc(e.message)}</p>`;
    return;
  }
  box.innerHTML = settingsHtml(services);
  showLook();
  document.getElementById("look-box").addEventListener("click", lookClick);
  box.querySelector(".svc-list").addEventListener("click", e => {
    const b = e.target.closest(".seg-btn");
    if (b) setStatus(b.closest(".svc"), b);
  });
  if (people) showPeople(people);
  else document.getElementById("people-box").innerHTML = `<p class="empty">Couldn't load the people.</p>`;
  const peopleBox = document.getElementById("people-box");   // new on every visit, so these listeners never pile up
  peopleBox.addEventListener("click", e => {
    const sync = e.target.closest("#people-sync");
    if (sync) syncPeople(sync);
  });
  peopleBox.addEventListener("submit", e => {
    if (!e.target.closest("#person-form")) return;
    e.preventDefault();
    addPerson(e.target);
  });
}

export { showSettings };
