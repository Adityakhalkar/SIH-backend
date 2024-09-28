from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import requests
from utils.db import setToken, getToken
from sentinelhub import SHConfig, SentinelHubRequest, MimeType, BBox, CRS, DataCollection, MosaickingOrder
import matplotlib.pyplot as plt
import io
from PIL import Image, ImageEnhance
import dotenv
import os
import numpy as np
from oauthlib.oauth2 import BackendApplicationClient
from requests_oauthlib import OAuth2Session
from datetime import datetime, timezone
import aiohttp
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from bs4 import BeautifulSoup
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

sh_client_id = os.getenv("SH_CLIENT_ID")
sh_client_secret = os.getenv("SH_CLIENT_SECRET")

client = BackendApplicationClient(client_id=sh_client_id)
oauth = OAuth2Session(client=client)

# Get token for the session
token = oauth.fetch_token(token_url='https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token',
                          client_secret=sh_client_secret, include_client_id=True)

# All requests using this session will have an access token automatically added
resp = oauth.get("https://sh.dataspace.copernicus.eu/configuration/v1/wms/instances")
print(resp.content)

dotenv.load_dotenv()

app = FastAPI()
save_directory = "images"
if not os.path.exists(save_directory):
    print("Creating directory")
    os.makedirs(save_directory)
@app.get("/")
def read_root():
    return "Welcome to {project_name} backend!"

@app.get("/get-token")
async def get_token():
    url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "username": "khalkaraditya8@gmail.com",
        "password": "pyvkiw-niRcoh-rydto6",
        "grant_type": "password",
        "client_id": "cdse-public"
    }

    response = requests.post(url, headers=headers, data=data)
    token = response.json()['access_token']
    await setToken(token)
    return token

def last_info(bbox):
    data_collections = ["sentinel-2-l2a", "sentinel-1-grd", "sentinel-3-olci"]
    crs = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
    from_date = "2019-01-01T00:00:00Z"
    to_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # Current time

    latest_images = []

    for collection in data_collections:
        request_payload = {
            "bbox": bbox,
            "datetime": f"{from_date}/{to_date}",
            "collections": [collection],
            "limit": 1,  # Fetch only the latest image
        }

        url = "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0/search"
        response = oauth.post(url, json=request_payload)

        if response.status_code == 200:
            catalog_data = response.json()
            if catalog_data.get('features'):
                latest_image = catalog_data['features'][0]
                latest_date = latest_image['properties']['datetime']
                cloud_coverage = latest_image['properties'].get('eo:cloud_cover', 'N/A')
                latest_images.append({
                    "collection": collection,
                    "date": latest_date,
                    "cloud_coverage": cloud_coverage
                })
            else:
                print(f"No images found for {collection} in the given date range.")
        else:
            print(f"Failed to query {collection}. Status code: {response.status_code}")
            print("Response:", response.text)
            return None
    return latest_images

@app.get("/get-satellite-image")
async def get_satellite_image(
    coords: str
):
    token = await getToken() 
    if not token:
        return {"error": "Authentication token is missing. Please get the token first."}
    min_lon, min_lat, max_lon, max_lat = map(float, coords.split(","))
    # Configure Sentinel Hub
    config = SHConfig()
    config.sh_client_id = sh_client_id
    config.sh_client_secret = sh_client_secret
    config.sh_token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    config.sh_base_url = "https://sh.dataspace.copernicus.eu"
    bbox = [min_lon, min_lat, max_lon, max_lat]
    last_data = last_info([min_lon,min_lat,max_lon,max_lat])
    print(bbox)
    last_date = last_data[1]['date']
    evalscript = """
    //VERSION=3
    function setup() {
    return {
        input: ["VV"],
        output: { id: "default", bands: 1 },
    }
    }

    function evaluatePixel(samples) {
    return [20 * samples.VV]
    }
    """

    request = {
        "input": {
            "bounds": {
                "bbox": bbox,
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [
                {
                    "type": "sentinel-1-grd",
                    "dataFilter": {
                        "timeRange": {
                            "from": "2019-11-05T00:00:00Z",
                            "to": f"{last_date}",
                        },
                        "mosaickingOrder": "mostRecent",
                    },
                }
            ],
        },
        "output": {
            "width": 256,
            "height": 256,
            "responses": [
                {
                    "identifier": "default",
                    "format": {"type": "image/png"},
                }
            ],
        },
        "evalscript": evalscript,
    }

    url = "https://sh.dataspace.copernicus.eu/api/v1/process"
    response = oauth.post(url, json=request)
    if response.status_code == 200:
        # Save the PNG image
        with open("latest_satellite_image.png", "wb") as f:
            f.write(response.content)
        print("Image saved successfully as 'latest_satellite_image.png'.")
    else:
        print(f"Failed to retrieve image. Status code: {response.status_code}")
        print("Response:", response.text)
    print(last_date)
    return FileResponse("latest_satellite_image.png", media_type="image/png")

@app.get("/download-image/{file_name}")
async def download_image(file_name: str):
    file_path = os.path.join(save_directory, file_name)
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=file_name)
    else:
        raise HTTPException(status_code=404, detail="File not found.")

def init_webdriver():
    options = webdriver.ChromeOptions()
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()),options=options)
    return driver

@app.get("/marine-traffic")
async def get_marine_traffic():
    url = "https://www.marinetraffic.com/en/data/?asset_type=vessels&columns=flag,shipname,photo,recognized_next_port,reported_eta,reported_destination,current_port,imo,ship_type,show_on_live_map,time_of_latest_position,lat_of_latest_position,lon_of_latest_position,notes,speed&ship_type_in=8|Tankers&recognized_next_port_in=2341|MUMBAI"
    login_url = "https://www.marinetraffic.com/en/ais/home/centerx:-12.1/centery:25.0/zoom:4"
    email = "testershinobiai@gmail.com"
    password = "tester@1234"

    driver = init_webdriver()
    wait = WebDriverWait(driver, 10)
    try:
        # Step 1: Open the login page
        driver.get(login_url)
        time.sleep(5)  # Allow time for the page to load
        
        # Step 2: Find and click the login button to bring up the login form
        login_button = wait.until(EC.element_to_be_clickable((By.ID, 'login')))
        login_button.click()
        time.sleep(2)

        # Step 3: Fill out the login form
        email_input = driver.find_element(By.NAME, 'email')  # Email input field
        password_input = driver.find_element(By.NAME, 'password')  # Password input field

        email_input.send_keys(email)
        password_input.send_keys(password)

        # Step 4: Submit the form
        password_input.send_keys(Keys.RETURN)

        # Step 5: Wait for login to complete
        time.sleep(5)  # Adjust based on the login time required
        
        # Step 6: Navigate to the data URL after login
        driver.get(url)

        # Step 7: Scrape the required data
        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')

        # Example of extracting vessel data from the table
        vessels_data = []
        table = soup.find('table')  # Adjust this selector based on actual page structure
        if table:
            rows = table.find_all('tr')
            for row in rows[1:]:  # Skipping header row
                cols = row.find_all('td')
                vessel = {
                    'flag': cols[0].text.strip(),
                    'shipname': cols[1].text.strip(),
                    'photo': cols[2].find('img')['src'] if cols[2].find('img') else None,
                    'next_port': cols[3].text.strip(),
                    'reported_eta': cols[4].text.strip(),
                    'destination': cols[5].text.strip(),
                    'current_port': cols[6].text.strip(),
                    'imo': cols[7].text.strip(),
                    'ship_type': cols[8].text.strip(),
                    'position_time': cols[9].text.strip(),
                    'lat': cols[10].text.strip(),
                    'lon': cols[11].text.strip(),
                    'notes': cols[12].text.strip(),
                    'speed': cols[13].text.strip(),
                }
                vessels_data.append(vessel)

        return {"vessels": vessels_data}
    
    finally:
        driver.quit()
        