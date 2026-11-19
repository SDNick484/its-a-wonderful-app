// It's a Wonderful App: the settings screen. Subscriptions today: each streaming service is Subscribed, Considering
// or Ignore, and where-to-watch lines everywhere follow it (spec §7.2, decision 15).
import { api, esc, toast } from "./core.js";
import { loadMovies } from "./grid.js";

const CHOICES = [["subscribed", "Subscribed"], ["considering", "Considering"], ["ignore", "Ignore"]];

function serviceHtml(s) {
  const buttons = CHOICES.map(([value, label]) =>
    `<button type="button" class="seg-btn" data-status="${value}" aria-pressed="${s.status === value}">${label}</button>`).join("");
  return `<li class="svc" data-key="${esc(s.key)}"><span class="svc-name">${esc(s.name)}</span>`
    + `<div class="seg" role="group" aria-label="${esc(s.name)}">${buttons}</div></li>`;
}

function settingsHtml(services) {
  return `<h2 class="section-title">Settings</h2>`
    + `<h3 class="detail-label">Subscriptions</h3>`
    + `<p class="settings-hint">Subscribed services make a movie ready to watch. Considering ones show "(you don't have it)". `
    + `Ignore hides a service everywhere.</p>`
    + `<ul class="svc-list">${services.map(serviceHtml).join("")}</ul>`;
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
  try {
    services = await api("/api/services");
  } catch (e) {
    box.innerHTML = `<p class="empty">${esc(e.message)}</p>`;
    return;
  }
  box.innerHTML = settingsHtml(services);
  box.querySelector(".svc-list").addEventListener("click", e => {
    const b = e.target.closest(".seg-btn");
    if (b) setStatus(b.closest(".svc"), b);
  });
}

export { showSettings };
