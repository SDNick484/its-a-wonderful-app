"""Per-person ratings and the family rating (spec §8.2, §11). Ratings are 0.0-10.0 in 0.5 steps (common.validate_rating);
the family rating is their mean to one decimal, null when nobody has rated. Route-free: a bad request aborts with
common.make_err. Every change calls sync.after_rating_change(con, movie_id), which keeps Matinee in step (Task 9: a
no-op until then). `set` shadows the builtin inside this module on purpose (the plan's name for it); use no set() here.
No Flask object here (see CLAUDE.md)."""
from fractions import Fraction
from math import floor

from flask import abort

import movies
import people
import sync
from common import make_err, validate_rating


def mean_of(values):
    """The mean of ratings (0.5 steps) to one decimal, ties up (8.25 -> 8.3), or None for no ratings. Exact: the sum of
    0.5 steps is exact in binary, and the rounding is done on fractions, so no float ever decides a tie."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    twice = sum(round(v * 2) for v in values)
    tenths = floor(Fraction(twice, 2 * len(values)) * 10 + Fraction(1, 2))
    return tenths / 10


def set(con, movie_id, person_id, rating):
    """Save one person's rating of one movie, or clear it with None (or ""). 400 for anything but 0.0-10.0 in 0.5 steps,
    404 for an unknown movie or person. Then tells Matinee's sync that the movie's ratings changed."""
    rating = validate_rating(rating)
    movies.get_row(con, movie_id)
    people.get_row(con, person_id)
    if rating is None:
        con.execute("DELETE FROM person_ratings WHERE person_id=? AND movie_id=?", (person_id, movie_id))
    else:
        con.execute("INSERT INTO person_ratings (person_id, movie_id, rating) VALUES (?,?,?)"
                    " ON CONFLICT(person_id, movie_id) DO UPDATE SET rating=excluded.rating, updated_at=CURRENT_TIMESTAMP",
                    (person_id, movie_id, rating))
    con.commit()
    sync.after_rating_change(con, movie_id)


def family(con, movie_id):
    """{"mean": float | None, "by_person": [{"person_id", "name", "color", "rating"}]}: every active person in order,
    `rating` None for someone who hasn't rated, and `mean` (one decimal) over the ratings there are."""
    by_person = [{"person_id": r["id"], "name": r["name"], "color": r["color"], "rating": r["rating"]} for r in con.execute(
        "SELECT p.id, p.name, p.color, r.rating FROM people p"
        " LEFT JOIN person_ratings r ON r.person_id = p.id AND r.movie_id = ?"
        " WHERE p.active = 1 ORDER BY p.sort_order, p.id", (movie_id,))]
    return {"mean": mean_of(x["rating"] for x in by_person), "by_person": by_person}


def shown(con, movie_id, fam=None):
    """(rating, source) for the poster and the detail heading (spec §8.2). While Matinee owns the rating of a movie it
    holds (matinee_sync.rating_owner = 'matinee' and a title id) the shown rating is Matinee's user_rating, source
    'matinee'; otherwise it is the family mean, source 'family'. (None, None) when there is nothing to show."""
    s = con.execute("SELECT matinee_title_id, matinee_rating, rating_owner FROM matinee_sync WHERE movie_id=?", (movie_id,)).fetchone()
    if s is not None and s["rating_owner"] == "matinee" and s["matinee_title_id"] is not None and s["matinee_rating"] is not None:
        return s["matinee_rating"], "matinee"
    mean = (fam or family(con, movie_id))["mean"]
    return (mean, "family") if mean is not None else (None, None)


def out(con, movie_id):
    """What the page needs beside a movie: {"family_rating", "rating_source", "family": {mean, by_person}}."""
    fam = family(con, movie_id)
    rating, source = shown(con, movie_id, fam)
    return {"family_rating": rating, "rating_source": source, "family": fam}


def parse_body(data):
    """The `rating` of a PUT body {"rating": 8.5 | null}: 400 when the body or the key is missing."""
    if not isinstance(data, dict) or "rating" not in data:
        abort(make_err(400, 'Send {"rating": 8.5} (or null to clear it).'))
    return data["rating"]
