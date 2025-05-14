import os
from fastapi import FastAPI, Request
from geopy.distance import geodesic
import asyncio

app = FastAPI()
EDGE_LOCATION = (float(os.environ["LAT"]), float(os.environ["LON"]))

@app.post("/request")
async def handle_request(request: Request):
    data = await request.json()
    print("Got request")
    user_location = tuple(data["location"])
    distance = geodesic(user_location, EDGE_LOCATION).km
    delay = distance / 200  # ~200 km/ms
    await asyncio.sleep(delay)
    return {"response": "data", "delay": delay, "cdn_location": EDGE_LOCATION}