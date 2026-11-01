from pathlib import Path

import pandas as pd
import osmnx as ox

from src.road_network import download_road_network
from src.data_loader import load_datasets

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)


def main():
    vehicles, deliveries, _, fuel_prices = load_datasets()

    print("Downloading OSM road network...")
    G = download_road_network()

    # Use OSM speed attributes where available and a clearly
    # labelled fallback estimate where speed data is missing.
    ox.routing.add_edge_speeds(G, fallback=25)
    ox.routing.add_edge_travel_times(G)

    edges = ox.convert.graph_to_gdfs(
        G, nodes=False, fill_edge_geometry=False
    ).reset_index()

    roads = pd.DataFrame({
        "road_id": (
            edges["u"].astype(str) + "_" +
            edges["v"].astype(str) + "_" +
            edges["key"].astype(str)
        ),
        "from_node": edges["u"],
        "to_node": edges["v"],
        "edge_key": edges["key"],
        "distance_km": edges["length"] / 1000,
        "speed_kmh": edges["speed_kph"],
        "travel_time_min": edges["travel_time"] / 60,
        "speed_source": "OSM speed or estimated fallback"
    })

    roads.to_csv(OUT / "road_costs.csv", index=False)
    deliveries.to_csv(OUT / "delivery_inputs.csv", index=False)
    vehicles.to_csv(OUT / "vehicle_inputs.csv", index=False)

    # Calculate an estimated fuel cost for each road-vehicle pair.
    costs = roads.merge(vehicles, how="cross")
    costs = costs.merge(fuel_prices, on="fuel_type", how="left")

    if costs["price_per_litre"].isna().any():
        raise ValueError("A vehicle fuel type has no matching fuel price.")

    costs["estimated_fuel_litres"] = (
        costs["distance_km"] / costs["base_kmpl"]
    )
    costs["estimated_fuel_cost"] = (
        costs["estimated_fuel_litres"] * costs["price_per_litre"]
    )

    costs.to_csv(OUT / "road_vehicle_costs.csv", index=False)

    print("\nDataset generation successful!")
    print("Road segments:", len(roads))
    print("Vehicles:", len(vehicles))
    print("Deliveries:", len(deliveries))
    print("Road-vehicle rows:", len(costs))
    print("Output folder:", OUT)
    print("Created: road_costs.csv")
    print("Created: road_vehicle_costs.csv")
    print("Created: delivery_inputs.csv")
    print("Created: vehicle_inputs.csv")


if __name__ == "__main__":
    main()
