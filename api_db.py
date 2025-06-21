from flask_pymongo import PyMongo
from datetime import datetime

# Initialize PyMongo
mongo = PyMongo()

def init_app(app):
    """
    Initialize the MongoDB connection with the Flask app.

    :param app: Flask app instance
    """
    mongo.init_app(app)

def save_schedule_data(data):
    """
    Save the schedule data to MongoDB.

    :param data: Dictionary containing the schedule data
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
                # Accept both camelCase and snake_case for airing schedule
                airing_schedule = anime.get('airingSchedule') or anime.get('airing_schedule')
                mongo.db.animes.update_one(
                    {"id": anime.get('id')},
                    {
                        "$set": {
                            "title": anime.get('title'),
                            "airing_schedule": airing_schedule
                        }
                    },
                    upsert=True
                )
            except Exception as e:
                print(f"Error saving anime {anime.get('id', 'unknown')}: {e}. Full anime object: {anime}")


def load_schedule_data():
    """
    Load the schedule data from MongoDB.

    :return: Dictionary containing the schedule data organized by day of the week
    """
    schedule_data = {
        "Monday": [],
        "Tuesday": [],
        "Wednesday": [],
        "Thursday": [],
        "Friday": [],
        "Saturday": [],
        "Sunday": []
    }

    try: 
        animes = mongo.db.animes.find()
        for anime in animes:
            for edge in anime['airing_schedule']['edges']:
                airing_time = edge['node']['airingAt']
                airing_day = datetime.fromtimestamp(airing_time).strftime('%A')
                schedule_data[airing_day].append({
                    'id': anime['id'],
                    'title': anime['title'],
                    'airing_time': airing_time,
                    'episode': edge['node']['episode']
                })

    except Exception as e:
        print(f"Error loading schedule data: {e}")
    
    return schedule_data

def remove_anime(anime_id):
    """
    Remove an anime from the schedule data in MongoDB.

    :param anime_id: ID of the anime to be removed
    :return: Number of documents deleted
    """
    try:
        result = mongo.db.animes.delete_one({"id": anime_id})
        return result.deleted_count
    except Exception as e:
        print(f"Error removing anime {anime_id}: {e}")
        return 0