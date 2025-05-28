from fastapi import FastAPI, Request
from geopy.distance import geodesic
import httpx
import time
import os
import random

app = FastAPI()

# Edge node's physical location
NODE_LAT = float(os.getenv("LAT"))
NODE_LON = float(os.getenv("LON"))
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "50"))

# Network simulation parameters
SPEED_OF_LIGHT_KM_PER_SEC = 299792
FIBER_REFRACTIVE_INDEX = 1.47
FIBER_SPEED = SPEED_OF_LIGHT_KM_PER_SEC / FIBER_REFRACTIVE_INDEX
ROUTER_DELAY = 0.0001  # Reduced to 0.1ms per router hop
ESTIMATED_HOPS_PER_1000KM = 2

# Origin server URL
ORIGIN_URL = "http://origin:8000"

class ARCache:
    """Adaptive Replacement Cache implementation."""
    def __init__(self, size):
        self.cache_size = size
        self.p = 0  # Target size for T1
        
        # Initialize the lists
        self.T1 = {}  # Recent items
        self.T2 = {}  # Frequent items
        self.B1 = set()  # Ghost entries for T1
        self.B2 = set()  # Ghost entries for T2
    
    def replace(self, key):
        """Handle cache replacement."""
        if self.T1 and (len(self.B2) > len(self.B1) and len(self.T1) > self.p or len(self.T1) > self.cache_size):
            # Remove from T1 and add to B1
            lru_key = next(iter(self.T1))
            self.B1.add(lru_key)
            del self.T1[lru_key]
        else:
            # Remove from T2 and add to B2
            lru_key = next(iter(self.T2))
            self.B2.add(lru_key)
            del self.T2[lru_key]
            
        # Keep ghost lists at cache size
        while len(self.B1) > self.cache_size:
            self.B1.remove(next(iter(self.B1)))
        while len(self.B2) > self.cache_size:
            self.B2.remove(next(iter(self.B2)))
    
    def get(self, key):
        """Get an item from the cache."""
        if key in self.T1:
            # Move from T1 to T2 (frequently used)
            value = self.T1.pop(key)
            self.T2[key] = value
            return value, True
        elif key in self.T2:
            # Already in T2, move to MRU position
            value = self.T2.pop(key)
            self.T2[key] = value
            return value, True
        return None, False
    
    def put(self, key, value):
        """Add an item to the cache."""
        if key in self.B1:
            # Hit in B1: Increase p
            self.p = min(self.p + max(len(self.B2) / len(self.B1), 1), self.cache_size)
            self.replace(key)
            self.B1.remove(key)
            self.T2[key] = value
        elif key in self.B2:
            # Hit in B2: Decrease p
            self.p = max(self.p - max(len(self.B1) / len(self.B2), 1), 0)
            self.replace(key)
            self.B2.remove(key)
            self.T2[key] = value
        else:
            # Miss in all lists
            if len(self.T1) + len(self.T2) >= self.cache_size:
                self.replace(key)
            elif len(self.T1) + len(self.T2) + len(self.B1) + len(self.B2) >= self.cache_size:
                if len(self.B1) + len(self.B2) >= self.cache_size:
                    if self.B1:
                        self.B1.remove(next(iter(self.B1)))
                    else:
                        self.B2.remove(next(iter(self.B2)))
            self.T1[key] = value

# Initialize ARC cache
cache = ARCache(CACHE_SIZE)

def calculate_network_delay(client_lat: float, client_lon: float, is_cache_hit: bool = False) -> float:
    """Calculate network delay based on physical distance and realistic network factors."""
    server_location = (NODE_LAT, NODE_LON)
    client_location = (client_lat, client_lon)
    
    distance = geodesic(server_location, client_location).kilometers
    
    # Calculate propagation delay through fiber
    propagation_delay = distance / FIBER_SPEED
    
    # Calculate number of router hops based on distance
    num_hops = max(1, int(distance * ESTIMATED_HOPS_PER_1000KM / 1000))
    total_router_delay = num_hops * ROUTER_DELAY * 0.5  # Edge nodes have optimized routing
    
    # Add minimal base latency for edge node (0.1-0.2ms)
    base_latency = random.uniform(0.0001, 0.0002)
    
    # Add minimal jitter for edge node (±0.05ms)
    jitter = random.uniform(-0.00005, 0.00005)
    
    # For cache hits, we only need user->edge delay
    # For cache misses, the origin server will add its own delay
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
    
    # Check cache first
    content_data, cache_hit = cache.get(content_id)
    
    # Calculate network delay for user->edge path
    client_delay = calculate_network_delay(client_lat, client_lon)
    
    if not cache_hit:
        # Fetch from origin
        content_data = await fetch_from_origin(content_id)
        # Add to cache
        cache.put(content_id, content_data)
        # Total theoretical delay is user->edge + edge->origin
        total_delay = client_delay + content_data["metrics"]["network_delay"]
    else:
        # For cache hits, we only need the user->edge delay
        total_delay = client_delay
    
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