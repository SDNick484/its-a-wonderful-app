// It's a Wonderful App: constants, shared state and helpers (api, esc, toast). Imports nothing (CLAUDE.md).

const APP_NAME = "It's a Wonderful App";

// ================================================================= State
const state = {
  movies: [],
  shownIds: null,   // the ids the grid shows, in list order; null shows the whole list (search.js sets it)
  whys: {},         // movie id -> the one-line reason smart search gave for it (search.js sets it, the grid shows it)
};

// ================================================================= Helpers
function esc(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

let toastTimer = null;
let toastWired = false;
// Shows `msg` for `duration` ms. A duration of 0 keeps it up until it is tapped or another message replaces it (a
// message someone has to read and act on, like the shelf a disc is on).
function toast(msg, duration = 4000) {
  const el = document.getElementById("toast");
  if (!el) return;
  if (!toastWired) {
    toastWired = true;
    el.addEventListener("click", () => el.classList.remove("show"));
  }
  el.textContent = msg;
  if (duration === 0) el.classList.add("sticky");
  else el.classList.remove("sticky");
  el.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = duration > 0 ? setTimeout(() => el.classList.remove("show"), duration) : null;
}

// The media_player states that mean the Family Room TV is on, and whether GET /api/tv's answer says so.
const TV_ON_STATES = ["on", "playing", "paused", "idle", "buffering"];
function tvIsOn(tv) {
  return TV_ON_STATES.includes(tv.state);
}

// fetch() for the JSON API: sends a JSON body, throws an Error with .status (and the server's message) on failure.
async function api(path, opts = {}) {
  const headers = { Accept: "application/json", ...(opts.headers || {}) };
  let body = opts.body;
  if (body && typeof body === "object" && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const res = await fetch(path, { ...opts, body, headers });
  if (!res.ok) {
    let data = {};
    try {
      data = await res.json();
    } catch {
      // not JSON
    }
    if (res.status === 401) toast("Sign in first, then reload the page.");
    const err = new Error(data.error || res.statusText || "Request failed");
    err.status = res.status;
    throw err;
  }
  return await res.json();
}

export { api, APP_NAME, esc, state, toast, tvIsOn };
