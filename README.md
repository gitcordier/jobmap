# JobMap

Interactive job-listing visualiser backed by the **Adzuna Jobs API**, with geocoding via **Nominatim** (OpenStreetMap), persistence in **SQLite** (SQLAlchemy 2), and a live Leaflet map served by a pure-stdlib Python HTTP server.

---

## Architecture

```
jobmap/
├── config/
│   ├── settings.py          # Typed env-var facade (single source of truth)
│   └── params.json          # Live search parameters (R/W at runtime)
│
├── src/
│   ├── api/
│   │   └── adzuna.py        # Adzuna REST client (retry, pagination, typing)
│   ├── geo/
│   │   └── geocoder.py      # Nominatim geocoder with SQLite cache
│   ├── db/
│   │   ├── models.py        # SQLAlchemy ORM: Job, GeoCache
│   │   └── session.py       # Engine, SessionFactory, init_db()
│   ├── pipeline/
│   │   └── ingest.py        # End-to-end orchestrator (fetch → geocode → persist)
│   ├── export/
│   │   └── geojson.py       # DB → RFC 7946 GeoJSON serialiser
│   └── server/
│       ├── router.py        # Decorator-based HTTP router
│       └── handler.py       # BaseHTTPRequestHandler + route definitions
│
├── templates/
│   └── map.html             # Self-contained Leaflet SPA
│
└── scripts/
    ├── fetch_jobs.py        # CLI: run the ingestion pipeline
    └── serve.py             # CLI: start the development server
```

### Data flow

```
params.json
    │
    ▼
AdzunaClient.search()   ←──── Adzuna REST API
    │
    ▼
CachingGeocoder.resolve_many()  ←── Nominatim / GeoCache (SQLite)
    │
    ▼
Session.merge(Job)  ──────────────── SQLite (via SQLAlchemy)
    │
    ▼
jobs_as_geojson()  ───────────────── /api/jobs  ──── Leaflet map
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python ≥ 3.11 | Uses `match`, `tomllib`, PEP 695 generics |
| Adzuna API credentials | Free at [developer.adzuna.com](https://developer.adzuna.com) |
| Internet access | Adzuna API + Nominatim + OSM tile CDN |

---

## Setup

```bash
# 1. Clone / unpack the project
cd jobmap

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
cp .env.example .env
$EDITOR .env                     # Set ADZUNA_APP_ID and ADZUNA_APP_KEY
```

---

## Usage

### Option A — Interactive map (recommended)

Start the server, then open the browser:

```bash
python scripts/serve.py
# → http://127.0.0.1:8080/
```

Use the sidebar widgets to set your search criteria and press **Search & Fetch**.  
The application will:
1. Write your parameters to `config/params.json`.
2. Call the Adzuna API and geocode all results.
3. Persist the enriched jobs to `data/jobmap.db`.
4. Render the markers on the map.

### Option B — Headless ingestion

Run the pipeline from the command line (useful for scheduled jobs):

```bash
# Edit params manually first
$EDITOR config/params.json

# Run the pipeline
python scripts/fetch_jobs.py --verbose

# Then start the server to view results
python scripts/serve.py
```

---

## Configuration reference

### Environment variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `ADZUNA_APP_ID` | **required** | Adzuna application ID |
| `ADZUNA_APP_KEY` | **required** | Adzuna application secret |
| `ADZUNA_COUNTRY` | `gb` | ISO 3166-1 alpha-2 country code |
| `ADZUNA_RESULTS_PER_PAGE` | `50` | Results per API page (max 50) |
| `ADZUNA_MAX_PAGES` | `5` | Page fetch ceiling |
| `GEOCODER_USER_AGENT` | `jobmap/1.0` | Nominatim User-Agent |
| `GEOCODER_DELAY` | `1.1` | Inter-request delay (s) — Nominatim ToS |
| `DATABASE_URL` | `sqlite:///data/jobmap.db` | SQLAlchemy connection URL |
| `SERVER_HOST` | `127.0.0.1` | Server bind address |
| `SERVER_PORT` | `8080` | Server bind port |

### `config/params.json` fields

All fields mirror the [Adzuna Search API](https://developer.adzuna.com/docs/search) parameters:

| Field | Type | Description |
|---|---|---|
| `what` | string | Keywords / job title |
| `where` | string | Location (city, postcode, …) |
| `distance` | integer | Search radius (km) |
| `salary_min` | integer \| null | Minimum annual salary |
| `salary_max` | integer \| null | Maximum annual salary |
| `contract_type` | string \| null | `permanent` \| `contract` \| `part_time` \| `full_time` |
| `category` | string \| null | Adzuna category tag (e.g. `it-jobs`) |
| `sort_by` | string | `relevance` \| `date` \| `salary` |
| `max_pages` | integer | Pages to consume (overrides env var) |

---

## API endpoints

| Path | Method | Body | Description |
|---|---|---|---|
| `/` | GET | — | Serve `map.html` |
| `/api/params` | GET | — | Return current `params.json` |
| `/api/params` | POST | JSON | Overwrite `params.json` |
| `/api/jobs` | GET | — | GeoJSON FeatureCollection of geocoded jobs |
| `/api/fetch` | POST | — | Run ingestion pipeline; returns summary |

---

## Notes

- **Nominatim rate limiting** — The geocoder enforces a ≥ 1.1 s inter-request delay and caches results in `data/jobmap.db` to comply with [Nominatim's usage policy](https://operations.osmfoundation.org/policies/nominatim/).  Do not reduce `GEOCODER_DELAY` below 1.0.
- **Concurrent safety** — The HTTP server uses `ThreadingHTTPServer`; SQLAlchemy sessions are scoped per-call. Simultaneous fetch requests are serialised via a module-level lock.
- **Production use** — This server is designed for local development. For production, place behind a reverse proxy (nginx / caddy) with authentication.
