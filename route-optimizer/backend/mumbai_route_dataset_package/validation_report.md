# Validation report
generated 2026-10-22 09:37

## Counts
- records: 10000 (target 10000)

## Integrity checks
- PASS: edge_id unique
- PASS: all endpoints exist in the source graph
- PASS: no self-loops
- PASS: distances > 0
- PASS: travel times > 0
- PASS: delays >= 0
- PASS: estimated = base + traffic + weather
- PASS: fuel costs >= 0
- PASS: start coordinates inside Mumbai sanity box
- PASS: accident counts and tolls left missing (not zero)
- INFO: 109 edges share (from,to) with another edge = legitimate parallel roads kept via edge_key
- PASS: no duplicate (from,to,key)

## Missing values (% of rows)
- road_name: 53.5%
- speed_limit_kph: 98.8%
- geometry_wkt: 44.8%
- accident_count_12m: 100.0%
- toll_cost_inr: 100.0%

## Data-source breakdown (fields)
- DERIVED: 23 fields
- SIMULATED: 19 fields
- REAL_OSM: 16 fields
- UNKNOWN: 2 fields
- REAL_EXTERNAL_SOURCE: 1 fields
- speed limit from OSM: 1.2% of segments; the rest use ESTIMATED class defaults
- data_quality_level: {'PARTIAL': 9885, 'COMPLETE': 115}
- simulated closures: 28, incidents: 162, accident-prone: 989
- traffic_level counts: {'moderate': 4848, 'low': 3634, 'high': 1406, 'severe': 112}

## CSV vs JSON agreement
- PASS: same record count
- PASS: same column names and order
- PASS: same record IDs in same order
- PASS: numeric values agree
- PASS: every column is documented in data_dictionary.csv

## Graph loading + routing test (Dijkstra and A* only)
- graph: 4646 nodes, 10000 edges; weakly connected parts: 1; largest strongly connected part: 4558 nodes
- PASS: Dijkstra (6.28 min) and A* (6.28 min) agree between nodes 10001187594 and 2242610378