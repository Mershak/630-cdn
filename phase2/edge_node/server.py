from fastapi import FastAPI, Request
from geopy.distance import geodesic
import httpx
import time
import os
import random
from collections import OrderedDict

app = FastAPI()

# Edge node's physical location
NODE_LAT = float(os.getenv("LAT"))
NODE_LON = float(os.getenv("LON"))
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "50"))

# Network simulation parameters
SPEED_OF_LIGHT_KM_PER_SEC = 299792
FIBER_REFRACTIVE_INDEX = 1.47
FIBER_SPEED = SPEED_OF_LIGHT_KM_PER_SEC / FIBER_REFRACTIVE_INDEX
ROUTER_DELAY = 0.0001
ESTIMATED_HOPS_PER_1000KM = 2

# Origin server URL
ORIGIN_URL = "http://origin:8000"

# FIFO Cache using OrderedDict
cache = OrderedDict()

def calculate_network_delay(client_lat: float, client_lon: float) -> float:
    """Calculate network delay based on physical distance and realistic network factors."""
    server_location = (NODE_LAT, NODE_LON)
    client_location = (client_lat, client_lon)
    
    distance = geodesic(server_location, client_location).kilometers
    
    # Calculate propagation delay through fiber
    propagation_delay = distance / FIBER_SPEED
    
    # Calculate number of router hops based on distance
    num_hops = max(1, int(distance * ESTIMATED_HOPS_PER_1000KM / 1000))
    total_router_delay = num_hops * ROUTER_DELAY
    
    # Add base latency (processing, queuing, etc.) - between 1-2ms
    base_latency = random.uniform(0.001, 0.002)
    
    # Add jitter (±0.5ms)
    jitter = random.uniform(-0.0005, 0.0005)
    
    total_delay = propagation_delay + total_router_delay + base_latency + jitter
    return total_delay

async def fetch_from_origin(content_id: str) -> dict:
    """Fetch content from origin server."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{ORIGIN_URL}/content/{content_id}",
            params={
                "client_lat": NODE_LAT,
                "client_lon": NODE_LON
            }
        )
        return response.json()

@app.get("/content/{content_id}")
async def get_content(content_id: str, request: Request, client_lat: float, client_lon: float):
    request_start = time.time()
    
    # Calculate network delay to client
    client_delay = calculate_network_delay(client_lat, client_lon)
    
    # Check cache
    cache_hit = False
    if content_id in cache:
        content_data = cache[content_id]
        cache_hit = True
        # Move to end to maintain FIFO order
        cache.move_to_end(content_id)
        total_delay = client_delay
    else:
        # Fetch from origin
        content_data = await fetch_from_origin(content_id)
        
        # Add to cache
        cache[content_id] = content_data
        if len(cache) > CACHE_SIZE:
            # Remove oldest item (FIFO)
            cache.popitem(last=False)
            
        # Total theoretical delay includes origin server delay
        total_delay = client_delay + content_data["metrics"]["network_delay"]
    
    request_end = time.time()
    actual_processing_time = request_end - request_start
    
    return {
        "content": content_data["content"],
        "metrics": {
            "network_delay": total_delay,
            "processing_time": actual_processing_time,
            "cache_hit": cache_hit,
            "edge_node_location": {"lat": NODE_LAT, "lon": NODE_LON}
        }
    } 