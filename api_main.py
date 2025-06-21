from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from pymongo import MongoClient
from api_db import save_schedule_data, load_schedule_data, remove_anime

# Initialize the Flask app
app = Flask(__name__)

# CORS must be after app is created
CORS(app, resources={r"/*": {"origins": "*"}})  # or use "http://localhost:3000" for more security

# Regular PyMongo setup
mongo_client = MongoClient("mongodb+srv://giganotosaurus:Graynerpass01@animeschedulercluster.7d9oxyn.mongodb.net/anime_db?retryWrites=true&w=majority&appName=AnimeSchedulerCluster")
db = mongo_client.get_default_database()

# Pass db to your api_db functions as needed, or set it as a global in api_db

# AniList GraphQL API endpoint
url = 'https://graphql.anilist.co'

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

# Flask route to handle the POST request
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
    response = requests.post(url, json={'query': query, 'variables': variables})

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
    save_schedule_data(data, db)
    return jsonify({"message": "Schedule saved successfully"})

# Endpoint to load the schedule
@app.route('/loadSchedule', methods=['GET'])
def load_schedule():
    schedule_data = load_schedule_data(db)
    # Ensure a valid schedule object is always returned
    if not schedule_data or not isinstance(schedule_data, dict):
        schedule_data = {day: [] for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']}
    return jsonify(schedule_data)

# Endpoint to remove an anime
@app.route('/removeAnime/<int:anime_id>', methods=['DELETE'])
def remove_anime_route(anime_id):
    deleted_count = remove_anime(anime_id, db)
    if deleted_count > 0:
        return jsonify({"message": "Anime removed successfully"})
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
    response = requests.post('https://graphql.anilist.co', json={'query': query, 'variables': variables})
    if response.status_code == 200:
        return jsonify(response.json()['data']['Media'])
    else:
        return jsonify({'error': 'Failed to fetch from AniList'}), 500

if __name__ == '__main__':
    app.run(debug=True)
