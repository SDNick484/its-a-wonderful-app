"""Keeping Matinee's rating in step with the family's (spec §8.2). The real work arrives with the rating-sync task;
until then the hook ratings.set() calls after every change does nothing. Route-free; no Flask object (see CLAUDE.md)."""


def after_rating_change(con, movie_id):
    """Called after any change to a movie's person ratings. A no-op until the rating-sync task."""
    return None
