import requests

from auth.config import settings  # credentials come from the local .env (never commit them)

url = "https://auth.cma-cgm.com/as/token.oauth2"

headers = {
    "Content-Type": "application/x-www-form-urlencoded"
}

data = {
    "grant_type": "client_credentials",
    "client_id": settings.CMA_CGM_CLIENT_ID,
    "client_secret": settings.CMA_CGM_SECRET,
    "scope": ""  # Ensure no space after 'scope' in "scope2"
}

response = requests.post(url, headers=headers, data=data)

# Print the response from the server
print(response.status_code)
print(response.json())
