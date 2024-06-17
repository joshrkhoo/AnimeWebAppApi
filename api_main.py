from flask import Flask, request, jsonify
import requests
from flask_cors import CORS

# Initialize the Flask app
app = Flask(__name__)
CORS(app)

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

if __name__ == '__main__':
    app.run(debug=True)
