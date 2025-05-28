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
SPEED_OF_LIGHT_KM_PER_SEC = 299792
FIBER_REFRACTIVE_INDEX = 1.47
FIBER_SPEED = SPEED_OF_LIGHT_KM_PER_SEC / FIBER_REFRACTIVE_INDEX
ROUTER_DELAY = 0.0001  # Reduced to 0.1ms per router hop
ESTIMATED_HOPS_PER_1000KM = 2

# Edge node locations
EDGE_NODES = [
    {
        "id": "edge1",
        "location": "New York, NY",
        "lat": 40.7128,
        "lon": -74.0060,
        "url": "http://edge1:8000"
    },
    {
        "id": "edge2",
        "location": "Chicago, IL",
        "lat": 41.8781,
        "lon": -87.6298,
        "url": "http://edge2:8000"
    },
    {
        "id": "edge3",
        "location": "Los Angeles, CA",
        "lat": 34.0522,
        "lon": -118.2437,
        "url": "http://edge3:8000"
    },
    {
        "id": "edge4",
        "location": "Houston, TX",
        "lat": 29.7604,
        "lon": -95.3698,
        "url": "http://edge4:8000"
    }
]

# Simulated content database
CONTENT_DB = {
    f"content_{i}": "x" * random.randint(1000, 100000)  # Random content sizes
    for i in range(100)
}

def calculate_network_delay(client_lat: float, client_lon: float, is_edge_request: bool = False) -> float:
    """Calculate network delay based on physical distance and realistic network factors."""
    server_location = (SERVER_LAT, SERVER_LON)
    client_location = (client_lat, client_lon)
    
    distance = geodesic(server_location, client_location).kilometers
    
    # Calculate propagation delay through fiber
    propagation_delay = distance / FIBER_SPEED
    
    # Calculate number of router hops based on distance
    num_hops = max(1, int(distance * ESTIMATED_HOPS_PER_1000KM / 1000))
    total_router_delay = num_hops * ROUTER_DELAY
    
    if is_edge_request:
        # Edge nodes have optimized routing and lower base latency
        total_router_delay *= 0.5  # Fewer hops for edge->origin
        base_latency = random.uniform(0.0001, 0.0002)  # 0.1-0.2ms
        jitter = random.uniform(-0.00005, 0.00005)  # ±0.05ms
    else:
        # Regular user requests have normal latency
        base_latency = random.uniform(0.001, 0.002)  # 1-2ms
        jitter = random.uniform(-0.0005, 0.0005)  # ±0.5ms
    
    total_delay = propagation_delay + total_router_delay + base_latency + jitter
    return total_delay

@app.get("/discover_cdn")
async def discover_cdn(request: Request, client_lat: float, client_lon: float):
    """Find the closest edge node for the client."""
    client_location = (client_lat, client_lon)
    
    # Calculate distances to all edge nodes
    edge_distances = []
    for node in EDGE_NODES:
        node_location = (node["lat"], node["lon"])
        distance = geodesic(client_location, node_location).kilometers
        edge_distances.append((distance, node))
    
    # Sort by distance and return the closest node
    closest_edge = min(edge_distances, key=lambda x: x[0])[1]
    
    return {
        "edge_node": closest_edge,
        "distance_km": geodesic(client_location, (closest_edge["lat"], closest_edge["lon"])).kilometers
    }

@app.get("/content/{content_id}")
async def get_content(content_id: str, request: Request, client_lat: float, client_lon: float):
    """Serve content directly (used by edge nodes)."""
    request_start = time.time()
    
    # Check if request is from an edge node
    is_edge_request = any(
        abs(node["lat"] - client_lat) < 0.001 and abs(node["lon"] - client_lon) < 0.001
        for node in EDGE_NODES
    )
    
    # Calculate theoretical network delay based on who is making the request
    network_delay = calculate_network_delay(client_lat, client_lon, is_edge_request)
    
    # Get content or return 404
    content = CONTENT_DB.get(content_id, None)
    if content is None:
        return {"error": "Content not found"}
    
    request_end = time.time()
    actual_processing_time = request_end - request_start
        
    return {
        "content": content,
        "metrics": {
            "network_delay": network_delay,
            "processing_time": actual_processing_time,
            "content_size": len(content),
            "server_location": {"lat": SERVER_LAT, "lon": SERVER_LON}
        }
    } 