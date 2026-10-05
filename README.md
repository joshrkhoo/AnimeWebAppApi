# AnimeWebAppApi

Backend for [AnimeWebApp](https://github.com/joshrkhoo/AnimeWebApp): user accounts, each user's schedule and wishlist, and a proxy to the [AniList](https://anilist.co) GraphQL API for show data.

**Live:** https://anime-web-app-api-production.up.railway.app

## Tech stack

Python 3.11+, Flask, gunicorn, MongoDB (Atlas) via PyMongo.

## How it works

- **Accounts.** Passwords are stored only as scrypt hashes (via Werkzeug). Logging in creates a session: the client gets a random token and sends it as `Authorization: Bearer <token>`. The database stores only the token's SHA-256 hash. Sessions last 30 days and are deleted on logout; MongoDB removes expired ones automatically.
- **Library.** For each saved show the database stores only `(userId, animeId, list)`, where `list` is `schedule` or `wishlist`. Titles, posters and air times are fetched live from AniList on every load, so they never go stale.
- **Wishlist promotion.** When a library loads, any wishlisted show that has started airing, or premieres within 7 days, moves to the schedule and is returned in `promoted`. Shows that have finished or been cancelled are removed.
- **Caching.** AniList responses are cached in memory per process: 5 minutes per show, 15 minutes for browse lists.

### MongoDB collections (database `anime_db`)

| Collection  | Contents                                                     |
| ----------- | ------------------------------------------------------------ |
| `users`     | `username` (unique, lowercase), `passwordHash`, `createdAt`  |
| `sessions`  | `tokenHash`, `userId`, `createdAt`, `expiresAt` (TTL index)  |
| `schedules` | `userId`, `animeId`, `list`, `addedAt` (unique per user+show) |

`animes` is left over from the pre-accounts version and is no longer used.

## Endpoints

All endpoints except register, login, logout and health require a bearer token.

| Method   | Path                  | Description                                                              |
| -------- | --------------------- | ------------------------------------------------------------------------ |
| `POST`   | `/auth/register`      | `{username, password}` → `{token, user}`                                 |
| `POST`   | `/auth/login`         | `{username, password}` → `{token, user}`                                 |
| `POST`   | `/auth/logout`        | Ends the current session                                                 |
| `GET`    | `/auth/me`            | The logged-in user                                                       |
| `GET`    | `/search?q=`          | Airing or upcoming shows matching `q`                                    |
| `GET`    | `/browse/airing`      | Most popular shows airing now                                            |
| `GET`    | `/browse/upcoming`    | Most popular shows not yet released                                      |
| `GET`    | `/library`            | `{schedule, wishlist, promoted}` with live AniList data                  |
| `POST`   | `/library`            | `{id}` → `{show, list}`; upcoming shows go to the wishlist               |
| `DELETE` | `/library/<anime_id>` | Remove a show from either list                                           |
| `GET`    | `/health`             | `{ok: true}`                                                             |

If AniList can't be reached, endpoints return `502` with an error message.

## Configuration

| Variable          | Default                                  | Notes                                               |
| ----------------- | ---------------------------------------- | --------------------------------------------------- |
| `MONGODB_URI`     | `mongodb://localhost:27017/anime_db`     | Atlas connection string                              |
| `MONGODB_DB`      | `anime_db`                               | Database name; handy for testing against a scratch DB |
| `CORS_ORIGINS`    | `*`                                      | Comma-separated list of allowed frontend origins     |
| `ANILIST_API_URL` | `https://graphql.anilist.co`             |                                                     |
| `FLASK_PORT`      | `5000`                                   | Local `python api_main.py` only                      |
| `FLASK_DEBUG`     | `False`                                  | Local `python api_main.py` only                      |

For local development, put these in a `.env` file (git-ignored).

## Running locally

```bash
pip install -r requirements.txt
python api_main.py
```

The API runs at http://127.0.0.1:5000. On macOS, AirPlay Receiver also uses port 5000; set `FLASK_PORT` if it's taken (and update the frontend's `.env.development` to match).

To run against the production variables from Railway while keeping a separate database and open CORS:

```bash
railway run env MONGODB_DB=anime_db_dev CORS_ORIGINS='*' python api_main.py
```

## Deploying

Hosted on Railway: service `anime-web-app-api` in project "Projects". It isn't connected to GitHub, so deploy from this folder:

```bash
railway up
```

The `Procfile` starts gunicorn on Railway's `$PORT`. Production variables (`MONGODB_URI`, `CORS_ORIGINS`) are set on the Railway service. `CORS_ORIGINS` must include every frontend origin, currently `https://anime.joshrkhoo.com`, `https://anime-web-app-gilt.vercel.app` and `http://localhost:3000`.

Atlas Network Access must allow `0.0.0.0/0`, because Railway has no fixed outbound IP.
