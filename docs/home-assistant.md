# Home Assistant and the Family Room TV

The app guesses whether a movie was finished from the Family Room TV (spec §10.2). Home Assistant tells it when the
TV turns on or off and when its input (`source`) changes; the app never configures Home Assistant itself. This page
is the Home Assistant side. The names here are placeholders: `ha.example.com` for Home Assistant,
`wonderful.example.com` / `192.168.1.100:8772` for the app, `media_player.family_room_tv` for the TV.

(Two more webhooks go from the app to Home Assistant: the Family Room movie log that every finished movie is posted
to is `HA_WEBHOOK_URL`, see the README; and **Play on the Family Room TV**, which starts a movie on the TV, is
`HA_PLAY_WEBHOOK_URL`, see the last section here.)

## What the app does with the events

Only while exactly one movie is picked for tonight (**Watch tonight**, or **Keep watching tonight** on a paused one):

| The TV | The app |
|---|---|
| On, on an input that can play the movie | Opens a session; the movie is "watching" |
| On another input (YouTube, Live TV) while a session is open | Closes it (`source_changed`) |
| Off (or `standby`) while a session is open | Closes it (`tv_off`) |
| A session open longer than the runtime + 60 min | Closed at runtime + 60 (`timeout`); 4 hours with no runtime |

An input can play the movie when it is the `tv_source` of a streaming service TMDB lists the movie on
(`data/services.json`: `Netflix`, `Disney+`, `HBO Max` ...), `AV Receiver` when Matinee holds a physical copy of the
movie (a disc), or `Fandango at Home` when it holds a digital copy. Closing a session adds its length to the movie's
watched time and guesses: finished at 85 % of the runtime, otherwise not; no guess when the runtime is unknown. The
next time anyone opens the app it asks **Did you finish?** with the guess highlighted. The movie is paused after a
session closes, so a second night needs **Keep watching tonight** before the TV counts again.

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
   When the TV has several `media_player` entities, use the TV integration's own (the one whose `source_list` holds
   the app names), not a Cast or music-player entity.
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

## Play on the Family Room TV

The other direction: with `HA_PLAY_WEBHOOK_URL` set, the app's **Stream it** and **Start the disc** buttons ask Home
Assistant to start the movie on the TV. The app posts this to a Home Assistant webhook and waits up to 5 seconds for
the answer:

```json
{"event": "wonderful_play", "mode": "stream", "source": "Disney+", "title": "Example Movie"}
```

`mode` is `stream` (open an app) or `disc` (start the Blu-ray). `source` is the TV's input name: a `tv_source` from
`data/services.json`, `Fandango at Home` for a digital copy, or `AV Receiver` for a disc.

For a Netflix movie whose Netflix title id the app knows (found automatically, or saved in the **Netflix link** field
on the movie's page), the payload also carries that id, and the TV starts the movie itself instead of just opening the
app:

```json
{"event": "wonderful_play", "mode": "stream", "source": "Netflix", "title": "Example Movie", "content_id": "80183187"}
```

A digital copy we own (the movie shows "Our digital copy · Fandango at Home" on its page) starts the same way when
Matinee has the copy's Fandango at Home link:

```json
{"event": "wonderful_play", "mode": "stream", "source": "Fandango at Home", "title": "Example Movie", "content_id": "15429"}
```

`content_id` is 1 to 12 digits and is sent for Netflix and for an owned Fandango at Home copy; every other payload has
no `content_id` at all. Two things to make in
Home Assistant, a script that does the work and an automation that receives the webhook. The entity names are
placeholders: `media_player.family_room_tv` (the TV, as in "Set it up" above), `switch.watch_tv` and
`switch.watch_a_bluray` (the remote's activities as switches).

1. **The script** (**Settings → Automations & Scenes → Scripts → Add script → Edit in YAML**). Save it as "Play on the
   Family Room TV", then open **Settings → Devices & services → Entities**, find the script and set its entity id to
   `script.wonderful_play_on_tv`. Home Assistant derives the entity id from the alias when the script is first saved, so
   an alias that slugifies to that name gives the same result, but a script saved under any other alias will not match,
   and the automation below would call a script that doesn't exist. `mode: restart` means a second pick replaces the
   first instead of queueing behind a 60 second wait.

   ```yaml
   alias: "Play on the Family Room TV"
   mode: restart
   fields:
     mode:
       description: "stream to open an app, disc to start the Blu-ray"
       required: true
       selector:
         select:
           options:
             - stream
             - disc
     source:
       description: "The TV input to select, e.g. Disney+ or AV Receiver"
       required: true
       selector:
         text:
     content_id:
       description: "Optional: the title to start in the app, e.g. a Netflix title id. Empty just opens the app"
       selector:
         text:
   sequence:
     - choose:
         - conditions:
             - condition: template
               value_template: "{{ mode == 'stream' }}"
           sequence:
             - variables:
                 activity_started: "{{ not is_state('switch.watch_tv', 'on') }}"
             - if:
                 - condition: template
                   value_template: "{{ activity_started }}"
               then:
                 - action: switch.turn_on
                   target:
                     entity_id: switch.watch_tv
             - wait_template: >-
                 {{ states('media_player.family_room_tv') not in ['off', 'unavailable', 'unknown'] }}
               timeout: 60
               continue_on_timeout: false
             - if:
                 - condition: template
                   value_template: "{{ activity_started }}"
               then:
                 - delay:
                     seconds: 5
             - choose:
                 - conditions:
                     - condition: template
                       value_template: "{{ content_id is not none and (content_id | default('')) | string is match('^[0-9]{1,12}$') and source == 'Netflix' }}"
                   sequence:
                     - action: webostv.command
                       target:
                         entity_id: media_player.family_room_tv
                       data:
                         command: system.launcher/launch
                         payload:
                           id: netflix
                           contentId: "m=https://www.netflix.com/watch/{{ content_id }}&source_type=4"
                 - conditions:
                     - condition: template
                       value_template: "{{ content_id is not none and (content_id | default('')) | string is match('^[A-Za-z0-9_-]{1,64}$') and source == 'YouTube' }}"
                   sequence:
                     - action: webostv.command
                       target:
                         entity_id: media_player.family_room_tv
                       data:
                         command: system.launcher/launch
                         payload:
                           id: youtube.leanback.v4
                           contentId: "v={{ content_id }}"
                 - conditions:
                     - condition: template
                       value_template: "{{ content_id is not none and (content_id | default('')) | string is match('^[0-9]{1,12}$') and source == 'Fandango at Home' }}"
                   sequence:
                     - action: webostv.command
                       target:
                         entity_id: media_player.family_room_tv
                       data:
                         command: system.launcher/launch
                         payload:
                           id: vudu
                           contentId: "{{ content_id }}"
               default:
                 - action: media_player.select_source
                   target:
                     entity_id: media_player.family_room_tv
                   data:
                     source: "{{ source }}"
         - conditions:
             - condition: template
               value_template: "{{ mode == 'disc' }}"
           sequence:
             - if:
                 - condition: not
                   conditions:
                     - condition: state
                       entity_id: switch.watch_a_bluray
                       state: "on"
               then:
                 - action: switch.turn_on
                   target:
                     entity_id: switch.watch_a_bluray
   ```

   For a stream, the script first notes whether `switch.watch_tv` was off, and turns it on if so. It does this even
   when the TV is already on under another activity (Watch a Bluray, say) or was turned on some other way: the app then
   opens under Watch TV and the physical remote drives it. Then it waits up to 60 seconds for the TV to be on, meaning
   any state other than `off`, `unavailable` or `unknown` (a TV that reports `idle`, `playing`, `paused` or `buffering`
   counts), and gives up if it never is. Because the wait checks the TV's state rather than watching for a change, a TV
   that comes on just before the wait starts is not missed. If the script had to start Watch TV it gives the TV 5 more
   seconds to finish starting, even when starting the activity only returned once the TV was up. Then it opens the
   app: when `source` is `Netflix` or `Fandango at Home` and `content_id` is 1 to 12 digits, or `source` is `YouTube`
   and `content_id` is 1 to 64 letters, digits, `_` or `-`, it sends the TV's launcher a command that starts that title in the app
   (`webostv.command`, `system.launcher/launch`, from the LG webOS TV integration); in every other case, including a
   call with no `content_id`, it selects the app with `media_player.select_source` as before. The script checks the
   id itself (a null counts as no id), so a caller other than the automation below cannot put anything else into the
   launch command. A disc only starts Watch a Bluray; that activity is trusted to put the TV on `AV Receiver`.

   The Netflix and YouTube launch commands were tried on an LG webOS TV on 2026-11-26: Netflix started the title
   playing by itself, with no profile picker, and YouTube went straight to a film owned through Movies Anywhere.
   Disney+ ignored the same idea in five formats, so it isn't here. The Fandango at Home one was tried on 2026-11-27:
   the TV's Fandango at Home app (its launcher id is `vudu`) starts the film by itself when launched with its number.
   This app sends a `content_id` for Netflix and for an owned Fandango at Home copy; the YouTube case is
   for other callers of the script (a Matinee automation starting an owned film, say). A different TV brand needs its
   own launch action in place of `webostv.command`; without one the `default` branch still opens the app.

2. **The automation** (**Create → Edit in YAML**). It checks the payload and starts the script with `script.turn_on`,
   which returns at once: calling the script as an action would hold the webhook's answer for the script's whole
   run, and the app only waits 5 seconds. `local_only: true` limits the webhook to requests from your own network, and
   the TV is the only thing it touches (`source` goes to `media_player.select_source` and `content_id` to the TV's
   launcher), so the worst a leaked id can do is change that TV's app or title. The condition lets `content_id`
   through only when it is left out or is a string of 1 to 64 letters, digits, `_` or `-` (this app only sends
   digits), so nothing else can end up in the launch address; a payload without one still works and just opens the
   app. Replace `<a long random id>` with a long random string of your own (the id is the only credential;
   `openssl rand -hex 24` makes one):

   ```yaml
   alias: "It's a Wonderful App plays on the Family Room TV"
   mode: queued
   triggers:
     - trigger: webhook
       webhook_id: "<a long random id>"
       allowed_methods:
         - POST
       local_only: true
   conditions:
     - condition: template
       value_template: >-
         {{ trigger.json is defined
            and trigger.json.event == 'wonderful_play'
            and trigger.json.mode in ['stream', 'disc']
            and (trigger.json.source | default('')) | length > 0
            and (trigger.json.content_id is not defined
                 or (trigger.json.content_id is string
                     and trigger.json.content_id is match('^[A-Za-z0-9_-]{1,64}$'))) }}
   actions:
     - action: script.turn_on
       target:
         entity_id: script.wonderful_play_on_tv
       data:
         variables:
           mode: "{{ trigger.json.mode }}"
           source: "{{ trigger.json.source }}"
           content_id: "{{ trigger.json.content_id | default('') }}"
   ```

3. **Tell the app where it is.** The URL is the webhook's address on Home Assistant:
   `http://ha.example.com:8123/api/webhook/<a long random id>` (the app is on your network, so use Home Assistant's
   LAN address or name, not a Cloudflare one). It is a secret, so it goes in `/etc/conf.d/wonderful` on the app's
   host, never in a repo, and the app never logs or shows it:

   ```sh
   vim /etc/conf.d/wonderful        # HA_PLAY_WEBHOOK_URL="http://ha.example.com:8123/api/webhook/<a long random id>"
   rc-service wonderful restart
   ```

   With the setting empty (the default) the Play buttons don't show at all.

### Try it

From a machine on the LAN. This really does start the TV, so pick a service the TV has:

```sh
curl -s -i -X POST 'http://ha.example.com:8123/api/webhook/<a long random id>' \
  -H 'Content-Type: application/json' \
  -d '{"event": "wonderful_play", "mode": "stream", "source": "Disney+", "title": "Example Movie"}'
```

Home Assistant answers an empty `200` and the TV comes on in Watch TV and opens the app. A `200` doesn't prove the
webhook id is right: Home Assistant also answers `200` to an id it doesn't know and does nothing. The app then
reports "The TV didn't answer" once the TV events automation (above) is set up and has reported the TV's state, and
only "Sent to the TV." before that, since it has no way to tell. So check the first play in **Settings → Automations → (the automation) →
Traces**: a trace for it means the id matched; if there is none, fix the id in the automation or in
`HA_PLAY_WEBHOOK_URL`. The script's own **Traces** show which branch ran and whether the 60 second wait timed out.

To see a movie start by itself, add a title id (a Netflix one here; `80183187` is *Klaus*) and use the Netflix input:

```sh
curl -s -i -X POST 'http://ha.example.com:8123/api/webhook/<a long random id>' \
  -H 'Content-Type: application/json' \
  -d '{"event": "wonderful_play", "mode": "stream", "source": "Netflix", "title": "Example Movie", "content_id": "80183187"}'
```

A payload with a `content_id` that has anything else in it, such as `80183187; x`, is stopped by the automation's
condition and does nothing (its trace stops at the condition).
