from fastapi import FastAPI, Request
from geopy.distance import geodesic
import time
import os
import random

app = FastAPI()

# Server's physical location
SERVER_LAT = float(os.getenv("LAT", "39.8283"))
SERVER_LON = float(os.getenv("LON", "-77.6115"))

# Network simulation parameters
SPEED_OF_LIGHT_KM_PER_SEC = 299792  # Speed of light in km/s
FIBER_REFRACTIVE_INDEX = 1.47  # Typical refractive index of fiber optic cable
FIBER_SPEED = SPEED_OF_LIGHT_KM_PER_SEC / FIBER_REFRACTIVE_INDEX  # Speed in fiber
ROUTER_DELAY = 0.001  # 1ms per router hop
ESTIMATED_HOPS_PER_1000KM = 2  # Estimate 2 router hops per 1000km

# Simulated content database (for now just random response sizes)
CONTENT_DB = {
    f"content_{i}": "x" * random.randint(1000, 100000)  # Random content sizes
    for i in range(100)
}

def calculate_network_delay(client_lat: float, client_lon: float) -> float:
    """Calculate network delay based on physical distance and realistic network factors."""
    server_location = (SERVER_LAT, SERVER_LON)
    client_location = (client_lat, client_lon)
    
    # Calculate distance in kilometers
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

@app.get("/content/{content_id}")
async def get_content(content_id: str, request: Request, client_lat: float, client_lon: float):
    # Calculate network delay
    delay = calculate_network_delay(client_lat, client_lon)
    
    # Simulate processing time (0.01-0.1ms)
    processing_time = random.uniform(0.00001, 0.0001)
    
    # Simulate the actual delay
    time.sleep(delay + processing_time)
    
    # Get content or return 404
    content = CONTENT_DB.get(content_id, None)
    if content is None:
        return {"error": "Content not found"}
        
    return {
        "content": content,
        "metrics": {
            "network_delay": delay,
            "processing_time": processing_time,
            "total_time": delay + processing_time,
            "content_size": len(content),
            "server_location": {"lat": SERVER_LAT, "lon": SERVER_LON}
        }
    } 