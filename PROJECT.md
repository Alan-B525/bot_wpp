# Project: WhatsApp Bot Hidrométrico Restructuring & Enhancement

## Architecture
The system processes hydrometric monitoring reports received via WhatsApp and provides an interactive web dashboard for monitoring water levels and station communications:
1. **WhatsApp Ingestion & Pipeline**: `bot/client.py` receives messages/media via `bot/whatsapp_monitor.py`, passes them to `bot/measurement_agent.py` for NLP/heuristic extraction and operator-station inference, and saves raw chat messages and structured hydrometric measurements into `bot/measurement_store.py`.
2. **Database Layer**: SQLite database (`data/mediciones.db`) structured with normalized relational tables:
   - `estaciones`: master catalog of hydrological monitoring stations with geographic coordinates.
   - `operadores`: registered operators/senders with phone number, display name, and optional fixed station assignment.
   - `operador_estaciones`: historical operator reporting metrics and station dominance ratios used for inference.
   - `mensajes_chat`: raw inbound/outbound chat messages with timestamp, sender, and text.
   - `adjuntos_multimedia`: media files (photos, rules) linked to chat messages and sender.
   - `mediciones`: normalized measurements (level, trend, station, timestamp) with foreign keys to station, operator, chat message, and media attachment.
3. **Web Dashboard & Chat Viewer**: `dashboard_app.py` built on standard library HTTP server, rendering:
   - Interactive station catalog and Leaflet.js map with station status indicators.
   - WhatsApp Web Dark style modal/panel displaying full chronological conversation, photos, senders, timestamps, and hydrometric tags per station.
   - Clean UI without top summary KPIs.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Normalized Database Schema | 5 core relational tables (`estaciones`, `operadores`, `operador_estaciones`, `mensajes_chat`, `adjuntos_multimedia`, `mediciones`) with backward-compatible legacy views | M1 | Survey / R1 |
| 2 | Zero-Loss Data Migration | Preserves 402/402 mediciones, 534/534 chat messages, and 272/272 photo attachments from existing `data/mediciones.db` | M1 | Survey / R1 |
| 3 | Station Catalog Sanitization & Seeding | Remove 8 spurious station names (e.g. 'Estacionado', 'Regla Foto'), add missing high-volume stations (Coratei, PZA) and geographic coordinates | M1 | Survey / R1 |
| 4 | Real-time Live Chat Ingestion | Ensure `bot/client.py` saves live incoming WhatsApp messages to `mensajes_chat` via `store.save_chat_message` | M2 | Survey / R1 |
| 5 | Heuristic Extraction Hardening | Add 'estacionado' to trend regex; fix prefix/suffix word extraction boundary in `MeasurementAgent.fallback_parse`; fix string similarity subset bug in `compute_string_similarity` | M2 | Survey / R1 |
| 6 | Operator-Station Inference Engine | Consistency matrix (>=3 explicit reports, >=85% dominance) for auto-assigning single-station operators; strictly preserve unassigned for multi-station/unknown operators | M2 | Survey / R2 |
| 7 | Photo-Message Bi-Directional Association | Link photos to chat messages and measurements by sender phone and timestamp window (+/- 15 min), exposing `GET /api/estaciones/<id_or_name>/chat` | M3 | Survey / R3 |
| 8 | WhatsApp-Style Chat Viewer | Authentic WhatsApp Web Dark modal with date divider badges, sender colors, bubble tails, inline photo thumbnails with lightbox, hydro level badges, and station switcher | M3 | Survey / R3 |
| 9 | Dashboard Simplification (KPI Removal) | Completely eliminate top summary metric cards (`.kpi-grid`, `actualizarKPIs`) from dashboard layout | M4 | Survey / R4 |
| 10 | Interactive Map Catalog | Embed Leaflet.js dark map displaying station markers with coordinates and click-to-chat interaction | M4 | Survey / R3, R4 |
| 11 | Automated Verification Test Suite | Automated test suite validating migration, classification, operator inference matrix, photo-message link, chat API, and UI KPI removal | M5 | Survey / Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Database Schema & Zero-Loss Migration | `bot/measurement_store.py`, `scripts/migrate_database.py`, `data/mediciones.db` | none | DONE |
| M2 | Pipeline Hardening & Operator Inference | `bot/client.py`, `bot/measurement_agent.py`, `bot/measurement_store.py` | M1 | DONE |
| M3 | Photo Association & WhatsApp Chat Viewer | `dashboard_app.py`, `bot/measurement_store.py` | M1 | DONE |
| M4 | Dashboard Cleanup & Map Catalog | `dashboard_app.py` | M3 | DONE |
| M5 | Final Acceptance & Adversarial Hardening | `tests/test_e2e_verification.py`, full suite regression | M1, M2, M3, M4 | DONE |

## Interface Contracts
### Database Layer (`bot/measurement_store.py`)
- `get_or_create_operator(telefono, nombre)` -> `int` (operator_id)
- `infer_operator_station(operador_id_or_phone)` -> `Optional[int]` (station_id if consistent, None if multi-station/unknown)
- `save_chat_message(remitente_telefono, remitente_nombre, timestamp_str, texto, archivo_adjunto)` -> `int` (mensaje_id)
- `associate_photo_to_message(remitente_telefono, timestamp_str, foto_path)` -> `int` (adjunto_id)
- `get_station_chat_history(estacion_id_or_name, limit=100)` -> `Dict[str, Any]` (station metadata + chronological message array with photos and hydro badges)

### Extraction & Inference Layer (`bot/measurement_agent.py`)
- `MeasurementAgent.parse_message(texto, remitente_telefono=None, remitente_nombre=None)` -> `Dict[str, Any]` (incluye `estacion`, `nivel`, `tendencia`, `inferred_station`)

### Dashboard API (`dashboard_app.py`)
- `GET /api/estaciones`: returns array of stations including `latitud`, `longitud`, `total_mediciones`, `ultimo_nivel`, `ultima_tendencia`.
- `GET /api/estaciones/<id_or_name>/chat`: returns `{ "estacion": {...}, "mensajes": [...] }` with sender, timestamp, text, photo thumbnail path, level, trend.

## Code Layout
- `bot/`: Core logic modules
  - `client.py`: WhatsApp event listener and routing
  - `measurement_agent.py`: Message parsing, regex, Gemini fallback, inference invocation
  - `measurement_store.py`: SQLite schema, migration, CRUD operations, inference queries
  - `whatsapp_monitor.py`: Local WhatsApp Web browser automator / session monitor
- `data/`: SQLite databases and media attachments
  - `mediciones.db`: SQLite production database
  - `fotos/`: Physical photo repository (JPEG files)
- `scripts/`: Operational and migration scripts
  - `migrate_database.py`: Executable database migration and validation script
- `tests/`: Automated unit and integration test suite
  - `test_measurement_store.py`
  - `test_measurement_agent.py`
  - `test_dashboard_app.py`
  - `test_e2e_verification.py`
- `dashboard_app.py`: Web interface, Leaflet map, WhatsApp chat viewer modal
