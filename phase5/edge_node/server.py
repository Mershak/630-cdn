from fastapi import FastAPI, Request
from geopy.distance import geodesic
import httpx
import time
import os
import random
import asyncio
from collections import defaultdict
import json

app = FastAPI()

# Edge node's physical location
NODE_LAT = float(os.getenv("LAT"))
NODE_LON = float(os.getenv("LON"))
NODE_ID = os.getenv("NODE_ID")  # e.g., "edge1", "edge2"
CACHE_SIZE = int(os.getenv("CACHE_SIZE", "50"))

# Network simulation parameters
SPEED_OF_LIGHT_KM_PER_SEC = 299792
FIBER_REFRACTIVE_INDEX = 1.47
FIBER_SPEED = SPEED_OF_LIGHT_KM_PER_SEC / FIBER_REFRACTIVE_INDEX
ROUTER_DELAY = 0.0001  # 0.1ms per router hop
ESTIMATED_HOPS_PER_1000KM = 2

# Origin server URL
ORIGIN_URL = "http://origin:8000"

# Load tracking
active_requests = 0
LOAD_THRESHOLD = 3  # Start slowing at 3 concurrent requests
MAX_LOAD = 8       # Maximum concurrent requests
request_history = defaultdict(int)  # Track requests per user
processing_delay = 0.0001  # Fast processing (0.1ms)

# Load balancing parameters
LOAD_UPDATE_INTERVAL = 2  # Seconds between load updates
LOAD_HISTORY_SIZE = 12    # Keep 1 minute of history (12 * 5 seconds)
MAX_RECOMMENDATIONS = 2   # Prevent recommendation loops
LOAD_DIFF_THRESHOLD = 0.3  # Minimum load difference to trigger recommendation
HIGH_LOAD_THRESHOLD = 0.7  # Consider node as highly loaded

# Edge nodes registry (will be populated from environment)
EDGE_NODES = {}  # Will store {node_id: {"url": "...", "lat": X, "lon": Y, "load": Z}}
node_loads = defaultdict(list)  # Historical load tracking

# Cache implementation
class Cache:
    def __init__(self, size):
        self.size = size
        self.items = {}
        self.access_times = {}
    
    def get(self, key):
        """Get item from cache."""
        if key in self.items:
            self.access_times[key] = time.time()
            return self.items[key], True
        return None, False
    
    def put(self, key, value):
        """Add item to cache with FIFO replacement."""
        if len(self.items) >= self.size:
            # Remove oldest item
            oldest_key = min(self.access_times.items(), key=lambda x: x[1])[0]
            del self.items[oldest_key]
            del self.access_times[oldest_key]
        
        self.items[key] = value
        self.access_times[key] = time.time()

# Initialize cache
cache = Cache(CACHE_SIZE)

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
    
    # Add base latency
    base_latency = random.uniform(0.0001, 0.0002)
    
    # Add jitter
    jitter = random.uniform(-0.00005, 0.00005)
    
    total_delay = propagation_delay + total_router_delay + base_latency + jitter
    return total_delay

def calculate_load_delay() -> float:
    """Calculate additional delay based on current load with aggressive scaling."""
    if active_requests <= LOAD_THRESHOLD:
        return 0  # No delay for normal load
    
    # Aggressive exponential delay increase after threshold
    overload_factor = (active_requests - LOAD_THRESHOLD) / (MAX_LOAD - LOAD_THRESHOLD)
    if overload_factor > 1:
        overload_factor = 1
    
    # Delay kicks in strongly after threshold
    base_delay = 3.0 * (overload_factor ** 4)  # Very aggressive scaling after threshold
    
    # Add small jitter only during overload
    jitter = random.uniform(0, 0.05) * overload_factor
    
    return base_delay + jitter

def get_current_load_score() -> float:
    """Calculate a normalized load score between 0 and 1."""
    if active_requests <= LOAD_THRESHOLD:
        return active_requests / (MAX_LOAD * 2)  # Low load: 0 to 0.25
    else:
        # High load: 0.25 to 1.0
        overload = min(active_requests - LOAD_THRESHOLD, MAX_LOAD - LOAD_THRESHOLD)
        return 0.25 + (0.75 * overload / (MAX_LOAD - LOAD_THRESHOLD))

def get_network_load_stats():
    """Calculate average and standard deviation of load across all nodes."""
    loads = [node.get("load", 0.0) for node in EDGE_NODES.values()]
    loads.append(get_current_load_score())  # Include our load
    
    # Calculate average
    avg_load = sum(loads) / len(loads)
    
    # Calculate standard deviation
    variance = sum((x - avg_load) ** 2 for x in loads) / len(loads)
    std_dev = variance ** 0.5
    
    return avg_load, std_dev

def should_consider_recommendation(current_load: float, client_lat: float, client_lon: float) -> tuple[bool, str]:
    """Determine if we should recommend another node based on network-wide load."""
    # Don't recommend if we're not highly loaded
    if current_load < HIGH_LOAD_THRESHOLD:
        return False, ""
    
    # Find the least loaded node that's significantly better
    best_node = None
    best_score = float('inf')
    
    for node_id, node_data in EDGE_NODES.items():
        if node_id == NODE_ID:
            continue
            
        node_load = node_data.get("load", 0.0)
        
        # Only consider nodes with significantly lower load
        if node_load > current_load - LOAD_DIFF_THRESHOLD:
            continue
            
        # Calculate distance score (0 to 1, lower is better)
        distance = geodesic(
            (client_lat, client_lon),
            (node_data["lat"], node_data["lon"])
        ).kilometers
        max_distance = 3000  # Approximate max distance across continental US
        distance_score = min(1.0, distance / max_distance)
        
        # Combined score (70% distance, 30% load)
        score = 0.7 * distance_score + 0.3 * node_load
        
        if score < best_score:
            best_score = score
            best_node = node_id
    
    if best_node:
        return True, best_node
    return False, ""

async def update_node_registry():
    """Fetch the list of edge nodes from origin server."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{ORIGIN_URL}/edge_nodes")
        EDGE_NODES.update(response.json())

async def share_load_info():
    """Periodically share load information with other nodes."""
    # Initial delay to allow other nodes to start
    await asyncio.sleep(5)
    
    async with httpx.AsyncClient(
        timeout=2.0,
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
    ) as client:
        while True:
            try:
                current_load = get_current_load_score()
                print(f"[{NODE_ID}] Current load: {current_load:.2f}, Active requests: {active_requests}")
                
                # Update local load history
                node_loads[NODE_ID] = node_loads[NODE_ID][-LOAD_HISTORY_SIZE:] + [current_load]
                
                # Share load with other nodes in parallel
                update_tasks = []
                for node_id, node_data in EDGE_NODES.items():
                    if node_id != NODE_ID:
                        task = client.post(
                            f"{node_data['url']}/load_update",
                            json={
                                "node_id": NODE_ID,
                                "load": current_load,
                                "timestamp": time.time(),
                                "active_requests": active_requests
                            },
                            timeout=1.0
                        )
                        update_tasks.append((node_id, task))
                
                if update_tasks:
                    for node_id, task in update_tasks:
                        try:
                            await task
                            print(f"[{NODE_ID}] Successfully updated load with {node_id}")
                        except Exception as e:
                            print(f"[{NODE_ID}] Failed to update {node_id}: {str(e)}")
                            await update_node_registry()
                
                # Print current load distribution
                print(f"\n[{NODE_ID}] Current network load distribution:")
                for node_id, node_data in EDGE_NODES.items():
                    load = node_data.get("load", 0.0)
                    print(f"  {node_id}: {load:.2f} ({node_data.get('active_requests', 0)} active requests)")
                print(f"  {NODE_ID}: {current_load:.2f} ({active_requests} active requests)\n")
                
                await asyncio.sleep(LOAD_UPDATE_INTERVAL)
            except Exception as e:
                print(f"[{NODE_ID}] Error in load sharing: {str(e)}")
                await asyncio.sleep(LOAD_UPDATE_INTERVAL)

@app.on_event("startup")
async def startup_event():
    """Initialize the edge node on startup."""
    await update_node_registry()
    asyncio.create_task(share_load_info())

@app.post("/load_update")
async def receive_load_update(data: dict):
    """Receive load updates from other nodes."""
    node_id = data["node_id"]
    load = data["load"]
    timestamp = data.get("timestamp", time.time())
    active_reqs = data.get("active_requests", 0)
    
    if node_id in EDGE_NODES:
        EDGE_NODES[node_id]["load"] = load
        EDGE_NODES[node_id]["last_update"] = timestamp
        EDGE_NODES[node_id]["active_requests"] = active_reqs
        node_loads[node_id] = node_loads[node_id][-LOAD_HISTORY_SIZE:] + [load]
        print(f"[{NODE_ID}] Received load update from {node_id}: {load:.2f}")
    else:
        print(f"[{NODE_ID}] Received update from unknown node {node_id}, refreshing registry")
        await update_node_registry()
    
    return {"status": "ok"}

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
async def get_content(
    content_id: str,
    request: Request,
    client_lat: float,
    client_lon: float,
    recommendations: int = 0
):
    global active_requests
    
    # Get current load score
    current_load = get_current_load_score()
    print(f"[{NODE_ID}] Received request for {content_id}. Current load: {current_load:.2f}, Active requests: {active_requests}")
    
    # Check if we should recommend another node
    if recommendations < MAX_RECOMMENDATIONS:
        recommend_decision, best_node = should_consider_recommendation(current_load, client_lat, client_lon)
        if recommend_decision:
            target_node = EDGE_NODES[best_node]
            target_load = target_node.get("load", 0.0)
            print(f"[{NODE_ID}] Recommending {best_node} (our load: {current_load:.2f}, target load: {target_load:.2f})")
            
            # Return recommendation to user
            return {
                "status": "recommend_node",
                "recommended_node": {
                    "node_id": best_node,
                    "url": target_node["url"],
                    "location": {
                        "lat": target_node["lat"],
                        "lon": target_node["lon"]
                    },
                    "current_load": target_load,
                    "distance_km": geodesic(
                        (client_lat, client_lon),
                        (target_node["lat"], target_node["lon"])
                    ).kilometers
                },
                "reason": {
                    "current_node_load": current_load,
                    "target_node_load": target_load,
                    "load_threshold": HIGH_LOAD_THRESHOLD,
                    "load_difference": current_load - target_load
                }
            }
    
    # Process request normally if no recommendation
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
        
        response_data = {
            "status": "success",
            "content": content_data["content"],
            "metrics": {
                "network_delay": total_delay,
                "processing_time": actual_processing_time,
                "cache_hit": cache_hit,
                "edge_node_location": {"lat": NODE_LAT, "lon": NODE_LON},
                "current_load": active_requests,
                "load_delay": load_delay,
                "node_id": NODE_ID
            }
        }
        
        print(f"[{NODE_ID}] Completed request for {content_id}. "
              f"Cache hit: {cache_hit}, Load delay: {load_delay:.3f}s, "
              f"Total delay: {total_delay:.3f}s")
        
        return response_data
    finally:
        active_requests -= 1 