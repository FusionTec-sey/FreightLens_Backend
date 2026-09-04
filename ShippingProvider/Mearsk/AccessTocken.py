import requests
import time

CLIENT_ID = "RVgxOM09RDSTUAAAPQ0KHHYCZbrIXxAv"
CLIENT_SECRET = "L1ThtaCvgSvQVrG3"

_token_data = {
    "access_token": None,
    "expires_at": 0  # epoch time
}

def get_access_token():
    current_time = time.time()
    
    # Return token if it's still valid
    if _token_data["access_token"] and current_time < _token_data["expires_at"]:
        return _token_data["access_token"]

    # Request a new token
    token_url = "https://api.maersk.com/customer-identity/oauth/v2/access_token"
    token_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Consumer-Key": CLIENT_ID,
    }
    token_data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }

    response = requests.post(token_url, headers=token_headers, data=token_data)
    response.raise_for_status()

    json_data = response.json()
    access_token = json_data["access_token"]
    expires_in = json_data.get("expires_in", 3600)  # fallback to 1 hour if missing

    # Store token with expiry time
    _token_data["access_token"] = access_token
    _token_data["expires_at"] = current_time + expires_in - 30  # 30s buffer
    # print(access_token)
    return access_token
