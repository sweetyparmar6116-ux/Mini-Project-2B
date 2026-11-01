from pathlib import Path
import pandas as pd

# Project root is the parent of the src folder
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"


def load_datasets():
    """Load and validate the project's four CSV datasets."""

    vehicles = pd.read_csv(DATA_DIR / "vehicles.csv")
    deliveries = pd.read_csv(DATA_DIR / "deliveries.csv")
    gps = pd.read_csv(DATA_DIR / "gps_observations.csv")
    fuel_prices = pd.read_csv(DATA_DIR / "fuel_prices.csv")

    required_columns = {
        "vehicles": (vehicles, {
            "vehicle_id", "capacity_kg", "fuel_type", "base_kmpl"
        }),
        "deliveries": (deliveries, {
            "delivery_id", "latitude", "longitude", "demand_kg"
        }),
        "gps_observations": (gps, {
            "vehicle_id", "timestamp", "latitude",
            "longitude", "speed_kmh"
        }),
        "fuel_prices": (fuel_prices, {
            "fuel_type", "price_per_litre"
        }),
    }

    for name, (df, required) in required_columns.items():
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{name}.csv is missing columns: {missing}")

    if (vehicles["capacity_kg"] <= 0).any():
        raise ValueError("Vehicle capacity must be positive.")

    if (vehicles["base_kmpl"] <= 0).any():
        raise ValueError("Vehicle mileage must be positive.")

    if (deliveries["demand_kg"] < 0).any():
        raise ValueError("Delivery demand cannot be negative.")

    if not gps["speed_kmh"].between(0, 130).all():
        raise ValueError("GPS speeds must be between 0 and 130 km/h.")

    if (fuel_prices["price_per_litre"] <= 0).any():
        raise ValueError("Fuel prices must be positive.")

    return vehicles, deliveries, gps, fuel_prices


if __name__ == "__main__":
    vehicles, deliveries, gps, fuel_prices = load_datasets()

    print("All four datasets loaded and validated!")
    print("Vehicles:", len(vehicles))
    print("Deliveries:", len(deliveries))
    print("GPS observations:", len(gps))
    print("Fuel price records:", len(fuel_prices))
