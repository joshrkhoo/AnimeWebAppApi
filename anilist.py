"""Thin AniList GraphQL client with a small in-memory cache."""
import html
import os
import re
import time

import requests

ANILIST_API_URL = os.getenv("ANILIST_API_URL", "https://graphql.anilist.co")

# Statuses that mean the show can no longer air new episodes
FINISHED_STATUSES = {"FINISHED", "CANCELLED"}
ACTIVE_STATUSES = ["RELEASING", "NOT_YET_RELEASED"]

MEDIA_FIELDS = """
  id
  siteUrl
  title { romaji english }
  coverImage { extraLarge large color }
  bannerImage
  status
  format
  episodes
  genres
  averageScore
  nextAiringEpisode { episode airingAt }
  startDate { year month day }
"""

MEDIA_CACHE_TTL = 5 * 60
LIST_CACHE_TTL = 15 * 60

# Upcoming shows stay on the wishlist until they're within this window of airing
WISHLIST_WINDOW = 7 * 24 * 60 * 60

_media_cache = {}  # id -> (fetched_at, media)
_list_cache = {}  # status -> (fetched_at, [media])


class AniListError(Exception):
    pass


def _query(query, variables):
    try:
        response = requests.post(
            ANILIST_API_URL,
            json={"query": query, "variables": variables},
            timeout=10,
        )
    except requests.RequestException as e:
        raise AniListError(f"AniList request failed: {e}") from e

    if response.status_code != 200:
        raise AniListError(f"AniList returned {response.status_code}")

    body = response.json()
    if body.get("errors"):
        raise AniListError(body["errors"][0].get("message", "AniList error"))
    return body["data"]


def search_airing(text):
    """Search shows that are airing or about to air."""
    data = _query(
        f"""
        query ($search: String) {{
          Page(perPage: 8) {{
            media(search: $search, type: ANIME, status_in: [RELEASING, NOT_YET_RELEASED],
                  sort: [SEARCH_MATCH, POPULARITY_DESC]) {{ {MEDIA_FIELDS} }}
          }}
        }}
        """,
        {"search": text},
    )
    return data["Page"]["media"]


def is_upcoming(media):
    """True while a show hasn't started and isn't premiering within the next week."""
    if media["status"] != "NOT_YET_RELEASED":
        return False
    next_episode = media.get("nextAiringEpisode")
    return not next_episode or next_episode["airingAt"] - time.time() > WISHLIST_WINDOW


def popular(status):
    """Most popular shows with the given status (RELEASING or NOT_YET_RELEASED)."""
    now = time.time()
    cached = _list_cache.get(status)
    if cached and now - cached[0] < LIST_CACHE_TTL:
        return cached[1]

    data = _query(
        f"""
        query ($status: MediaStatus) {{
          Page(perPage: 30) {{
            media(type: ANIME, status: $status, sort: POPULARITY_DESC, isAdult: false) {{ {MEDIA_FIELDS} }}
          }}
        }}
        """,
        {"status": status},
    )
    media = data["Page"]["media"]
    _list_cache[status] = (now, media)
    for m in media:
        _media_cache[m["id"]] = (now, m)
    return media


def media_by_ids(ids):
    """Fetch shows by id, serving recent results from cache. Returns {id: media}."""
    now = time.time()
    result = {}
    missing = []
    for anime_id in ids:
        cached = _media_cache.get(anime_id)
        if cached and now - cached[0] < MEDIA_CACHE_TTL:
            result[anime_id] = cached[1]
        else:
            missing.append(anime_id)

    for i in range(0, len(missing), 50):
        batch = missing[i:i + 50]
        data = _query(
            f"""
            query ($ids: [Int]) {{
              Page(perPage: 50) {{
                media(id_in: $ids, type: ANIME) {{ {MEDIA_FIELDS} }}
              }}
            }}
            """,
            {"ids": batch},
        )
        for m in data["Page"]["media"]:
            _media_cache[m["id"]] = (now, m)
            result[m["id"]] = m

    return result


DETAILS_CACHE_TTL = 30 * 60
_details_cache = {}  # id -> (fetched_at, details)

_SPOILER_RE = re.compile(r"~!.*?!~", re.S)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean_description(text):
    """AniList descriptions contain HTML tags and ~!spoiler!~ blocks; return plain text."""
    if not text:
        return ""
    text = _SPOILER_RE.sub("", text)
    text = _BR_RE.sub("\n", text)
    text = html.unescape(_TAG_RE.sub("", text))
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def details(anime_id):
    """Everything the details panel shows. Returns None if the show doesn't exist."""
    now = time.time()
    cached = _details_cache.get(anime_id)
    if cached and now - cached[0] < DETAILS_CACHE_TTL:
        return cached[1]

    data = _query(
        f"""
        query ($id: Int) {{
          Media(id: $id, type: ANIME) {{
            {MEDIA_FIELDS}
            title {{ native }}
            description(asHtml: false)
            season
            seasonYear
            duration
            source
            popularity
            endDate {{ year month day }}
            studios(isMain: true) {{ nodes {{ name }} }}
            externalLinks {{ site url type language color icon notes isDisabled }}
            trailer {{ id site }}
          }}
        }}
        """,
        {"id": anime_id},
    )
    media = data["Media"]
    if media is None:
        return None

    trailer = media.pop("trailer") or {}
    trailer_urls = {
        "youtube": "https://www.youtube.com/watch?v={}",
        "dailymotion": "https://www.dailymotion.com/video/{}",
    }
    url_format = trailer_urls.get(trailer.get("site"))
    media["trailerUrl"] = url_format.format(trailer["id"]) if url_format and trailer.get("id") else None

    media["description"] = _clean_description(media["description"])
    media["studios"] = [s["name"] for s in media["studios"]["nodes"]]
    streaming = {}
    for link in media.pop("externalLinks") or []:
        if link["type"] == "STREAMING" and not link["isDisabled"]:
            streaming.setdefault(link["url"], {k: link[k] for k in ("site", "url", "language", "color", "icon", "notes")})
    media["streaming"] = list(streaming.values())

    _details_cache[anime_id] = (now, media)
    return media
