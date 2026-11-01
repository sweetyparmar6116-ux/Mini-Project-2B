import pandas as pd


def estimate_road_speeds(gps_data):
    """
    Estimate average speed for each road ID.

    Expected columns:
    road_id, speed_kmh
    """
    required = {"road_id", "speed_kmh"}

    if not required.issubset(gps_data.columns):
        raise ValueError(f"Required columns: {required}")

    valid = gps_data[
        gps_data["speed_kmh"].between(1, 130)
    ].copy()

    return (
        valid.groupby("road_id", as_index=False)
        ["speed_kmh"]
        .mean()
        .rename(columns={"speed_kmh": "estimated_speed_kmh"})
    )


def calculate_travel_time(distance_km, speed_kmh):
    """Calculate travel time in minutes."""
    if speed_kmh <= 0:
        raise ValueError("Speed must be greater than zero.")

    return (distance_km / speed_kmh) * 60


if __name__ == "__main__":
    # SIMULATED observations for testing only
    sample = pd.DataFrame({
        "road_id": ["R1", "R1", "R1", "R2", "R2"],
        "speed_kmh": [24, 18, 21, 30, 25]
    })

    print("SIMULATED GPS observations")
    print(estimate_road_speeds(sample))
    print("Travel time for 1.2 km at 24 km/h:",
          calculate_travel_time(1.2, 24), "minutes")