
import hashlib
import math
import os
import random
import re
import time

import networkx as nx

try:
    import weather_service
except ImportError:
    weather_service = None


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "mumbai_metro.graphml")

COST_PER_KM = 8.0
DEFAULT_SPEED = 25.0

WEIGHTS_WITH_WEATHER = {
    "distance": 0.40,
    "time": 0.30,
    "weather": 0.30,
}

WEIGHTS_WITHOUT_WEATHER = {
    "distance": 0.60,
    "time": 0.40,
}

# Generate more paths than we need, then retain diverse alternatives.
MAX_WEATHER_CANDIDATES = 4
DEFAULT_CANDIDATE_COUNT = 8

FREE_SPEED = {
    "motorway": 80,
    "trunk": 65,
    "primary": 50,
    "secondary": 40,
    "tertiary": 30,
    "residential": 25,
    "service": 15,
    "unclassified": 25,
}

ROAD_ENERGY_FACTOR = {
    "motorway": 0.9,
    "trunk": 0.95,
    "primary": 1.0,
    "secondary": 1.05,
    "tertiary": 1.1,
    "residential": 1.15,
    "service": 1.25,
    "unclassified": 1.1,
}


# ============================================================
# BASIC HELPERS
# ============================================================

def _safe_float(value, default=0.0):
    try:
        if isinstance(value, (list, tuple)):
            value = value[0] if value else default

        result = float(value)
        return result if math.isfinite(result) else float(default)

    except (TypeError, ValueError, IndexError):
        return float(default)


def _first_value(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None

    return value


def _road_type(data):
    value = _first_value(data.get("highway", "unclassified"))

    if not value:
        return "unclassified"

    return str(value).lower()


def _speed_limit(data):
    value = _first_value(data.get("maxspeed"))

    if value is not None:
        match = re.search(r"\d+(?:\.\d+)?", str(value))

        if match:
            speed = float(match.group())

            if "mph" in str(value).lower():
                speed *= 1.60934

            if speed > 0:
                return min(speed, 130.0)

    return float(FREE_SPEED.get(_road_type(data), DEFAULT_SPEED))


def _road_energy_factor(data):
    return ROAD_ENERGY_FACTOR.get(_road_type(data), 1.0)


def _rand(key):
    digest = hashlib.md5(
        str(key).encode("utf-8")
    ).hexdigest()

    return int(digest[:8], 16) / 0xFFFFFFFF


def level(value):
    if value < 0.34:
        return "Low"

    if value < 0.67:
        return "Medium"

    return "High"


def vehicle_cost_per_km(
    vehicle_type=None,
    vehicle_efficiency=None,
    energy_price=None,
):
    """Estimate vehicle energy cost per kilometre."""

    efficiency = _safe_float(vehicle_efficiency, 0)
    price = _safe_float(energy_price, 0)

    if efficiency > 0 and price > 0:
        return price / efficiency

    vehicle = str(vehicle_type or "").lower()

    if "electric" in vehicle or vehicle == "ev":
        return 2.0

    if "bike" in vehicle or "motorcycle" in vehicle:
        return 2.5

    if "truck" in vehicle:
        return 12.0

    if "bus" in vehicle:
        return 15.0

    return COST_PER_KM


# ============================================================
# GRAPH LOADING
# ============================================================

def load_graph():
    if not os.path.exists(CACHE_FILE):
        raise FileNotFoundError(
            f"Graph file not found: {CACHE_FILE}"
        )

    print(f"Loading road graph: {CACHE_FILE}")

    graph = nx.read_graphml(
        CACHE_FILE,
        node_type=str,
        force_multigraph=True,
    )

    if not graph.is_directed():
        graph = graph.to_directed()

    if graph.number_of_nodes() == 0:
        raise ValueError("The GraphML file contains no nodes.")

    sample_node = next(iter(graph.nodes))
    sample_data = graph.nodes[sample_node]

    if "x" not in sample_data or "y" not in sample_data:
        raise ValueError(
            "Graph nodes must contain x and y coordinates. "
            "Expected x = longitude and y = latitude."
        )

    print(
        f"Graph ready: {graph.number_of_nodes():,} nodes, "
        f"{graph.number_of_edges():,} edges."
    )

    return graph


def to_simple(graph):
    """
    Convert a MultiGraph/MultiDiGraph into a simple graph.

    The shortest parallel edge is retained. Direction is preserved,
    so one-way roads represented in the directed source graph remain
    directed in the routing graph.
    """

    if not isinstance(graph, (nx.MultiDiGraph, nx.MultiGraph)):
        return graph

    simple = nx.DiGraph() if graph.is_directed() else nx.Graph()

    simple.graph.update(graph.graph)
    simple.add_nodes_from(graph.nodes(data=True))

    for u, v, data in graph.edges(data=True):
        edge_data = dict(data)

        length = max(
            0.0,
            _safe_float(edge_data.get("length"), 1.0),
        )
        edge_data["length"] = length

        if simple.has_edge(u, v):
            existing_length = _safe_float(
                simple[u][v].get("length"),
                float("inf"),
            )

            if length < existing_length:
                simple[u][v].update(edge_data)
        else:
            simple.add_edge(u, v, **edge_data)

    return simple


# ============================================================
# SIMULATED TRAFFIC AND ROAD RISK
# These are estimates, NOT live traffic or verified safety data.
# ============================================================

def traffic_of(data, key=""):
    traffic_values = {
        "motorway": 0.65,
        "trunk": 0.70,
        "primary": 0.78,
        "secondary": 0.60,
        "tertiary": 0.48,
        "residential": 0.35,
        "service": 0.20,
        "unclassified": 0.40,
    }

    base = traffic_values.get(_road_type(data), 0.40)
    variation = (_rand(key) - 0.5) * 0.20

    return max(0.0, min(1.0, base + variation))


def risk_of(data, key=""):
    risk_values = {
        "motorway": 0.35,
        "trunk": 0.40,
        "primary": 0.50,
        "secondary": 0.45,
        "tertiary": 0.40,
        "residential": 0.30,
        "service": 0.25,
        "unclassified": 0.35,
    }

    base = risk_values.get(_road_type(data), 0.35)
    variation = (_rand(f"risk:{key}") - 0.5) * 0.20

    return max(0.0, min(1.0, base + variation))


def _edge_metrics(data, u=None, v=None):
    length = max(
        0.0,
        _safe_float(data.get("length"), 0.0),
    )

    distance_km = length / 1000.0
    road = _road_type(data)
    speed = max(5.0, _speed_limit(data))

    key = f"{u}:{v}:{road}"
    traffic = traffic_of(data, key)
    risk = risk_of(data, key)

    estimated_speed = max(
        5.0,
        speed * (1.0 - 0.55 * traffic),
    )

    time_minutes = (distance_km / estimated_speed) * 60.0

    cost = (
        distance_km
        * COST_PER_KM
        * _road_energy_factor(data)
    )

    return {
        "distance_km": distance_km,
        "time_minutes": time_minutes,
        "cost": cost,
        "traffic": traffic,
        "risk": risk,
        "road_type": road,
    }


# ============================================================
# DISTANCE CALCULATIONS
# ============================================================

def _distance_weight(u, v, data):
    return max(
        0.0,
        _safe_float(data.get("length"), 1.0),
    )
def _traffic_time_weight(u, v, data):
    """
    Estimate travel time for a road segment, including
    the existing simulated traffic effect.

    Returns estimated minutes.
    """
    metrics = _edge_metrics(data, u, v)
    return max(0.001, metrics["time_minutes"])

def _path_distance_metres(graph, path):
    total = 0.0

    for u, v in zip(path, path[1:]):
        if not graph.has_edge(u, v):
            return float("inf")

        total += _distance_weight(u, v, graph[u][v])

    return total


def _haversine_metres(node_a, node_b, graph):
    a = graph.nodes[node_a]
    b = graph.nodes[node_b]

    if not all(
        key in a and key in b
        for key in ("x", "y")
    ):
        return 0.0

    lon1 = math.radians(_safe_float(a["x"]))
    lat1 = math.radians(_safe_float(a["y"]))
    lon2 = math.radians(_safe_float(b["x"]))
    lat2 = math.radians(_safe_float(b["y"]))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    value = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2.0) ** 2
    )

    value = max(0.0, min(1.0, value))

    return 6_371_000.0 * 2.0 * math.atan2(
        math.sqrt(value),
        math.sqrt(1.0 - value),
    )


# ============================================================
# NEAREST ROAD-NODE SEARCH
# ============================================================

def nearest_node(graph, latitude, longitude):
    best_node = None
    best_distance = float("inf")

    latitude_factor = math.cos(math.radians(latitude)) ** 2

    for node, data in graph.nodes(data=True):
        if "x" not in data or "y" not in data:
            continue

        node_lon = _safe_float(data["x"], float("nan"))
        node_lat = _safe_float(data["y"], float("nan"))

        if not (
            math.isfinite(node_lon)
            and math.isfinite(node_lat)
        ):
            continue

        distance = (
            (node_lat - latitude) ** 2
            + (node_lon - longitude) ** 2 * latitude_factor
        )

        if distance < best_distance:
            best_distance = distance
            best_node = node

    if best_node is None:
        raise ValueError(
            "No graph nodes with valid x/y coordinates were found."
        )

    return best_node


# ============================================================
# DIJKSTRA AND A*
# ============================================================

def _run_dijkstra(graph, source, target, traffic_aware=False):
    weight_function = (
        _traffic_time_weight
        if traffic_aware
        else _distance_weight
    )

    return nx.dijkstra_path(
        graph,
        source,
        target,
        weight=weight_function,
    )


def _run_astar(graph, source, target, traffic_aware=False):
    if traffic_aware:
        # Straight-line distance divided by the maximum assumed
        # road speed gives a lower-bound travel-time heuristic.
        def heuristic(u, v):
            return (
                _haversine_metres(u, v, graph)
                / (130.0 * 1000.0 / 60.0)
            )

        weight_function = _traffic_time_weight

    else:
        heuristic = lambda u, v: _haversine_metres(u, v, graph)
        weight_function = _distance_weight

    return nx.astar_path(
        graph,
        source,
        target,
        heuristic=heuristic,
        weight=weight_function,
    )


# ============================================================
# CANDIDATE ROUTE DIVERSITY
# ============================================================

def _edge_set(path):
    return set(zip(path, path[1:]))


def _route_overlap(path_a, path_b):
    """
    Return the proportion of shared directed edges.

    1.0 means the routes use the same edges.
    0.0 means they share no directed edges.
    """

    edges_a = _edge_set(path_a)
    edges_b = _edge_set(path_b)

    denominator = max(len(edges_a), len(edges_b), 1)

    return len(edges_a & edges_b) / denominator


def _generate_candidates(graph, source, target, count=8):
    """
    Generate alternative paths using accumulated edge penalties.

    The ordinary shortest path is added first. Subsequent searches
    penalize edges already used by discovered candidates. This gives
    Dijkstra an incentive to explore other road corridors rather than
    repeatedly returning the same shortest route.

    This is a diversity heuristic, not a guarantee that every route
    will be completely disjoint.
    """

    if source == target:
        return [[source]]

    candidates = []
    seen = set()
    edge_usage = {}

    def add(path):
        if not path:
            return False

        signature = tuple(path)

        if signature in seen:
            return False

        if not all(
            graph.has_edge(u, v)
            for u, v in zip(path, path[1:])
        ):
            return False

        seen.add(signature)
        candidates.append(path)

        for edge in zip(path, path[1:]):
            edge_usage[edge] = edge_usage.get(edge, 0) + 1

        return True

    # Always try the ordinary shortest path first.
    try:
        add(_run_dijkstra(graph, source, target))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return []

    # A* can sometimes find a useful additional path. If it finds the
    # same path, the deduplication check simply ignores it.
    try:
        add(_run_astar(graph, source, target))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        pass

    rng = random.Random(f"diverse:{source}:{target}")

    max_attempts = max(count * 5, 12)

    for attempt in range(max_attempts):
        if len(candidates) >= count:
            break

        # Penalize previously used edges. Penalties accumulate as
        # multiple discovered routes share an edge.
        penalty_strength = 1.5 + (attempt % 4) * 0.75
        attempt_salt = rng.random()

        def diversified_weight(u, v, data):
            length = max(
                0.001,
                _safe_float(data.get("length"), 1.0),
            )

            usage = edge_usage.get((u, v), 0)

            # The multiplier discourages repeatedly using the same
            # roads while keeping every edge weight positive.
            usage_penalty = min(
                12.0,
                usage * penalty_strength,
            )

            # Small deterministic perturbations help break ties.
            # They are intentionally much weaker than edge penalties.
            tie_breaker = 1.0 + (
                0.015
                * _rand(
                    f"{u}:{v}:{attempt_salt}:{attempt}"
                )
            )

            return length * (1.0 + usage_penalty) * tie_breaker

        try:
            path = nx.dijkstra_path(
                graph,
                source,
                target,
                weight=diversified_weight,
            )
            add(path)

        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue

    # Return paths ordered by their actual road distance, not their
    # temporary penalized search weight.
    candidates.sort(
        key=lambda path: _path_distance_metres(graph, path)
    )

    return candidates


def _select_diverse_candidates(
    graph,
    paths,
    limit=MAX_WEATHER_CANDIDATES,
    max_overlap=0.85,
):
    """
    Keep the shortest route, then prefer alternatives with less
    overlap against routes already selected.

    If not enough diverse alternatives exist, fill remaining slots
    with the shortest remaining unique paths.
    """

    if not paths:
        return []

    ordered = sorted(
        paths,
        key=lambda path: _path_distance_metres(graph, path),
    )

    selected = [ordered[0]]
    selected_signatures = {tuple(ordered[0])}

    remaining = [
        path for path in ordered[1:]
        if tuple(path) not in selected_signatures
    ]

    while remaining and len(selected) < limit:
        eligible = []

        for path in remaining:
            overlaps = [
                _route_overlap(path, chosen)
                for chosen in selected
            ]

            maximum_overlap = max(overlaps, default=0.0)

            if maximum_overlap <= max_overlap:
                eligible.append((path, maximum_overlap))

        if eligible:
            # Prefer a reasonably short route among routes that are
            # sufficiently different from the already selected ones.
            chosen_path, _ = min(
                eligible,
                key=lambda item: (
                    _path_distance_metres(graph, item[0]),
                    item[1],
                ),
            )
        else:
            # The network may not provide enough alternative corridors.
            # Use the shortest remaining path rather than inventing one.
            chosen_path = remaining[0]

        selected.append(chosen_path)
        selected_signatures.add(tuple(chosen_path))
        remaining.remove(chosen_path)

    return selected


# ============================================================
# GENETIC ALGORITHM
# ============================================================

def _crossover_paths(path_a, path_b, rng):
    positions = {}

    for index, node in enumerate(path_b):
        positions.setdefault(node, []).append(index)

    shared = []

    for index_a, node in enumerate(path_a):
        for index_b in positions.get(node, []):
            shared.append((index_a, index_b))

    if not shared:
        return None

    index_a, index_b = rng.choice(shared)

    return path_a[:index_a] + path_b[index_b:]


def _run_genetic_algorithm(
    graph,
    source,
    target,
    candidates,
    generations=12,
    population_size=10,
):
    if not candidates:
        return None

    rng = random.Random(f"GA:{source}:{target}")
    population = list(candidates)

    while len(population) < population_size:
        population.append(rng.choice(population))

    for _ in range(generations):
        population.sort(
            key=lambda path: _path_distance_metres(graph, path)
        )

        next_population = population[
            :max(2, population_size // 3)
        ]

        while len(next_population) < population_size:
            parent_a = rng.choice(population)
            parent_b = rng.choice(population)

            child = _crossover_paths(parent_a, parent_b, rng)

            valid = (
                child
                and all(
                    graph.has_edge(u, v)
                    for u, v in zip(child, child[1:])
                )
            )

            next_population.append(
                child if valid else rng.choice(population)
            )

        population = next_population

    return min(
        population,
        key=lambda path: _path_distance_metres(graph, path),
    )


# ============================================================
# ANT COLONY OPTIMIZATION
# ============================================================

def _run_ant_colony(
    graph,
    candidates,
    source,
    target,
    iterations=20,
):
    if not candidates:
        return None

    rng = random.Random(f"ACO:{source}:{target}")
    pheromone = [1.0] * len(candidates)

    for _ in range(iterations):
        scores = []

        for index, path in enumerate(candidates):
            distance = max(
                1.0,
                _path_distance_metres(graph, path),
            )
            scores.append(pheromone[index] / distance)

        total = sum(scores)

        if total <= 0:
            selected = rng.randrange(len(candidates))
        else:
            threshold = rng.random() * total
            cumulative = 0.0
            selected = len(candidates) - 1

            for index, score in enumerate(scores):
                cumulative += score

                if cumulative >= threshold:
                    selected = index
                    break

        pheromone = [value * 0.85 for value in pheromone]

        distance = max(
            1.0,
            _path_distance_metres(graph, candidates[selected]),
        )

        pheromone[selected] += 1.0 / distance

    return min(
        candidates,
        key=lambda path: _path_distance_metres(graph, path),
    )


# ============================================================
# SIMULATED ANNEALING
# ============================================================

def _run_simulated_annealing(
    graph,
    candidates,
    source,
    target,
    iterations=100,
):
    if not candidates:
        return None

    rng = random.Random(f"SA:{source}:{target}")

    current = rng.choice(candidates)
    best = current

    current_distance = _path_distance_metres(graph, current)
    best_distance = current_distance
    temperature = 1000.0

    for _ in range(iterations):
        neighbour = rng.choice(candidates)
        neighbour_distance = _path_distance_metres(
            graph,
            neighbour,
        )

        difference = neighbour_distance - current_distance

        if (
            difference < 0
            or rng.random() < math.exp(
                -difference / max(temperature, 0.001)
            )
        ):
            current = neighbour
            current_distance = neighbour_distance

        if current_distance < best_distance:
            best = current
            best_distance = current_distance

        temperature *= 0.95

    return best


# ============================================================
# BELLMAN-FORD ON CANDIDATE SUBGRAPH
# ============================================================

def _run_bellman_ford_candidate_graph(
    graph,
    source,
    target,
    candidates,
):
    if not candidates:
        return None

    nodes = set()

    for path in candidates:
        nodes.update(path)

    subgraph = graph.subgraph(nodes).copy()

    try:
        return nx.bellman_ford_path(
            subgraph,
            source,
            target,
            weight=_distance_weight,
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


# ============================================================
# ALGORITHM COMPARISON
# ============================================================

def compare_algorithms(graph, source, target):
    results = {}

    exact_algorithms = {
        "Dijkstra": lambda: _run_dijkstra(
            graph, source, target
        ),
        "A*": lambda: _run_astar(
            graph, source, target
        ),
    }

    for name, function in exact_algorithms.items():
        started = time.perf_counter()

        try:
            path = function()

            results[name] = {
                "distance_km": round(
                    _path_distance_metres(graph, path) / 1000,
                    3,
                ),
                "runtime_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                "status": "success",
                "_path": path,
            }

        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            results[name] = {
                "distance_km": None,
                "runtime_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                "status": str(exc),
                "_path": None,
            }

    if not results["Dijkstra"]["_path"]:
        raise nx.NetworkXNoPath(
            f"No road route found between {source} and {target}."
        )

    candidates = _generate_candidates(
        graph,
        source,
        target,
        count=DEFAULT_CANDIDATE_COUNT,
    )

    heuristic_algorithms = {
        "Genetic Algorithm": lambda: _run_genetic_algorithm(
            graph, source, target, candidates
        ),
        "Ant Colony Optimization": lambda: _run_ant_colony(
            graph, candidates, source, target
        ),
        "Simulated Annealing": lambda: _run_simulated_annealing(
            graph, candidates, source, target
        ),
        "Bellman-Ford (candidate graph)": lambda:
            _run_bellman_ford_candidate_graph(
                graph, source, target, candidates
            ),
    }

    for name, function in heuristic_algorithms.items():
        started = time.perf_counter()

        try:
            path = function()

            if not path or not all(
                graph.has_edge(u, v)
                for u, v in zip(path, path[1:])
            ):
                raise nx.NetworkXNoPath("No valid route found.")

            results[name] = {
                "distance_km": round(
                    _path_distance_metres(graph, path) / 1000,
                    3,
                ),
                "runtime_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                "status": "success",
                "_path": path,
            }

        except Exception as exc:
            results[name] = {
                "distance_km": None,
                "runtime_ms": round(
                    (time.perf_counter() - started) * 1000,
                    3,
                ),
                "status": f"unavailable: {exc}",
                "_path": None,
            }

    valid_paths = [
        item["_path"]
        for item in results.values()
        if item.get("_path")
    ]

    best_path = min(
        valid_paths,
        key=lambda path: _path_distance_metres(graph, path),
    )

    for item in results.values():
        item.pop("_path", None)

    return best_path, results


# ============================================================
# ROUTE METRICS
# ============================================================

def route_metrics(graph, path):
    distance = 0.0
    time_minutes = 0.0
    cost = 0.0
    traffic_total = 0.0
    risk_total = 0.0
    edge_count = 0

    for u, v in zip(path, path[1:]):
        if not graph.has_edge(u, v):
            continue

        metrics = _edge_metrics(graph[u][v], u, v)

        distance += metrics["distance_km"]
        time_minutes += metrics["time_minutes"]
        cost += metrics["cost"]
        traffic_total += metrics["traffic"]
        risk_total += metrics["risk"]
        edge_count += 1

    return {
        "distance_km": distance,
        "time_minutes": time_minutes,
        "cost": cost,
        "traffic": (
            traffic_total / edge_count if edge_count else 0.0
        ),
        "risk": risk_total / edge_count if edge_count else 0.0,
    }


# ============================================================
# SCORING HELPERS
# Lower normalized scores are better.
# ============================================================

def _normalize_values(values):
    if not values:
        return []

    minimum = min(values)
    maximum = max(values)

    if math.isclose(minimum, maximum):
        return [0.0] * len(values)

    difference = maximum - minimum

    return [
        (value - minimum) / difference
        for value in values
    ]


def _path_to_coordinates(graph, path):
    coordinates = []

    for node in path:
        data = graph.nodes[node]

        if "x" in data and "y" in data:
            coordinates.append([
                _safe_float(data["y"]),
                _safe_float(data["x"]),
            ])

    return coordinates


# ============================================================
# ROUTE WEATHER
# ============================================================

def _get_route_weather(coordinates, journey_minutes=None):
    """
    Fetch forecast data for a candidate route over its estimated
    journey duration. Weather failures are explicitly reported.
    """

    unavailable = {
        "source": "Open-Meteo",
        "data_type": "Current conditions and hourly forecast",
        "available": False,
        "weather_risk": None,
        "message": "Weather data unavailable.",
    }

    if weather_service is None:
        unavailable["message"] = (
            "weather_service.py could not be imported."
        )
        return unavailable

    try:
        duration = max(
            1,
            int(math.ceil(_safe_float(journey_minutes, 120))),
        )

        result = weather_service.get_route_weather(
            coordinates,
            journey_minutes=duration,
        )

        if not isinstance(result, dict):
            unavailable["message"] = (
                "Weather service returned an unexpected response."
            )
            return unavailable

        if not result.get("available"):
            return {
                **unavailable,
                **result,
                "available": False,
            }

        weather_risk = _safe_float(
            result.get("weather_risk"),
            float("nan"),
        )

        if not math.isfinite(weather_risk):
            return {
                **unavailable,
                "message": "Weather risk was missing or invalid.",
            }

        result["weather_risk"] = max(
            0.0,
            min(1.0, weather_risk),
        )

        return result

    except Exception as exc:
        return {
            **unavailable,
            "message": f"Weather request failed: {str(exc)[:200]}",
        }


# ============================================================
# MAIN WEATHER-AWARE ROUTE SELECTION
# ============================================================

def find_best_route(
    G,
    D,
    src_latlon,
    dst_latlon,
    vehicle_type=None,
    vehicle_efficiency=None,
    energy_price=None,
):
    source_lat, source_lon = map(float, src_latlon)
    destination_lat, destination_lon = map(float, dst_latlon)

    try:
        source = nearest_node(G, source_lat, source_lon)
        target = nearest_node(
            G,
            destination_lat,
            destination_lon,
        )
    except Exception as exc:
        raise ValueError(
            f"Unable to snap locations to the road graph: {exc}"
        ) from exc

    if source not in D or target not in D:
        raise ValueError(
            "Source or destination was not found in the routing graph."
        )

    if source == target:
        candidate_paths = [[source]]
        comparison = {}
    else:
        # Keep the algorithm comparison in the response, but generate
        # candidate paths separately for weather-aware selection.
        _, comparison = compare_algorithms(D, source, target)

        candidate_paths = _generate_candidates(
            D,
            source,
            target,
            count=DEFAULT_CANDIDATE_COUNT,
        )

    # Deduplicate and validate every candidate path.
    unique_paths = []
    seen_paths = set()

    for path in candidate_paths:
        if not path:
            continue

        signature = tuple(path)

        if signature in seen_paths:
            continue

        if not all(
            D.has_edge(u, v)
            for u, v in zip(path, path[1:])
        ):
            continue

        seen_paths.add(signature)
        unique_paths.append(path)

    if not unique_paths:
        raise nx.NetworkXNoPath(
            "No valid candidate routes were found."
        )

    # Keep short routes while preferring alternatives that use
    # meaningfully different directed road edges.
    candidate_paths = _select_diverse_candidates(
        D,
        unique_paths,
        limit=MAX_WEATHER_CANDIDATES,
    )

    candidates = []

    for index, path in enumerate(candidate_paths):
        metrics = route_metrics(D, path)
        coordinates = _path_to_coordinates(G, path)

        candidates.append({
            "candidate_id": index + 1,
            "path_nodes": path,
            "coordinates": coordinates,
            "metrics": metrics,
        })

    # Fetch weather separately for each candidate route.
    weather_results = []

    for candidate in candidates:
        weather_results.append(
            _get_route_weather(
                candidate["coordinates"],
                journey_minutes=(
                    candidate["metrics"]["time_minutes"]
                ),
            )
        )

    weather_available = (
        len(weather_results) == len(candidates)
        and all(
            item.get("available") is True
            for item in weather_results
        )
    )

    if weather_available:
        weights = dict(WEIGHTS_WITH_WEATHER)
        scoring_method = "distance_time_weather"
    else:
        weights = dict(WEIGHTS_WITHOUT_WEATHER)
        scoring_method = "distance_time_fallback"

    # Weather delay is a bounded planning heuristic, not a live
    # traffic measurement. Maximum estimated delay is 30%.
    for index, candidate in enumerate(candidates):
        base_time = max(
            0.0,
            candidate["metrics"]["time_minutes"],
        )

        if weather_available:
            weather_risk = weather_results[index]["weather_risk"]
            delay_factor = min(0.30, 0.30 * weather_risk)
        else:
            weather_risk = None
            delay_factor = 0.0

        delay_minutes = base_time * delay_factor
        adjusted_time = base_time + delay_minutes

        candidate["base_time_minutes"] = base_time
        candidate["weather_delay_minutes"] = delay_minutes
        candidate["weather_delay_percent"] = delay_factor * 100.0
        candidate["estimated_time_minutes"] = adjusted_time
        candidate["weather"] = weather_results[index]
        candidate["weather_risk"] = weather_risk

    distances = [
        candidate["metrics"]["distance_km"]
        for candidate in candidates
    ]

    times = [
        candidate["estimated_time_minutes"]
        for candidate in candidates
    ]

    normalized_distances = _normalize_values(distances)
    normalized_times = _normalize_values(times)

    if weather_available:
        weather_risks = [
            candidate["weather_risk"]
            for candidate in candidates
        ]
        normalized_weather = _normalize_values(weather_risks)
    else:
        normalized_weather = [None] * len(candidates)

    # Lower score is better.
    for index, candidate in enumerate(candidates):
        score = (
            weights["distance"] * normalized_distances[index]
            + weights["time"] * normalized_times[index]
        )

        if weather_available:
            score += (
                weights["weather"] * normalized_weather[index]
            )

        candidate["normalized_scores"] = {
            "distance": round(
                normalized_distances[index], 4
            ),
            "time": round(
                normalized_times[index], 4
            ),
            "weather": (
                round(normalized_weather[index], 4)
                if weather_available
                else None
            ),
        }

        candidate["selection_score"] = round(score, 6)

    selected = min(
        candidates,
        key=lambda item: item["selection_score"],
    )

    selected_metrics = selected["metrics"]
    selected_weather = selected["weather"]
    selected_coordinates = selected["coordinates"]

    if weather_available:
        route_name = "Weather-Aware Recommended Route"
        selection_preference = "multi_factor_weather"
        algorithm_name = (
            "Distance + weather-adjusted time + weather risk"
        )
        weather_status = (
            "Forecast data was used to compare candidate routes. "
            "Travel-time adjustments are estimates."
        )
    else:
        route_name = "Recommended Route (Weather Unavailable)"
        selection_preference = "distance_time_fallback"
        algorithm_name = "Distance + estimated time scoring"
        weather_status = (
            "Weather data was unavailable for at least one candidate. "
            "Weather was excluded from route selection."
        )

    distance_km = selected_metrics["distance_km"]
    base_time = selected["base_time_minutes"]
    estimated_time = selected["estimated_time_minutes"]

    route = {
        "name": route_name,
        "algorithm": algorithm_name,
        "distance_km": round(distance_km, 3),
        "distance": round(distance_km, 3),

        # Existing frontend time fields retain their names.
        # They contain the adjusted estimate when weather is available.
        "time_minutes": round(estimated_time, 2),
        "duration_minutes": round(estimated_time, 2),
        "estimated_time_minutes": round(estimated_time, 2),

        "base_time_minutes": round(base_time, 2),
        "weather_delay_minutes": round(
            selected["weather_delay_minutes"], 2
        ),
        "weather_delay_percent": round(
            selected["weather_delay_percent"], 2
        ),

        "cost": round(selected_metrics["cost"], 2),
        "traffic": round(selected_metrics["traffic"], 3),
        "risk": round(selected_metrics["risk"], 3),
        "coordinates": selected_coordinates,
        "path": selected_coordinates,
        "selection_score": selected["selection_score"],
        "normalized_scores": selected["normalized_scores"],

        # Backend metadata. The frontend does not need to render
        # weather details.
        "weather": selected_weather,
        "weather_risk": selected["weather_risk"],
        "weather_risk_level": (
            level(selected["weather_risk"])
            if selected["weather_risk"] is not None
            else "Unavailable"
        ),
    }

    candidate_comparison = []

    for candidate in candidates:
        metrics = candidate["metrics"]

        candidate_comparison.append({
            "candidate_id": candidate["candidate_id"],
            "distance_km": round(metrics["distance_km"], 3),
            "base_time_minutes": round(
                candidate["base_time_minutes"], 2
            ),
            "time_minutes": round(
                candidate["estimated_time_minutes"], 2
            ),
            "weather_delay_minutes": round(
                candidate["weather_delay_minutes"], 2
            ),
            "weather_risk": candidate["weather_risk"],
            "selection_score": candidate["selection_score"],
            "selected": (
                candidate["candidate_id"]
                == selected["candidate_id"]
            ),
            "normalized_scores": candidate["normalized_scores"],
            "overlap_with_selected": round(
                _route_overlap(
                    candidate["path_nodes"],
                    selected["path_nodes"],
                ),
                4,
            ),
        })

    return {
        "routes": [route],
        "best_index": 0,
        "selected_preference": selection_preference,
        "routing_objective": scoring_method,
        "weights": weights,
        "weather": selected_weather,
        "weather_available": weather_available,
        "weather_status": weather_status,
        "candidate_count": len(candidates),
        "candidate_comparison": candidate_comparison,
        "vehicle_cost_per_km": vehicle_cost_per_km(
            vehicle_type=vehicle_type,
            vehicle_efficiency=vehicle_efficiency,
            energy_price=energy_price,
        ),
        "snapped_source": [
            _safe_float(G.nodes[source]["y"]),
            _safe_float(G.nodes[source]["x"]),
        ],
        "snapped_destination": [
            _safe_float(G.nodes[target]["y"]),
            _safe_float(G.nodes[target]["x"]),
        ],
        "algorithm_comparison": comparison,
    }
