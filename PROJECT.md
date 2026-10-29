# Project: WhatsApp Bot Hidrométrico Restructuring & Enhancement — Phase 2 (Audit Console, AI Immutability & Ingestion Fortification)

## Architecture
The hydrometric monitoring system processes river level reports received via WhatsApp, extracts structured water level data, and provides an interactive web dashboard with an audit console:
1. **Database & Storage Layer (`bot/measurement_store.py`, `scripts/migrate_database.py`)**:
   - Normalized relational tables in SQLite (`estaciones`, `operadores`, `operador_estaciones`, `mensajes_chat`, `adjuntos_multimedia`, `mediciones`).
   - Decoupled schema separating original immutable AI extractions (`ia_estacion_detectada`, `ia_valor_metros`, `ia_tendencia`, `ia_confianza`, `observaciones_ia`) from official audited fields (`estacion_id`, `valor_metros`, `valor_cm`, `tendencia_rio`, `estado_revision`, `actualizado_en`).
   - Protection against spurious station creation via `allow_create=False` and strict fuzzy matching (threshold 0.78) against active stations.
   - Comprehensive audit operations (`update_measurement` with operator pinning, soft delete to `'DESCARTADO'`, and `create_manual_measurement_from_message`).
2. **AI & Ingestion Layer (`bot/measurement_agent.py`, `bot/client.py`)**:
   - Real-time WhatsApp event listener in `bot/client.py` using a thread-safe Producer-Consumer queue (`queue.Queue`) with a dedicated daemon worker thread.
   - Strict causal order: save chat message -> save attachment -> enqueue task with explicit `mensaje_id` and `adjunto_id` -> worker calls Gemini -> persist measurement with foreign keys.
   - Deterministic extraction in `bot/measurement_agent.py` using Pydantic schema (`MeasurementExtraction`) and `response_schema` in `types.GenerateContentConfig` with modern models `gemini-2.5-flash` and `gemini-2.5-flash-lite`.
3. **Audit Console & Dashboard Layer (`dashboard_app.py`)**:
   - Standard library HTTP server exposing REST API:
     * `PUT /api/mediciones/<id>`: full official audit and operator pinning.
     * `POST /api/mediciones/manual`: manual measurement tagging from historic message.
     * `DELETE /api/mediciones/<id>`: soft-delete setting `estado_revision = 'DESCARTADO'`.
     * `GET /api/mediciones`: filtering by `estado_revision` ('PENDIENTE', 'VALIDADO', 'CORREGIDO', 'DESCARTADO', 'TODOS').
     * `do_OPTIONS`: CORS preflight handling.
   - Split-View Audit Console (`#modal-foto`):
     * Left Column: Interactive photo viewer with zoom (0.5x–4.0x) and rotation (-90°/+90°) + chronological WhatsApp timeline highlighting the origin message and 1-click photo re-linking.
     * Right Column: Real-time visual comparison "Detectado por IA" (read-only) vs "Datos Oficiales" (editable form with catalog selector, level in meters and cm, trend, timestamp, status, operator pinning checkbox, "Guardar y Validar", and "Descartar falso positivo").
   - Station chat modal (`#modal-whatsapp-chat`): interactive button `+ Etiquetar Medición` on untagged bubbles.
4. **Verification & Testing Suite (`tests/`)**:
   - Comprehensive unit and integration test suites:
     * `tests/test_measurement_store.py`, `tests/test_m1_*.py`
     * `tests/test_measurement_agent.py`
     * `tests/test_dashboard_app.py`
     * `tests/test_e2e_verification.py`

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | AI Immutability & Human Editing Schema | Separate `ia_*` columns from official audited fields (`estacion_id`, `valor_metros`, `valor_cm`, `tendencia_rio`, `estado_revision`, `actualizado_en`) in `mediciones` | M1 | R1 |
| 2 | Idempotent Zero-Loss Migration | Migration script updating database safely, reconciling photo count discrepancies (290 vs 288) and passing repeated migrations | M1 | R1 |
| 3 | Spurious Station Prevention (`allow_create=False`) | `get_or_create_station` defaults to `allow_create=False`; unmatched stations return `None` and store `estacion_id = NULL`, `estado_revision = 'PENDIENTE'` without polluting catalog | M1 | R1 |
| 4 | Full Measurement Audit in Store | `update_measurement` audits station, levels, trend, timestamp, status, attachment, and operator pinning, strictly preserving `ia_*` fields | M1 | R1 |
| 5 | Manual Measurement Creation from Message | `create_manual_measurement_from_message` creates measurement linked to existing `mensaje_id`, operator, and photo with status 'VALIDADO'/'CORREGIDO' | M1 | R1 |
| 6 | Absolute OS Path Decoupling | Replace hardcoded absolute paths with dynamic environment variable / relative fallback in `measurement_store.py` | M1 | R1 |
| 7 | Supported Gemini 2.5 Models | Replace deprecated model names with `gemini-2.5-flash` (default) and `gemini-2.5-flash-lite` (fallback) in `bot/measurement_agent.py` | M2 | R2 |
| 8 | Deterministic Pydantic Extraction | Define `MeasurementExtraction` Pydantic model and configure `types.GenerateContentConfig(response_schema=...)`, eliminating fragile markdown regex | M2 | R2 |
| 9 | Producer-Consumer Ingestion Queue | Replace unmanaged `threading.Thread` with thread-safe `queue.Queue` and dedicated worker thread in `bot/client.py` | M2 | R2 |
| 10 | Strict Ingestion Causal Order | Pipeline order: `save_chat_message` -> `save_photo` & `associate_photo_to_message` -> enqueue -> worker -> `save_measurement(..., mensaje_id, adjunto_id)` | M2 | R2 |
| 11 | REST Endpoints for Audit | Implement `PUT /api/mediciones/<id>`, `POST /api/mediciones/manual`, `DELETE /api/mediciones/<id>` (soft-delete), and `do_OPTIONS` | M3 | R3 |
| 12 | Status Filtering in `GET /api/mediciones` | Support query parameter `estado_revision` ('PENDIENTE', 'VALIDADO', 'CORREGIDO', 'DESCARTADO', 'TODOS') | M3 | R3 |
| 13 | Split-View Photo Viewer with Zoom & Rotation | Left column of `#modal-foto`: photo viewport with CSS transform zoom (0.5x–4.0x) and rotation (-90°/+90°) controls | M3 | R3 |
| 14 | Timeline & 1-Click Photo Re-linking | Left column of `#modal-foto`: chronological WhatsApp chat thread highlighting origin message and enabling photo re-linking by clicking attachments | M3 | R3 |
| 15 | Real-Time Comparison Card & Audit Form | Right column of `#modal-foto`: side-by-side "Detectado por IA" vs "Datos Oficiales" with full editing form, operator pinning, and discard button | M3 | R3 |
| 16 | Manual Tagging Button in Station Chat | `#modal-whatsapp-chat` displays interactive `+ Etiquetar Medición` button on untagged bubbles routing to manual creation | M3 | R3 |
| 17 | Automated Verification & Regression Suite | Full suite regression and 4-tier E2E testing validating all requirements without mocks on clean database clones | M4 | R4 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Data & Storage: AI Immutability & Human Editing | `bot/measurement_store.py`, `scripts/migrate_database.py` | none | DONE |
| M2 | IA & Ingesta: Deterministic Gemini 2.5 & Queue | `bot/measurement_agent.py`, `bot/client.py` | M1 | DONE |
| M3 | Backend & Split-View Audit Console | `dashboard_app.py`, `tests/test_dashboard_app.py` | M1 | DONE |
| M4 | Final E2E Verification & Adversarial Hardening | `tests/test_e2e_verification.py`, full suite regression | M1, M2, M3 | DONE |

## Interface Contracts
### Database Layer (`bot/measurement_store.py`)
- `get_or_create_station(name: str, river: Optional[str] = None, allow_create: bool = False) -> Optional[int]`
- `update_measurement(measurement_id: int, station_id: Optional[int] = None, valor_metros: Optional[float] = None, tendencia_rio: Optional[str] = None, timestamp_medicion: Optional[str] = None, estado_revision: Optional[str] = None, adjunto_id: Optional[int] = None, foto_path: Optional[str] = None, fijar_operador: bool = False) -> bool`
- `create_manual_measurement_from_message(mensaje_id: int, station_id: int, valor_metros: float, tendencia_rio: Optional[str] = None, timestamp_medicion: Optional[str] = None, estado_revision: str = 'VALIDADO') -> int`
- `query_measurements(..., estado_revision: Optional[str] = None) -> List[Dict[str, Any]]`

### IA & Ingesta Layer (`bot/measurement_agent.py`, `bot/client.py`)
- `MeasurementExtraction(pydantic.BaseModel)`: fields `es_medicion_valida`, `estacion`, `rio`, `valor_original`, `valor_metros`, `valor_cm`, `unidad_detectada`, `tendencia`, `origen`, `confianza`, `lectura_regla_foto`.
- `MeasurementAgent.parse_message(..., explicit_model=None)` -> `Dict[str, Any]` including `ia_*` fields.
- `WhatsAppForwarderBot.ingestion_queue`: thread-safe `queue.Queue` accepting tuples `(mensaje_id, adjunto_id, full_text, image_bytes, foto_path, timestamp_str, sender_name, sender_number)`.

### Dashboard REST API (`dashboard_app.py`)
- `PUT /api/mediciones/<id>`: JSON payload `{ "estacion_id": int, "valor_metros": float, "tendencia_rio": str, "timestamp_medicion": str, "estado_revision": str, "adjunto_id": Optional[int], "foto_path": Optional[str], "fijar_operador": bool }` -> 200 `{ "success": True, "message": str }`.
- `POST /api/mediciones/manual`: JSON payload `{ "mensaje_id": int, "estacion_id": int, "valor_metros": float, "tendencia_rio": str, "timestamp_medicion": Optional[str], "estado_revision": Optional[str] }` -> 200 `{ "success": True, "medicion_id": int }`.
- `DELETE /api/mediciones/<id>` -> 200 `{ "success": True, "message": "Medición descartada (soft delete)" }`.
- `GET /api/mediciones?estado_revision=<PENDIENTE|VALIDADO|CORREGIDO|DESCARTADO|TODOS>` -> 200 `[ {...}, ... ]`.

## Code Layout
- `bot/`: Core backend and bot logic
  - `client.py`: WhatsApp event listener, producer-consumer queue, sequential worker
  - `measurement_agent.py`: Pydantic structured extraction, Gemini 2.5 flash/lite, fallback regex
  - `measurement_store.py`: SQLite normalized schema, AI immutability, audit operations, station catalog
- `data/`: SQLite databases and media
  - `mediciones.db`: SQLite production database
  - `fotos/`: Physical photo repository (JPEG files)
- `scripts/`: Operational and migration scripts
  - `migrate_database.py`: Executable database migration and idempotency validation script
- `dashboard_app.py`: Web interface, REST API endpoints, Split-View audit modal, station chat modal
- `tests/`: Automated unit and integration test suite
  - `test_measurement_store.py`: Unit tests for store schema and operations
  - `test_m1_*.py`: Migration idempotency and stress tests
  - `test_measurement_agent.py`: Agent extraction and fallback tests
  - `test_dashboard_app.py`: REST API and UI structure tests
  - `test_e2e_verification.py`: End-to-end acceptance and regression tests
