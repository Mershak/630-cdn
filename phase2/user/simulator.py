import httpx
import asyncio
import random
import time
import os
import pandas as pd
from datetime import datetime
from pathlib import Path
from geopy.distance import geodesic

# Configuration
REQUESTS_PER_USER = int(os.getenv("REQUESTS_PER_USER", "20"))
ORIGIN_URL = os.getenv("ORIGIN_URL", "http://origin:8000")

# Ensure results directory exists
RESULTS_DIR = Path("/app/results")
RESULTS_DIR.mkdir(exist_ok=True)

# Fixed user locations - each edge node has 1 very close user and 1 slightly farther user
# Chicago has 3 users to create future overload scenario
USERS = [
    # Chicago users (3 users)
    {"id": 1, "city": "Chicago Downtown", "lat": 41.8781, "lon": -87.6298},  # Right in downtown
    {"id": 2, "city": "Chicago North", "lat": 42.0451, "lon": -87.6877},     # Evanston area
    {"id": 3, "city": "Chicago West", "lat": 41.8825, "lon": -87.9089},      # Oak Park area
    
    # New York users
    {"id": 4, "city": "Manhattan", "lat": 40.7128, "lon": -74.0060},        # Very close
    {"id": 5, "city": "Newark", "lat": 40.7357, "lon": -74.1724},           # Bit farther
    
    # Los Angeles users
    {"id": 6, "city": "LA Downtown", "lat": 34.0522, "lon": -118.2437},     # Very close
    {"id": 7, "city": "Santa Monica", "lat": 34.0195, "lon": -118.4912},    # Bit farther
    
    # Houston users
    {"id": 8, "city": "Houston Downtown", "lat": 29.7604, "lon": -95.3698}, # Very close
    {"id": 9, "city": "The Woodlands", "lat": 30.1658, "lon": -95.4613},    # Bit farther
]

def generate_request_sequence():
    """Generate a sequence of requests."""
    return [f"content_{i % 100}" for i in range(REQUESTS_PER_USER)]

class User:
    def __init__(self, user_data: dict):
        self.id = user_data["id"]
        self.location = {
            "city": user_data["city"],
            "lat": user_data["lat"],
            "lon": user_data["lon"]
        }
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_network_time = 0
        self.cache_hits = 0
        self.request_sequence = generate_request_sequence()
        self.results = []
        self.edge_node = None
        
        # Calculate distance to origin
        self.distance_to_origin = geodesic(
            (self.location["lat"], self.location["lon"]),
            (39.8283, -77.6115)  # Ashburn, VA
        ).kilometers

    async def discover_cdn(self):
        """Find the closest edge node."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ORIGIN_URL}/discover_cdn",
                params={
                    "client_lat": self.location["lat"],
                    "client_lon": self.location["lon"]
                }
            )
            data = response.json()
            self.edge_node = data["edge_node"]
            self.distance_to_edge = data["distance_km"]

    async def make_requests(self):
        # First discover the closest CDN edge node
        await self.discover_cdn()
        
        async with httpx.AsyncClient() as client:
            for i, content_id in enumerate(self.request_sequence):
                try:
                    request_start = time.time()
                    response = await client.get(
                        f"{self.edge_node['url']}/content/{content_id}",
                        params={
                            "client_lat": self.location["lat"],
                            "client_lon": self.location["lon"]
                        }
                    )
                    request_end = time.time()
                    
                    if response.status_code == 200:
                        self.successful_requests += 1
                        data = response.json()
                        
                        # Use the theoretical network delay instead of actual request time
                        theoretical_time = data["metrics"]["network_delay"]
                        self.total_network_time += theoretical_time
                        
                        # Track cache hits
                        if data["metrics"]["cache_hit"]:
                            self.cache_hits += 1
                        
                        # Store request info
                        self.results.append({
                            "request_number": i + 1,
                            "content_id": content_id,
                            "theoretical_time": theoretical_time,
                            "actual_time": request_end - request_start,
                            "cache_hit": data["metrics"]["cache_hit"]
                        })
                    else:
                        self.failed_requests += 1
                except Exception as e:
                    print(f"Error for user {self.id}, request {i+1}: {str(e)}")
                    self.failed_requests += 1
                
                # Think time between requests
                await asyncio.sleep(random.uniform(0.1, 1.0))
    
    def get_summary(self):
        return {
            "user_id": self.id,
            "city": self.location["city"],
            "distance_to_origin_km": self.distance_to_origin,
            "distance_to_edge_km": self.distance_to_edge,
            "edge_node_location": self.edge_node["location"],
            "total_network_time": self.total_network_time,
            "average_request_time": self.total_network_time / max(self.successful_requests, 1),
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "cache_hits": self.cache_hits,
            "cache_hit_ratio": self.cache_hits / max(self.successful_requests, 1)
        }

async def main():
    # Create users with fixed locations
    users = [User(user_data) for user_data in USERS]
    
    # Start time for the whole simulation
    simulation_start = time.time()
    
    # Run all users concurrently
    await asyncio.gather(*(user.make_requests() for user in users))
    
    # Calculate total simulation time
    simulation_time = time.time() - simulation_start
    
    # Collect user summaries
    user_summaries = [user.get_summary() for user in users]
    
    # Create DataFrame and clean up the data
    df = pd.DataFrame(user_summaries)
    
    # Round numeric columns
    df['distance_to_origin_km'] = df['distance_to_origin_km'].round(1)
    df['distance_to_edge_km'] = df['distance_to_edge_km'].round(1)
    df['total_network_time'] = df['total_network_time'].round(3)
    df['average_request_time'] = (df['average_request_time'] * 1000).round(1)  # Convert to ms and round
    df['cache_hit_ratio'] = df['cache_hit_ratio'].round(3)
    
    # Sort by distance to edge
    df = df.sort_values('distance_to_edge_km')
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"phase2_results_{timestamp}.csv"
    df.to_csv(csv_path, index=False, float_format='%.3g')
    print(f"\nResults saved to: {csv_path}")
    
    # Print summary statistics
    print("\nSimulation Summary:")
    print(f"Total simulation time: {simulation_time:.2f} seconds")
    print(f"Number of users: {len(USERS)}")
    print(f"Requests per user: {REQUESTS_PER_USER}")
    
    # Calculate average improvements
    avg_origin_distance = df["distance_to_origin_km"].mean()
    avg_edge_distance = df["distance_to_edge_km"].mean()
    distance_improvement = ((avg_origin_distance - avg_edge_distance) / avg_origin_distance) * 100
    
    print(f"\nDistance Improvement:")
    print(f"Average distance to origin: {avg_origin_distance:.1f}km")
    print(f"Average distance to edge: {avg_edge_distance:.1f}km")
    print(f"Distance reduction: {distance_improvement:.1f}%")
    
    print("\nCache Performance:")
    total_cache_hit_ratio = (df["cache_hits"].sum() / df["successful_requests"].sum()).round(3)
    print(f"Overall cache hit ratio: {total_cache_hit_ratio:.1%}")
    
    # Group by edge node to show load distribution
    print("\nLoad Distribution by Edge Node:")
    edge_node_stats = df.groupby('edge_node_location').agg({
        'successful_requests': 'sum',
        'cache_hits': 'sum',
        'average_request_time': 'mean'
    }).round(1)
    edge_node_stats['cache_hit_ratio'] = (edge_node_stats['cache_hits'] / edge_node_stats['successful_requests']).round(3)
    print(edge_node_stats)
    
    # Print detailed statistics
    print("\nDetailed User Statistics (sorted by distance to edge):")
    for _, row in df.iterrows():
        print(f"{row['city']:20} - Edge: {row['edge_node_location']:15} "
              f"Distance: {row['distance_to_edge_km']:5.1f}km, "
              f"Total Time: {row['total_network_time']*1000:6.1f}ms, "
              f"Avg Time: {row['average_request_time']:5.1f}ms, "
              f"Cache Hits: {row['cache_hit_ratio']:.1%}")

if __name__ == "__main__":
    asyncio.run(main()) 