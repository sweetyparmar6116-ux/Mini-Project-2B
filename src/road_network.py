import osmnx as ox
import networkx as nx


def download_road_network():
    """Download a small drivable road network around Andheri Station."""

    graph = ox.graph_from_point(
        (19.1197, 72.8464),
        dist=3000,
        network_type="drive",
        simplify=True
    )

    return graph


def get_shortest_route(graph, start_node, end_node):
    """Find the shortest-distance route."""

    return nx.shortest_path(
        graph,
        source=start_node,
        target=end_node,
        weight="length"
    )


if __name__ == "__main__":
    try:
        print("Downloading the Andheri road network...")
        G = download_road_network()

        print("Road network downloaded successfully!")
        print("Nodes:", len(G.nodes))
        print("Road segments:", len(G.edges))

    except Exception as error:
        print("Could not download the road network.")
        print("Error:", error)