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
REQUESTS_PER_USER = {
    "Chicago": 30,  # Chicago users make more requests
    "default": 20   # Other users make normal number of requests
}
ORIGIN_URL = os.getenv("ORIGIN_URL", "http://origin:8000")

# Ensure results directory exists
RESULTS_DIR = Path("/app/results")
RESULTS_DIR.mkdir(exist_ok=True)

# Fixed user locations with more Chicago users to create overload
USERS = [
    # Chicago users (6 users - doubled from before)
    {"id": 1, "city": "Chicago Downtown", "lat": 41.8781, "lon": -87.6298},
    {"id": 2, "city": "Chicago North", "lat": 42.0451, "lon": -87.6877},
    {"id": 3, "city": "Chicago West", "lat": 41.8825, "lon": -87.9089},
    {"id": 4, "city": "Chicago South", "lat": 41.7275, "lon": -87.6533},
    {"id": 5, "city": "Chicago East", "lat": 41.8936, "lon": -87.6224},
    {"id": 6, "city": "Chicago Suburb", "lat": 42.0334, "lon": -87.7825},
    
    # New York users (unchanged)
    {"id": 7, "city": "Manhattan", "lat": 40.7128, "lon": -74.0060},
    {"id": 8, "city": "Newark", "lat": 40.7357, "lon": -74.1724},
    
    # Los Angeles users (unchanged)
    {"id": 9, "city": "LA Downtown", "lat": 34.0522, "lon": -118.2437},
    {"id": 10, "city": "Santa Monica", "lat": 34.0195, "lon": -118.4912},
    
    # Houston users (unchanged)
    {"id": 11, "city": "Houston Downtown", "lat": 29.7604, "lon": -95.3698},
    {"id": 12, "city": "The Woodlands", "lat": 30.1658, "lon": -95.4613}
]

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
        self.total_load_delay = 0
        self.cache_hits = 0
        self.recommendations = 0
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

    async def make_request(self, content_id: str, edge_url: str, recommendations: int = 0):
        """Make a request to an edge node with recommendation handling."""
        response = await self.client.get(
            f"{edge_url}/content/{content_id}",
            params={
                "client_lat": self.location["lat"],
                "client_lon": self.location["lon"],
                "recommendations": recommendations
            }
        )
        
        data = response.json()
        
        # Check if we got a node recommendation
        if data.get("status") == "recommend_node":
            if recommendations < 2:  # Limit recommendation chain
                recommended = data["recommended_node"]
                print(f"{self.location['city']}: Received recommendation to use {recommended['node_id']} "
                      f"(load: {recommended['current_load']:.2f}, distance: {recommended['distance_km']:.1f}km)")
                
                self.recommendations += 1
                
                # Try the recommended node
                return await self.make_request(content_id, recommended["url"], recommendations + 1)
            else:
                print(f"{self.location['city']}: Too many recommendations, using current node anyway")
        
        return data

    async def make_requests(self):
        """Make a series of requests with load-aware edge node selection."""
        # First discover the closest CDN edge node
        await self.discover_cdn()
        
        # Create a shared client for all requests
        async with httpx.AsyncClient(timeout=30.0) as client:
            self.client = client
            
            # Determine number of requests based on location
            num_requests = REQUESTS_PER_USER["Chicago"] if "Chicago" in self.location["city"] else REQUESTS_PER_USER["default"]
            
            for i in range(num_requests):
                try:
                    # Generate content request based on location
                    if "Chicago" in self.location["city"]:
                        # Chicago users request more data-heavy content
                        content_id = f"content_{random.randint(80, 99)}" if random.random() < 0.7 else f"content_{random.randint(0, 79)}"
                    else:
                        # Other users have normal request patterns
                        r = random.random()
                        if r < 0.6:  # 60% popular content
                            content_id = f"content_{random.randint(0, 9)}"
                        elif r < 0.9:  # 30% semi-popular
                            content_id = f"content_{random.randint(10, 29)}"
                        else:  # 10% rare
                            content_id = f"content_{random.randint(30, 99)}"
                    
                    start_time = time.time()
                    data = await self.make_request(content_id, self.edge_node["url"])
                    end_time = time.time()
                    
                    if data.get("status") == "success":
                        self.successful_requests += 1
                        metrics = data["metrics"]
                        
                        # Track metrics
                        self.total_network_time += metrics["network_delay"]
                        self.total_load_delay += metrics.get("load_delay", 0)
                        if metrics.get("cache_hit", False):
                            self.cache_hits += 1
                    else:
                        self.failed_requests += 1
                        print(f"Error for user {self.id}: Unexpected response status")
                    
                except Exception as e:
                    self.failed_requests += 1
                    print(f"Error for user {self.id}: {str(e)}")
                
                # Chicago users have shorter think times to create more load
                think_time = random.uniform(0.05, 0.2) if "Chicago" in self.location["city"] else random.uniform(0.1, 1.0)
                await asyncio.sleep(think_time)
    
    def get_summary(self):
        return {
            "user_id": self.id,
            "city": self.location["city"],
            "distance_to_origin_km": self.distance_to_origin,
            "distance_to_edge_km": self.distance_to_edge,
            "edge_node_location": self.edge_node["location"],
            "total_network_time": self.total_network_time,
            "total_load_delay": self.total_load_delay,
            "average_request_time": self.total_network_time / max(self.successful_requests, 1),
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "cache_hits": self.cache_hits,
            "cache_hit_ratio": self.cache_hits / max(self.successful_requests, 1),
            "recommendations_received": self.recommendations
        }

async def main():
    # Create users
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
    df['total_load_delay'] = df['total_load_delay'].round(3)
    df['average_request_time'] = (df['average_request_time'] * 1000).round(1)  # Convert to ms and round
    df['cache_hit_ratio'] = df['cache_hit_ratio'].round(3)
    
    # Sort by distance to edge
    df = df.sort_values('distance_to_edge_km')
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"phase5_results_{timestamp}.csv"
    df.to_csv(csv_path, index=False, float_format='%.3g')
    print(f"\nResults saved to: {csv_path}")
    
    # Print summary statistics
    print("\nSimulation Summary:")
    print(f"Total simulation time: {simulation_time:.2f} seconds")
    print(f"Number of users: {len(USERS)}")
    
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
    
    print("\nLoad Balancing:")
    total_recommendations = df["recommendations_received"].sum()
    print(f"Total node recommendations: {total_recommendations}")
    print(f"Average recommendations per user: {total_recommendations/len(USERS):.1f}")
    
    # Print detailed statistics
    print("\nDetailed User Statistics (sorted by distance to edge):")
    for _, row in df.iterrows():
        print(f"{row['city']:20} - Edge: {row['edge_node_location']:15} "
              f"Distance: {row['distance_to_edge_km']:5.1f}km, "
              f"Total Time: {row['total_network_time']*1000:6.1f}ms, "
              f"Load Delay: {row['total_load_delay']*1000:6.1f}ms, "
              f"Cache Hits: {row['cache_hit_ratio']:.1%}, "
              f"Recommendations: {row['recommendations_received']}")

if __name__ == "__main__":
    asyncio.run(main()) 