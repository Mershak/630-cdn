# Phase 4: CDN Overload Simulation

This phase simulates an overload scenario at the Chicago edge node to demonstrate how CDN performance degrades under heavy load.

## Key Changes from Phase 3

1. **Edge Node Load Simulation**
   - Added active request tracking
   - Implemented load-based processing delays
   - Thresholds: 5 requests before slowdown, max 10 concurrent requests
   - Exponential delay increase up to 100ms at max load

2. **Chicago Load Generation**
   - Increased Chicago users from 3 to 6
   - Each Chicago user makes 50 requests (vs 20 for others)
   - 70% of requests are for large content (IDs 80-99)
   - Shorter think times between requests (0.05-0.2s vs 0.1-1.0s)

3. **Content Size Variation**
   - Content IDs 0-9: 5-10KB (popular content)
   - Content IDs 10-29: 10-50KB (semi-popular)
   - Content IDs 30-79: 1-100KB (regular)
   - Content IDs 80-99: 100-500KB (large content)

4. **Enhanced Metrics**
   - Added load delay tracking
   - Current load monitoring
   - Per-edge node statistics
   - Content size impact on delays

## Expected Behavior

1. Chicago edge node will show:
   - Higher average response times
   - More load-based delays
   - Lower cache hit rates
   - Higher total network time

2. Other edge nodes will maintain:
   - Normal response times
   - Minimal load-based delays
   - Better cache performance
   - Consistent network times

## Running the Simulation

1. Build and start the containers:
   ```bash
   docker-compose up --build
   ```

2. Results will be saved to:
   - CSV file in `./results` directory
   - Detailed console output with statistics

## Metrics Explanation

- `total_network_time`: Base network delay + content transfer time
- `total_load_delay`: Additional delay from server load
- `average_request_time`: Average total time per request
- `cache_hit_ratio`: Percentage of requests served from cache
- `current_load`: Number of concurrent requests at measurement time 