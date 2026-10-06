import os

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient

import anilist
import api_db
import auth

# Local development reads .env; in production the variables come from Railway
load_dotenv()

app = Flask(__name__)

# CORS_ORIGINS is a comma-separated list of allowed frontend origins
cors_origins = os.getenv("CORS_ORIGINS", "*")
if cors_origins == "*":
    CORS(app)
else:
    CORS(app, origins=[o.strip() for o in cors_origins.split(",")])

client = MongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017/anime_db"))
db = client[os.getenv("MONGODB_DB", "anime_db")]

try:
    auth.create_indexes(db)
    api_db.create_indexes(db)
except Exception as e:
    print(f"Error creating indexes: {e}")

login_required = auth.require_auth(db)


@app.errorhandler(anilist.AniListError)
def handle_anilist_error(e):
    print(f"AniList error: {e}")
    return jsonify({"error": "Couldn't reach AniList. Try again in a moment."}), 502


@app.get("/health")
def health():
    return jsonify({"ok": True})


# --- Auth ---

@app.post("/auth/register")
def register():
    username, password, error = auth.validate_credentials(request.get_json(silent=True) or {})
    if error:
        return jsonify({"error": error}), 400
    user = auth.register(db, username, password)
    if user is None:
        return jsonify({"error": "That username is taken."}), 409
    return jsonify({"token": auth.create_session(db, user), "user": auth.public_user(user)}), 201


@app.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip().lower()
    user = auth.authenticate(db, username, str(data.get("password", "")))
    if user is None:
        return jsonify({"error": "Wrong username or password."}), 401
    return jsonify({"token": auth.create_session(db, user), "user": auth.public_user(user)})


@app.post("/auth/logout")
def logout():
    auth.delete_session(db)
    return jsonify({"ok": True})


@app.get("/auth/me")
@login_required
def me():
    return jsonify({"user": auth.public_user(g.user)})


# --- Browsing ---

@app.get("/search")
@login_required
def search():
    text = request.args.get("q", "").strip()
    if not text:
        return jsonify([])
    return jsonify(anilist.search_airing(text[:100]))


@app.get("/browse/<kind>")
@login_required
def browse(kind):
    statuses = {"airing": "RELEASING", "upcoming": "NOT_YET_RELEASED"}
    if kind not in statuses:
        return jsonify({"error": "Unknown list."}), 404
    return jsonify(anilist.popular(statuses[kind]))


@app.get("/anime/<int:anime_id>")
@login_required
def anime_details(anime_id):
    show = anilist.details(anime_id)
    if show is None:
        return jsonify({"error": "Couldn't find that anime."}), 404
    return jsonify(show)


# --- Library (schedule + wishlist) ---

@app.get("/library")
@login_required
def get_library():
    """The user's schedule and wishlist with live airing info.

    Finished shows are dropped. Wishlist shows that have started airing (or premiere
    within a week) move to the schedule and are reported in `promoted`.
    """
    user_id = g.user["_id"]
    entries = api_db.library_entries(db, user_id)
    media = anilist.media_by_ids(list(entries))

    finished = {i for i, m in media.items() if m["status"] in anilist.FINISHED_STATUSES}
    if finished:
        api_db.remove_entries(db, user_id, finished)

    promoted = [
        i for i, list_name in entries.items()
        if list_name == api_db.WISHLIST and i in media and i not in finished
        and not anilist.is_upcoming(media[i])
    ]
    if promoted:
        api_db.move_entries(db, user_id, promoted, api_db.SCHEDULE)
        for i in promoted:
            entries[i] = api_db.SCHEDULE

    library = {api_db.SCHEDULE: [], api_db.WISHLIST: []}
    for i, list_name in entries.items():
        if i in media and i not in finished:
            library[list_name].append(media[i])
    library["promoted"] = [media[i] for i in promoted]
    return jsonify(library)


@app.post("/library")
@login_required
def add_to_library():
    """Upcoming shows go on the wishlist; everything else goes on the schedule."""
    try:
        anime_id = int((request.get_json(silent=True) or {}).get("id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Missing anime id."}), 400

    show = anilist.media_by_ids([anime_id]).get(anime_id)
    if show is None:
        return jsonify({"error": "Couldn't find that anime."}), 404
    if show["status"] in anilist.FINISHED_STATUSES:
        return jsonify({"error": "That show has finished airing."}), 400

    list_name = api_db.WISHLIST if anilist.is_upcoming(show) else api_db.SCHEDULE
    api_db.save_entry(db, g.user["_id"], anime_id, list_name)
    return jsonify({"show": show, "list": list_name}), 201


@app.delete("/library/<int:anime_id>")
@login_required
def remove_from_library(anime_id):
    api_db.remove_entries(db, g.user["_id"], [anime_id])
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "False").lower() == "true",
            port=int(os.getenv("FLASK_PORT", 5000)))
