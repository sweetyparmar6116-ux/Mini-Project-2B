"""STEP 1: download Mumbai graph, visualise it, run Dijkstra Andheri -> Bandra."""
import networkx as nx
import osmnx as ox

from engine import load_graph

G = load_graph()
print(f"Nodes: {len(G.nodes)}  Edges: {len(G.edges)}")
ox.plot_graph(G, node_size=0, edge_linewidth=0.4)          # visualise network

src = ox.geocode("Andheri Station, Mumbai, India")          # (lat, lon)
dst = ox.geocode("Bandra Station, Mumbai, India")
s = ox.distance.nearest_nodes(G, X=src[1], Y=src[0])
t = ox.distance.nearest_nodes(G, X=dst[1], Y=dst[0])

path = nx.shortest_path(G, s, t, weight="length")           # Dijkstra
length = nx.shortest_path_length(G, s, t, weight="length")
print(f"Shortest route: {length / 1000:.2f} km, {len(path)} nodes")
ox.plot_graph_route(G, path, route_linewidth=4, node_size=0)
