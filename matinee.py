"""The Matinee client (spec §8): ownership and shelf location, the household rating, watches and people, over urllib
against Matinee's editor API (/admin/api) with `Authorization: Bearer <MATINEE_API_KEY>`. Route-free: a failure raises
Unavailable or Rejected and the caller decides what to show. No Flask object here (see CLAUDE.md).

Matinee being down must never take this app down, so the two failures are told apart for the caller:
  Unavailable  Matinee could not be asked or did not answer properly: no key set, timeout, refused or dropped
               connection, HTTP 5xx, or a reply that is not Matinee's JSON. Nothing is known; try again later.
  Rejected     Matinee answered and said no (HTTP 4xx: a wrong key is 401, a bad rating 400). `status` and `message`
               carry what it said. Retrying the same request will not help."""
import json, urllib.error, urllib.request

from common import clean
from settings import MATINEE_API_KEY, MATINEE_URL, UA

TIMEOUT = 5


class Unavailable(Exception):
    """Matinee could not answer (see the module docstring). `message` is for a person; it never holds the key."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class Rejected(Exception):
    """Matinee answered with an HTTP 4xx. `status` is that code, `message` what Matinee said (or a plain default)."""

    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status, self.message = status, message


def configured():
    """True when there is a key to send: an empty MATINEE_API_KEY means no Matinee sync (spec §16)."""
    return bool(MATINEE_API_KEY)


def client():
    """A Client for the settings in force now (read on each call, so a test or a restart sees a change)."""
    return Client(MATINEE_URL, MATINEE_API_KEY)


class Client:
    def __init__(self, url, key, timeout=TIMEOUT):
        self.url, self.key, self.timeout = (url or "").strip().rstrip("/"), (key or "").strip(), timeout

    # ------------------------------------------------------------------------------------------ transport
    def _call(self, method, path, body=None):
        """One request; the decoded JSON object. Unavailable or Rejected, never anything else, whatever urllib does."""
        if not self.key:
            raise Unavailable("Matinee sync is off: add MATINEE_API_KEY to /etc/conf.d/wonderful.")
        if not self.url.startswith(("http://", "https://")):
            raise Unavailable("MATINEE_URL must start with http:// or https://.")
        headers = {"User-Agent": UA, "Accept": "application/json", "Authorization": f"Bearer {self.key}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.loads(r.read(2 * 1024 * 1024))
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                raise Unavailable(f"Matinee had a problem (HTTP {e.code}).") from None
            raise Rejected(e.code, _said(e) or f"Matinee refused the request (HTTP {e.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise Unavailable("Matinee didn't answer.") from None
        if not isinstance(payload, dict):
            raise Unavailable("Matinee sent something we couldn't read.")
        return payload

    # ------------------------------------------------------------------------------------------ the routes (spec §8)
    def owned(self, tmdb_id):
        """GET /admin/api/tmdb/<tmdb_id>/owned -> {title_id, summary, location_path}. `title_id` is Matinee's id for the
        title or None when Matinee doesn't have it. `summary` is Matinee's text for the copies ("Blu-ray", "Blu-ray ·
        Digital HD (Movies Anywhere)"), None when it has no copy. `location_path` is the first copy's shelf ("Family
        Room › Media Cabinet › Shelf 2"), None when no copy has one."""
        d = self._call("GET", f"/admin/api/tmdb/{int(tmdb_id)}/owned")
        title_id = d.get("title_id")
        if title_id is not None and (isinstance(title_id, bool) or not isinstance(title_id, int)):
            raise Unavailable("Matinee sent something we couldn't read.")
        copies = [c for c in d.get("copies") or [] if isinstance(c, dict)]
        path = next((clean(c.get("location_path")) for c in copies if clean(c.get("location_path"))), None)
        return {"title_id": title_id, "summary": clean(d.get("summary")), "location_path": path}

    def title(self, title_id):
        """GET /admin/api/titles/<id> -> Matinee's whole title record (`user_rating`, `watches[{watched_date, …}]`)."""
        return self._call("GET", f"/admin/api/titles/{int(title_id)}")

    def set_rating(self, title_id, rating):
        """PUT /admin/api/titles/<id>/rating. Matinee takes 0.5 steps and answers 400 (Rejected) to anything else."""
        self._call("PUT", f"/admin/api/titles/{int(title_id)}/rating", {"rating": rating})

    def log_watch(self, title_id, watched_date, attendees):
        """POST /admin/api/titles/<id>/watches -> the new watch's id. `watched_date` is YYYY-MM-DD, `attendees` names
        Matinee knows (a name it doesn't know is a 400, Rejected). Never sends "live": this app tells Home Assistant
        itself (spec §8.3), and Matinee doing it too would log the movie twice."""
        d = self._call("POST", f"/admin/api/titles/{int(title_id)}/watches",
                       {"watched_date": watched_date, "attendees": list(attendees)})
        watch = d.get("watch")
        watch_id = watch.get("id") if isinstance(watch, dict) else None
        if isinstance(watch_id, bool) or not isinstance(watch_id, int):
            raise Unavailable("Matinee sent something we couldn't read.")   # unknown whether the watch was saved
        return watch_id

    def people(self):
        """GET /admin/api/people -> [{id, name, kind, color, sort_order, active, watch_count}] in Matinee's order."""
        d = self._call("GET", "/admin/api/people")
        people = d.get("people")
        if not isinstance(people, list):
            raise Unavailable("Matinee sent something we couldn't read.")
        return [p for p in people if isinstance(p, dict)]


def _said(err):
    """The `error` text of an HTTP error's JSON body, or None."""
    try:
        d = json.loads(err.read(64 * 1024))
    except (OSError, ValueError, AttributeError):
        return None
    return clean(d.get("error")) if isinstance(d, dict) else None
