#!/usr/bin/env python
"""
generate_dataset.py - Hybrid Mumbai route dataset (REAL OSM topology + SIMULATED factors)

Run (beginner version):
    python generate_dataset.py --graph backend/mumbai_metro.graphml
Options:
    --target 10000            number of directed road segments wanted
    --seed 42                 random seed (same seed + same graph = identical dataset)
    --vehicle car             motorcycle | car | taxi | lcv | heavy
    --time-of-day morning_peak  off_peak | morning_peak | evening_peak | night
    --day-type weekday        weekday | weekend
    --weather clear           clear | cloudy | rainy | heavy_rain
    --out-dir mumbai_route_dataset_package
    --no-geometry             leave out the (long) geometry_wkt column

Needs: pandas numpy networkx (osmnx optional). Nothing here is paid or needs an API key.
It only READS your graph file; it never modifies your project.
"""
import argparse, ast, datetime as dt, hashlib, json, math, re, shutil
from collections import deque
from pathlib import Path
import numpy as np
import pandas as pd
import networkx as nx

# ======================================================================================
# 1. ASSUMPTION TABLES  (every number here is an ASSUMPTION unless stated; change freely)
# ======================================================================================
# Default free-flow speed (km/h) by OSM road class - used ONLY when OSM has no maxspeed (flagged ESTIMATED)
DEFAULT_SPEED = {"motorway": 80, "trunk": 60, "primary": 50, "secondary": 40, "tertiary": 35,
                 "unclassified": 30, "residential": 25, "living_street": 15, "service": 15, "other": 25}
# How busy a road class tends to be (0..1) - the starting point for simulated congestion
CLASS_BUSY = {"motorway": .50, "trunk": .55, "primary": .55, "secondary": .45, "tertiary": .38,
              "unclassified": .30, "residential": .25, "living_street": .15, "service": .20, "other": .30}
CLASS_QUALITY = {"motorway": .85, "trunk": .80, "primary": .75, "secondary": .65, "tertiary": .60,
                 "unclassified": .50, "residential": .55, "living_street": .50, "service": .45, "other": .55}
CLASS_RISK = {"motorway": .45, "trunk": .50, "primary": .50, "secondary": .40, "tertiary": .35,
              "unclassified": .30, "residential": .25, "living_street": .20, "service": .20, "other": .30}
# Time-of-day multiplier on base busyness (weekday / weekend)
TOD_MULT = {"weekday": {"morning_peak": 1.00, "off_peak": 0.55, "evening_peak": 1.10, "night": 0.20},
            "weekend": {"morning_peak": 0.50, "off_peak": 0.50, "evening_peak": 0.70, "night": 0.20}}
# Fixed, made-up scenario clock times (SIMULATED scenario labels, not real observations)
TOD_CLOCK = {"morning_peak": "09:00", "off_peak": "14:00", "evening_peak": "18:30", "night": "23:00"}
DAY_DATE = {"weekday": "2026-01-12", "weekend": "2026-01-17"}         # a Monday / a Saturday
WEATHER = {"clear": dict(rain=0.0, vis=10000, factor=1.00), "cloudy": dict(rain=0.0, vis=8000, factor=0.98),
           "rainy": dict(rain=5.0, vis=3000, factor=0.85), "heavy_rain": dict(rain=25.0, vis=800, factor=0.65)}
# Vehicle profiles (ALL ASSUMPTIONS). k = how strongly congestion slows that vehicle.
VEHICLES = {"motorcycle": dict(fuel="petrol", eff=45.0, sf=1.00, cap=150, k=0.60),
            "car":        dict(fuel="petrol", eff=15.0, sf=1.00, cap=400, k=0.75),
            "taxi":       dict(fuel="diesel", eff=16.0, sf=1.00, cap=400, k=0.75),
            "lcv":        dict(fuel="diesel", eff=12.0, sf=0.90, cap=1000, k=0.80),
            "heavy":      dict(fuel="diesel", eff=4.5, sf=0.75, cap=9000, k=0.85)}
CONG_FUEL_PENALTY = 0.25        # effective km/l = nominal km/l x (1 - 0.25 x congestion)
BOX = (18.85, 72.75, 19.35, 73.05)

# ======================================================================================
# 2. FIELD SPEC  (name, group, unit, provenance, depends_on_simulated, description)
#    This ONE table drives the column order, the data dictionary and the JSON metadata.
# ======================================================================================
R, X, S, D, U = "REAL_OSM", "REAL_EXTERNAL_SOURCE", "SIMULATED", "DERIVED", "UNKNOWN"
FIELDS = [
 ("edge_id", "A road", "text", D, False, "Unique ID 'from|to|key' of the directed edge (matches the networkx edge)."),
 ("edge_key", "A road", "int", R, False, "OSM/networkx parallel-edge key (0,1,..). Parallel roads are kept, not merged."),
 ("osm_way_id", "A road", "text", R, False, "OSM way id(s); several ids joined by ';' if the edge merges ways. Blank if absent."),
 ("from_node", "A road", "id", R, False, "Start node id in the road graph."),
 ("to_node", "A road", "id", R, False, "End node id in the road graph."),
 ("from_latitude", "A road", "deg", R, False, "Start node latitude (WGS84)."),
 ("from_longitude", "A road", "deg", R, False, "Start node longitude."),
 ("to_latitude", "A road", "deg", R, False, "End node latitude."),
 ("to_longitude", "A road", "deg", R, False, "End node longitude."),
 ("road_name", "A road", "text", R, False, "OSM name; blank = not named in OSM (not invented)."),
 ("road_type", "A road", "text", R, False, "OSM 'highway' class of the segment (first value if several)."),
 ("oneway", "A road", "bool", R, False, "True if the segment is one-way per OSM; blank if unknown. Direction = from_node->to_node."),
 ("road_length_m", "A road", "m", R, False, "Length computed by OSMnx from OSM geometry (haversine fallback if missing, flagged)."),
 ("distance_km", "A road", "km", D, False, "road_length_m / 1000."),
 ("speed_limit_kph", "A road", "km/h", R, False, "OSM maxspeed converted to km/h. BLANK when OSM has none (NOT estimated here)."),
 ("road_quality_score", "A road", "0-1 (1=best)", S, False, "Simulated from road class + seeded noise. OSM surface data was not used."),
 ("geometry_wkt", "A road", "WKT", R, False, "Real curve geometry if the graph has it; blank = straight line between the two nodes."),
 ("base_travel_time_min", "B time", "min", D, True, "distance_km / free_flow_speed_kph x 60 (no traffic, no weather)."),
 ("traffic_delay_min", "B time", "min", D, True, "time with simulated congestion minus base time."),
 ("weather_delay_min", "B time", "min", D, True, "extra time caused by weather_speed_factor on top of traffic."),
 ("estimated_travel_time_min", "B time", "min", D, True, "base + traffic_delay + weather_delay. Use as default routing time."),
 ("free_flow_speed_kph", "B time", "km/h", D, True, "(speed_limit if known else class default) x vehicle_speed_factor, clipped 5..120."),
 ("free_flow_speed_source", "B time", "text", D, False, "OSM_MAXSPEED or ESTIMATED_CLASS_DEFAULT."),
 ("time_of_day", "B time", "text", S, False, "Scenario: morning_peak/off_peak/evening_peak/night."),
 ("day_type", "B time", "text", S, False, "Scenario: weekday/weekend."),
 ("scenario_timestamp", "B time", "ISO8601", S, False, "Fixed fictional timestamp for the scenario (not a real observation)."),
 ("travel_time_offpeak_clear_min", "B time", "min", D, True, "Same segment, weekday off-peak, clear weather (time-dependent routing)."),
 ("travel_time_morning_peak_clear_min", "B time", "min", D, True, "Weekday morning peak, clear."),
 ("travel_time_evening_peak_clear_min", "B time", "min", D, True, "Weekday evening peak, clear."),
 ("travel_time_evening_peak_rainy_min", "B time", "min", D, True, "Weekday evening peak, rainy."),
 ("traffic_level", "C traffic", "text", S, False, "low <0.25, moderate <0.50, high <0.75, severe >=0.75 (on congestion_index)."),
 ("congestion_index", "C traffic", "0-0.95", S, False, "base busyness x time-of-day multiplier (+0.15 if incident), clipped. NOT live traffic."),
 ("traffic_speed_kph", "C traffic", "km/h", D, True, "free_flow x (1 - k x congestion_index); k depends on vehicle."),
 ("incident_flag", "C traffic", "bool", S, False, "Simulated incident (probability rises with busyness). Not a real incident."),
 ("road_closure_flag", "C traffic", "bool", S, False, "Simulated closure (p=0.3%). Routing code should skip these edges. Not a real closure."),
 ("weather_condition", "D weather", "text", S, False, "clear/cloudy/rainy/heavy_rain scenario (city-wide)."),
 ("rainfall_mm_per_hour", "D weather", "mm/h", S, False, "Scenario rainfall with +-20% per-edge jitter."),
 ("visibility_m", "D weather", "m", S, False, "Scenario visibility with +-15% jitter."),
 ("weather_speed_factor", "D weather", "0-1", S, False, "Speed multiplier: clear 1.00, cloudy .98, rainy .85, heavy_rain .65."),
 ("accident_count_12m", "E safety", "count", U, False, "ALWAYS BLANK: no official per-segment accident data was available."),
 ("accident_risk_score", "E safety", "0-1 (1=riskiest)", S, False, "Simulated: .55 x class risk + .25 x (1-quality) + .20 x noise."),
 ("accident_prone_flag", "E safety", "bool", S, True, "True if accident_risk_score is in the top 10% of this dataset (simulated)."),
 ("road_safety_score", "E safety", "0-1 (1=safest)", D, True, "1 - accident_risk_score."),
 ("fuel_type", "F cost", "text", S, False, "Fuel of the chosen vehicle profile (assumption)."),
 ("fuel_efficiency_km_per_litre", "F cost", "km/l", D, True, "Effective: vehicle nominal km/l x (1 - 0.25 x congestion_index)."),
 ("fuel_price_inr_per_litre", "F cost", "INR/l", X, False, "Mumbai petrol 111.21 / diesel 97.83 INR/l (news reports mid-Oct 2026; verify with oil companies)."),
 ("estimated_fuel_litres", "F cost", "litre", D, True, "distance_km / fuel_efficiency_km_per_litre."),
 ("estimated_fuel_cost_inr", "F cost", "INR", D, True, "estimated_fuel_litres x fuel_price_inr_per_litre."),
 ("toll_cost_inr", "F cost", "INR", U, False, "ALWAYS BLANK: no verified toll data. Blank is NOT zero."),
 ("total_segment_cost_inr", "F cost", "INR", D, True, "Equals fuel cost ONLY (toll unknown) - see total_cost_basis."),
 ("total_cost_basis", "F cost", "text", D, False, "FUEL_ONLY_TOLL_UNKNOWN."),
 ("vehicle_type", "G vehicle", "text", S, False, "Vehicle profile used for this file."),
 ("vehicle_capacity_kg", "G vehicle", "kg", S, False, "Assumed payload capacity of the profile."),
 ("vehicle_speed_factor", "G vehicle", "0-1", S, False, "Assumed speed multiplier vs. free flow."),
 ("vehicle_fuel_efficiency_km_per_litre", "G vehicle", "km/l", S, False, "Assumed nominal efficiency (before congestion)."),
 ("vehicle_access_allowed", "G vehicle", "text", R, False, "FALSE if OSM access=no/private; otherwise UNKNOWN (no restriction facts were invented)."),
 ("vehicle_access_source", "G vehicle", "text", R, False, "REAL_OSM when access tag exists, else UNKNOWN."),
 ("vehicle_scenario_id", "G vehicle", "text", D, False, "VS-<vehicle>-<day>-<time>-<weather>."),
 ("data_quality_flag", "H quality", "text", D, False, "OK or ';'-joined codes: SPEED_LIMIT_ESTIMATED, NAME_MISSING, ONEWAY_UNKNOWN, LENGTH_RECOMPUTED, ACCESS_RESTRICTED."),
 ("data_quality_level", "H quality", "text", D, False, "COMPLETE (no codes) or PARTIAL."),
 ("simulation_seed", "H quality", "int", D, False, "Seed used for all SIMULATED values.")]
COLS = [f[0] for f in FIELDS]

# ======================================================================================
# 3. SMALL HELPERS
# ======================================================================================
def u01(seed, key, salt):
    """Repeatable pseudo-random number in [0,1) for (seed, edge, purpose). Order-independent."""
    h = hashlib.blake2b(f"{seed}|{key}|{salt}".encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2 ** 64

def first_val(v):
    """OSM values can be lists (even stored as text like "['a','b']"). Return the first item as text."""
    if v is None or (isinstance(v, float) and math.isnan(v)): return ""
    if isinstance(v, (list, tuple, set)): return str(next(iter(v))) if len(v) else ""
    s = str(v).strip()
    if s.startswith("["):
        try:
            lst = ast.literal_eval(s); return str(lst[0]) if lst else ""
        except Exception: return s
    return s

def join_val(v):
    if v is None or (isinstance(v, float) and math.isnan(v)): return ""
    if isinstance(v, (list, tuple, set)): return ";".join(map(str, v))
    s = str(v).strip()
    if s.startswith("["):
        try: return ";".join(map(str, ast.literal_eval(s)))
        except Exception: return s
    return s

def fnum(x):
    try: return float(x)
    except Exception: return float("nan")

def parse_speed(v):
    m = re.match(r"^(\d+(\.\d+)?)\s*(mph|km/h|kmh|kph)?$", first_val(v).lower())
    if not m: return float("nan")
    return round(float(m.group(1)) * (1.60934 if m.group(3) == "mph" else 1), 1)

def parse_bool(v):
    s = first_val(v).lower()
    if s in ("true", "yes", "1", "-1"): return True
    if s in ("false", "no", "0"): return False
    return None

def road_class(rt):
    return first_val(rt).replace("_link", "") or "other"

def pick(table, rt):
    return table.get(road_class(rt), table["other"])

def haversine_m(la1, lo1, la2, lo2):
    p1, p2 = math.radians(la1), math.radians(la2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))

# ======================================================================================
# 4. READ GRAPH + CHOOSE A CONNECTED BLOCK OF ~10,000 EDGES (real topology, nothing invented)
# ======================================================================================
def find_graph(arg):
    for c in ([arg] if arg else []) + ["mumbai_metro.graphml", "backend/mumbai_metro.graphml",
                                       "backend/mumbai.graphml", "mumbai.graphml"]:
        if c and Path(c).exists(): return Path(c)
    return None

def load_graph(path):
    try:
        import osmnx as ox
        return ox.load_graphml(path)
    except Exception:
        return nx.read_graphml(path)

def iter_edges(G):
    if G.is_multigraph(): yield from G.edges(keys=True, data=True)
    else:
        for u, v, d in G.edges(data=True): yield u, v, 0, d

def select_edges(G, target):
    """Grow a region outward (breadth-first) from the graph centre so the chosen roads stay connected.
    Keep every real edge whose two ends are both inside the region (never more than target), then top up
    with real 'frontier' edges until target is reached. Self-loops are dropped."""
    nodes = sorted(G.nodes, key=str)
    ys = np.array([fnum(G.nodes[n].get("y")) for n in nodes]); xs = np.array([fnum(G.nodes[n].get("x")) for n in nodes])
    cy, cx = np.nanmedian(ys), np.nanmedian(xs)
    start = nodes[int(np.nanargmin((ys - cy) ** 2 + (xs - cx) ** 2))]
    nm = lambda a, b: G.number_of_edges(a, b) if a != b else 0
    inside, rank, order, count, q = set(), {}, [], 0, deque([start])
    seen = {start}
    while q:
        n = q.popleft()
        nbrs = set(G.successors(n)) | set(G.predecessors(n))
        add = sum(nm(n, m) + nm(m, n) for m in nbrs if m in inside)
        if count + add > target: break
        inside.add(n); rank[n] = len(order); order.append(n); count += add
        for m in sorted(nbrs, key=str):
            if m not in seen: seen.add(m); q.append(m)
    chosen = [(u, v, k) for u, v, k, _ in iter_edges(G) if u in inside and v in inside and u != v]
    chosen.sort(key=lambda e: (rank[e[0]], rank[e[1]], str(e[2])))
    if len(chosen) < target:                       # top up with frontier edges (one end inside)
        extra = [(u, v, k) for u, v, k, _ in iter_edges(G) if u != v and ((u in inside) != (v in inside))]
        extra.sort(key=lambda e: (min(rank.get(e[0], 10**9), rank.get(e[1], 10**9)), str(e[0]), str(e[1]), str(e[2])))
        chosen += extra[: target - len(chosen)]
    return chosen[:target], start

# ======================================================================================
# 5. SIMULATION FORMULAS
# ======================================================================================
def traffic_level(c):
    return "low" if c < .25 else "moderate" if c < .5 else "high" if c < .75 else "severe"

def times(ff_vehicle, dist_km, cong, k, wfactor):
    """base / with-traffic / final minutes.  speed_traffic = ff x (1 - k x congestion);  speed_final = that x weather."""
    base = dist_km / ff_vehicle * 60
    sp_t = max(3.0, ff_vehicle * (1 - k * cong))
    t_traffic = dist_km / sp_t * 60
    t_final = dist_km / (sp_t * wfactor) * 60
    return base, t_traffic, t_final, sp_t

def build_table(G, chosen, a):
    veh = VEHICLES[a.vehicle]
    price = {"petrol": a.price_petrol, "diesel": a.price_diesel}[veh["fuel"]]
    w = WEATHER[a.weather]
    rows, raw_risk = [], []
    for u, v, k in chosen:
        e = G.get_edge_data(u, v, k) if G.is_multigraph() else G.get_edge_data(u, v)
        eid = f"{u}|{v}|{k}"
        nu, nv = G.nodes[u], G.nodes[v]
        la1, lo1, la2, lo2 = fnum(nu.get("y")), fnum(nu.get("x")), fnum(nv.get("y")), fnum(nv.get("x"))
        flags = []
        length = fnum(e.get("length"))
        if not (length > 0):
            length = haversine_m(la1, lo1, la2, lo2); flags.append("LENGTH_RECOMPUTED")
        dist = length / 1000
        rt = first_val(e.get("highway")) or "other"
        name = join_val(e.get("name"))
        if not name: flags.append("NAME_MISSING")
        ow = parse_bool(e.get("oneway"))
        if ow is None: flags.append("ONEWAY_UNKNOWN")
        lim = parse_speed(e.get("maxspeed"))
        if math.isnan(lim): ff_base, src = pick(DEFAULT_SPEED, rt), "ESTIMATED_CLASS_DEFAULT"; flags.append("SPEED_LIMIT_ESTIMATED")
        else: ff_base, src = lim, "OSM_MAXSPEED"
        ff = min(120.0, max(5.0, ff_base * veh["sf"]))
        acc = first_val(e.get("access")).lower()
        if acc in ("no", "private"): access, asrc = "FALSE", "REAL_OSM"; flags.append("ACCESS_RESTRICTED")
        elif acc: access, asrc = "UNKNOWN", "REAL_OSM"
        else: access, asrc = "UNKNOWN", "UNKNOWN"
        geom = e.get("geometry"); wkt = getattr(geom, "wkt", None) or (str(geom) if isinstance(geom, str) and geom.upper().startswith("LINESTRING") else "")
        # ---- simulated, edge-level (do not depend on scenario) ----
        busy = min(1.0, max(0.0, pick(CLASS_BUSY, rt) + (u01(a.seed, eid, "busy") - .5) * .5))
        incident = u01(a.seed, eid, "inc") < 0.01 + 0.02 * busy
        closure = u01(a.seed, eid, "clo") < 0.003
        quality = min(1.0, max(.05, pick(CLASS_QUALITY, rt) + (u01(a.seed, eid, "q") - .5) * .3))
        risk = min(1.0, max(0.0, .55 * pick(CLASS_RISK, rt) + .25 * (1 - quality) + .20 * u01(a.seed, eid, "risk")))
        raw_risk.append(risk)
        mult = lambda day, tod: TOD_MULT[day][tod]
        cong_of = lambda day, tod: min(.95, max(0.0, busy * mult(day, tod) + (.15 if incident else 0)))
        # ---- chosen scenario ----
        cong = cong_of(a.day_type, a.time_of_day)
        rain = w["rain"] * (1 + (u01(a.seed, eid, "rain") - .5) * .4) if w["rain"] else 0.0
        vis = w["vis"] * (1 + (u01(a.seed, eid, "vis") - .5) * .3)
        base, t_tr, t_fin, sp_t = times(ff, dist, cong, veh["k"], w["factor"])
        eff = max(1.0, veh["eff"] * (1 - CONG_FUEL_PENALTY * cong))
        litres = dist / eff; fuel_cost = litres * price
        # ---- time-dependent columns (same vehicle) ----
        td = lambda day, tod, wx: times(ff, dist, cong_of(day, tod), veh["k"], WEATHER[wx]["factor"])[2]
        rows.append({
            "edge_id": eid, "edge_key": k, "osm_way_id": join_val(e.get("osmid")), "from_node": u, "to_node": v,
            "from_latitude": la1, "from_longitude": lo1, "to_latitude": la2, "to_longitude": lo2,
            "road_name": name, "road_type": rt, "oneway": ow, "road_length_m": round(length, 2),
            "distance_km": round(dist, 5), "speed_limit_kph": lim, "road_quality_score": round(quality, 3),
            "geometry_wkt": "" if a.no_geometry else wkt,
            "base_travel_time_min": round(base, 4), "traffic_delay_min": round(t_tr - base, 4),
            "weather_delay_min": round(t_fin - t_tr, 4), "estimated_travel_time_min": round(t_fin, 4),
            "free_flow_speed_kph": round(ff, 2), "free_flow_speed_source": src,
            "time_of_day": a.time_of_day, "day_type": a.day_type,
            "scenario_timestamp": f"{DAY_DATE[a.day_type]}T{TOD_CLOCK[a.time_of_day]}:00+05:30",
            "travel_time_offpeak_clear_min": round(td("weekday", "off_peak", "clear"), 4),
            "travel_time_morning_peak_clear_min": round(td("weekday", "morning_peak", "clear"), 4),
            "travel_time_evening_peak_clear_min": round(td("weekday", "evening_peak", "clear"), 4),
            "travel_time_evening_peak_rainy_min": round(td("weekday", "evening_peak", "rainy"), 4),
            "traffic_level": traffic_level(cong), "congestion_index": round(cong, 4),
            "traffic_speed_kph": round(sp_t, 2), "incident_flag": bool(incident), "road_closure_flag": bool(closure),
            "weather_condition": a.weather, "rainfall_mm_per_hour": round(rain, 2), "visibility_m": round(vis, 0),
            "weather_speed_factor": w["factor"],
            "accident_count_12m": np.nan, "accident_risk_score": round(risk, 3), "accident_prone_flag": False,
            "road_safety_score": round(1 - risk, 3),
            "fuel_type": veh["fuel"], "fuel_efficiency_km_per_litre": round(eff, 3), "fuel_price_inr_per_litre": price,
            "estimated_fuel_litres": round(litres, 5), "estimated_fuel_cost_inr": round(fuel_cost, 4),
            "toll_cost_inr": np.nan, "total_segment_cost_inr": round(fuel_cost, 4), "total_cost_basis": "FUEL_ONLY_TOLL_UNKNOWN",
            "vehicle_type": a.vehicle, "vehicle_capacity_kg": veh["cap"], "vehicle_speed_factor": veh["sf"],
            "vehicle_fuel_efficiency_km_per_litre": veh["eff"], "vehicle_access_allowed": access,
            "vehicle_access_source": asrc, "vehicle_scenario_id": f"VS-{a.vehicle}-{a.day_type}-{a.time_of_day}-{a.weather}",
            "data_quality_flag": ";".join(flags) if flags else "OK",
            "data_quality_level": "PARTIAL" if flags else "COMPLETE", "simulation_seed": a.seed})
    df = pd.DataFrame(rows)[COLS]
    df["accident_prone_flag"] = df["accident_risk_score"] >= np.percentile(raw_risk, 90)
    return df

# ======================================================================================
# 6. EXPORT + DOCUMENTS
# ======================================================================================
def export(df, out, a, graph_path, start_node, src_edges, src_nodes):
    out.mkdir(parents=True, exist_ok=True)
    csv_p, json_p = out / "mumbai_route_dataset.csv", out / "mumbai_route_dataset.json"
    df.to_csv(csv_p, index=False)
    meta = {"dataset_name": "Mumbai Route Optimization Dataset", "record_count": int(len(df)),
            "geographic_area": "Mumbai, Maharashtra, India",
            "data_method": "Hybrid: real OpenStreetMap road topology + SIMULATED traffic/weather/safety/cost factors",
            "source_graph_file": str(graph_path), "source_graph_edges": src_edges, "source_graph_nodes": src_nodes,
            "region_start_node": str(start_node), "seed": a.seed, "generated_on": dt.date.today().isoformat(),
            "scenario": {"vehicle": a.vehicle, "time_of_day": a.time_of_day, "day_type": a.day_type, "weather": a.weather},
            "missing_value_rule": "Missing = null in JSON / empty in CSV. Never silently zero.",
            "warning": "SIMULATED fields are NOT live traffic, official accident records, or verified tolls.",
            "field_provenance": {f[0]: f[3] for f in FIELDS}}
    recs = json.loads(df.replace("", np.nan).to_json(orient="records"))   # blank text -> null
    json_p.write_text(json.dumps({**meta, "records": recs}, ensure_ascii=False), encoding="utf-8")
    dd = pd.DataFrame(FIELDS, columns=["field", "group", "unit", "provenance", "depends_on_simulated_inputs", "description"])
    dd.to_csv(out / "data_dictionary.csv", index=False)
    pd.DataFrame([{"vehicle_type": k, "fuel_type": v["fuel"], "nominal_km_per_litre": v["eff"], "speed_factor": v["sf"],
                   "capacity_kg": v["cap"], "congestion_sensitivity_k": v["k"], "data_type": "SIMULATED_ASSUMPTION"}
                  for k, v in VEHICLES.items()]).to_csv(out / "vehicle_profiles.csv", index=False)
    return csv_p, json_p

README = """# Mumbai Route Optimization Dataset (hybrid)

**What it is:** one row per DIRECTED road segment. Roads, node ids, coordinates, names, classes, lengths, one-way and
maxspeed are REAL (OpenStreetMap, ODbL, via your OSMnx graphml). Traffic, weather, road quality, risk and vehicle
numbers are SIMULATED. Nothing simulated is live traffic or an official accident record.

## How it was made
1. Read your graphml (nothing in your project is changed).
2. Pick ~10,000 edges as a CONNECTED block: grow a region outward from the graph centre, keep every real edge inside it,
   then add real frontier edges until the target is reached. (Random edges would break routing.) Parallel edges kept (edge_key).
3. Simulate factors with a fixed seed ({seed}); each value depends only on (seed, edge_id, purpose) so results are reproducible.

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
"""

# ======================================================================================
# 7. VALIDATION
# ======================================================================================
def validate(df, out, G, a, target, csv_p, json_p):
    L = ["# Validation report", f"generated {dt.datetime.now():%Y-%m-%d %H:%M}", ""]
    ok = lambda c, m: L.append(f"- {'PASS' if c else 'FAIL'}: {m}")
    L += ["## Counts", f"- records: {len(df)} (target {target})"]
    if len(df) != target: L.append(f"- NOTE: fewer than target - the graph only had {len(df)} usable non-loop edges.")
    L += ["", "## Integrity checks"]
    ok(df["edge_id"].is_unique, "edge_id unique")
    nodes = {str(n) for n in G.nodes}
    ok(df["from_node"].astype(str).isin(nodes).all() and df["to_node"].astype(str).isin(nodes).all(), "all endpoints exist in the source graph")
    ok((df["from_node"] != df["to_node"]).all(), "no self-loops")
    ok((df["distance_km"] > 0).all() and (df["road_length_m"] > 0).all(), "distances > 0")
    ok((df["estimated_travel_time_min"] > 0).all() and (df["base_travel_time_min"] > 0).all(), "travel times > 0")
    ok((df["traffic_delay_min"] >= -1e-6).all() and (df["weather_delay_min"] >= -1e-6).all(), "delays >= 0")
    ok(np.allclose(df.base_travel_time_min + df.traffic_delay_min + df.weather_delay_min, df.estimated_travel_time_min, atol=1e-3), "estimated = base + traffic + weather")
    ok((df["estimated_fuel_cost_inr"] >= 0).all(), "fuel costs >= 0")
    ok(df["from_latitude"].between(BOX[0], BOX[2]).all() and df["from_longitude"].between(BOX[1], BOX[3]).all(), "start coordinates inside Mumbai sanity box")
    ok(df["accident_count_12m"].isna().all() and df["toll_cost_inr"].isna().all(), "accident counts and tolls left missing (not zero)")
    dup = df.duplicated(["from_node", "to_node"], keep=False)
    L.append(f"- INFO: {int(dup.sum())} edges share (from,to) with another edge = legitimate parallel roads kept via edge_key")
    ok(not df.duplicated(["from_node", "to_node", "edge_key"]).any(), "no duplicate (from,to,key)")
    L += ["", "## Missing values (% of rows)"]
    mv = (df.replace("", np.nan).isna().mean() * 100).round(1)
    L += [f"- {c}: {v}%" for c, v in mv.items() if v > 0] or ["- none"]
    L += ["", "## Data-source breakdown (fields)"]
    for p, n in pd.Series([f[3] for f in FIELDS]).value_counts().items(): L.append(f"- {p}: {n} fields")
    real_speed = (df["free_flow_speed_source"] == "OSM_MAXSPEED").mean() * 100
    L += [f"- speed limit from OSM: {real_speed:.1f}% of segments; the rest use ESTIMATED class defaults",
          f"- data_quality_level: {df['data_quality_level'].value_counts().to_dict()}",
          f"- simulated closures: {int(df.road_closure_flag.sum())}, incidents: {int(df.incident_flag.sum())}, accident-prone: {int(df.accident_prone_flag.sum())}",
          f"- traffic_level counts: {df['traffic_level'].value_counts().to_dict()}"]
    L += ["", "## CSV vs JSON agreement"]
    c2 = pd.read_csv(csv_p, low_memory=False); j = json.loads(json_p.read_text(encoding="utf-8")); j2 = pd.DataFrame(j["records"])
    ok(len(c2) == len(j2) == j["record_count"], "same record count")
    ok(list(c2.columns) == list(j2.columns), "same column names and order")
    ok((c2["edge_id"].astype(str).values == j2["edge_id"].astype(str).values).all(), "same record IDs in same order")
    num = c2.select_dtypes("number").columns
    ok(all(np.allclose(c2[c].astype(float), pd.to_numeric(j2[c], errors="coerce").astype(float), equal_nan=True, rtol=1e-9, atol=1e-9) for c in num), "numeric values agree")
    ok(set(COLS) == set(c2.columns), "every column is documented in data_dictionary.csv")
    L += ["", "## Graph loading + routing test (Dijkstra and A* only)"]
    H = nx.MultiDiGraph()
    for r in df.itertuples():
        H.add_node(r.from_node, y=r.from_latitude, x=r.from_longitude); H.add_node(r.to_node, y=r.to_latitude, x=r.to_longitude)
        H.add_edge(r.from_node, r.to_node, key=r.edge_key, time=r.estimated_travel_time_min)
    scc = max(nx.strongly_connected_components(H), key=len)
    L.append(f"- graph: {H.number_of_nodes()} nodes, {H.number_of_edges()} edges; weakly connected parts: {nx.number_weakly_connected_components(H)}; largest strongly connected part: {len(scc)} nodes")
    if len(scc) > 10:
        ids = sorted(scc, key=str); s, t = ids[0], ids[len(ids) // 2]
        maxff = df["free_flow_speed_kph"].max()
        h = lambda n, g: haversine_m(H.nodes[n]["y"], H.nodes[n]["x"], H.nodes[g]["y"], H.nodes[g]["x"]) / 1000 / maxff * 60
        pd_ = nx.dijkstra_path_length(H, s, t, weight="time"); pa = nx.astar_path_length(H, s, t, heuristic=h, weight="time")
        ok(abs(pd_ - pa) < 1e-6, f"Dijkstra ({pd_:.2f} min) and A* ({pa:.2f} min) agree between nodes {s} and {t}")
    else:
        L.append("- FAIL: no large strongly connected component to test routing")
    (out / "validation_report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    return not any(x.startswith("- FAIL") for x in L)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph"); ap.add_argument("--target", type=int, default=10000); ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--vehicle", default="car", choices=VEHICLES); ap.add_argument("--time-of-day", default="morning_peak", choices=TOD_CLOCK)
    ap.add_argument("--day-type", default="weekday", choices=DAY_DATE); ap.add_argument("--weather", default="clear", choices=WEATHER)
    ap.add_argument("--price-petrol", type=float, default=111.21); ap.add_argument("--price-diesel", type=float, default=97.83)
    ap.add_argument("--out-dir", default="mumbai_route_dataset_package"); ap.add_argument("--no-geometry", action="store_true")
    ap.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    gp = find_graph(a.graph)
    if not gp:
        raise SystemExit("Graph file not found. Pass --graph path/to/your_mumbai_graph.graphml (an OSMnx GraphML file). "
                         "To make one: ox.graph_from_bbox(bbox, network_type='drive') then ox.save_graphml(G, 'mumbai.graphml').")
    print(f"Loading {gp} ...")
    G = load_graph(gp)
    print(f"Graph: {G.number_of_nodes()} nodes, {sum(1 for _ in iter_edges(G))} edges")
    chosen, start = select_edges(G, a.target)
    print(f"Selected {len(chosen)} directed edges (target {a.target})")
    df = build_table(G, chosen, a)
    out = Path(a.out_dir)
    csv_p, json_p = export(df, out, a, gp, start, sum(1 for _ in iter_edges(G)), G.number_of_nodes())
    (out / "README.md").write_text(README.format(seed=a.seed), encoding="utf-8")
    (out / "generate_dataset.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    good = validate(df, out, G, a, a.target, csv_p, json_p)
    if not a.no_zip:
        shutil.make_archive(str(out), "zip", str(out)); print(f"Zip: {out}.zip")
    print("\nDONE - all checks passed" if good else "\nDONE - some checks FAILED, read validation_report.md")

if __name__ == "__main__":
    main()