"""Per-user library storage: each saved show is on the schedule or the wishlist.

Only (userId, animeId, list) is stored. Airing times change every week, so they
are always read live from AniList instead of being saved here — storing them was
what let saved shows go stale and disappear from the schedule.
"""
from datetime import datetime, timezone

SCHEDULE = "schedule"
WISHLIST = "wishlist"


def create_indexes(db):
    db.schedules.create_index([("userId", 1), ("animeId", 1)], unique=True)


def library_entries(db, user_id):
    """Returns {animeId: list_name}, oldest first."""
    docs = db.schedules.find({"userId": user_id}, {"animeId": 1, "list": 1}).sort("addedAt", 1)
    # Entries saved before the wishlist existed have no list field
    return {d["animeId"]: d.get("list", SCHEDULE) for d in docs}


def save_entry(db, user_id, anime_id, list_name):
    """Add a show to a list; saving one that's already there just updates its list."""
    db.schedules.update_one(
        {"userId": user_id, "animeId": anime_id},
        {"$set": {"list": list_name}, "$setOnInsert": {"addedAt": datetime.now(timezone.utc)}},
        upsert=True,
    )


def move_entries(db, user_id, anime_ids, list_name):
    db.schedules.update_many(
        {"userId": user_id, "animeId": {"$in": list(anime_ids)}},
        {"$set": {"list": list_name}},
    )


def remove_entries(db, user_id, anime_ids):
    result = db.schedules.delete_many({"userId": user_id, "animeId": {"$in": list(anime_ids)}})
    return result.deleted_count
