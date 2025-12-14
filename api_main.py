from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, os
from pymongo import MongoClient
from api_db import save_schedule_data, load_schedule_data, remove_anime, cleanup_finished_anime, create_indexes
from dotenv import load_dotenv

# Load environment variables from .env file
# In production, use .env.production or set environment variables directly
env_file = '.env.production' if os.getenv('FLASK_ENV') == 'production' else '.env'
load_dotenv(env_file)

# Initialize the Flask app
app = Flask(__name__)

# CORS configuration from environment variable
cors_origins = os.getenv('CORS_ORIGINS', '*')
if cors_origins == '*':
    CORS(app)  # Allow all origins
else:
    # Allow specific origins (comma-separated)
    origins = [origin.strip() for origin in cors_origins.split(',')]
    CORS(app, origins=origins)

# MongoDB connection from environment variable
# Defaults to local MongoDB if not set
mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/anime_db')

client = MongoClient(mongo_uri)
db = client["anime_db"]

# Create indexes on startup
create_indexes(db)

# AniList GraphQL API endpoint from environment variable
anilist_api_url = os.getenv('ANILIST_API_URL', 'https://graphql.anilist.co')

# Define the GraphQL query
# We are searching for an anime by its title
query = '''
query ($search: String) {
  Page {
    media(search: $search, type: ANIME) {
      id
      title {
        romaji
        english
        native
      }
      coverImage {
        extraLarge
        large
        medium
      }
      status
      nextAiringEpisode {
        episode
        airingAt
        timeUntilAiring
      }
      airingSchedule {
        edges {
          node {
            airingAt
            timeUntilAiring
            episode
          }
        }
      }
    }
  }
}
'''



@app.route('/api', methods=['POST'])
def get_anime():
    """
    This function handles the POST request to the '/api' route.
    It gets the anime title from the request JSON data and uses it to make a query to the AniList GraphQL API.
    The response from the API is returned as a JSON response.
    If the request fails, an error message is returned.

    NOTE: direct browser access results in a get request, which will return an error message as the route only accepts POST requests. 
        - use postman to check the api
    """
    data = request.get_json()
    print(data)

    anime_name = data.get('title')


    # Define our query variables and values that will be used in the query request
    variables = {
        'search': anime_name
    }

    # Make the HTTP API request using requests.post
    response = requests.post(anilist_api_url, json={'query': query, 'variables': variables})

    # Check if the response is successful
    if response.status_code == 200:
        # Return the response as JSON
        return jsonify(response.json())
    else:
        # Return an error message
        return jsonify({"error": "Failed to get list of anime"}), 400
    

# Endpoint to save the schedule
@app.route('/saveSchedule', methods=['POST'])
def save_schedule():
    data = request.get_json()
    print("Received data for saving:", data)
    save_schedule_data(data, db, anilist_api_url)
    return jsonify({"message": "Schedule saved successfully"})

# Endpoint to load the schedule
@app.route('/loadSchedule', methods=['GET'])
def load_schedule():
    """
    Load the schedule from the database.
    Automatically removes finished anime entries before loading.
    """
    schedule_data = load_schedule_data(db, anilist_api_url)
    # Ensure a valid schedule object is always returned
    if not schedule_data or not isinstance(schedule_data, dict):
        schedule_data = {day: [] for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']}
    return jsonify(schedule_data)

# Endpoint to manually cleanup finished anime
@app.route('/cleanupFinishedAnime', methods=['POST'])
def cleanup_finished_anime_route():
    """
    Manually trigger cleanup of finished anime entries.
    This is called automatically when loading the schedule, but can be triggered manually if needed.
    Uses AniList API to check anime status (FINISHED, CANCELLED, etc.)
    
    :return: JSON response with count of deleted entries
    """
    deleted_count = cleanup_finished_anime(db, anilist_api_url)
    return jsonify({
        "message": "Cleanup completed",
        "deleted_count": deleted_count
    })

# Endpoint to remove an anime
@app.route('/removeAnime/<int:anime_id>', methods=['DELETE'])
def remove_anime_route(anime_id):
    """
    Remove all entries for an anime from the database.
    
    This endpoint removes all documents associated with the given anime ID,
    including all episodes and airing times.
    
    :param anime_id: The ID of the anime to remove
    :return: JSON response with success message and count of deleted entries
    """
    deleted_count = remove_anime(anime_id, db)
    if deleted_count > 0:
        return jsonify({
            "message": f"Anime removed successfully",
            "deleted_count": deleted_count
        })
    else:
        return jsonify({"message": "Anime not found"}), 404

@app.route('/fetchAnimeById', methods=['POST'])
def fetch_anime_by_id():
    data = request.get_json()
    anime_id = data.get('id')
    if not anime_id:
        return jsonify({'error': 'No anime id provided'}), 400
    query = '''
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        title { romaji english native }
        coverImage { extraLarge large medium }
        status
        nextAiringEpisode {
          episode
          airingAt
          timeUntilAiring
        }
        airingSchedule {
          edges {
            node {
              airingAt
              timeUntilAiring
              episode
            }
          }
        }
      }
    }
    '''
    variables = {'id': anime_id}
    response = requests.post(anilist_api_url, json={'query': query, 'variables': variables})
    if response.status_code == 200:
        return jsonify(response.json()['data']['Media'])
    else:
        return jsonify({'error': 'Failed to fetch from AniList'}), 500

# Endpoint to retrieve multiple anime by their ids
@app.route('/fetchAnimeByIds', methods=['POST'])
def fetch_anime_by_ids():
    data = request.get_json()
    anime_ids = data.get('ids', [])
    if not anime_ids:
        return jsonify({'error': 'No anime ids provided'}), 400
    query = '''
    query ($ids: [Int]) {
      Page(perPage: 50) {
        media(id_in: $ids, type: ANIME) {
          id
          title { romaji english native }
          coverImage { extraLarge large medium }
          status
          nextAiringEpisode {
            episode
            airingAt
            timeUntilAiring
          }
          airingSchedule {
            edges {
              node {
                airingAt
                timeUntilAiring
                episode
              }
            }
          }
        }
      }
    }
    '''
    variables = {'ids': anime_ids}
    response = requests.post(anilist_api_url, json={'query': query, 'variables': variables})
    if response.status_code == 200:
        return jsonify(response.json()['data']['Page']['media'])
    else:
        return jsonify({'error': 'Failed to fetch from AniList'}), 500

if __name__ == '__main__':
    # Get configuration from environment variables
    flask_port = int(os.getenv('FLASK_PORT', 5000))
    flask_debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=flask_debug, port=flask_port)
