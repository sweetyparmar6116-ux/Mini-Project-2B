
import asyncio
import json
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import engine
import traffic_service


# ============================================================
# GRAPH INITIALIZATION
# ============================================================

G = None
D = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global G, D

    G = engine.load_graph()
    D = engine.to_simple(G)

    print(
        f"Graph ready: {G.number_of_nodes():,} nodes, "
        f"{G.number_of_edges():,} edges."
    )

    yield

    print("Route optimization API stopped.")


app = FastAPI(
    title="AI Driven Intelligent Route Optimization",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# REQUEST MODEL
# ============================================================

class RouteRequest(BaseModel):
    source: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)

    source_lat: Optional[float] = None
    source_lon: Optional[float] = None

    destination_lat: Optional[float] = None
    destination_lon: Optional[float] = None

    vehicle_type: Optional[str] = None
    fuel_type: Optional[str] = None

    vehicle_efficiency: Optional[float] = None
    energy_price: Optional[float] = None


class RouteTrafficRequest(BaseModel):
    coordinates: list[tuple[float, float]] = Field(
        ...,
        min_length=2,
        max_length=100,
    )


# ============================================================
# GEOCODING
# ============================================================

def geocode_place(place: str):
    """
    Convert an address or place name into latitude and longitude
    using OpenStreetMap Nominatim.
    """
    query = urllib.parse.urlencode({
        "q": place,
        "format": "jsonv2",
        "limit": 1,
    })

    url = f"https://nominatim.openstreetmap.org/search?{query}"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "RouteOptimizerStudentProject/1.0"
        },
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        results = json.loads(response.read().decode("utf-8"))

    if not results:
        raise ValueError(f"Location not found: {place}")

    return (
        float(results[0]["lat"]),
        float(results[0]["lon"]),
    )


async def resolve_coordinates(
    place: str,
    latitude: Optional[float],
    longitude: Optional[float],
):
    if latitude is not None and longitude is not None:
        if not (-90 <= latitude <= 90):
            raise ValueError("Latitude must be between -90 and 90.")

        if not (-180 <= longitude <= 180):
            raise ValueError("Longitude must be between -180 and 180.")

        return float(latitude), float(longitude)

    return await asyncio.to_thread(geocode_place, place)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def home():
    return {
        "message": "Route Optimization API is running.",
        "routing_objective": "shortest_road_distance",
        "preferences_enabled": False,
        "endpoints": ["/health", "/suggest", "/route"],
    }


@app.get("/health")
def health():
    if G is None or D is None:
        raise HTTPException(
            status_code=503,
            detail="Road graph is not ready.",
        )

    return {
        "status": "ready",
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
    }


# ============================================================
# PLACE SUGGESTIONS
# Response format: [{label, lat, lon}]
# ============================================================

@app.get("/suggest")
async def suggest(q: str):
    q = q.strip()

    if len(q) < 2:
        return []

    params = urllib.parse.urlencode({
        "q": q,
        "format": "jsonv2",
        "limit": 5,
        "addressdetails": 1,
    })

    url = f"https://nominatim.openstreetmap.org/search?{params}"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "RouteOptimizerStudentProject/1.0"
        },
    )

    try:
        def fetch_results():
            with urllib.request.urlopen(
                request, timeout=15
            ) as response:
                return json.loads(
                    response.read().decode("utf-8")
                )

        results = await asyncio.to_thread(fetch_results)

        return [
            {
                "label": item.get("display_name", q),
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
            }
            for item in results
        ]

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Location search failed: {exc}",
        ) from exc


# ============================================================
# ROUTE OPTIMIZATION
# No preference validation or preference-based selection.
# ============================================================

@app.post("/route")
async def route(request: RouteRequest):
    if G is None or D is None:
        raise HTTPException(
            status_code=503,
            detail="Road graph is not ready.",
        )

    try:
        source_coordinates = await resolve_coordinates(
            request.source,
            request.source_lat,
            request.source_lon,
        )

        destination_coordinates = await resolve_coordinates(
            request.destination,
            request.destination_lat,
            request.destination_lon,
        )

        result = await asyncio.to_thread(
            engine.find_best_route,
            G,
            D,
            source_coordinates,
            destination_coordinates,
            vehicle_type=request.vehicle_type,
            vehicle_efficiency=request.vehicle_efficiency,
            energy_price=request.energy_price,
        )

        return {
    **result,
    "source": {
        "label": request.source,
        "lat": source_coordinates[0],
        "lon": source_coordinates[1],
    },
    "destination": {
        "label": request.destination,
        "lat": destination_coordinates[0],
        "lon": destination_coordinates[1],
    },
    "data_status": (
        "OSM road-network data with live traffic when available and "
        "estimated risk"
    ),
}

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        print(f"Route calculation failed: {exc}")

        raise HTTPException(
            status_code=500,
            detail=f"Route calculation failed: {exc}",
        ) from exc


@app.post("/traffic")
async def route_traffic(request: RouteTrafficRequest):
    for latitude, longitude in request.coordinates:
        if not (-90 <= latitude <= 90):
            raise HTTPException(
                status_code=422,
                detail="Latitude must be between -90 and 90.",
            )
        if not (-180 <= longitude <= 180):
            raise HTTPException(
                status_code=422,
                detail="Longitude must be between -180 and 180.",
            )

    segments = await asyncio.to_thread(
        traffic_service.get_route_traffic,
        request.coordinates,
    )
    updated_at = max(
        (
            segment["updated_at"]
            for segment in segments
            if segment.get("updated_at")
        ),
        default=None,
    )

    return {
        "available": bool(segments),
        "source": "TomTom Live Traffic" if segments else None,
        "updated_at": updated_at,
        "segments": segments,
        "message": (
            None
            if segments
            else (
                "Configure TOMTOM_API_KEY in backend/.env to enable live "
                "traffic."
                if not traffic_service.TOMTOM_API_KEY
                else "TomTom returned no live traffic readings. Check the "
                "API key, account quota, and network connection."
            )
        ),
    }
