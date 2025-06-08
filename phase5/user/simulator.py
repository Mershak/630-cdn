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

def generate_request_sequence(city: str):
    """Generate a sequence of requests with city-specific patterns."""
    num_requests = REQUESTS_PER_USER["Chicago"] if "Chicago" in city else REQUESTS_PER_USER["default"]
    sequence = []
    
    if "Chicago" in city:
        # Chicago users request more data-heavy content (higher indices)
        # and make requests more frequently to popular items
        for _ in range(num_requests):
            if random.random() < 0.7:  # 70% large content
                sequence.append(f"content_{random.randint(80, 99)}")  # Larger content
            else:
                sequence.append(f"content_{random.randint(0, 79)}")
    else:
        # Other users have normal request patterns
        for _ in range(num_requests):
            if random.random() < 0.6:  # 60% popular content
                sequence.append(f"content_{random.randint(0, 9)}")
            elif random.random() < 0.9:  # 30% semi-popular
                sequence.append(f"content_{random.randint(10, 29)}")
            else:  # 10% rare
                sequence.append(f"content_{random.randint(30, 99)}")
    
    return sequence

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
        self.request_sequence = generate_request_sequence(user_data["city"])
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

    async def start_and_confirm_session(self):
        async with httpx.AsyncClient() as client:
            while True:
                response = await client.post(f"{self.edge_node['url']}/start_session")
                if response.status_code == 200:
                    print("God ok from ", self.edge_node['url'])
                    break
                elif response.status_code == 302:
                    self.edge_node['url'] = response.json()['redirect']
                    print("user in ", self.location["city"] , "asked ", self.edge_node['url'] , "Redirected to " ,response.json()['redirect'])

    async def end_session(self):
        async with httpx.AsyncClient() as client:
            await client.post(f"{self.edge_node['url']}/end_session")

    async def make_requests(self):
        # First discover the closest CDN edge node
        await self.discover_cdn()

        await self.start_and_confirm_session()
        
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
                        
                        # Track theoretical network delay and load-based delay
                        theoretical_time = data["metrics"]["network_delay"]
                        load_delay = data["metrics"].get("load_delay", 0)
                        self.total_network_time += theoretical_time
                        self.total_load_delay += load_delay
                        
                        # Track cache hits
                        if data["metrics"]["cache_hit"]:
                            self.cache_hits += 1
                        
                        # Store request info
                        self.results.append({
                            "request_number": i + 1,
                            "content_id": content_id,
                            "theoretical_time": theoretical_time,
                            "actual_time": request_end - request_start,
                            "load_delay": load_delay,
                            "cache_hit": data["metrics"]["cache_hit"],
                            "current_load": data["metrics"].get("current_load", 0)
                        })
                    else:
                        self.failed_requests += 1
                except Exception as e:
                    print(f"Error for user {self.id}, request {i+1}: {str(e)}")
                    self.failed_requests += 1
                
                # Chicago users have shorter think times to create more load
                think_time = random.uniform(0.05, 0.2) if "Chicago" in self.location["city"] else random.uniform(0.1, 1.0)
                await asyncio.sleep(think_time)
            
            print("Session ended")
            await self.end_session()
    
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
    
    # Group by edge node to show load distribution
    print("\nLoad Distribution by Edge Node:")
    edge_node_stats = df.groupby('edge_node_location').agg({
        'successful_requests': 'sum',
        'cache_hits': 'sum',
        'average_request_time': 'mean',
        'total_load_delay': 'sum'
    }).round(1)
    edge_node_stats['cache_hit_ratio'] = (edge_node_stats['cache_hits'] / edge_node_stats['successful_requests']).round(3)
    print(edge_node_stats)
    
    # Print detailed statistics
    print("\nDetailed User Statistics (sorted by distance to edge):")
    for _, row in df.iterrows():
        print(f"{row['city']:20} - Edge: {row['edge_node_location']:15} "
              f"Distance: {row['distance_to_edge_km']:5.1f}km, "
              f"Total Time: {row['total_network_time']*1000:6.1f}ms, "
              f"Load Delay: {row['total_load_delay']*1000:6.1f}ms, "
              f"Avg Time: {row['average_request_time']:5.1f}ms, "
              f"Cache Hits: {row['cache_hit_ratio']:.1%}")

if __name__ == "__main__":
    asyncio.run(main()) 