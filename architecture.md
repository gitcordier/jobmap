# JobMap — Architecture & Flow Reference

---

## 1. Module Import Graph — all dependencies

Three tiers: project modules, third-party packages, stdlib groups.
Dashed edge = lazy import inside a function body.

```mermaid
graph TD

    subgraph SCRIPTS["scripts/"]
        SERVE["serve.py"]
        FETCH["fetch_jobs.py"]
    end

    subgraph SRV["src/server/"]
        HANDLER["handler.py"]
        ROUTER["router.py"]
    end

    subgraph PIPE["src/pipeline/"]
        INGEST["ingest.py"]
    end

    subgraph EXP["src/export/"]
        GEOJSON["geojson.py"]
    end

    subgraph API["src/api/"]
        ADZUNA["adzuna.py"]
    end

    subgraph GEO["src/geo/"]
        GEOCODER["geocoder.py"]
    end

    subgraph DB["src/db/"]
        MODELS["models.py"]
        SESSION["session.py"]
    end

    subgraph CFG["config/"]
        SETTINGS["settings.py"]
    end

    subgraph TP["Third-party"]
        REQUESTS["requests + urllib3"]
        GEOPY["geopy"]
        SQLALCHEMY["sqlalchemy"]
        DOTENV["python-dotenv"]
    end

    subgraph SL["stdlib"]
        SL_NET["http.server"]
        SL_THR["threading"]
        SL_DT["datetime"]
        SL_IO["pathlib + os"]
        SL_JSON["json"]
        SL_CLI["argparse + sys"]
        SL_TIME["time"]
        SL_LOG["logging + typing + dataclasses"]
    end

    %% ── scripts ──────────────────────────────────────────────
    SERVE --> SETTINGS
    SERVE --> SESSION
    SERVE --> HANDLER
    SERVE --> SL_NET
    SERVE --> SL_CLI
    SERVE --> SL_IO
    SERVE --> SL_LOG

    FETCH --> SETTINGS
    FETCH --> INGEST
    FETCH --> SL_CLI
    FETCH --> SL_JSON
    FETCH --> SL_IO
    FETCH --> SL_LOG

    %% ── server ────────────────────────────────────────────────
    HANDLER --> SETTINGS
    HANDLER --> GEOJSON
    HANDLER --> ROUTER
    HANDLER -.->|lazy in trigger_fetch| INGEST
    HANDLER --> SL_NET
    HANDLER --> SL_THR
    HANDLER --> SL_JSON
    HANDLER --> SL_IO
    HANDLER --> SL_LOG

    ROUTER --> SL_LOG

    %% ── pipeline ──────────────────────────────────────────────
    INGEST --> SETTINGS
    INGEST --> ADZUNA
    INGEST --> MODELS
    INGEST --> SESSION
    INGEST --> GEOCODER
    INGEST --> SQLALCHEMY
    INGEST --> SL_JSON
    INGEST --> SL_IO
    INGEST --> SL_LOG

    %% ── export ────────────────────────────────────────────────
    GEOJSON --> MODELS
    GEOJSON --> SESSION
    GEOJSON --> SQLALCHEMY
    GEOJSON --> SL_LOG

    %% ── api ───────────────────────────────────────────────────
    ADZUNA --> SETTINGS
    ADZUNA --> REQUESTS
    ADZUNA --> SL_LOG

    %% ── geo ───────────────────────────────────────────────────
    GEOCODER --> SETTINGS
    GEOCODER --> MODELS
    GEOCODER --> SESSION
    GEOCODER --> GEOPY
    GEOCODER --> SL_TIME
    GEOCODER --> SL_LOG

    %% ── db ────────────────────────────────────────────────────
    SESSION --> SETTINGS
    SESSION --> MODELS
    SESSION --> SQLALCHEMY
    SESSION --> SL_LOG

    MODELS --> SQLALCHEMY
    MODELS --> SL_DT
    MODELS --> SL_LOG

    %% ── config ────────────────────────────────────────────────
    SETTINGS --> DOTENV
    SETTINGS --> SL_IO
    SETTINGS --> SL_LOG

    %% ── colour coding ─────────────────────────────────────────
    classDef project  fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    classDef thirdpty fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef stdlib   fill:#f1f5f9,stroke:#94a3b8,color:#334155

    class SERVE,FETCH,HANDLER,ROUTER,INGEST,GEOJSON,ADZUNA,GEOCODER,MODELS,SESSION,SETTINGS project
    class REQUESTS,GEOPY,SQLALCHEMY,DOTENV thirdpty
    class SL_NET,SL_THR,SL_DT,SL_IO,SL_JSON,SL_CLI,SL_TIME,SL_LOG stdlib
```

---

## 2. Request / Response Map (all HTTP routes)

```mermaid
graph LR
    Browser -->|GET /| HANDLER
    Browser -->|GET /api/params| HANDLER
    Browser -->|POST /api/params| HANDLER
    Browser -->|POST /api/fetch| HANDLER
    Browser -->|GET /api/jobs| HANDLER

    HANDLER -->|read file| HTML["templates/map.html"]
    HANDLER -->|read file| PARAMS["config/params.json"]
    HANDLER -->|write file| PARAMS
    HANDLER -->|run pipeline| INGEST["ingest.run()"]
    HANDLER -->|query DB| GEOJSON["jobs_as_geojson()"]

    INGEST -->|HTTP GET| ADZUNA_API["Adzuna REST API"]
    INGEST -->|HTTP GET| NOMINATIM["Nominatim\n(OpenStreetMap)"]
    INGEST -->|read/write| DB["data/jobmap.db\nSQLite"]

    GEOJSON -->|read| DB
    HTML -->|tiles| OSM["OSM Tile CDN\ntile.openstreetmap.org"]
```

---

## 3. Search and Fetch Timeline (single button press)

Three sequential phases triggered by a single button press.

![Job Map Sequence Diagram](./timeline.png)

```mermaid
graph TD

    subgraph P1["Phase 1 — POST /api/params"]
        A1["Browser
collects form values"]
        A2["POST /api/params
sent to JobMapHandler"]
        A3["Router dispatches
to update_params"]
        A4["Read existing
params.json"]
        A5["Write merged
params.json"]
        A6["200 ok
returned to browser"]
        A1-->A2-->A3-->A4-->A5-->A6
    end

    subgraph P2["Phase 2 — POST /api/fetch"]
        B1["POST /api/fetch
sent to JobMapHandler"]
        B2["Router dispatches
to trigger_fetch"]
        B3["Acquire
pipeline lock"]
        B4["Lazy import
ingest.run called"]
        B5["init_db
migrations applied"]
        B6["load_params
reads params.json"]

        subgraph B_LOOP["Paginate pages 1 to max_pages"]
            C1["AdzunaClient.search
called with params"]
            C2["HTTP GET
Adzuna REST API page N"]
            C3["Deserialise results
to RawJob list"]
            C4{"Empty page?"}
            C5["Accumulate
RawJob list"]
            C1-->C2-->C3-->C4
            C4-->|no|C5-->C1
        end

        subgraph B_GEO["Geocode unique locations"]
            D1["cache lookup
GeoCache by key"]
            D2{"Row found?"}
            D3{"lat is null?"}
            D4["Return
lat lon"]
            D5["Return
None — known failure"]
            D6["sleep 1 second
Nominatim rate limit"]
            D7["HTTP geocode
Nominatim"]
            D8["Write result
to GeoCache"]
            D1-->D2
            D2-->|yes|D3
            D2-->|no|D6-->D7-->D8-->D4
            D3-->|no|D4
            D3-->|yes|D5
        end

        B7["SELECT MAX search_run
from SQLite"]
        B8["session.merge each Job
search_run = N plus 1"]
        B9["session.commit"]
        B10["Release
pipeline lock"]
        B11["200 ok with
fetch summary"]

        B1-->B2-->B3-->B4-->B5-->B6
        B6-->B_LOOP
        B_LOOP-->|page empty or max reached|B_GEO
        B_GEO-->B7-->B8-->B9-->B10-->B11
    end

    subgraph P3["Phase 3 — GET /api/jobs"]
        E1["GET /api/jobs
sent to JobMapHandler"]
        E2["Router dispatches
to get_jobs"]
        E3["SELECT MAX search_run"]
        E4["SELECT jobs for
latest run with coords"]
        E5["Convert rows
to GeoJSON features"]
        E6["200 GeoJSON
no-store returned"]
        E7["Clear existing
map markers"]
        E8["Add new markers
to cluster group"]
        E9["Fit map
to new bounds"]
        E1-->E2-->E3-->E4-->E5-->E6-->E7-->E8-->E9
    end

    A6 --> B1
    B11 --> E1

    style P1 fill:#dbeafe,stroke:#3b82f6
    style P2 fill:#dcfce7,stroke:#16a34a
    style P3 fill:#fef9c3,stroke:#ca8a04
```
---

## 4. Geocoding Cache Logic

```mermaid
flowchart TD
    A["resolve(location)"] --> B["normalise: strip + lowercase"]
    B --> C{"SELECT geo_cache\nWHERE location = key"}
    C -->|row found, lat IS NOT NULL| D["return (lat, lon) ✓"]
    C -->|row found, lat IS NULL| E["return None\n(known failure — skip)"]
    C -->|no row| F["sleep ≥ 1.1 s"]
    F --> G["Nominatim HTTP GET"]
    G -->|result found| H["INSERT geo_cache (lat, lon)"]
    G -->|no result / timeout| I["INSERT geo_cache (NULL, NULL)"]
    H --> D
    I --> E
```

---

## 5. search_run Isolation Mechanism

```mermaid
graph LR
    S1["Search 1\nLondon · Python\nJobs A B C D\nsearch_run = 1"]
    S2["Search 2\nParis · Data Eng\nJobs E F G\nsearch_run = 2"]
    S3["Search 3\nBerlin · DevOps\nJobs H I J K\nsearch_run = 3"]
    GET["GET /api/jobs\nWHERE search_run = MAX\nreturns H I J K only"]

    S1 -->|next search overwrites| S2
    S2 -->|next search overwrites| S3
    S3 -->|read latest run| GET

    style S1 fill:#e2e8f0,stroke:#94a3b8
    style S2 fill:#e2e8f0,stroke:#94a3b8
    style S3 fill:#dbeafe,stroke:#3b82f6
    style GET fill:#dcfce7,stroke:#16a34a
```

---

## 6. Persistence Layer Schema

```mermaid
erDiagram
    JOB {
        string   id              PK
        string   title
        string   company
        string   location_raw
        float    latitude
        float    longitude
        string   description
        float    salary_min
        float    salary_max
        string   contract_type
        string   category
        string   redirect_url
        string   created_at
        string   fetched_at
        int      search_run
    }

    GEO_CACHE {
        string   location        PK
        float    latitude
        float    longitude
        string   resolved_at
    }

    JOB }o--o| GEO_CACHE : "location_raw resolves via"
```

---

## 7. Server Dispatch Chain

```mermaid
flowchart LR
    TCP["TCP socket\n:8080"] --> THS["ThreadingHTTPServer\none thread / request"]
    THS --> DG["do_GET\ndo_POST\ndo_OPTIONS"]
    DG --> RD["Router.dispatch()\nlookup method+path\nin dict"]
    RD -->|matched| FN["route handler fn\nupdate_params()\nget_jobs()\ntrigger_fetch() …"]
    RD -->|no match| E404["_send_error 404"]
    FN --> JSON["_send_json()\nCache-Control: no-store"]
    FN --> HTML["_send_html()"]
```

---

## 8. File Layout vs Responsibility

```
jobmap/
│
├── .env                     ← secrets (never committed)
├── .env.example             ← template
├── requirements.txt
│
├── config/
│   ├── settings.py          ← single typed facade over os.environ
│   └── params.json          ← mutable search state (R/W at runtime)
│
├── src/
│   ├── api/
│   │   └── adzuna.py        ← HTTP adapter: Adzuna → [RawJob]
│   │                           retry, pagination, deserialisation
│   ├── geo/
│   │   └── geocoder.py      ← location string → (lat, lon)
│   │                           Nominatim + SQLite cache
│   ├── db/
│   │   ├── models.py        ← ORM: Job, GeoCache
│   │   └── session.py       ← engine, SessionFactory, init_db + migrations
│   ├── pipeline/
│   │   └── ingest.py        ← orchestrator: params → fetch → geocode → persist
│   ├── export/
│   │   └── geojson.py       ← DB → RFC 7946 GeoJSON (latest run only)
│   └── server/
│       ├── router.py        ← decorator route registry
│       └── handler.py       ← BaseHTTPRequestHandler + all route bodies
│
├── templates/
│   └── map.html             ← self-contained SPA
│                               Leaflet + MarkerCluster + search widgets
│                               pure fetch() API calls, no framework
│
└── scripts/
    ├── serve.py             ← CLI: ThreadingHTTPServer entry point
    ├── fetch_jobs.py        ← CLI: headless pipeline (no server needed)
    └── debug_params.py      ← diagnostic: POST→GET round-trip diff
```
