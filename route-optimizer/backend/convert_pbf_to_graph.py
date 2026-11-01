
from pathlib import Path

import networkx as nx
from pyrosm import OSM

BASE_DIR = Path(__file__).resolve().parent
PBF_FILE = BASE_DIR / "planet_72.616,18.877_73.123,19.233.osm.pbf"
OUTPUT_FILE = BASE_DIR / "mumbai_metro.graphml"


def main():
    if not PBF_FILE.exists():
        raise FileNotFoundError(f"Map file not found: {PBF_FILE}")

    print("Reading Mumbai road data...")
    osm = OSM(str(PBF_FILE))
    roads = osm.get_network(network_type="driving")

    if roads.empty:
        raise RuntimeError("No drivable roads were found.")

    graph = nx.MultiDiGraph()
    graph.graph["crs"] = "EPSG:4326"

    print(f"Processing {len(roads):,} road segments...")

    for _, road in roads.iterrows():
        geometry = road.geometry
        if geometry is None or geometry.is_empty:
            continue

        coordinates = list(geometry.coords)
        if len(coordinates) < 2:
            continue

        # Preserve road direction and connect every adjacent point.
        points = []
        for lon, lat, *rest in coordinates:
            node = (round(float(lon), 7), round(float(lat), 7))
            points.append(node)

            if node not in graph:
                graph.add_node(node, x=node[0], y=node[1])

        length = float(road.get("length", 0) or 0)
        if length <= 0:
            continue

        highway = str(road.get("highway", "unclassified"))
        oneway = str(road.get("oneway", "")).lower()
        reverse_oneway = oneway in {"-1", "reverse"}

        directed_points = list(reversed(points)) if reverse_oneway else points
        segment_lengths = []

        for a, b in zip(directed_points, directed_points[1:]):
            from math import hypot

            # Approximate segment length from coordinates, adjusted for latitude.
            lat_mid = (a[1] + b[1]) / 2
            dx = (b[0] - a[0]) * 111320 * __import__("math").cos(
                __import__("math").radians(lat_mid)
            )
            dy = (b[1] - a[1]) * 110540
            segment_lengths.append(hypot(dx, dy))

        total = sum(segment_lengths)
        if total <= 0:
            continue

        speed_text = str(road.get("maxspeed", "") or "")
        digits = "".join(ch if ch.isdigit() else " " for ch in speed_text)
        try:
            speed_kmh = float(digits.split()[0]) if digits.strip() else 30.0
        except (ValueError, IndexError):
            speed_kmh = 30.0

        for (a, b), seg_len in zip(
            zip(directed_points, directed_points[1:]), segment_lengths
        ):
            if seg_len <= 0:
                continue

            edge_data = {
                "length": float(seg_len),
                "highway": highway,
                "maxspeed": speed_kmh,
                "name": str(road.get("name", "") or ""),
            }

            graph.add_edge(a, b, **edge_data)

            # Two-way roads can be travelled in both directions.
            if oneway not in {"yes", "true", "1", "-1", "reverse"}:
                graph.add_edge(b, a, **edge_data)

    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise RuntimeError("The road graph is empty; output was not saved.")

    print(f"Graph nodes: {graph.number_of_nodes():,}")
    print(f"Directed road edges: {graph.number_of_edges():,}")
    print(f"Saving graph to {OUTPUT_FILE}...")

    nx.write_graphml(graph, OUTPUT_FILE)

    print("Conversion complete!")
    print(f"Created: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
