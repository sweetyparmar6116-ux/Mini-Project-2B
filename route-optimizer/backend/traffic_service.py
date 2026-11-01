import os
import requests
from dotenv import load_dotenv
from functools import lru_cache

load_dotenv()

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY")

TOMTOM_URL = (
    "https://api.tomtom.com/traffic/services/4/"
    "flowSegmentData/absolute/10/json"
)

@lru_cache(maxsize=100)
def get_live_traffic(latitude, longitude):
    if not TOMTOM_API_KEY:
        print("TomTom API key not found.")
        return None

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

        traffic = 1 - (current_speed / free_flow_speed)
        traffic = max(0.0, min(1.0, traffic))
        return {
            "current_speed": current_speed,
            "free_flow_speed": free_flow_speed,
            "traffic": round(traffic, 3),
            "confidence": data.get("confidence"),
            "road_closure": data.get("roadClosure", False),
            "source": "TomTom Live Traffic",
        }
    except requests.RequestException as error:
        print("TomTom request failed:", error)
        return None
    except (ValueError, TypeError, KeyError) as error:
        print("TomTom response error:", error)
        return None


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
