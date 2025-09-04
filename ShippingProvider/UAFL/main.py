import requests
from bs4 import BeautifulSoup

url = "https://www.uaflshipping.com/Tracking?BookingNo=KHIPOV2506002"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Example: find a table with tracking details
    table = soup.find('table')  # You might need to specify class or id

    if table:
        for row in table.find_all('tr'):
            columns = [col.get_text(strip=True) for col in row.find_all(['td', 'th'])]
            print(columns)
    else:
        print("Tracking table not found.")
else:
    print(f"Failed to load page: {response.status_code}")
