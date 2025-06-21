from datetime import datetime

def save_schedule_data(data, db):
    """
    Save the schedule data to MongoDB.

    :param data: Dictionary containing the schedule data
    :param db: MongoDB database object
    """
    print("Received data for saving:", data)
    for day, animes in data.items():
        if not isinstance(animes, list):
            print(f"Warning: Expected a list for day '{day}', got {type(animes)}. Skipping.")
            continue
        for anime in animes:
            if not isinstance(anime, dict):
                print(f"Warning: Expected a dict for anime, got {type(anime)}. Skipping. Value: {anime}")
                continue
            try:
                # Save the full anime object, including all fields
                result = db.animes.update_one(
                    {"id": anime.get('id'), "episode": anime.get('episode'), "airing_time": anime.get('airing_time')},
                    {"$set": anime},
                    upsert=True
                )
                print(f"Saved anime {anime.get('id')} - matched: {result.matched_count}, modified: {result.modified_count}, upserted: {result.upserted_id}")
            except Exception as e:
                print(f"Error saving anime {anime.get('id', 'unknown')}: {e}. Full anime object: {anime}")

def load_schedule_data(db):
    """
    Load the schedule data from MongoDB.

    :param db: MongoDB database object
    :return: Dictionary containing the schedule data organized by day of the week
    """
    schedule_data = {day: [] for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}

    try: 
        animes = db.animes.find()
        for anime in animes:
            # Remove the MongoDB _id field (not JSON serializable)
            if '_id' in anime:
                del anime['_id']
            airing_time = anime.get('airing_time')
            if airing_time is not None:
                if isinstance(airing_time, str):
                    try:
                        airing_time = int(airing_time)
                    except Exception:
                        try:
                            airing_time = int(datetime.fromisoformat(airing_time).timestamp())
                        except Exception:
                            print(f"Could not parse airing_time: {airing_time}")
                            continue
                airing_day = datetime.fromtimestamp(airing_time).strftime('%A')
                schedule_data[airing_day].append(anime)

    except Exception as e:
        print(f"Error loading schedule data: {e}")
    
    return schedule_data

def remove_anime(anime_id, db):
    """
    Remove an anime from the schedule data in MongoDB.

    :param anime_id: ID of the anime to be removed
    :param db: MongoDB database object
    :return: Number of documents deleted
    """
    try:
        result = db.animes.delete_one({"id": anime_id})
        return result.deleted_count
    except Exception as e:
        print(f"Error removing anime {anime_id}: {e}")
        return 0