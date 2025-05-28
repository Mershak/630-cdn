from fastapi import FastAPI, Request
from geopy.distance import geodesic
import httpx
import time
import os
import random
import asyncio
from collections import defaultdict

app = FastAPI()

# Edge node's physical location
NODE_LAT = float(os.getenv("LAT"))
NODE_LON = float(os.getenv("LON"))
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "50"))

# Network simulation parameters
SPEED_OF_LIGHT_KM_PER_SEC = 299792
FIBER_REFRACTIVE_INDEX = 1.47
FIBER_SPEED = SPEED_OF_LIGHT_KM_PER_SEC / FIBER_REFRACTIVE_INDEX
ROUTER_DELAY = 0.0001  # 0.1ms per router hop
ESTIMATED_HOPS_PER_1000KM = 2

# Origin server URL
ORIGIN_URL = "http://origin:8000"

# Load tracking with more aggressive thresholds
active_requests = 0
LOAD_THRESHOLD = 3  # Start slowing at 4 concurrent requests
MAX_LOAD = 8       # Maximum concurrent requests
request_history = defaultdict(int)  # Track requests per user
processing_delay = 0.0001  # Back to original fast processing (0.1ms)

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
    
    def get(self, key):
        """Get an item from the cache."""
        if key in self.T1:
            # Move from T1 to T2
            item = self.T1.pop(key)
            self.T2[key] = item
            return item, True
        elif key in self.T2:
            # Already in T2, just return
            return self.T2[key], True
        return None, False
    
    def put(self, key, value):
        """Add an item to the cache."""
        # Case 1: Item in B1 (recently evicted from T1)
        if key in self.B1:
            # Increase target size for T1
            self.p = min(self.p + max(1, len(self.B2) / len(self.B1)), self.cache_size)
            self._replace(key)
            self.B1.remove(key)
            self.T2[key] = value
            
        # Case 2: Item in B2 (recently evicted from T2)
        elif key in self.B2:
            # Decrease target size for T1
            self.p = max(self.p - max(1, len(self.B1) / len(self.B2)), 0)
            self._replace(key)
            self.B2.remove(key)
            self.T2[key] = value
            
        # Case 3: New item
        else:
            total_items = len(self.T1) + len(self.T2)
            
            # Case 3a: Cache has space
            if total_items < self.cache_size:
                self.T1[key] = value
                
            # Case 3b: Cache is full
            else:
                if len(self.T1) + len(self.B1) == self.cache_size:
                    if len(self.T1) < self.cache_size:
                        self.B1.remove(next(iter(self.B1)))
                        self._replace(key)
                    else:
                        evicted_key = next(iter(self.T1))
                        self.B1.add(evicted_key)
                        self.T1.pop(evicted_key)
                else:
                    if len(self.T1) + len(self.T2) + len(self.B1) + len(self.B2) >= self.cache_size:
                        if len(self.T1) + len(self.T2) + len(self.B1) + len(self.B2) == 2 * self.cache_size:
                            self.B2.remove(next(iter(self.B2)))
                    self._replace(key)
                self.T1[key] = value
    
    def _replace(self, key):
        """Helper method for replacement."""
        if len(self.T1) >= max(1, self.p):
            # Move from T1 to B1
            evicted_key = next(iter(self.T1))
            self.B1.add(evicted_key)
            self.T1.pop(evicted_key)
        else:
            # Move from T2 to B2
            evicted_key = next(iter(self.T2))
            self.B2.add(evicted_key)
            self.T2.pop(evicted_key)

# Initialize ARC cache
cache = ARCache(CACHE_SIZE)

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
    
    # Add base latency (processing, queuing, etc.)
    base_latency = random.uniform(0.0001, 0.0002)
    
    # Add jitter
    jitter = random.uniform(-0.00005, 0.00005)
    
    total_delay = propagation_delay + total_router_delay + base_latency + jitter
    return total_delay

def calculate_load_delay() -> float:
    """Calculate additional delay based on current load with more aggressive scaling."""
    if active_requests <= LOAD_THRESHOLD:
        return 0  # No delay for normal load
    
    # More aggressive exponential delay increase after threshold
    overload_factor = (active_requests - LOAD_THRESHOLD) / (MAX_LOAD - LOAD_THRESHOLD)
    if overload_factor > 1:
        overload_factor = 1
    
    # Delay kicks in strongly after threshold
    # At max load (8 requests): up to 3 seconds
    # At threshold + 1 (5 requests): ~100ms
    # At threshold + 2 (6 requests): ~500ms
    base_delay = 3.0 * (overload_factor ** 4)  # Very aggressive scaling after threshold
    
    # Add small jitter only during overload
    jitter = random.uniform(0, 0.05) * overload_factor
    
    return base_delay + jitter

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
    global active_requests
    
    # Increment active requests counter
    active_requests += 1
    client_ip = request.client.host
    request_history[client_ip] += 1
    
    try:
        request_start = time.time()
        
        # Calculate network delay for user->edge path
        client_delay = calculate_network_delay(client_lat, client_lon)
        
        # Check cache first
        content_data, cache_hit = cache.get(content_id)
        
        if not cache_hit:
            # Fetch from origin
            content_data = await fetch_from_origin(content_id)
            # Add to cache
            cache.put(content_id, content_data)
            # Total theoretical delay includes origin server delay
            total_delay = client_delay + content_data["metrics"]["network_delay"]
        else:
            # For cache hits, we only need the user->edge delay
            total_delay = client_delay
        
        # Add load-based processing delay
        load_delay = calculate_load_delay()
        total_delay += load_delay
        
        request_end = time.time()
        actual_processing_time = request_end - request_start
        
        return {
            "content": content_data["content"],
            "metrics": {
                "network_delay": total_delay,
                "processing_time": actual_processing_time,
                "cache_hit": cache_hit,
                "edge_node_location": {"lat": NODE_LAT, "lon": NODE_LON},
                "current_load": active_requests,
                "load_delay": load_delay
            }
        }
    finally:
        # Decrement active requests counter
        active_requests -= 1 