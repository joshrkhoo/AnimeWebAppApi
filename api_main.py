from flask import Flask, request, jsonify
import requests

# Initialize the Flask app
app = Flask(__name__)

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
@app.route('/api', methods=['GET'])
def get_anime():

    data = request.get_json()

    # Get the search query from the request data
    anime_name = data.get('title')

    # Check if the anime_name is provided
    if not anime_name:
        return jsonify({"error": "Anime Doesnt Exist"}), 400


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
