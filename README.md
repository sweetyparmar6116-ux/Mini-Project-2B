# Mini-Project-2B
# Condition-Aware Integrated Vehicle Route Optimization System

A condition-aware route optimization system for urban logistics that combines accident-risk prediction, fuel-consumption estimation, mathematical optimization, and dynamic rerouting to identify cost-effective routes for a single delivery vehicle.

## 📌 Project Overview

Traditional route-planning systems often focus on finding the shortest or fastest route. However, the shortest route may not always be the most economical or suitable for a delivery vehicle.

This project proposes a **Condition-Aware Integrated Vehicle Route Optimization System** that considers multiple factors when planning a delivery trip:

- Travel time
- Fuel consumption and fuel cost
- Predicted accident risk
- Road-network characteristics
- Traffic and weather conditions
- Vehicle characteristics
- Delivery-stop sequence
- Dynamic road incidents and route deviations

The system initially generates an optimized multi-stop delivery route. During the journey, GPS monitoring tracks the vehicle's position and speed. If an accident, road closure, significant delay, or route deviation is detected, the system can calculate an alternative path. If the disruption changes the best order of the remaining delivery stops, the optimization model can be solved again.

The system is designed for a selected urban study area in Mumbai, Maharashtra, India.

## 🎯 Objectives

1. Develop a road network using OpenStreetMap (OSM).
2. Estimate road-level travel speed and travel time.
3. Estimate vehicle fuel consumption and fuel cost.
4. Predict road-segment accident risk using Random Forest.
5. Combine time, fuel cost, and accident-risk exposure into a composite route cost.
6. Construct a stop-to-stop cost matrix using Dijkstra's algorithm.
7. Optimize the order of delivery stops using Mixed Integer Linear Programming (MILP).
8. Use an exact optimization solver to establish optimality when possible.
9. Monitor the vehicle using GPS position and speed.
10. Use A* search for rapid path-level rerouting after disruptions.
11. Re-optimize the remaining delivery plan when necessary.

## 🏗️ System Architecture

```text
User Inputs
    |
    v
Vehicle and Delivery Details
    |
    v
OSM Road Network + Supporting Datasets
    |
    v
Data Preprocessing
    |
    +--------------------------+
    |                          |
    v                          v
Random Forest             Road Information
Accident-Risk             and Traffic Profile
Prediction                     |
    |                          |
    +------------+-------------+
                 |
                 v
       Speed and Fuel Model
                 |
                 v
      Time + Fuel + Risk Cost
                 |
                 v
       Dijkstra Cost Matrix
                 |
                 v
       MILP Route Optimization
                 |
                 v
       Exact MILP Solver
        (Branch & Bound /
         Branch & Cut)
                 |
                 v
         Initial Route
                 |
                 v
          GPS Monitoring
                 |
                 v
      Incident/Deviation Detection
                 |
          +------+------+
          |             |
       No issue       Issue detected
          |             |
          v             v
    Continue trip   Update road graph
                        |
                        v
                    A* Rerouting
                        |
                        v
                Is stop order affected?
                    /         \
                  No           Yes
                  |             |
                  v             v
                A* path     Rebuild costs
                accepted        |
                                v
                            Solve MILP
                                |
                                v
                       Updated delivery route
```

## ⚙️ Technologies and Algorithms

| Component | Purpose |
|---|---|
| Python | Main implementation language, if used in the final codebase |
| OpenStreetMap (OSM) | Road-network data |
| Random Forest | Accident-risk prediction |
| Fuel-consumption model | Estimate fuel usage and fuel cost |
| Dijkstra's algorithm | Construct the stop-to-stop cost matrix |
| MILP | Optimize the sequence of delivery stops |
| CBC or HiGHS | Candidate open-source MILP solvers |
| Branch & Bound / Branch & Cut | Exact optimization methods used internally by the solver |
| A* search | Dynamic path-level rerouting |
| GPS | Monitor vehicle position and observed speed |
| Recorded or simulated GPS traces | Demonstrate vehicle movement |
| Simulated traffic profile | Represent time-dependent traffic conditions in the demonstration |

The final implementation should document the actual libraries and solver selected by the team.

## 🧠 Algorithms Explained

### 1. Random Forest — Accident-Risk Prediction

Random Forest is a supervised machine-learning algorithm used to estimate the relative accident risk associated with a road segment and its conditions.

**Possible input features include:**

- Road classification
- Speed limit
- Road length
- Number of lanes, when available
- Junction characteristics, when available
- Historical accident information
- Weather conditions
- Time of day
- Day of the week
- Traffic factor
- Road-condition features, when available

**Output:** A predicted risk score for each road segment under the supplied conditions.

The predicted score becomes an input to the route-cost model.

Random Forest does not select the route, guarantee safety, or predict the exact occurrence of an individual accident. Its performance depends on the quality, relevance, and representativeness of its training data.

### 2. Fuel and Travel-Time Model

Before the trip, actual vehicle speed is unavailable. The system estimates speed using the road speed limit, vehicle speed limits, and the traffic factor.

A simplified speed-estimation formula is:

\[
v_e=\max\left(v_{\min},
\min(v_{\text{limit}},v_{\text{vehicle}})\times k_{\text{traffic}}\right)
\]

Where:

- \(v_e\) = estimated road speed
- \(v_{\text{limit}}\) = road speed limit
- \(v_{\text{vehicle}}\) = vehicle's maximum allowed speed
- \(k_{\text{traffic}}\) = traffic adjustment factor
- \(v_{\min}\) = minimum speed used to avoid division by zero

If a speed limit is missing from OSM, a documented default based on road class may be used.

Estimated travel time is:

\[
t_e=\frac{d_e}{v_e}
\]

where distance and speed must use compatible units.

The project uses a speed-dependent fuel-consumption model:

\[
f(v)=a+\frac{b}{v}+cv^2
\]

Estimated fuel consumption for a road segment is:

\[
F_e=d_e f(v_e)k_{\text{load}}k_{\text{road}}k_{\text{age}}
\]

Here, \(k_{\text{age}}\) is an optional vehicle-age or condition adjustment. It should be included only if implemented in the final version.

Fuel cost is:

\[
C_e=F_e\times P_{\text{fuel}}
\]

Where \(P_{\text{fuel}}\) is the price per litre.

The fuel coefficients and adjustment factors must be documented and calibrated against suitable vehicle data where possible. If assumed values are used, they must be identified as simulation parameters rather than measured real-world fuel performance.

### 3. Composite Edge Cost

The system combines travel time, fuel cost, and accident-risk exposure into one normalized cost.

\[
r_e=p_e d_e
\]

Where:

- \(p_e\) = predicted accident-risk score
- \(d_e\) = road-segment distance
- \(r_e\) = risk exposure

The composite edge cost is:

\[
w_e=
w_1\frac{t_e}{T_0}
+w_2\frac{C_e}{C_0}
+w_3\frac{r_e}{R_0}
\]

Subject to:

\[
w_1+w_2+w_3=1
\]

The default preference weights are:

- Travel time: \(w_1=0.4\)
- Fuel cost: \(w_2=0.3\)
- Accident-risk exposure: \(w_3=0.3\)

The reference values \(T_0\), \(C_0\), and \(R_0\) normalize the different quantities.

These weights represent configurable preferences, not experimentally proven universal optimal values.

### 4. Dijkstra's Algorithm — Cost Matrix Construction

Dijkstra's algorithm calculates minimum composite-cost paths through the road graph.

Instead of directly giving the entire road network to the delivery-sequencing model, the system calculates the cost between important locations, such as:

- Depot
- Customer A
- Customer B
- Customer C
- Final destination

The resulting matrix contains the minimum composite cost between each relevant pair of stops. Corresponding travel-time, fuel-cost, risk, and road-path information can also be retained.

Dijkstra is used for this preprocessing stage because it can calculate minimum costs from one source to multiple destinations when edge weights are non-negative.

### 5. MILP — Multi-Stop Route Optimization

The delivery problem is formulated as a single-vehicle, multi-stop routing problem with a fixed starting depot and final destination.

The decision variable is:

\[
x_{ij}\in\{0,1\}
\]

where \(x_{ij}=1\) means the vehicle travels from stop \(i\) to stop \(j\) in the selected stop sequence.

The objective is:

\[
\min \sum_{i,j} W_{ij}x_{ij}
\]

Where \(W_{ij}\) is the composite cost between stops \(i\) and \(j\).

The model enforces the applicable constraints:

- Start at the specified depot.
- End at the specified destination.
- Visit every required intermediate stop.
- Enter and leave each intermediate stop according to the routing formulation.
- Prevent disconnected subtours.
- Respect the maximum route-duration constraint, when enabled.

The final model uses a subtour-elimination formulation such as Miller–Tucker–Zemlin (MTZ).

Because the current design uses one vehicle, multi-vehicle routing and capacity allocation are not part of the implemented optimization. Vehicle capacity can be checked before solving the routing problem.

### 6. Branch & Bound / Branch & Cut

MILP is the mathematical formulation. Branch & Bound and Branch & Cut are exact optimization techniques that the selected solver may use internally.

They systematically explore candidate integer solutions and eliminate parts of the search space that cannot improve the current solution.

The team does not need to implement these techniques separately when using a solver that already supports them.

An optimality claim is justified only when the solver reports an optimal solution for the defined mathematical instance. A zero reported optimality gap, together with optimal solver status, is the appropriate evidence for that claim.

### 7. GPS Monitoring

During the trip, GPS supplies observations such as:

- Latitude and longitude
- Timestamp
- Observed speed, when available
- Heading, when available

The system associates the vehicle's position with the road network and compares its progress with the planned route.

GPS is used for monitoring and disruption detection. It is not a substitute for OSM road data or a source of historical accident information.

For a demonstration, GPS input may be recorded, replayed, or simulated. The chosen method must be disclosed.

### 8. A* — Dynamic Rerouting

When an incident occurs, the road graph is updated to reflect the changed conditions.

For example:

- A closed road is removed from the usable graph.
- A blocked road is marked unavailable.
- A delayed or risky road may receive a higher cost.

A* then searches for a minimum-cost path from the vehicle's current location to its next required stop.

The heuristic must be appropriate for the edge-cost definition and must not overestimate the remaining cost if optimal pathfinding is required.

A* handles path-level rerouting. It does not independently optimize the order of every remaining delivery stop.

If a disruption changes the best stop sequence, the system can rebuild the relevant cost matrix and solve the remaining MILP again.

## 📊 Data Sources

The project distinguishes real datasets from simulated demonstration inputs.

| Data | Purpose | Status |
|---|---|---|
| OpenStreetMap | Road geometry, road classes, and available speed limits | Real open data |
| Historical accident dataset | Train and evaluate the risk-prediction model | Real dataset; exact source must be documented |
| Weather data | Represent environmental conditions | Real data where collected from a documented source |
| Traffic profile | Adjust expected road speeds | Simulated in the current demonstration design |
| Vehicle information | Type, fuel, capacity, weight, and condition | User-provided or configured inputs |
| GPS trace | Monitor vehicle position and speed | Recorded or simulated/replayed |
| Delivery stops | Define the routing problem | Demo locations unless real locations are supplied |
| Incident scenarios | Test road closures and rerouting | Simulated or injected for testing |
| Fuel-model coefficients | Estimate fuel consumption | Assumed unless calibrated against real measurements |

### Data preparation

The preprocessing stage should:

1. Remove invalid or duplicate records.
2. Standardize units and column names.
3. Handle missing values.
4. Match accident records to road segments where possible.
5. Encode categorical features.
6. Check class imbalance in accident data.
7. Separate training and testing data to avoid leakage.
8. Store road-edge attributes in a consistent format.
9. Validate that every required stop can be mapped to the road graph.

**Important:** The exact accident dataset, weather provider, download URLs, and data licences should be added after the team confirms the sources actually used. No dataset should be described as integrated merely because it is proposed in the design.

## 🚚 Example Vehicle Configuration

A sample vehicle configuration is:

| Parameter | Example |
|---|---|
| Vehicle type | Truck |
| Fuel type | Diesel |
| Vehicle capacity | 5,000 kg |
| Vehicle weight | 3,000 kg |
| Vehicle size | Large |
| Fuel price | Configurable |
| Vehicle age | Optional, if implemented |
| Maximum route duration | Configurable |

These are example inputs, not calibrated measurements.

If the vehicle is carrying deliveries, the total delivery load must satisfy:

\[
\text{Delivery load}\leq\text{Vehicle capacity}
\]

The implementation must define clearly whether the vehicle-weight field represents empty vehicle weight or gross vehicle weight, so the capacity check is applied consistently.

## 🔄 End-to-End Workflow

1. The user enters vehicle details, the depot, delivery stops, the final destination, and optimization preferences.
2. The system loads the selected OSM road network.
3. Road and environmental data are cleaned and transformed into graph attributes.
4. Random Forest predicts accident-risk scores for relevant road segments.
5. Estimated speed and travel time are calculated for each road segment.
6. Fuel consumption and fuel cost are estimated.
7. Time, fuel cost, and risk exposure are combined into a normalized edge cost.
8. Dijkstra's algorithm constructs the stop-to-stop cost matrix.
9. MILP selects the best feasible order of delivery stops.
10. The exact solver returns a route and solver-status information.
11. The stored road-level paths are combined into the initial route.
12. GPS monitoring tracks vehicle movement during execution.
13. When a disruption is detected, the graph is updated and A* calculates an alternative path.
14. If the stop order is no longer suitable, the remaining optimization problem is solved again.
15. The system presents the updated route and its calculated metrics.

## 📁 Suggested Repository Structure

Adapt this structure to the actual files in the repository.

```text
condition-aware-route-optimization/
│
├── README.md
├── requirements.txt
├── .gitignore
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── README.md
│
├── models/
│   └── README.md
│
├── src/
│   ├── data_preprocessing.py
│   ├── road_network.py
│   ├── accident_prediction.py
│   ├── speed_estimation.py
│   ├── fuel_model.py
│   ├── edge_cost.py
│   ├── dijkstra_matrix.py
│   ├── milp_optimizer.py
│   ├── gps_monitoring.py
│   ├── astar_rerouting.py
│   └── main.py
│
├── tests/
│   ├── test_fuel_model.py
│   ├── test_dijkstra.py
│   ├── test_milp.py
│   └── test_rerouting.py
│
└── docs/
    ├── system_architecture.md
    └── methodology.md
```

This is a suggested organization. Keep only the files that exist or are planned for the actual implementation.

## 💻 Installation

The following instructions assume the project is implemented in Python. Adjust the dependencies to match the actual code.

### Prerequisites

- Python 3.10 or another version supported by the selected dependencies
- Git
- An internet connection for downloading permitted open datasets
- A compatible MILP solver, either installed separately or supplied through a Python package

### Step 1: Clone the repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd condition-aware-route-optimization
```

Replace the placeholder with your repository's actual URL.

### Step 2: Create a virtual environment

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install dependencies

If the repository contains `requirements.txt`:

```bash
pip install -r requirements.txt
```

The final dependency list may include packages for:

- Road-network processing
- Graph algorithms
- Data manipulation
- Machine learning
- MILP optimization
- GPS/data visualization

The exact packages depend on the implementation. Do not install or document an assumed dependency until the code requires it.

### Step 4: Prepare the datasets

Follow the instructions in `data/README.md`.

Download or prepare the required road, accident, and weather data. Store raw and processed datasets separately.

Do not commit large datasets, restricted data, private GPS traces, or files whose licences prohibit redistribution.

### Step 5: Run the application

If the project uses the proposed entry point:

```bash
python src/main.py
```

The actual command should be updated to match the application's real entry point and configuration requirements.

## 🧪 Testing and Evaluation

The system should be tested component by component before being evaluated end to end.

### 1. Accident-risk prediction

Evaluate the Random Forest model using suitable classification metrics:

- Precision
- Recall
- F1-score
- ROC-AUC, where appropriate
- Confusion matrix

If accident data is imbalanced, accuracy alone is insufficient.

### 2. Fuel estimation

Test fuel calculations using known inputs and verify:

- Distance units
- Speed units
- Fuel-consumption units
- Load and road adjustment factors
- Fuel price conversion

Compare predictions with measured fuel data if available. Otherwise, describe the outputs as model estimates.

### 3. Route optimization

Test whether the MILP solution:

- Starts at the correct depot
- Visits every required stop
- Ends at the specified destination
- Avoids invalid subtours
- Respects applicable constraints
- Minimizes the defined objective

For small test cases, compare the solver's solution with an independently verified optimum where practical.

### 4. Dynamic rerouting

Inject an incident on the current route and verify that:

- The blocked road is not selected.
- A* finds a feasible alternative when one exists.
- The updated path connects the current position to the required next stop.
- MILP is rerun when the remaining stop order needs to change.

### 5. Baseline comparison

Compare the proposed system against appropriate baselines, such as:

- Shortest-distance routing
- Shortest-time routing
- Routing without accident-risk cost
- Routing without fuel cost
- Routing with and without dynamic rerouting

Report actual measurements from the implemented tests rather than assumed performance improvements.

## 📈 Evaluation Metrics

| Metric | Purpose |
|---|---|
| Total distance | Measures the length of the selected route |
| Estimated travel time | Measures predicted journey duration |
| Estimated fuel consumption | Measures predicted fuel use |
| Estimated fuel cost | Measures predicted monetary fuel cost |
| Composite route cost | Measures the defined time-fuel-risk objective |
| Predicted risk exposure | Measures accumulated model-based risk exposure |
| Solver runtime | Measures optimization time |
| Optimality gap | Measures the solver's remaining optimality uncertainty |
| Rerouting time | Measures how quickly an alternative path is calculated |
| Constraint violations | Checks whether the solution respects the model |

All comparisons must use consistent inputs and objective definitions.

## 🔐 Optimality and Limitations

The project uses exact MILP optimization to obtain a provably optimal solution when the solver successfully proves optimality.

A zero optimality gap and an optimal solver status support the claim that the returned solution is globally optimal **for the specified mathematical model, data, and objective**.

This does not mean the route is guaranteed to be globally best under every real-world condition.

The following limitations apply:

1. The initial traffic profile is simulated rather than a verified live traffic feed.
2. GPS monitoring requires recorded, replayed, simulated, or actual GPS observations.
3. Fuel-model coefficients may be assumptions unless calibrated with vehicle-specific data.
4. Accident-risk predictions depend on the available dataset and model quality.
5. A predicted accident-risk score is not a guarantee of safety.
6. Missing or inaccurate OSM attributes can affect speed and route estimates.
7. Dynamic rerouting is only as reliable as the updated road conditions supplied to it.
8. Exact optimization can become computationally expensive as the problem grows.
9. A* provides path-level rerouting, not an automatic proof of optimality for the entire multi-stop delivery plan.
10. A previously optimal route may cease to be optimal when the underlying conditions change.

## 🚀 Future Enhancements

Potential extensions include:

- Integration with a verified live traffic provider.
- Live incident and road-closure feeds.
- More accurate vehicle-specific fuel calibration.
- Vehicle-age and maintenance-condition modelling.
- Improved time-dependent speed estimation.
- Multiple-vehicle routing.
- Vehicle capacity allocation within the optimization model.
- Customer delivery time windows.
- Live GPS device integration.
- Additional optimization baselines and larger benchmark instances.
- A web-based dashboard for route visualization and monitoring.

These are future enhancements, not claims about existing functionality.

## 👥 Project Team

**Project:** Condition-Aware Integrated Vehicle Route Optimization System

**Domain:** Urban Logistics, Machine Learning, Graph Algorithms, and Operations Research

**Study Area:** Mumbai, Maharashtra, India

**Team Members:** Add the names of all four project members here.

**Academic Project:** Mini Project — Third Year

## 📚 References and Data Acknowledgements

- **OpenStreetMap:** Road-network data. https://www.openstreetmap.org/
- **OpenStreetMap Copyright and Licence:** https://www.openstreetmap.org/copyright
- **Random Forest:** Breiman, L. (2001). Random Forests. *Machine Learning*, 45, 5–32. https://doi.org/10.1023/A:1010933404324
- **Dijkstra's Algorithm:** Dijkstra, E. W. (1959). A Note on Two Problems in Connexion with Graphs. *Numerische Mathematik*, 1, 269–271.
- **A* Search:** Hart, P. E., Nilsson, N. J., and Raphael, B. (1968). A Formal Basis for the Heuristic Determination of Minimum Cost Paths. *IEEE Transactions on Systems Science and Cybernetics*, 4(2), 100–107.
- **MILP and Solver Documentation:** Add the documentation for the actual solver used, such as CBC or HiGHS.
- **Accident and Weather Datasets:** Add the exact dataset titles, publishers, access links, and licences used in the implementation.

## 📄 Licence

Choose a licence appropriate for your project and the datasets used. If no licence has been selected, leave the repository's licensing status unspecified until the team decides.

---

**Summary:** This project integrates Random Forest accident-risk prediction, fuel and travel-time estimation, Dijkstra-based cost-matrix construction, MILP-based multi-stop route optimization, GPS monitoring, and A* dynamic rerouting into a single condition-aware urban logistics workflow.
