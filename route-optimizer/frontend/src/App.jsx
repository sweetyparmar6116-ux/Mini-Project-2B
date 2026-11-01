
import { useEffect, useMemo, useRef, useState } from "react";
import {
  MapContainer,
  TileLayer,
  Polyline,
  Marker,
  Tooltip,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";

const API = "http://localhost:8000";
const MIN_TRAFFIC_OVERLAY_SLOWDOWN = 0.08;
const REVERSE_GEOCODING_API =
  "https://nominatim.openstreetmap.org/reverse";
const selectionFactorLabels = {
  distance: "Distance",
  time: "Estimated travel time",
  traffic: "Traffic",
  weather: "Weather risk",
};

const pin = (letter, cls) =>
  L.divIcon({
    className: "",
    html: `<div class="pin ${cls}">${letter}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });

const fmtTime = (minutes) => {
  const value = Number(minutes);

  if (!Number.isFinite(value) || value < 0) return "N/A";

  const total = Math.round(value);

  if (total < 60) return `${total} min`;

  return `${Math.floor(total / 60)} h ${total % 60} min`;
};

const fmtDistance = (distance) => {
  const value = Number(distance);

  return Number.isFinite(value) && value >= 0
    ? `${value.toFixed(2)} km`
    : "N/A";
};

const fmtTraffic = (value) => {
  const traffic = Number(value);

  if (!Number.isFinite(traffic) || traffic < 0) return "N/A";

  return `${Math.round(traffic * 100)}%`;
};

const fmtCost = (value) => {
  const cost = Number(value);

  if (!Number.isFinite(cost) || cost < 0) return "N/A";

  return `₹${cost.toFixed(2)}`;
};

const fmtRisk = (value) => {
  const risk = Number(value);

  if (!Number.isFinite(risk) || risk < 0) return "N/A";

  return `${(risk * 100).toFixed(0)}%`;
};

const trafficLevel = (value) => {
  const traffic = Number(value);

  if (!Number.isFinite(traffic) || traffic < 0) return "N/A";

  if (traffic < 0.35) return "Low";
  if (traffic < 0.7) return "Medium";
  return "High";
};

function formatWeather(weather, fallback) {
  if (typeof weather === "string" && weather.trim()) return weather;
  if (!weather || typeof weather !== "object") return fallback;
  if (weather.available === false) return weather.message || fallback;

  const description =
    weather.description ??
    weather.conditions?.find((condition) => condition.description)
      ?.description;
  const temperature = Number(weather.temperature_c);
  const summary = [
    description,
    Number.isFinite(temperature) ? `${Math.round(temperature)}°C` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return summary || (weather.available ? "Forecast available" : fallback);
}

function formatTrafficUpdatedAt(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString();
}

function normalizeCoordinates(rawCoordinates) {
  if (
    rawCoordinates &&
    !Array.isArray(rawCoordinates) &&
    Array.isArray(rawCoordinates.coordinates)
  ) {
    rawCoordinates = rawCoordinates.coordinates.map((point) =>
      Array.isArray(point) && point.length >= 2
        ? [point[1], point[0]]
        : point
    );
  }

  return Array.isArray(rawCoordinates)
    ? rawCoordinates
        .map((point) => {
          if (Array.isArray(point) && point.length >= 2) {
            return [Number(point[0]), Number(point[1])];
          }

          if (point && typeof point === "object") {
            const lat = Number(
              point.lat ?? point.latitude ?? point.y
            );
            const lon = Number(
              point.lon ??
              point.lng ??
              point.longitude ??
              point.x
            );
            return [lat, lon];
          }

          return null;
        })
        .filter(
          (point) =>
            point &&
            Number.isFinite(point[0]) &&
            Number.isFinite(point[1]) &&
            point[0] >= -90 &&
            point[0] <= 90 &&
            point[1] >= -180 &&
            point[1] <= 180
        )
    : [];
}

function downsampleCoordinates(coords, maxPoints = 100) {
  if (coords.length <= maxPoints) return coords;

  return Array.from({ length: maxPoints }, (_, index) => {
    const sourceIndex = Math.round(
      (index * (coords.length - 1)) / (maxPoints - 1)
    );
    return coords[sourceIndex];
  });
}

// Normalize route coordinates and metrics from the backend.
function normalizeRoute(route) {
  const rawCoordinates =
    route.coords ??
    route.coordinates ??
    route.path ??
    route.geometry ??
    [];
  const coords = normalizeCoordinates(rawCoordinates);
  const liveTrafficSegments = Array.isArray(
    route.live_traffic_segments
  )
    ? route.live_traffic_segments
        .map((segment) => ({
          ...segment,
          coords: normalizeCoordinates(
            segment.coordinates ?? segment.coords
          ),
        }))
        .filter(
          (segment) =>
            segment.coords.length >= 2 &&
            Number.isFinite(Number(segment.traffic))
        )
    : [];

  return {
    ...route,
    coords,
    live_traffic_segments: liveTrafficSegments,
    distance_km: Number(
      route.distance_km ??
      route.distanceKm ??
      route.distance ??
      0
    ),
    eta_min: Number(
      route.eta_min ??
      route.duration_min ??
      route.time_minutes ??
      route.duration_minutes ??
      route.estimated_time_minutes ??
      route.estimated_time ??
      0
    ),
  };
}


// Convert GPS coordinates into a readable address.
async function getReadableAddress(lat, lon, signal) {
  const url = new URL(REVERSE_GEOCODING_API);

  url.search = new URLSearchParams({
    format: "jsonv2",
    lat: String(lat),
    lon: String(lon),
    zoom: "18",
    addressdetails: "1",
  }).toString();

  const response = await fetch(url.toString(), {
    headers: {
      Accept: "application/json",
    },
    signal,
  });

  if (!response.ok) {
    throw new Error("Could not retrieve the address.");
  }

  const result = await response.json();
  const address = result.address ?? {};

  const area =
    address.suburb ??
    address.neighbourhood ??
    address.residential ??
    address.quarter ??
    address.village ??
    address.town ??
    address.city_district;

  const city =
    address.city ??
    address.town ??
    address.village ??
    address.municipality ??
    address.county;

  const parts = [
    address.road,
    address.pedestrian,
    address.footway,
    area,
    city,
    address.state,
  ]
    .filter(Boolean)
    .filter(
      (part, index, allParts) =>
        allParts.findIndex(
          (other) =>
            other.toLowerCase() === part.toLowerCase()
        ) === index
    );

  // Use the complete returned display name if detailed components are absent.
  return parts.join(", ") || result.display_name || "";
}

function MapResizeFix() {
  const map = useMap();

  useEffect(() => {
    const resize = () => map.invalidateSize({ pan: false });
    const timer = setTimeout(resize, 150);

    window.addEventListener("resize", resize);

    let observer;

    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(resize);
      observer.observe(map.getContainer());
    }

    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", resize);
      observer?.disconnect();
    };
  }, [map]);

  return null;
}

function MapController({ bounds, fitSignal }) {
  const map = useMap();

  useEffect(() => {
    if (bounds.length >= 2) {
      map.fitBounds(bounds, {
        padding: [40, 40],
        maxZoom: 15,
      });
    }
  }, [bounds, fitSignal, map]);

  return null;
}

function PlaceInput({ label, place, onPlace, onEnter, extra }) {
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const typing = useRef(false);

  useEffect(() => {
    if (!typing.current || place.label.trim().length < 3) {
      setItems([]);
      setOpen(false);
      return;
    }

    const controller = new AbortController();

    const timer = setTimeout(async () => {
      try {
        const response = await fetch(
          `${API}/suggest?q=${encodeURIComponent(place.label)}`,
          { signal: controller.signal }
        );

        if (!response.ok) {
          setItems([]);
          setOpen(false);
          return;
        }

        const result = await response.json();

        // Support both a raw array and { suggestions: [...] }.
        const suggestions = Array.isArray(result)
          ? result
          : Array.isArray(result.suggestions)
            ? result.suggestions
            : [];

        const normalizedItems = suggestions
          .map((item) => ({
            ...item,
            label: item.label ?? item.name ?? "",
            lat: Number(item.lat),
            lon: Number(item.lon),
          }))
          .filter(
            (item) =>
              item.label &&
              Number.isFinite(item.lat) &&
              Number.isFinite(item.lon)
          );

        setItems(normalizedItems);
        setOpen(normalizedItems.length > 0);
      } catch (error) {
        if (error.name !== "AbortError") {
          setItems([]);
          setOpen(false);
        }
      }
    }, 500);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [place.label]);

  return (
    <div className="field">
      <label>{label}</label>

      <div className="field-row">
        <input
          type="text"
          value={place.label}
          placeholder={`Search ${label.toLowerCase()}...`}
          autoComplete="off"
          onChange={(event) => {
            typing.current = true;
            onPlace({ label: event.target.value });
          }}
          onFocus={() => {
            if (items.length) setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              setOpen(false);
              onEnter();
            }
          }}
        />

        {extra}
      </div>

      {open && items.length > 0 && (
        <ul className="suggest">
          {items.map((item, index) => (
            <li
              key={`${item.lat}-${item.lon}-${index}`}
              onMouseDown={(event) => {
                event.preventDefault();
                typing.current = false;
                onPlace(item);
                setOpen(false);
              }}
            >
              {item.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const vehicleOptions = [
  { value: "Bike", label: "🏍️ Bike / Scooter" },
  { value: "Car", label: "🚗 Car" },
  { value: "Auto", label: "🛺 Auto-rickshaw" },
  { value: "Truck", label: "🚚 Truck" },
  { value: "Bus", label: "🚌 Bus" },
  { value: "Walk", label: "🚶 Walking" },
];

const formControlStyle = {
  width: "100%",
  boxSizing: "border-box",
  padding: "10px 12px",
  borderRadius: "8px",
  border: "1px solid var(--line, #34383f)",
  background: "var(--panel, #1b1c20)",
  color: "inherit",
  font: "inherit",
};

export default function App() {
  const [source, setSource] = useState({
    label: "Andheri Station",
  });

  const [destination, setDestination] = useState({
    label: "Bandra Station",
  });

  const [vehicle, setVehicle] = useState("Bike");

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState("");
  const [fitSignal, setFitSignal] = useState(0);

  // Avoid applying an old address lookup after a newer location request.
  const locationRequestRef = useRef(0);
  const trafficPollingRef = useRef(null);
  const trafficRequestRef = useRef(0);

  useEffect(
    () => () => {
      trafficRequestRef.current += 1;
      if (trafficPollingRef.current) {
        clearInterval(trafficPollingRef.current);
      }
    },
    []
  );

  function stopTrafficRefresh() {
    trafficRequestRef.current += 1;
    if (trafficPollingRef.current) {
      clearInterval(trafficPollingRef.current);
      trafficPollingRef.current = null;
    }
  }

  const routes = useMemo(() => {
    if (!Array.isArray(data?.routes)) return [];

    return data.routes
      .map((route, originalIndex) => ({
        ...normalizeRoute(route),
        originalIndex,
      }))
      .filter(
        (route) =>
          route.coords.length >= 2 &&
          Number.isFinite(route.distance_km)
      );
  }, [data]);

  // Respect the route selected by the backend.
  const recommendation = useMemo(() => {
    if (!routes.length) return null;

    const selectedIndex = Number.isInteger(data?.best_index)
      ? data.best_index
      : 0;

    return (
      routes.find((route) => route.originalIndex === selectedIndex) ??
      routes[0]
    );
  }, [routes, data?.best_index]);

  const bounds = useMemo(
    () => recommendation?.coords ?? [],
    [recommendation]
  );

  async function find() {
    if (!source.label.trim() || !destination.label.trim()) {
      setError("Enter both a starting point and a destination.");
      return;
    }

    setLoading(true);
    setError("");
    setData(null);
    stopTrafficRefresh();
    const trafficRequestId = trafficRequestRef.current;

    try {
      const response = await fetch(`${API}/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: source.label,
          destination: destination.label,
          source_lat: source.lat,
          source_lon: source.lon,
          destination_lat: destination.lat,
          destination_lon: destination.lon,
          vehicle_type: vehicle,
        }),
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(
          typeof result.detail === "string"
            ? result.detail
            : "Could not calculate a route. Check your locations."
        );
      }

      if (!Array.isArray(result.routes) || !result.routes.length) {
        throw new Error("No routes returned. Try different locations.");
      }

      const normalizedRoutes = result.routes.map(
        (route, originalIndex) => ({
          ...normalizeRoute(route),
          originalIndex,
        })
      );

      const usableRoutes = normalizedRoutes.filter(
        (route) =>
          route.coords.length >= 2 &&
          Number.isFinite(route.distance_km)
      );

      if (!usableRoutes.length) {
        throw new Error(
          "The backend returned no usable road coordinates. Check the route geometry format in engine.py or main.py."
        );
      }

      const backendBestIndex = Number.isInteger(result.best_index)
        ? result.best_index
        : 0;

      const mappedBestIndex = usableRoutes.findIndex(
        (route) => route.originalIndex === backendBestIndex
      );

      setData({
        ...result,
        routes: usableRoutes,
        best_index: mappedBestIndex >= 0 ? mappedBestIndex : 0,
      });

      setFitSignal((value) => value + 1);

      const selectedRouteIndex =
        mappedBestIndex >= 0 ? mappedBestIndex : 0;
      const selectedRoute = usableRoutes[selectedRouteIndex];
      let trafficRefreshInProgress = false;
      const updateTraffic = async () => {
        if (trafficRefreshInProgress) return;
        trafficRefreshInProgress = true;

        try {
          const trafficResponse = await fetch(`${API}/traffic`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              coordinates: downsampleCoordinates(selectedRoute.coords),
            }),
          });
          const trafficResult = await trafficResponse.json();

          if (!trafficResponse.ok) {
            throw new Error(
              typeof trafficResult.detail === "string"
                ? trafficResult.detail
                : "Live traffic could not be refreshed."
            );
          }
          if (trafficRequestRef.current !== trafficRequestId) return;

          const trafficSegments = normalizeRoute({
            live_traffic_segments: trafficResult.segments,
          }).live_traffic_segments;

          setData((current) => {
            if (!current) return current;
            return {
              ...current,
              live_traffic_available: trafficResult.available,
              traffic_source: trafficResult.source,
              traffic_updated_at: trafficResult.updated_at,
              traffic_message: trafficResult.message,
              traffic_refresh_error: "",
              routes: current.routes.map((route, index) =>
                index === selectedRouteIndex
                  ? {
                      ...route,
                      live_traffic_segments: trafficSegments,
                      traffic_is_live: trafficResult.available,
                      traffic_updated_at: trafficResult.updated_at,
                      traffic: trafficSegments.length
                        ? trafficSegments.reduce(
                            (total, segment) =>
                              total + Number(segment.traffic),
                            0
                          ) / trafficSegments.length
                        : route.traffic,
                    }
                  : route
              ),
            };
          });
        } catch (trafficError) {
          if (trafficRequestRef.current !== trafficRequestId) return;

          setData((current) => {
            if (!current) return current;
            return {
              ...current,
              live_traffic_available: false,
              traffic_source: null,
              traffic_updated_at: null,
              traffic_message: "",
              traffic_refresh_error: trafficError.message,
              routes: current.routes.map((route, index) =>
                index === selectedRouteIndex
                  ? {
                      ...route,
                      live_traffic_segments: [],
                      traffic_is_live: false,
                      traffic_updated_at: null,
                    }
                  : route
              ),
            };
          });
        } finally {
          trafficRefreshInProgress = false;
        }
      };

      void updateTraffic();
      trafficPollingRef.current = setInterval(
        updateTraffic,
        60_000
      );
    } catch (err) {
      setError(
        err.message === "Failed to fetch"
          ? "Cannot reach the backend. Check that FastAPI is running."
          : err.message
      );
    } finally {
      setLoading(false);
    }
  }

  // Get GPS coordinates, then look up a readable address.
  function useMyLocation() {
    stopTrafficRefresh();
    setError("");

    if (!navigator.geolocation) {
      setError(
        "Geolocation is not supported by this browser. Try Chrome or Edge."
      );
      return;
    }

    const requestId = ++locationRequestRef.current;

    setLocating(true);

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        if (requestId !== locationRequestRef.current) return;

        const lat = position.coords.latitude;
        const lon = position.coords.longitude;

        // Set the real GPS coordinates immediately.
        setSource({
          label: "My location",
          lat,
          lon,
        });

        setData(null);
        setError("");
        setLocating(false);

        try {
          const readableAddress = await getReadableAddress(lat, lon);

          // Ignore the result if another location request has started.
          if (requestId !== locationRequestRef.current) return;

          if (readableAddress) {
            setSource((current) => {
              // Do not overwrite a location the user has since changed.
              if (current.lat !== lat || current.lon !== lon) {
                return current;
              }

              return {
                ...current,
                label: readableAddress,
              };
            });
          }
        } catch (err) {
          if (requestId === locationRequestRef.current) {
            console.warn(
              "Address lookup failed. GPS coordinates are still available.",
              err
            );
          }
        }
      },
      (locationError) => {
        if (requestId !== locationRequestRef.current) return;

        let message = "Could not get your current location.";

        if (locationError.code === 1) {
          message =
            "Location permission was denied. Allow location access in your browser settings and try again.";
        } else if (locationError.code === 2) {
          message =
            "Your location is unavailable. Check your device location settings and try again.";
        } else if (locationError.code === 3) {
          message =
            "Getting your location took too long. Please try again.";
        }

        setError(message);
        setLocating(false);
      },
      {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 0,
      }
    );
  }

  function swap() {
    stopTrafficRefresh();
    setSource(destination);
    setDestination(source);
    setError("");
    setData(null);
  }

  const markerSource =
    data?.snapped_source ??
    (data?.source
      ? [data.source.lat, data.source.lon]
      : null);

  const markerDestination =
    data?.snapped_destination ??
    (data?.destination
      ? [data.destination.lat, data.destination.lon]
      : null);

  const validPosition = (position) =>
    Array.isArray(position) &&
    position.length >= 2 &&
    Number.isFinite(Number(position[0])) &&
    Number.isFinite(Number(position[1])) &&
    Number(position[0]) >= -90 &&
    Number(position[0]) <= 90 &&
    Number(position[1]) >= -180 &&
    Number(position[1]) <= 180;

const deadEnds = Array.isArray(data?.dead_ends)
  ? data.dead_ends
  : [];

  const selectionFactors = Object.entries(data?.weights ?? {})
    .filter(([factor, weight]) =>
      selectionFactorLabels[factor] && Number(weight) > 0
    )
    .map(([factor, weight]) => ({
      key: factor,
      label: selectionFactorLabels[factor],
      weight: Number(weight),
      score: Number(recommendation?.normalized_scores?.[factor]),
    }));

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="panel">
  <h3>🚧 Road Dead Ends</h3>

  <div className="stats">
    <div>
      <b>{deadEnds.length}</b>
      <small>Detected points</small>
    </div>

    <div>
      <b>{routes.length}</b>
      <small>Candidate routes</small>
    </div>
  </div>

  <p className="hint">
    Red markers identify possible dead-end nodes
    detected near the selected route.
  </p>

  {data && deadEnds.length === 0 && (
    <p className="hint">
      No possible dead ends were found near this route.
      Try another route to check a different area.
    </p>
  )}

  {!data && (
    <p className="hint">
      Calculate a route to inspect nearby dead ends.
    </p>
  )}
</div>
        <h1>Route Optimizer</h1>

        <p className="hint">
  Explore alternative road routes, compare estimated travel times,
  and identify the recommended route and detected road dead ends.
</p>
        <div className="panel">
          <PlaceInput
            label="From"
            place={source}
            onPlace={(place) => {
              stopTrafficRefresh();
              setData(null);
              setSource(place);
            }}
            onEnter={find}
            extra={
              <button
                className="icon-btn"
                title="Use my current location"
                aria-label="Use my current location"
                onClick={useMyLocation}
                disabled={locating}
              >
                {locating ? "⏳" : "📍"}
              </button>
            }
          />

          {locating && (
            <p className="hint">
              Getting your current location...
            </p>
          )}

          <button className="swap" title="Swap locations" onClick={swap}>
            ⇅ Swap
          </button>

          <PlaceInput
            label="To"
            place={destination}
            onPlace={(place) => {
              stopTrafficRefresh();
              setData(null);
              setDestination(place);
            }}
            onEnter={find}
          />

          <button className="primary" onClick={find} disabled={loading}>
            {loading ? "Finding route..." : "Find best route"}
          </button>

          {error && <p className="error">{error}</p>}
        </div>

        <div className="panel">
          <h3>🚘 Choose your vehicle</h3>

          <p className="hint">
            Choose your vehicle for the trip. Route selection is based on
            the backend's route-scoring conditions, not vehicle type alone.
          </p>

          <div className="field">
            <label htmlFor="vehicle-type">Vehicle type</label>

            <select
              id="vehicle-type"
              value={vehicle}
              onChange={(event) => setVehicle(event.target.value)}
              style={formControlStyle}
            >
              {vehicleOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {recommendation ? (
          <>
            <div className="panel">
              <h3>★ Recommended Route</h3>

              <p className="hint">
                Chosen from {data.candidate_count ?? routes.length} candidate
                routes using the weighted criteria below. The lowest total
                score wins.
              </p>

              <div className="selection-breakdown">
                <div className="selection-score">
                  <span>Selection score</span>
                  <strong>
                    {Number.isFinite(Number(recommendation.selection_score))
                      ? Number(recommendation.selection_score).toFixed(4)
                      : "N/A"}
                  </strong>
                  <small>Lower is better</small>
                </div>

                <div className="selection-factors">
                  {selectionFactors.map((factor) => {
                    const hasScore = Number.isFinite(factor.score);
                    const relativeQuality = hasScore
                      ? Math.max(0, Math.min(1, 1 - factor.score))
                      : 0;

                    return (
                      <div
                        className="selection-factor"
                        key={factor.key}
                      >
                        <div className="selection-factor-heading">
                          <strong>{factor.label}</strong>
                          <span>{Math.round(factor.weight * 100)}% weight</span>
                        </div>
                        <div
                          className="selection-factor-meter"
                          role="img"
                          aria-label={`${factor.label}: ${Math.round(
                            factor.weight * 100
                          )}% weight, ${
                            hasScore
                              ? `relative score ${factor.score.toFixed(2)} out of 1, lower is better`
                              : "score unavailable"
                          }`}
                        >
                          <span
                            style={{
                              width: `${relativeQuality * 100}%`,
                            }}
                          />
                        </div>
                        <small>
                          {hasScore
                            ? `Relative score ${factor.score.toFixed(2)} / 1 · lower is better`
                            : "Relative score unavailable"}
                        </small>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="stats">
                <div>
                  <b>{fmtDistance(recommendation.distance_km)}</b>
                  <small>Distance</small>
                </div>

                <div>
                  <b>{fmtTime(recommendation.eta_min)}</b>
                  <small>Estimated time</small>
                </div>

                <div>
                  <b>{fmtTraffic(recommendation.traffic)}</b>
                  <small>
                    {recommendation.traffic_is_live
                      ? "Live traffic"
                      : `${trafficLevel(recommendation.traffic)} · estimated`}
                  </small>
                </div>
              </div>

              <div
                className={`traffic-status ${
                  data.live_traffic_available
                    ? "traffic-status-live"
                    : "traffic-status-unavailable"
                }`}
                role="status"
              >
                <span className="traffic-status-dot" />
                <div>
                  <strong>
                    {data.live_traffic_available
                      ? "Live traffic · TomTom"
                      : "Live traffic unavailable"}
                  </strong>
                  <small>
                    {data.live_traffic_available
                      ? `Updated ${formatTrafficUpdatedAt(
                          data.traffic_updated_at
                        ) || "just now"} · refreshes every minute`
                      : data.traffic_refresh_error
                        ? `Update failed: ${data.traffic_refresh_error}`
                        : data.traffic_message ||
                          "Showing estimated traffic only."}
                  </small>
                </div>
              </div>

              <div className="route-meta-grid">
                <div>
                  <span>Cost</span>
                  <strong>{fmtCost(recommendation.cost)}</strong>
                </div>

                <div>
                  <span>Risk</span>
                  <strong>{fmtRisk(recommendation.risk)}</strong>
                </div>

                <div>
                  <span>Weather</span>
                  <strong>
                    {formatWeather(
                      recommendation.weather,
                      data?.weather_available ? "Forecasted" : "Unavailable"
                    )}
                  </strong>
                </div>
              </div>

              <small className="hint">
                The dashboard also reflects the backend-selected route, with
                traffic, cost, and risk values included.
              </small>
            </div>

            {routes.length > 1 && (
              <div className="panel">
                <h3>📊 All route changes</h3>

                <div className="route-list">
                  {routes.map((route, index) => {
                    const isSelected =
                      route.originalIndex === data?.best_index;

                    return (
                      <div
                        key={`route-summary-${route.originalIndex}`}
                        className={`route-card ${
                          isSelected ? "route-card-selected" : ""
                        }`}
                      >
                        <div className="route-card-header">
                          <strong>
                            {isSelected ? "Recommended" : `Route ${index + 1}`}
                          </strong>
                          {isSelected && <span className="pill">Best</span>}
                        </div>

                        <div className="route-card-grid">
                          <div>
                            <span>Distance</span>
                            <strong>{fmtDistance(route.distance_km)}</strong>
                          </div>
                          <div>
                            <span>Time</span>
                            <strong>{fmtTime(route.eta_min)}</strong>
                          </div>
                          <div>
                            <span>Traffic</span>
                            <strong>
                              {fmtTraffic(route.traffic)}
                              {route.traffic_is_live ? " · Live" : " · Est."}
                            </strong>
                          </div>
                          <div>
                            <span>Risk</span>
                            <strong>{fmtRisk(route.risk)}</strong>
                          </div>
                          <div>
                            <span>Cost</span>
                            <strong>{fmtCost(route.cost)}</strong>
                          </div>
                          <div>
                            <span>Weather</span>
                            <strong>
                              {formatWeather(
                                route.weather,
                                data?.weather_available
                                  ? "Forecasted"
                                  : "Unavailable"
                              )}
                            </strong>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="hint">
            Enter a starting point and destination, then select Find best
            route.
          </p>
        )}
      </aside>

      <main className="map-wrap">
        <MapContainer
          center={[19.09, 72.85]}
          zoom={12}
          zoomControl
          style={{ height: "100%", width: "100%" }}
        >
          <MapResizeFix />

          <TileLayer
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap contributors"
          />

          <MapController bounds={bounds} fitSignal={fitSignal} />

          {routes.map((route, index) => {
            if (route.coords.length < 2) return null;

            const isRecommended =
              route.originalIndex === data?.best_index;
            const routeColors = [
              "#16a34a",
              "#2563eb",
              "#9333ea",
              "#ea580c",
              "#0891b2",
              "#db2777",
            ];

            return (
              <Polyline
                key={`route-${route.originalIndex}`}
                positions={route.coords}
                pathOptions={{
                  color: isRecommended
                    ? "#16a34a"
                    : routeColors[(index + 1) % routeColors.length],
                  weight: isRecommended ? 7 : 5,
                  opacity: isRecommended ? 1 : 0.8,
                }}
              >
                <Tooltip sticky>
                  {isRecommended
                    ? "★ Recommended Route"
                    : `Alternative Route ${index + 1}`}
                  {" · "}
                  {fmtDistance(route.distance_km)}
                  {" · "}
                  {fmtTime(route.eta_min)}
                  {" · "}
                  Traffic {fmtTraffic(route.traffic)}
                </Tooltip>
              </Polyline>
            );
          })}

          {routes.flatMap((route) =>
            route.live_traffic_segments
              .filter(
                (segment) =>
                  Number(segment.traffic) >=
                  MIN_TRAFFIC_OVERLAY_SLOWDOWN
              )
              .map((segment, index) => (
                <Polyline
                  key={`traffic-${route.originalIndex}-${index}`}
                  positions={segment.coords}
                  pathOptions={{
                    color: Number(segment.traffic) >= 0.2
                      ? "#b91c1c"
                      : "#ef4444",
                    weight: 12,
                    opacity: 1,
                    lineCap: "round",
                    lineJoin: "round",
                  }}
                >
                  <Tooltip sticky>
                    Live congestion · {fmtTraffic(segment.traffic)}
                    {segment.current_speed
                      ? ` · ${Math.round(segment.current_speed)} km/h`
                      : ""}
                  </Tooltip>
                </Polyline>
              ))
          )}

          {data && (
            <div className="traffic-legend" aria-live="polite">
              <strong>Traffic overlay</strong>
              <span>
                <i className="traffic-legend-line" />
                Red marks live slowdowns
              </span>
              <small>
                {data.live_traffic_available
                  ? "Live speeds at least 8% below free flow · refreshes every minute"
                  : "Live congestion overlay unavailable"}
              </small>
            </div>
          )}

          {(data?.dead_ends ?? []).map((point, index) => {
            const lat = Number(point.lat);
            const lon = Number(point.lon);

            if (
              !Number.isFinite(lat) ||
              !Number.isFinite(lon) ||
              lat < -90 ||
              lat > 90 ||
              lon < -180 ||
              lon > 180
            ) {
              return null;
            }

            return (
              <Marker
                key={`dead-end-${index}`}
                position={[lat, lon]}
                icon={pin("!", "pin-dead-end")}
              >
                <Tooltip>Possible road dead end</Tooltip>
              </Marker>
            );
          })}
        </MapContainer>

        <button
          className="fit"
          disabled={bounds.length < 2}
          onClick={() => setFitSignal((value) => value + 1)}
        >
          Fit route
        </button>
      </main>
    </div>
  );
}
