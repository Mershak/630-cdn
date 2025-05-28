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
ORIGIN_URL = "http://origin:8000"

# Origin server location (Ashburn, VA)
ORIGIN_LAT = 39.8283
ORIGIN_LON = -77.6115

# Ensure results directory exists
RESULTS_DIR = Path("/app/results")
RESULTS_DIR.mkdir(exist_ok=True)

# Fixed user locations - matching Phase 2 exactly for comparison
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
        self.request_sequence = generate_request_sequence()
        self.results = []
        
        # Calculate distance to origin
        self.distance_to_origin = geodesic(
            (self.location["lat"], self.location["lon"]),
            (ORIGIN_LAT, ORIGIN_LON)
        ).kilometers

    async def make_requests(self):
        async with httpx.AsyncClient() as client:
            for i, content_id in enumerate(self.request_sequence):
                try:
                    request_start = time.time()
                    response = await client.get(
                        f"{ORIGIN_URL}/content/{content_id}",
                        params={
                            "client_lat": self.location["lat"],
                            "client_lon": self.location["lon"]
                        }
                    )
                    request_end = time.time()
                    
                    if response.status_code == 200:
                        self.successful_requests += 1
                        request_time = request_end - request_start
                        self.total_network_time += request_time
                        
                        # Store basic request info
                        self.results.append({
                            "request_number": i + 1,
                            "content_id": content_id,
                            "request_time": request_time
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
            "total_network_time": self.total_network_time,
            "average_request_time": self.total_network_time / max(self.successful_requests, 1),
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests
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
    df['total_network_time'] = df['total_network_time'].round(3)
    df['average_request_time'] = (df['average_request_time'] * 1000).round(1)  # Convert to ms and round
    
    # Sort by distance to origin
    df = df.sort_values('distance_to_origin_km')
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"phase1_results_{timestamp}.csv"
    df.to_csv(csv_path, index=False, float_format='%.3g')
    print(f"\nResults saved to: {csv_path}")
    
    # Print summary statistics
    print("\nSimulation Summary:")
    print(f"Total simulation time: {simulation_time:.2f} seconds")
    print(f"Number of users: {len(USERS)}")
    print(f"Requests per user: {REQUESTS_PER_USER}")
    
    # Calculate average distance
    avg_distance = df["distance_to_origin_km"].mean()
    print(f"\nAverage distance to origin: {avg_distance:.1f}km")
    
    # Group by city area to show geographic distribution
    print("\nGeographic Distribution of Response Times:")
    city_stats = df.groupby(df['city'].str.split().str[0]).agg({
        'successful_requests': 'sum',
        'average_request_time': 'mean',
        'distance_to_origin_km': 'mean'
    }).round(1)
    print(city_stats)
    
    # Print detailed statistics
    print("\nDetailed User Statistics (sorted by distance):")
    for _, row in df.iterrows():
        print(f"{row['city']:20} - Distance: {row['distance_to_origin_km']:5.1f}km, "
              f"Total Time: {row['total_network_time']*1000:6.1f}ms, "
              f"Avg Time: {row['average_request_time']:5.1f}ms")

if __name__ == "__main__":
    asyncio.run(main()) 