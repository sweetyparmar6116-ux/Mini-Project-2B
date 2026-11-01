# Mumbai Route Optimization Dataset (hybrid)

**What it is:** one row per DIRECTED road segment. Roads, node ids, coordinates, names, classes, lengths, one-way and
maxspeed are REAL (OpenStreetMap, ODbL, via your OSMnx graphml). Traffic, weather, road quality, risk and vehicle
numbers are SIMULATED. Nothing simulated is live traffic or an official accident record.

## How it was made
1. Read your graphml (nothing in your project is changed).
2. Pick ~10,000 edges as a CONNECTED block: grow a region outward from the graph centre, keep every real edge inside it,
   then add real frontier edges until the target is reached. (Random edges would break routing.) Parallel edges kept (edge_key).
3. Simulate factors with a fixed seed (42); each value depends only on (seed, edge_id, purpose) so results are reproducible.

## Key formulas (all in generate_dataset.py)
- distance_km = road_length_m / 1000
- free_flow = (maxspeed if OSM has it else class default) x vehicle_speed_factor      (class default = ESTIMATED, flagged)
- congestion = clip(base_busyness x time_of_day_multiplier (+0.15 if incident), 0, 0.95); base_busyness = class value +- noise
- speed_traffic = free_flow x (1 - k x congestion)          (k = vehicle congestion sensitivity)
- base_time = distance / free_flow x 60 ;  time_traffic = distance / speed_traffic x 60 ;  final = distance / (speed_traffic x weather_factor) x 60
- traffic_delay = time_traffic - base ; weather_delay = final - time_traffic ; estimated = base + traffic_delay + weather_delay
- effective km/l = nominal x (1 - 0.25 x congestion) ; fuel cost = distance / effective km/l x price
- toll = unknown (blank). total_segment_cost = fuel cost ONLY (see total_cost_basis). Blank is never treated as 0.

## Run
    pip install pandas numpy networkx
    python generate_dataset.py --graph backend/mumbai_metro.graphml
    python generate_dataset.py --graph backend/mumbai_metro.graphml --vehicle taxi --time-of-day evening_peak --weather rainy

## Load into a routing graph
    import pandas as pd, networkx as nx
    df = pd.read_csv("mumbai_route_dataset.csv")
    df = df[~df.road_closure_flag]                      # skip simulated closures (or keep & set weight=inf)
    G = nx.MultiDiGraph()
    for r in df.itertuples():
        G.add_node(r.from_node, y=r.from_latitude, x=r.from_longitude)
        G.add_node(r.to_node, y=r.to_latitude, x=r.to_longitude)
        G.add_edge(r.from_node, r.to_node, key=r.edge_key, time=r.estimated_travel_time_min,
                   cost=r.estimated_fuel_cost_inr, risk=r.accident_risk_score, cong=r.congestion_index, dist=r.distance_km)
    path = nx.shortest_path(G, source, target, weight="time")          # Dijkstra
    # A*: heuristic(n, t) = haversine_km(n, t) / MAX_FF_KPH * 60  (never overestimates, so it stays optimal)

## Algorithms: what the data supports (NOT what is implemented)
Only Dijkstra and A* are run, as a loading test, in validation_report.md. Bellman-Ford, bidirectional Dijkstra, K-shortest paths
work on the same weights. Floyd-Warshall needs a much smaller subgraph. Time-dependent routing uses the four travel_time_* columns.
Vehicle routing (capacities/demands) needs customer data that this dataset does not contain.

## Weighted multi-factor score (weights configurable)
    route_score = w1*norm_time + w2*norm_cost + w3*norm_risk + w4*norm_congestion
Compute route TOTALS first (sum time, sum cost; length-weighted mean of risk and congestion), then min-max normalise each factor
across the candidate routes: norm = (x - min)/(max - min), 0 if max==min. Start with 0.35/0.20/0.20/0.25 and test sensitivity by changing
one weight at a time. Missing factor: drop it and re-divide the remaining weights so they sum to 1 (never treat missing as 0).

## Time-dependent routing
Use travel_time_morning_peak_clear_min, ..._offpeak_..., ..._evening_peak_clear_min, ..._evening_peak_rainy_min: the same edge has a
different time per scenario. Pick the column by departure scenario; regenerate with other flags for other vehicles/weather.

## Sources / assumptions to verify
Fuel prices: petrol 111.21 / diesel 97.83 INR/litre (news reports, mid-Oct 2026; verify). Vehicle efficiencies, class speeds, busyness,
weather factors, closure/incident rates are ASSUMPTIONS. Accident counts and tolls: not available -> left blank.
