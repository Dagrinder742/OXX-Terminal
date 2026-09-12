# kalshi/test_connection.py
import os
import requests
from auth import load_private_key_from_file, get_auth_headers

# Configuration
API_KEY_ID = "837934ae-214d-4a46-86ff-dbfb21619e49"                                                                     # Your Key ID from howto
KEY_FILE_PATH = r"C:\Users\krayz\AndroidStudioProjects\OXXTerminal\app\src\main\Python\kalshi\main.txt"                  # Ensure this matches your local private key filename
BASE_URL = "https://external-api.kalshi.com"                                                                            # Live production endpoint
PATH = "/trade-api/v2/portfolio/balance"

def test_connection():
    if not os.path.exists(KEY_FILE_PATH):
        print(f"Error: Private key file '{KEY_FILE_PATH}' not found in current directory.")
        return

    print("Loading private key...")
    private_key = load_private_key_from_file(KEY_FILE_PATH)

    print("Generating signed headers for live API...")
    headers = get_auth_headers(
        api_key_id=API_KEY_ID,
        private_key=private_key,
        method="GET",
        path=PATH
    )

    full_url = BASE_URL + PATH
    print(f"Sending GET request to {full_url}...")

    try:
        response = requests.get(full_url, headers=headers)
        print(f"Response Status Code: {response.status_code}")
        print("Response Body:")
        print(response.json())
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_connection()
