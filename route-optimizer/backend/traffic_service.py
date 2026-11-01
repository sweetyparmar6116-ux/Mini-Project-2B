import os
import os
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

import requests
from dotenv import load_dotenv

load_dotenv()

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY")
TRAFFIC_CACHE_TTL_SECONDS = 30
MAX_ROUTE_TRAFFIC_SAMPLES = 8
_traffic_cache = {}
_traffic_cache_lock = Lock()

TOMTOM_URL = (
    "https://api.tomtom.com/traffic/services/4/"
    "flowSegmentData/absolute/10/json"
)


def get_live_traffic(latitude, longitude):
    if not TOMTOM_API_KEY:
        return None

    latitude = float(latitude)
    longitude = float(longitude)
    cache_key = (round(latitude, 5), round(longitude, 5))
    current_time = monotonic()

    with _traffic_cache_lock:
        cached = _traffic_cache.get(cache_key)
        if cached and current_time - cached[0] < TRAFFIC_CACHE_TTL_SECONDS:
            return cached[1]

    params = {
        "key": TOMTOM_API_KEY,
        "point": f"{latitude},{longitude}",
        "unit": "KMPH",
    }

    try:
        response = requests.get(
            TOMTOM_URL,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json().get("flowSegmentData", {})
        current_speed = data.get("currentSpeed")
        free_flow_speed = data.get("freeFlowSpeed")

        if current_speed is None or free_flow_speed in (None, 0):
            return None

        traffic = (
            1.0
            if data.get("roadClosure")
            else 1 - (current_speed / free_flow_speed)
        )
        traffic = max(0.0, min(1.0, traffic))
        geometry = data.get("coordinates") or {}
        raw_coordinates = (
            geometry.get("coordinate", [])
            if isinstance(geometry, dict)
            else []
        )
        coordinates = [
            [float(point["latitude"]), float(point["longitude"])]
            for point in raw_coordinates
            if isinstance(point, dict)
            and point.get("latitude") is not None
            and point.get("longitude") is not None
        ]
        result = {
            "current_speed": current_speed,
            "free_flow_speed": free_flow_speed,
            "traffic": round(traffic, 3),
            "confidence": data.get("confidence"),
            "road_closure": data.get("roadClosure", False),
            "source": "TomTom Live Traffic",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "coordinates": coordinates,
        }

        with _traffic_cache_lock:
            expired_keys = [
                key
                for key, (cached_at, _) in _traffic_cache.items()
                if monotonic() - cached_at >= TRAFFIC_CACHE_TTL_SECONDS
            ]
            for key in expired_keys:
                _traffic_cache.pop(key, None)
            if len(_traffic_cache) >= 100:
                _traffic_cache.pop(next(iter(_traffic_cache)))
            _traffic_cache[cache_key] = (monotonic(), result)

        return result
    except requests.RequestException as error:
        status = (
            error.response.status_code
            if error.response is not None
            else "network error"
        )
        print(f"TomTom request failed ({status}).")
        return None
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        print("TomTom response error:", error)
        return None


def get_route_traffic(coordinates):
    """Fetch live traffic for evenly spaced sections of a route."""
    edges = list(zip(coordinates, coordinates[1:]))
    if not edges:
        return []

    sample_count = min(MAX_ROUTE_TRAFFIC_SAMPLES, len(edges))
    if sample_count == 1:
        sample_indices = [0]
    else:
        sample_indices = sorted({
            round(i * (len(edges) - 1) / (sample_count - 1))
            for i in range(sample_count)
        })

    segments = []
    for index in sample_indices:
        start, end = edges[index]
        midpoint = (
            (float(start[0]) + float(end[0])) / 2,
            (float(start[1]) + float(end[1])) / 2,
        )
        traffic = get_live_traffic(*midpoint)
        if not traffic:
            continue

        segments.append({
            **traffic,
            "coordinates": traffic["coordinates"] or [start, end],
        })

    return segments


def get_road_traffic(graph, u, v):
    try:
        start = graph.nodes[u]
        end = graph.nodes[v]
        start_lat = float(start["y"])
        start_lon = float(start["x"])
        end_lat = float(end["y"])
        end_lon = float(end["x"])
        midpoint_lat = (start_lat + end_lat) / 2
        midpoint_lon = (start_lon + end_lon) / 2
        return get_live_traffic(midpoint_lat, midpoint_lon)
    except (KeyError, TypeError, ValueError):
        return None
