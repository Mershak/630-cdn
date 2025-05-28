# Phase 5: Load-Aware Edge Node Selection

This phase builds on Phase 4 by adding load-aware edge node selection. Instead of using HTTP redirects, edge nodes now recommend alternative nodes to users when they become overloaded.

## Key Changes

1. **Load-Based Node Recommendations**
   - Edge nodes track their load and share it with other nodes
   - When a node is overloaded (load > 70%), it recommends less loaded nodes to users
   - Recommendations consider both load (30%) and distance (70%) when selecting alternative nodes
   - Users can follow up to 2 recommendations before settling on a node

2. **Load Monitoring and Sharing**
   - Edge nodes periodically share their load information (every 2 seconds)
   - Load is normalized on a 0-1 scale:
     - 0-0.25: Normal load (0-3 requests)
     - 0.25-1.0: High load (4-8 requests)
   - Nodes must have at least 30% less load to be recommended

3. **User Behavior**
   - Chicago users generate more load:
     - 30 requests per user (vs 20 for others)
     - 70% heavy content requests
     - Shorter think times (50-200ms vs 100ms-1s)
   - 6 Chicago users (doubled from Phase 4)
   - Other locations unchanged (2 users each)

4. **Metrics and Monitoring**
   - New metrics for load balancing:
     - Number of recommendations received
     - Load distribution across nodes
     - Recommendation success rate
   - Detailed logging of load states and recommendations

## Components

1. **Edge Node**
   - Tracks active requests and load score
   - Shares load information with other nodes
   - Makes recommendations based on load and distance
   - Still maintains FIFO cache and network delay simulation

2. **User Simulator**
   - Handles node recommendations gracefully
   - Tracks recommendation statistics
   - Implements different load patterns for Chicago vs other users

3. **Origin Server**
   - Maintains registry of edge nodes
   - Provides initial node discovery
   - Serves content with simulated size variations

## Running the Simulation

```bash
docker-compose up --build
```

Results will be saved in the `results` directory with timestamp.

## Expected Behavior

1. Initially, users connect to their closest edge nodes
2. As Chicago nodes become overloaded:
   - They recommend alternative nodes to users
   - Users follow recommendations to less loaded nodes
3. Load gradually spreads across the network
4. Users balance between network delay and load delay

## Results Analysis

The simulation tracks:
- Load distribution across nodes
- Number and success of recommendations
- Impact on response times and cache performance
- Distance vs load tradeoffs

Look for:
- Effective load spreading from Chicago nodes
- Reasonable distance penalties from recommendations
- Overall system stability 