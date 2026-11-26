// It's a Wonderful App: Play on the Family Room TV (design 2026-11-26, §5.3, §5.4). playHtml draws the movie page's
// section; startPlay owns the tap: one request at a time, the messages, and the watch for the TV to say it got there.
// Task 5 calls startPlay from the main page with its own `say` (a toast), so nothing here touches the movie's page.
import { api, esc, tvIsOn } from "./core.js";

const PLAY_POLL_MS = 3000;       // ask where the TV is this often...
const PLAY_WAIT_MS = 90000;      // ...for this long, then say it didn't answer
const SLACK_MS = 5000;           // an event this far before the tap still counts (the clocks of two machines)

let inFlight = false;             // a play request is in flight: another tap sends nothing
let playRound = 0;               // which play the TV watch belongs to; a newer play ends an older watch

// window.__playTimings = {poll, wait} (ms) lets a browser test shorten the 3 s and 90 s.
function timings() {
  const t = window.__playTimings || {};
  return { poll: t.poll ?? PLAY_POLL_MS, wait: t.wait ?? PLAY_WAIT_MS };
}

// ================================================================= the section
function streamBox(s, many) {
  const line = s.owned ? `Our digital copy · ${s.name}` : `On ${s.name}`;
  return `<div class="play-box"><p class="play-line">${esc(line)}</p>`
    + `<button type="button" class="btn" data-play="stream" data-service="${esc(s.service)}">${esc(many ? `Stream it on ${s.name}` : "Stream it")}</button></div>`;
}

// "Play on the Family Room TV": the disc box (the shelf line, Start the disc), a box per service, and the status line
// under them. "" when Play is off for this movie (m.play is null) or nothing can play it.
function playHtml(m) {
  const play = m.play;
  const stream = play?.stream || [];
  if (!play || (!stream.length && !play.disc)) return "";
  return `<section id="detail-play-box"><h3 class="detail-label">Play on the Family Room TV</h3>`
    + (play.disc ? `<div class="play-box"><p class="play-line">${esc(play.disc.label)}</p>`
      + `<button type="button" class="btn" data-play="disc">Start the disc</button></div>` : "")
    + stream.map(s => streamBox(s, stream.length > 1)).join("")
    + `<p class="play-status" id="detail-play-status" aria-live="polite"></p></section>`;
}

// ================================================================= the tap
// What the opening line calls the target: the service's name, or "the disc".
function openingName(movie, body) {
  const play = movie.play || {};
  const kind = body.mode === "auto" ? play.auto : body.mode;
  if (kind === "disc") return "the disc";
  const stream = play.stream || [];
  const pick = body.service ? stream.find(s => s.service === body.service) : stream[0];
  return pick ? pick.name : movie.title;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// True when `tv` ({state, source, at}) says the TV came on the answer's input at or after the tap. `at` and `sent_at`
// carry different offsets, so they are compared as dates, never as strings.
function arrived(tv, answer) {
  return tvIsOn(tv) && typeof tv.source === "string" && tv.source.toLowerCase() === answer.source.toLowerCase()
    && Boolean(tv.at) && new Date(tv.at).getTime() >= new Date(answer.sent_at).getTime() - SLACK_MS;
}

// A disc's messages end with the shelf line, so whoever reads one can go and get the disc.
function sentence(answer, text) {
  return answer.mode === "disc" ? `${text} ${answer.label}: go get it!` : text;
}

function confirmed(answer) {
  return answer.mode === "disc" ? `The TV is ready. ${answer.label}: go get it!` : `${answer.name} is open on the Family Room TV.`;
}

// Ask the TV's state every poll interval until it is on the target, or the wait is up. Stops quietly when a newer play
// has begun.
async function watchTv(answer, say, mine) {
  const { poll, wait } = timings();
  const sticky = answer.mode === "disc";
  const end = Date.now() + wait;
  while (Date.now() < end) {
    await sleep(poll);
    if (mine !== playRound) return;
    let tv = null;
    try {
      tv = await api("/api/tv");
    } catch {
      // one missed look is nothing: the next one tries again
    }
    if (mine !== playRound) return;
    if (tv && arrived(tv, answer)) {
      say(confirmed(answer), sticky);
      return;
    }
  }
  say(sentence(answer, "The TV didn't answer. Try the remote."), sticky);
}

// Play `movie` with `body` ({mode: "auto" | "stream" | "disc", service?}), telling `say(text, sticky)` how it goes: Opening...,
// then the server's sentence on a failure, or what §5.3 settles (confirmed, "Sent to the TV." when the TV has never
// reported, or the answer after watching it). A disc's messages are `sticky`: they carry the shelf line, so they stay
// until dismissed. Resolves, when the server answers and not when the TV does, to the server's answer, or null on a
// failure or when another play is still waiting for its answer.
async function startPlay(movie, body, say) {
  if (inFlight) return null;
  inFlight = true;
  const mine = ++playRound;
  const asked = body.mode === "auto" ? movie.play?.auto : body.mode;
  say(`Opening ${openingName(movie, body)} on the Family Room TV…`, asked === "disc");
  let answer;
  try {
    answer = await api(`/api/movies/${movie.id}/play`, { method: "POST", body });
  } catch (e) {
    say(e.status ? e.message : "Couldn't send that. Check the connection and try again.", asked === "disc");
    return null;
  } finally {
    inFlight = false;
  }
  const sticky = answer.mode === "disc";
  if (answer.confirmed) {
    say(confirmed(answer), sticky);
  } else if (!answer.tv?.at) {
    say(sentence(answer, "Sent to the TV."), sticky);      // the TV has never reported: the events automation isn't set up
  } else {
    if (sticky) say(`${answer.label}: go get it!`, true);   // the shelf line doesn't wait for the TV
    watchTv(answer, say, mine);
  }
  return answer;
}

export { playHtml, startPlay };
