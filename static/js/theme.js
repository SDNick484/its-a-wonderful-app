// It's a Wonderful App: the Advent themes (spec §14.2, §14.3). The server says which scene today gets (GET /api/theme,
// by the host's local date) and whether the household turned themes off or chose Light or Dark (GET /api/theme/prefs).
// This module puts the scene on the page: it sets data-theme on <html>, loads static/themes/<key>/theme.css (the art,
// the glow and the tuning), and runs one <canvas> of snow, sparks and the sleigh. Motion stops under
// prefers-reduced-motion and pauses while the tab is hidden. Imports only core.js.
import { api } from "./core.js";

const THEME_NAMES = { fireplace: "Fireplace", toystore: "Toy store", tree: "Christmas tree", sleigh: "Santa's sleigh" };
const PREVIEW_KEY = "wonderful-preview";   // sessionStorage: a preview lasts until the tab closes (spec §14.2)
const RECHECK_MS = 30 * 60 * 1000;         // a phone left open overnight asks again when it wakes
const SLEIGH_FIRST_MS = [4000, 9000];      // the first sleigh comes soon, so a preview shows it...
const SLEIGH_EVERY_MS = [45000, 90000];    // ...then one every 45 to 90 seconds
const SLEIGH_CROSS_MS = 11000;

const themeState = {
  today: null,                              // { theme, until } from /api/theme, or null when unreachable
  prefs: { enabled: true, mode: "system" },
  fetchedAt: 0,
  shown: null,                              // the theme key on screen, or null for the plain look
};

const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

// ================================================================= Preview (session only)
function readPreview() {
  try {
    const v = sessionStorage.getItem(PREVIEW_KEY);
    return v === "plain" || (v !== null && Object.hasOwn(THEME_NAMES, v)) ? v : null;
  } catch {
    return null;   // storage blocked: the preview lasts until the page reloads
  }
}
let previewMemory = null;
function getPreview() {
  return previewMemory ?? readPreview();
}

// "fireplace" | ... | "plain" (show the plain look) | null (back to what today says).
function previewTheme(choice) {
  previewMemory = choice;
  try {
    if (choice) sessionStorage.setItem(PREVIEW_KEY, choice);
    else sessionStorage.removeItem(PREVIEW_KEY);
  } catch {
    // keep it in memory only
  }
  applyTheme();
}

// The theme to show: a preview wins, then themes-off, then the calendar.
function chosenTheme() {
  const preview = getPreview();
  if (preview) return preview === "plain" ? null : preview;
  if (!themeState.prefs.enabled) return null;
  return themeState.today?.theme || null;
}

// ================================================================= The page
function setSheet(key) {
  let link = document.getElementById("theme-css");
  if (!key) {
    link?.remove();
    return;
  }
  const href = `/static/themes/${key}/theme.css`;
  if (!link) {
    link = document.createElement("link");
    link.id = "theme-css";
    link.rel = "stylesheet";
    document.head.appendChild(link);
  }
  if (link.getAttribute("href") !== href) link.setAttribute("href", href);
}

function applyTheme() {
  const root = document.documentElement;
  const key = chosenTheme();
  root.dataset.scheme = themeState.prefs.mode;
  if (key) root.dataset.theme = key;
  else delete root.dataset.theme;
  setSheet(key);
  themeState.shown = key;
  fx.setTheme(key);
}

// ================================================================= Snow, sparks and the sleigh
const fx = (() => {
  const canvas = () => document.getElementById("fx");
  const s = { key: null, raf: 0, last: 0, w: 0, h: 0, dpr: 1, flakes: [], sparks: [], sleighAt: 0, sleigh: null, sparkDebt: 0 };

  const rand = (a, b) => a + Math.random() * (b - a);

  // A CSS length like "75%" from the scene (theme.css owns where things are in its picture), as a 0-1 share.
  function share(name, fallback) {
    const v = getComputedStyle(document.getElementById("scene")).getPropertyValue(name).trim();
    return v.endsWith("%") && Number.isFinite(parseFloat(v)) ? parseFloat(v) / 100 : fallback;
  }

  function resize() {
    const c = canvas();
    if (!c) return;
    s.dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    s.w = c.clientWidth;
    s.h = c.clientHeight;
    c.width = Math.max(1, Math.round(s.w * s.dpr));
    c.height = Math.max(1, Math.round(s.h * s.dpr));
    const want = Math.max(18, Math.min(46, Math.round(s.w / 11)));
    while (s.flakes.length < want) s.flakes.push(newFlake(true));
    s.flakes.length = want;
  }

  function newFlake(anywhere) {
    return { x: rand(0, s.w), y: anywhere ? rand(0, s.h) : rand(-20, -4), r: rand(1, 2.6), vy: rand(14, 34),
             sway: rand(6, 18), phase: rand(0, 6.3), a: rand(0.35, 0.8) };
  }

  function newSpark() {
    const x = share("--fx-x", 0.5) * s.w + rand(-s.w * 0.1, s.w * 0.1);
    const y = share("--fx-y", 0.75) * s.h;
    return { x, y, vx: rand(-18, 18), vy: -rand(50, 130), life: 0, max: rand(1.1, 2.4), r: rand(0.8, 2) };
  }

  function nextSleigh(now, first) {
    const [a, b] = first ? SLEIGH_FIRST_MS : SLEIGH_EVERY_MS;
    s.sleighAt = now + rand(a, b);
  }

  // A plain gold silhouette: a sleigh with a rider and two animals ahead of it, facing right, drawn at scale u.
  function drawSleigh(ctx, x, y, u, t) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(u, u);
    ctx.fillStyle = "#f7d98a";
    ctx.strokeStyle = "#f7d98a";
    ctx.lineWidth = 0.07;
    ctx.lineCap = "round";
    ctx.beginPath();                                                    // the bowl
    ctx.moveTo(-1, -0.55); ctx.lineTo(-1, 0.1); ctx.quadraticCurveTo(-0.9, 0.45, -0.4, 0.45);
    ctx.lineTo(0.6, 0.45); ctx.quadraticCurveTo(1.05, 0.4, 1.15, -0.25); ctx.lineTo(0.95, -0.25);
    ctx.quadraticCurveTo(0.85, 0.1, 0.55, 0.1); ctx.lineTo(-0.6, 0.1); ctx.lineTo(-0.6, -0.55);
    ctx.closePath(); ctx.fill();
    ctx.beginPath();                                                    // the runner
    ctx.moveTo(-1.1, 0.68); ctx.lineTo(1.0, 0.68); ctx.quadraticCurveTo(1.4, 0.68, 1.3, 0.3); ctx.stroke();
    ctx.beginPath(); ctx.arc(-0.2, -0.78, 0.2, 0, 6.3); ctx.fill();     // the rider
    ctx.beginPath(); ctx.moveTo(-0.45, -0.6); ctx.lineTo(-0.2, -1.2); ctx.lineTo(0.05, -0.6); ctx.closePath(); ctx.fill();
    ctx.lineWidth = 0.035;
    for (const [i, off] of [[0, 2.7], [1, 4.3]]) {                      // two animals, legs galloping
      const bx = 1.3 + off;
      const swing = Math.sin(t * 9 + i * 1.7) * 0.28;
      ctx.beginPath(); ctx.ellipse(bx, -0.1, 0.52, 0.24, 0, 0, 6.3); ctx.fill();
      ctx.beginPath(); ctx.ellipse(bx + 0.6, -0.42, 0.18, 0.13, -0.5, 0, 6.3); ctx.fill();
      ctx.lineWidth = 0.07;
      ctx.beginPath();
      ctx.moveTo(bx - 0.35, 0); ctx.lineTo(bx - 0.5 - swing, 0.55);
      ctx.moveTo(bx - 0.2, 0.05); ctx.lineTo(bx - 0.15 + swing, 0.55);
      ctx.moveTo(bx + 0.3, 0.05); ctx.lineTo(bx + 0.45 - swing, 0.55);
      ctx.moveTo(bx + 0.4, 0); ctx.lineTo(bx + 0.7 + swing, 0.5);
      ctx.stroke();
      ctx.lineWidth = 0.035;
      ctx.beginPath();                                                  // antlers
      ctx.moveTo(bx + 0.62, -0.52); ctx.lineTo(bx + 0.5, -0.95); ctx.lineTo(bx + 0.62, -0.85);
      ctx.moveTo(bx + 0.5, -0.95); ctx.lineTo(bx + 0.36, -0.85);
      ctx.stroke();
    }
    ctx.lineWidth = 0.02;
    ctx.beginPath(); ctx.moveTo(1.15, -0.2); ctx.lineTo(1.8, -0.15); ctx.lineTo(3.3, -0.05); ctx.stroke();   // the reins
    ctx.restore();
  }

  function frame(now) {
    s.raf = requestAnimationFrame(frame);
    const c = canvas();
    if (!c) return;
    const dt = Math.min((now - (s.last || now)) / 1000, 0.06);
    s.last = now;
    const ctx = c.getContext("2d");
    ctx.setTransform(s.dpr, 0, 0, s.dpr, 0, 0);
    ctx.clearRect(0, 0, s.w, s.h);

    ctx.fillStyle = "#fff";
    for (const f of s.flakes) {                                          // gentle snow in all four
      f.y += f.vy * dt;
      f.phase += dt * 0.8;
      if (f.y > s.h + 4) Object.assign(f, newFlake(false), { x: rand(0, s.w) });
      ctx.globalAlpha = f.a;
      ctx.beginPath();
      ctx.arc(f.x + Math.sin(f.phase) * f.sway, f.y, f.r, 0, 6.3);
      ctx.fill();
    }

    if (s.key === "fireplace") {                                         // sparks rise from the fire
      s.sparkDebt += dt * 11;
      while (s.sparkDebt >= 1) { s.sparkDebt -= 1; s.sparks.push(newSpark()); }
      s.sparks = s.sparks.filter(p => p.life < p.max);
      for (const p of s.sparks) {
        p.life += dt;
        p.x += p.vx * dt + Math.sin(p.life * 6 + p.vy) * 0.4;
        p.y += p.vy * dt;
        const k = 1 - p.life / p.max;
        ctx.globalAlpha = Math.max(0, k);
        ctx.fillStyle = k > 0.5 ? "#ffd27a" : "#ff7a32";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * (0.5 + k), 0, 6.3);
        ctx.fill();
      }
    }

    if (s.key === "sleigh") {                                            // across the moon, now and then
      if (!s.sleigh && now >= s.sleighAt) s.sleigh = { t0: now };
      if (s.sleigh) {
        const k = (now - s.sleigh.t0) / SLEIGH_CROSS_MS;
        if (k >= 1) {
          s.sleigh = null;
          nextSleigh(now, false);
        } else {
          const u = Math.max(14, Math.min(s.w, s.h) * 0.05);
          const x = -u * 8 + k * (s.w + u * 12);
          const y = share("--moon-y", 0.16) * s.h + (0.5 - k) * s.h * 0.05 + Math.sin(k * 12) * u * 0.1;
          ctx.globalAlpha = 0.95;
          drawSleigh(ctx, x, y, u, now / 1000);
          for (let i = 1; i <= 14; i++) {                                // a trail of glitter behind it
            ctx.globalAlpha = 0.5 * (1 - i / 15) * (0.6 + 0.4 * Math.sin(now / 90 + i));
            ctx.fillStyle = "#fff4cc";
            ctx.beginPath();
            ctx.arc(x - u * 1.2 - i * u * 0.28, y + Math.sin(i * 1.3 + now / 200) * u * 0.18, u * 0.05, 0, 6.3);
            ctx.fill();
          }
        }
      }
    }
    ctx.globalAlpha = 1;
    c.dataset.frames = String(Number(c.dataset.frames || 0) + 1);
  }

  function run() {
    const c = canvas();
    if (!c) return;
    const want = Boolean(s.key) && !document.hidden && !reduced.matches;
    if (want && !s.raf) {
      resize();
      s.last = 0;
      s.raf = requestAnimationFrame(frame);
    } else if (!want && s.raf) {
      cancelAnimationFrame(s.raf);
      s.raf = 0;
    }
    if (!want) c.getContext("2d").clearRect(0, 0, c.width, c.height);
    c.dataset.running = String(Boolean(s.raf));
  }

  function setTheme(key) {
    if (key !== s.key) {
      s.key = key;
      s.sparks = [];
      s.sleigh = null;
      nextSleigh(performance.now(), true);
    }
    run();
  }

  function wire() {
    document.addEventListener("visibilitychange", run);
    reduced.addEventListener("change", run);
    window.addEventListener("resize", () => {
      if (s.raf) resize();
    });
  }
  return { setTheme, wire, run };
})();

// ================================================================= Loading and settings
async function loadTheme() {
  const [today, prefs] = await Promise.all([api("/api/theme").catch(() => null), api("/api/theme/prefs").catch(() => null)]);
  if (today) themeState.today = today;
  if (prefs) themeState.prefs = prefs;
  themeState.fetchedAt = Date.now();
  applyTheme();
}

async function startTheme() {
  fx.wire();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() - themeState.fetchedAt > RECHECK_MS) loadTheme();   // Sunday may have come
  });
  await loadTheme();
}

// What the settings screen shows: today's calendar answer, the household's choices, the preview, what is on screen.
function themeInfo() {
  return { today: themeState.today, prefs: { ...themeState.prefs }, preview: getPreview(), shown: themeState.shown };
}

// Saves Themes on/off and/or Light/Dark/System for the whole household, and shows the change at once.
async function savePrefs(patch) {
  themeState.prefs = await api("/api/theme/prefs", { method: "PUT", body: patch });
  applyTheme();
  return { ...themeState.prefs };
}

export { THEME_NAMES, previewTheme, savePrefs, startTheme, themeInfo };
