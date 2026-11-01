# Intelligent Route Optimizer – MVP (Phase 1)

## 1. Backend setup
```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate      Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
```

## 2. STEP 1 – download Mumbai graph, plot it, run Dijkstra
```bash
python step1_explore.py
```
First run downloads the road network (needs internet) and caches it as `mumbai.graphml`.

## 3. Start the API (all 4 factors + scoring)
```bash
uvicorn main:app --reload
# test: http://localhost:8000/docs
```

## 4. Frontend
```bash
npm create vite@latest frontend -- --template react
cd frontend
npm install leaflet react-leaflet
# replace frontend/src/App.jsx with frontend-src/App.jsx
npm run dev      # open http://localhost:5173
```
(If react-leaflet complains about React version, use `npm install react-leaflet@4 leaflet`
 with React 18.)

## Where to change things later
- Weights: `PREFERENCES` in engine.py
- Cost: `COST_PER_KM` (₹8) in engine.py
- Fake traffic / risk data: `traffic_of()` / `risk_of()` – swap for real CSV/API
- Area: `BBOX` in engine.py (delete mumbai.graphml after changing)
