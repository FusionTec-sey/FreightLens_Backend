import requests

url = "https://auth.cma-cgm.com/as/token.oauth2"

headers = {
    "Content-Type": "application/x-www-form-urlencoded"
}

data = {
    "grant_type": "client_credentials",
    "client_id": "beapp-fusiontech",
    "client_secret": "T3FefGXrLjQBWCQT98D1VsbKXb1aKGgOWamRUSGWkDmvlNzR1ZsLv0El8XF7RDFS",
    "scope": ""  # Ensure no space after 'scope' in "scope2"
}

response = requests.post(url, headers=headers, data=data)

# Print the response from the server
print(response.status_code)
print(response.json())
