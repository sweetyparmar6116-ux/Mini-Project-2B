
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timezone


WEATHER_API = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "IntelligentRouteOptimizer/1.0"

ROUTE_SAMPLE_COUNT = 5
DEFAULT_JOURNEY_MINUTES = 120
MAX_FORECAST_HOURS = 24


def _number(value, default=None):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _average(values):
    valid = [v for v in values if v is not None]
    return round(sum(valid) / len(valid), 2) if valid else None


def sample_route_coordinates(coordinates, count=ROUTE_SAMPLE_COUNT):
    """Select evenly spaced latitude/longitude points along a route."""
    if not coordinates:
        return []

    valid = []

    for point in coordinates:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue

        lat = _number(point[0])
        lon = _number(point[1])

        if lat is not None and lon is not None:
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                valid.append((lat, lon))

    if not valid:
        return []

    if len(valid) <= count:
        indexes = list(range(len(valid)))
    elif count <= 1:
        indexes = [0]
    else:
        indexes = sorted({
            round(i * (len(valid) - 1) / (count - 1))
            for i in range(count)
        })

    result = []
    seen = set()

    for index in indexes:
        point = valid[index]
        key = (round(point[0], 4), round(point[1], 4))

        if key not in seen:
            seen.add(key)
            result.append(point)

    return result


def _description(code):
    code = int(_number(code, -1))

    descriptions = {
        0: "Clear",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Freezing fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Freezing drizzle",
        57: "Heavy freezing drizzle",
        61: "Light rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Light snowfall",
        73: "Moderate snowfall",
        75: "Heavy snowfall",
        77: "Snow grains",
        80: "Light rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Light snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with hail",
        99: "Severe thunderstorm with hail",
    }

    return descriptions.get(code, "Unknown conditions")


def _weather_risk(weather):
    """
    Transparent prototype heuristic, normalized from 0 to 1.
    This is not an official road-safety or weather prediction.
    """
    code = int(_number(weather.get("weather_code"), -1))

    rain = max(0.0, _number(weather.get("rain_mm"), 0.0))
    showers = max(0.0, _number(weather.get("showers_mm"), 0.0))
    precipitation = max(
        0.0, _number(weather.get("precipitation_mm"), 0.0)
    )
    probability = max(
        0.0, min(100.0,
            _number(weather.get("precipitation_probability"), 0.0)
        )
    )

    wind = max(
        0.0, _number(weather.get("wind_speed_kmh"), 0.0)
    )
    gust = max(
        wind, _number(weather.get("wind_gusts_kmh"), wind)
    )

    visibility = _number(weather.get("visibility_m"))
    temperature = _number(weather.get("temperature_c"))
    snowfall = max(
        0.0, _number(weather.get("snowfall_cm"), 0.0)
    )

    # Precipitation intensity and likelihood.
    rain_intensity = min(
        1.0, max(rain, showers, precipitation) / 10.0
    )
    rain_risk = max(
        rain_intensity * 0.7,
        (probability / 100.0) * 0.5,
    )

    # WMO weather-code severity.
    code_risks = {
        45: 0.65, 48: 0.80,
        51: 0.20, 53: 0.30, 55: 0.45,
        56: 0.60, 57: 0.75,
        61: 0.30, 63: 0.50, 65: 0.80,
        66: 0.70, 67: 0.90,
        71: 0.40, 73: 0.60, 75: 0.85, 77: 0.40,
        80: 0.35, 81: 0.55, 82: 0.85,
        85: 0.50, 86: 0.85,
        95: 0.85, 96: 0.95, 99: 1.0,
    }
    code_risk = code_risks.get(code, 0.0)

    # Wind and gust penalties.
    wind_risk = min(1.0, max(0.0, (wind - 25.0) / 65.0))
    gust_risk = min(1.0, max(0.0, (gust - 35.0) / 65.0))
    wind_risk = max(wind_risk, gust_risk)

    # Visibility penalty.
    visibility_risk = 0.0

    if visibility is not None:
        if visibility < 200:
            visibility_risk = 1.0
        elif visibility < 500:
            visibility_risk = 0.90
        elif visibility < 1000:
            visibility_risk = 0.75
        elif visibility < 3000:
            visibility_risk = 0.50
        elif visibility < 5000:
            visibility_risk = 0.20

    # Snow and possible freezing conditions.
    snow_risk = min(1.0, snowfall / 2.0)
    freezing_risk = 0.0

    if temperature is not None and temperature <= 0:
        if code in (56, 57, 66, 67, 71, 73, 75, 77, 85, 86):
            freezing_risk = 0.90

    risk = (
        0.25 * rain_risk
        + 0.30 * code_risk
        + 0.15 * wind_risk
        + 0.20 * visibility_risk
        + 0.05 * snow_risk
        + 0.05 * freezing_risk
    )

    return round(max(0.0, min(1.0, risk)), 4)


def _hourly_weather(hourly, index):
    """Convert one hourly forecast entry to normalized weather data."""
    def get(name, default=None):
        values = hourly.get(name) or []
        if index >= len(values):
            return default
        return _number(values[index], default)

    temperature = get("temperature_2m")
    code = int(get("weather_code", -1))
    rain = get("rain", 0.0)
    showers = get("showers", 0.0)
    precipitation = get("precipitation", 0.0)
    probability = get("precipitation_probability", 0.0)
    wind = get("wind_speed_10m", 0.0)
    gusts = get("wind_gusts_10m", wind)
    visibility = get("visibility")
    snowfall = get("snowfall", 0.0)

    item = {
        "temperature_c": temperature,
        "rain_mm": rain,
        "showers_mm": showers,
        "precipitation_mm": precipitation,
        "precipitation_probability": probability,
        "wind_speed_kmh": wind,
        "wind_gusts_kmh": gusts,
        "visibility_m": visibility,
        "snowfall_cm": snowfall,
        "weather_code": code,
        "description": _description(code),
    }

    item["weather_risk"] = _weather_risk(item)
    return item


def _extract_location_weather(payload, journey_minutes=120):
    """Summarize forecast conditions over the estimated journey window."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []

    if not times:
        raise ValueError("Hourly weather forecast is unavailable.")

    current = payload.get("current") or {}
    current_time = current.get("time")

    # Find the current forecast hour.
    start_index = 0

    if current_time in times:
        start_index = times.index(current_time)
    else:
        try:
            now = datetime.now(timezone.utc)
            parsed = [
                datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
                if "+" not in t and "Z" not in t
                else datetime.fromisoformat(t.replace("Z", "+00:00"))
                for t in times
            ]
            start_index = min(
                range(len(parsed)),
                key=lambda i: abs((parsed[i] - now).total_seconds()),
            )
        except (ValueError, TypeError):
            start_index = 0

    duration = max(
        60,
        min(
            int(_number(journey_minutes, DEFAULT_JOURNEY_MINUTES)),
            MAX_FORECAST_HOURS * 60,
        ),
    )
    hours_to_check = max(1, math.ceil(duration / 60.0) + 1)
    end_index = min(len(times), start_index + hours_to_check)

    forecasts = [
        _hourly_weather(hourly, i)
        for i in range(start_index, end_index)
    ]

    if not forecasts:
        raise ValueError("No forecast entries were available.")

    risks = [item["weather_risk"] for item in forecasts]

    # Preserve the worst expected hour as well as the average.
    average_risk = sum(risks) / len(risks)
    maximum_risk = max(risks)

    # A maximum-risk contribution prevents a short severe period
    # from disappearing inside a low average.
    route_risk = 0.65 * average_risk + 0.35 * maximum_risk

    current_weather = forecasts[0]

    return {
        "temperature_c": _average(
            [item["temperature_c"] for item in forecasts]
        ),
        "humidity_percent": _number(
            (payload.get("current") or {}).get("relative_humidity_2m")
        ),
        "rain_mm": _average([item["rain_mm"] for item in forecasts]),
        "precipitation_mm": _average(
            [item["precipitation_mm"] for item in forecasts]
        ),
        "precipitation_probability": max(
            item["precipitation_probability"] or 0
            for item in forecasts
        ),
        "wind_speed_kmh": max(
            item["wind_speed_kmh"] or 0 for item in forecasts
        ),
        "wind_gusts_kmh": max(
            item["wind_gusts_kmh"] or 0 for item in forecasts
        ),
        "visibility_m": min(
            (
                item["visibility_m"]
                for item in forecasts
                if item["visibility_m"] is not None
            ),
            default=None,
        ),
        "snowfall_cm": max(
            item["snowfall_cm"] or 0 for item in forecasts
        ),
        "weather_code": current_weather["weather_code"],
        "description": current_weather["description"],
        "weather_risk": round(route_risk, 4),
        "maximum_sampled_weather_risk": round(maximum_risk, 4),
        "forecast_hours_checked": len(forecasts),
        "forecast": [
            {
                "time": times[start_index + i],
                **item,
            }
            for i, item in enumerate(forecasts)
        ],
        "model_times": times[start_index:end_index],
    }


def fetch_weather_for_coordinates(coordinates, timeout=15):
    """Fetch current and hourly forecast data for multiple locations."""
    if not coordinates:
        return []

    valid = []

    for point in coordinates:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            raise ValueError(
                "Each coordinate must contain latitude and longitude."
            )

        lat = _number(point[0])
        lon = _number(point[1])

        if lat is None or lon is None:
            raise ValueError("Invalid weather coordinates.")

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Weather coordinates are outside valid ranges.")

        valid.append((lat, lon))

    query = {
        "latitude": ",".join(f"{lat:.5f}" for lat, _ in valid),
        "longitude": ",".join(f"{lon:.5f}" for _, lon in valid),
        "current": (
            "temperature_2m,relative_humidity_2m,precipitation,"
            "rain,showers,snowfall,weather_code,"
            "wind_speed_10m,wind_gusts_10m"
        ),
        "hourly": (
            "temperature_2m,relative_humidity_2m,"
            "precipitation_probability,precipitation,rain,showers,"
            "snowfall,weather_code,wind_speed_10m,wind_gusts_10m,"
            "visibility"
        ),
        "forecast_days": 2,
        "timezone": "auto",
    }

    url = f"{WEATHER_API}?{urllib.parse.urlencode(query)}"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if isinstance(payload, dict):
        payloads = [payload]
    elif isinstance(payload, list):
        payloads = payload
    else:
        raise ValueError("Unexpected weather API response.")

    if len(payloads) != len(valid):
        raise ValueError(
            "Weather API returned a different number of locations."
        )

    results = []

    for item in payloads:
        if not isinstance(item, dict) or not item.get("hourly"):
            raise ValueError("Hourly forecast data is missing.")

        results.append(item)

    return results


def get_route_weather(coordinates, journey_minutes=None):
    """
    Evaluate forecast conditions at sampled route points.

    If journey_minutes is supplied, use that duration to determine
    the forecast window. Otherwise, inspect the next two hours.
    """
    samples = sample_route_coordinates(coordinates)

    if not samples:
        raise ValueError("No valid route coordinates to evaluate.")

    duration = (
        DEFAULT_JOURNEY_MINUTES
        if journey_minutes is None
        else journey_minutes
    )

    payloads = fetch_weather_for_coordinates(samples)
    points = [
        _extract_location_weather(payload, duration)
        for payload in payloads
    ]

    risks = [point["weather_risk"] for point in points]
    average_risk = sum(risks) / len(risks)

    # Weight the worst location more heavily so one severe segment
    # is not hidden by otherwise favorable weather.
    maximum_risk = max(risks, default=0.0)
    route_risk = 0.65 * average_risk + 0.35 * maximum_risk

    forecasts = []

    for index, point in enumerate(points):
        forecasts.append({
            "sample_index": index + 1,
            "weather_risk": point["weather_risk"],
            "maximum_sampled_weather_risk":
                point["maximum_sampled_weather_risk"],
            "description": point["description"],
            "temperature_c": point["temperature_c"],
            "rain_mm": point["rain_mm"],
            "precipitation_mm": point["precipitation_mm"],
            "precipitation_probability":
                point["precipitation_probability"],
            "wind_speed_kmh": point["wind_speed_kmh"],
            "wind_gusts_kmh": point["wind_gusts_kmh"],
            "visibility_m": point["visibility_m"],
            "snowfall_cm": point["snowfall_cm"],
            "forecast_hours_checked": point["forecast_hours_checked"],
            "model_times": point["model_times"],
            "forecast": point["forecast"],
        })

    all_hourly = [
        hour
        for point in points
        for hour in point["forecast"]
    ]

    def values(key):
        return [
            _number(hour.get(key))
            for hour in all_hourly
            if _number(hour.get(key)) is not None
        ]

    model_times = sorted({
        t for point in points for t in point["model_times"]
    })

    return {
        "source": "Open-Meteo",
        "data_type": "Current conditions and hourly weather forecast",
        "available": True,
        "sample_count": len(points),
        "journey_minutes_evaluated": int(
            _number(duration, DEFAULT_JOURNEY_MINUTES)
        ),
        "temperature_c": _average(values("temperature_c")),
        "rain_mm": _average(values("rain_mm")),
        "precipitation_mm": _average(values("precipitation_mm")),
        "precipitation_probability": max(
            values("precipitation_probability"), default=0.0
        ),
        "wind_speed_kmh": max(values("wind_speed_kmh"), default=0.0),
        "wind_gusts_kmh": max(values("wind_gusts_kmh"), default=0.0),
        "visibility_m": min(
            values("visibility_m"), default=None
        ),
        "snowfall_cm": max(values("snowfall_cm"), default=0.0),
        "weather_risk": round(route_risk, 4),
        "maximum_sampled_weather_risk": round(maximum_risk, 4),
        "conditions": forecasts,
        "model_times": model_times,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
