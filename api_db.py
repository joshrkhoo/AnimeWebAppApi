from datetime import datetime
import time
import requests
from zoneinfo import ZoneInfo

def parse_airing_time(airing_time):
    """
    Parse airing_time whether it's unix int or ISO string into unix int.
    
    :param airing_time: int (unix seconds) or str (ISO format)
    :return: int (unix seconds) or None
    """
    if airing_time is None:
        return None
    
    if isinstance(airing_time, int):
        return airing_time
    
    if isinstance(airing_time, str):
        try:
            # Try parsing as unix timestamp string
            return int(airing_time)
        except ValueError:
            try:
                # Try parsing as ISO string
                dt = datetime.fromisoformat(airing_time.replace('Z', '+00:00'))
                return int(dt.timestamp())
            except (ValueError, AttributeError):
                print(f"Could not parse airing_time: {airing_time}")
                return None
    
    return None

def extract_title(anime):
    """Extract title string: prefer english else romaji."""
    title_obj = anime.get('title', {})
    if isinstance(title_obj, dict):
        return title_obj.get('english') or title_obj.get('romaji') or ''
    return str(title_obj) if title_obj else ''

def extract_cover_image(anime):
    """Extract coverImage string: prefer extraLarge else large else medium."""
    cover_obj = anime.get('coverImage', {})
    if isinstance(cover_obj, dict):
        return cover_obj.get('extraLarge') or cover_obj.get('large') or cover_obj.get('medium') or ''
    return str(cover_obj) if cover_obj else ''

def fetch_status_from_anilist(anime_ids, anilist_api_url='https://graphql.anilist.co'):
    """
    Fetch status from AniList API for given anime IDs.
    Returns dict mapping anime_id -> status.
    """
    if not anime_ids:
        return {}
    
    query = '''
    query ($ids: [Int]) {
      Page(page: 1, perPage: 50) {
        media(id_in: $ids, type: ANIME) {
          id
          status
        }
      }
    }
    '''
    
    status_map = {}
    batch_size = 50
    
    for i in range(0, len(anime_ids), batch_size):
        batch_ids = anime_ids[i:i + batch_size]
        variables = {'ids': batch_ids}
        
        try:
            response = requests.post(
                anilist_api_url,
                json={'query': query, 'variables': variables},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                media_list = data.get('data', {}).get('Page', {}).get('media', [])
                
                for media in media_list:
                    anime_id = media.get('id')
                    status = media.get('status')
                    if anime_id and status:
                        status_map[anime_id] = status
        except requests.RequestException as e:
            print(f"Error fetching status from AniList for batch: {e}")
            continue
    
    return status_map

def save_schedule_data(data, db, anilist_api_url="https://graphql.anilist.co"):
    """
    Save schedule data using one-doc-per-anime.
    Keeps the earliest upcoming airing_time per anime id.
    """
    now = int(time.time())

    # 1) Collapse: id -> {anime, nextAiringAt, nextEpisode}
    anime_map = {}
    for animes in (data or {}).values():
        if not isinstance(animes, list):
            continue
        for anime in animes:
            if not isinstance(anime, dict):
                continue

            try:
                anime_id = int(anime.get("id"))
            except (TypeError, ValueError):
                continue

            next_at = parse_airing_time(anime.get("airing_time"))
            if next_at is None or next_at < now:
                continue

            prev = anime_map.get(anime_id)
            if prev is None or next_at < prev["nextAiringAt"]:
                anime_map[anime_id] = {
                    "anime": anime,
                    "nextAiringAt": int(next_at),
                    "nextEpisode": anime.get("episode"),
                }

    if not anime_map:
        return

    ids = list(anime_map.keys())

    # 2) Fetch existing statuses in ONE DB call (avoid N+1 queries)
    existing_status = {
        d["id"]: d.get("status")
        for d in db.animes.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "status": 1})
    }

    # 3) Fetch missing statuses from AniList (batched)
    missing_ids = [i for i in ids if not existing_status.get(i)]
    status_map = fetch_status_from_anilist(missing_ids, anilist_api_url) if missing_ids else {}

    # 4) Upsert
    for anime_id, info in anime_map.items():
        anime = info["anime"]

        update_doc = {
            "id": anime_id,
            "nextEpisode": info["nextEpisode"],
            "nextAiringAt": info["nextAiringAt"],
            "updatedAt": now,
        }

        title = extract_title(anime)
        if title:
            update_doc["title"] = title

        cover = extract_cover_image(anime)
        if cover:
            update_doc["coverImage"] = cover

        site_url = anime.get("siteUrl")
        if site_url:
            update_doc["siteUrl"] = site_url

        status = existing_status.get(anime_id) or status_map.get(anime_id) or anime.get("status")
        if status:
            update_doc["status"] = status

        db.animes.update_one({"id": anime_id}, {"$set": update_doc}, upsert=True)

# Status values that indicate an anime has finished airing
FINISHED_STATUSES = {"FINISHED", "CANCELLED"}

def cleanup_finished_anime(db, anilist_api_url='https://graphql.anilist.co'):
    """
    Remove anime entries that have finished airing from the database.
    Batch queries AniList GraphQL Media(id_in: $ids, type: ANIME) { id status } in chunks of 50.
    If status in {FINISHED, CANCELLED}, deletes those docs with one delete_many({"id": {"$in": [...]}}).
    
    :param db: MongoDB database object
    :param anilist_api_url: AniList GraphQL API URL
    :return: Number of documents deleted
    """
    try:
        # Get all unique anime IDs from the database
        unique_anime_ids = list(db.animes.distinct("id"))
        
        if not unique_anime_ids:
            return 0
        
        # Query AniList API to check status for all anime in batches
        query = '''
        query ($ids: [Int]) {
          Page(page: 1, perPage: 50) {
            media(id_in: $ids, type: ANIME) {
              id
              status
            }
          }
        }
        '''
        
        # Batch process anime IDs (AniList allows up to 50 per query)
        batch_size = 50
        finished_anime_ids = []
        
        for i in range(0, len(unique_anime_ids), batch_size):
            batch_ids = unique_anime_ids[i:i + batch_size]
            variables = {'ids': batch_ids}
            
            try:
                response = requests.post(
                    anilist_api_url,
                    json={'query': query, 'variables': variables},
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    media_list = data.get('data', {}).get('Page', {}).get('media', [])
                    
                    for media in media_list:
                        anime_id = media.get('id')
                        status = media.get('status')
                        
                        # Only delete if status is in FINISHED_STATUSES
                        if status in FINISHED_STATUSES:
                            finished_anime_ids.append(anime_id)
                            print(f"Anime {anime_id} marked as finished (status: {status})")
                
            except requests.RequestException as e:
                print(f"Error querying AniList API for batch: {e}")
                continue
        
        # Delete all finished anime in one operation
        if finished_anime_ids:
            result = db.animes.delete_many({"id": {"$in": finished_anime_ids}})
            deleted_count = result.deleted_count
            if deleted_count > 0:
                print(f"Cleanup completed: Removed {deleted_count} finished anime entry/entries")
            return deleted_count
        
        return 0
    except Exception as e:
        print(f"Error during cleanup of finished anime: {e}")
        return 0

def load_schedule_data(db, anilist_api_url='https://graphql.anilist.co'):
    """
    Load the schedule data from MongoDB.
    Queries anime docs where status is "RELEASING" or "NOT_YET_RELEASED" and nextAiringAt exists.
    Converts nextAiringAt to weekday using timezone "Australia/Melbourne".
    Returns { "Monday": [animeObj...], ... } where each animeObj includes:
    id, title, coverImage, episode (from nextEpisode), and a human readable datetime string.

    :param db: MongoDB database object
    :param anilist_api_url: AniList GraphQL API URL (unused but kept for compatibility)
    :return: Dictionary containing the schedule data organized by day of the week
    """
    # Clean up finished anime before loading
    cleanup_finished_anime(db, anilist_api_url)
    
    schedule_data = {day: [] for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}
    
    try:
        # Get current timestamp to filter out past episodes
        current_timestamp = int(time.time())
        
        # Query anime docs where status is "RELEASING" or "NOT_YET_RELEASED" and nextAiringAt exists
        # Include both statuses so we show upcoming anime even if they haven't started releasing yet
        animes = db.animes.find({
            "status": {"$in": ["RELEASING", "NOT_YET_RELEASED"]},
            "nextAiringAt": {"$exists": True, "$gte": current_timestamp}
        })
        
        # Timezone for Australia/Melbourne
        tz = ZoneInfo("Australia/Melbourne")
        
        for anime in animes:
            # Remove the MongoDB _id field (not JSON serializable)
            if '_id' in anime:
                del anime['_id']
            
            next_airing_at = anime.get('nextAiringAt')
            if next_airing_at is None:
                continue
            
            # Convert nextAiringAt to weekday using Australia/Melbourne timezone
            dt = datetime.fromtimestamp(int(next_airing_at), tz=tz)
            airing_day = dt.strftime('%A')
            
            # Create human readable datetime string
            datetime_str = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
            
            # Build anime object for frontend
            anime_obj = {
                'id': anime.get('id'),
                'title': anime.get('title', ''),
                'coverImage': anime.get('coverImage', ''),
                'episode': anime.get('nextEpisode'),
                'airing_time': next_airing_at,
                'datetime': datetime_str
            }
            
            # Add siteUrl if available
            if anime.get('siteUrl'):
                anime_obj['siteUrl'] = anime.get('siteUrl')
            
            schedule_data[airing_day].append(anime_obj)
        
        # Sort each day by airing time
        for day in schedule_data:
            schedule_data[day].sort(key=lambda x: x.get('airing_time', 0))
    
    except Exception as e:
        print(f"Error loading schedule data: {e}")
    
    return schedule_data

def remove_anime(anime_id, db):
    """
    Remove an anime from the schedule data in MongoDB.
    With one-doc-per-anime schema, this removes the single document.

    :param anime_id: ID of the anime to be removed
    :param db: MongoDB database object
    :return: Number of documents deleted
    """
    try:
        result = db.animes.delete_one({"id": anime_id})
        deleted_count = result.deleted_count
        if deleted_count > 0:
            print(f"Removed anime ID {anime_id}")
        return deleted_count
    except Exception as e:
        print(f"Error removing anime {anime_id}: {e}")
        return 0

def create_indexes(db):
    """
    Create MongoDB indexes for the animes collection.
    - Unique index on id
    - Index on (status, nextAiringAt)
    
    :param db: MongoDB database object
    """
    try:
        # Unique index on id
        db.animes.create_index("id", unique=True)
        print("Created unique index on 'id'")
        
        # Compound index on (status, nextAiringAt)
        db.animes.create_index([("status", 1), ("nextAiringAt", 1)])
        print("Created compound index on ('status', 'nextAiringAt')")
        
    except Exception as e:
        print(f"Error creating indexes: {e}")