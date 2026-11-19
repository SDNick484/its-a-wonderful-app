# Home Assistant and the Family Room TV

The app guesses whether a movie was finished from the Family Room TV (spec §10.2). Home Assistant tells it when the
TV turns on or off and when its input (`source`) changes; the app never configures Home Assistant itself. This page
is the Home Assistant side. The names here are placeholders: `ha.example.com` for Home Assistant,
`wonderful.example.com` / `192.168.1.100:8772` for the app, `media_player.family_room_tv` for the TV.

(The other direction, the Family Room movie log that every finished movie is posted to, is `HA_WEBHOOK_URL`; see the
README.)

## What the app does with the events

Only while exactly one movie is picked for tonight (**Watch tonight**, or **Keep watching tonight** on a paused one):

| The TV | The app |
|---|---|
| On, on an input that can play the movie | Opens a session; the movie is "watching" |
| On another input (YouTube, Live TV) while a session is open | Closes it (`source_changed`) |
| Off (or `standby`) while a session is open | Closes it (`tv_off`) |
| A session open longer than the runtime + 60 min | Closed at runtime + 60 (`timeout`); 4 hours with no runtime |

An input can play the movie when it is the `tv_source` of a streaming service TMDB lists the movie on
(`data/services.json`: `Netflix`, `Disney+`, `HBO Max` ...), or `AV Receiver` when Matinee says the movie is owned (a
disc). Closing a session adds its length to the movie's watched time and guesses: finished at 85 % of the runtime,
otherwise not; no guess when the runtime is unknown. The next time anyone opens the app it asks **Did you finish?**
with the guess highlighted. The movie is paused after a session closes, so a second night needs **Keep watching
tonight** before the TV counts again.

Everything else changes nothing and still answers 200: an event no newer than the last one (Home Assistant sending
it twice, or late and out of order by `at`), "on" with a session already open, "off" with none, no movie picked, two
picked, an `unavailable` TV, or no `source`. The answer says why:

```json
{"ok": true, "applied": false, "action": "ignored", "reason": "session already open"}
```

## Set it up

1. Find the TV's entity and its input names: **Developer tools → States**, `media_player.family_room_tv` (yours will
   be named differently). The `source` attribute must match a `tv_source` in `data/services.json` exactly as the TV
   spells it (case doesn't matter); the receiver input must be `AV Receiver`. If your TV names an app differently,
   change `tv_source` in `data/services.json` and restart the app (`rc-service wonderful restart`).
2. Put the hook secret in Home Assistant's `secrets.yaml`. It is `HA_HOOK_SECRET` in `/etc/conf.d/wonderful` on the
   app's host (the installer generated it):

   ```yaml
   wonderful_hook_secret: "the HA_HOOK_SECRET value"
   ```

3. Add the REST command to `configuration.yaml` (`vim /config/configuration.yaml`) and restart Home Assistant. Use
   the app's LAN address: through Cloudflare, Access would stop the request before the app sees it.

   ```yaml
   rest_command:
     wonderful_tv:
       url: "http://192.168.1.100:8772/hooks/tv"
       method: POST
       content_type: "application/json"
       headers:
         X-Hook-Secret: !secret wonderful_hook_secret
       payload: >-
         {"state": "{{ states(tv) }}",
          "source": "{{ state_attr(tv, 'source') }}",
          "at": "{{ now().isoformat() }}"}
   ```

   A missing `source` renders as `"None"`; the app reads that as no source.

4. Add the automation (**Settings → Automations → Create → Edit in YAML**). It fires when the TV's state changes
   (`to: null` leaves out attribute-only changes such as volume) and when its `source` changes. `mode: queued` keeps
   the events in order.

   ```yaml
   alias: "Family Room TV to It's a Wonderful App"
   mode: queued
   triggers:
     - trigger: state
       entity_id: media_player.family_room_tv
       to: null
     - trigger: state
       entity_id: media_player.family_room_tv
       attribute: source
   actions:
     - action: rest_command.wonderful_tv
       data:
         tv: media_player.family_room_tv
   ```

## Check it

From a machine on the LAN, with nothing picked for tonight:

```sh
curl -s -X POST http://192.168.1.100:8772/hooks/tv \
  -H 'Content-Type: application/json' -H 'X-Hook-Secret: <HA_HOOK_SECRET>' \
  -d '{"state": "on", "source": "Disney+", "at": "2026-12-12T19:31:04-08:00"}'
```

The answer is `{"action": "ignored", "applied": false, "ok": true, "reason": "no viewing tonight"}`. A 403 means the
secret doesn't match (or `HA_HOOK_SECRET` is empty: the hook is off). Note that a test event with an `at` later than
real events makes the app ignore the real ones until the clock passes it, so use a time in the past.

Then pick a movie with **Watch tonight**, turn the TV on to a service that has it, and look at Home Assistant's
**Settings → Automations → (the automation) → Traces**: the `rest_command` step shows the app's answer. Turn the TV
off and open the app: it asks **Did you finish?**.
