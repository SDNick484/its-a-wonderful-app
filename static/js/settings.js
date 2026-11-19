// It's a Wonderful App: the settings screen. Subscriptions: each streaming service is Subscribed, Considering or Ignore,
// and where-to-watch lines everywhere follow it (spec §7.2, decision 15). People: who rates (spec §8.4), copied from
// Matinee or added here.
import { api, esc, toast } from "./core.js";
import { loadMovies } from "./grid.js";
import { dotHtml } from "./rating.js";

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

function settingsHtml(services) {
  return `<h2 class="section-title">Settings</h2>`
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
