import httpx, time, asyncio

USER_LOCATIONS = [
    (34.0522, -118.2437),  # Los Angeles, CA
    (40.7128, -74.0060),   # New York, NY
    (41.8781, -87.6298),   # Chicago, IL
    (29.7604, -95.3698),   # Houston, TX
    (33.4484, -112.0740)   # Phoenix, AZ
]

EDGE_NODE_URL = "http://edge1:8000"

async def request_from_single_node(session, user_loc):
    url = EDGE_NODE_URL + "/request"
    print("sending request")
    try:
        r = await session.post(url, json={"location": user_loc}, timeout=30)
        return r.elapsed.total_seconds()
    except httpx.RequestError as e:
        print(f"Request error for {user_loc}: {e}")
        return None

async def simulate():
    time.sleep(5)  # Wait for edge node to start
    print("asd")
    async with httpx.AsyncClient() as client:
    #     start = time.time()
    #     time = request_from_single_node(client, USER_LOCATIONS[0])
    #     end = time.time()
    #     print("Durations per user:", time)
    #     print("Total time for all users:", end - start, "seconds")



        tasks = [request_from_single_node(client, loc) for loc in USER_LOCATIONS]
        start = time.time()
        durations = await asyncio.gather(*tasks)
        end = time.time()
        print("Durations per user:", durations)
        print("Total time for all users:", end - start, "seconds")

if __name__ == "__main__":
    # print("hello")
    asyncio.run(simulate())
