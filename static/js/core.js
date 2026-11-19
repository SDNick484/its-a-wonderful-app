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
function toast(msg, duration = 4000) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), duration);
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

export { api, APP_NAME, esc, state, toast };
