# E2E Test Infra: WhatsApp Bot Hidrométrico

## Test Philosophy
- Opaque-box, requirement-driven derived directly from `ORIGINAL_REQUEST.md`.
- Systematic testing across 4 tiers: Feature Coverage (Tier 1), Boundary & Corner Cases (Tier 2), Cross-Feature Interaction (Tier 3), and Real-World Hydrometric Workloads (Tier 4).
- Independent verification without depending on internal implementation details.

## Feature Inventory & Test Mapping
| # | Feature | Source | Tier 1 (Feature) | Tier 2 (Boundary) | Tier 3 (Cross) |
|---|---------|--------|:----------------:|:-----------------:|:--------------:|
| 1 | DB Schema & Migration Integrity | ORIGINAL_REQUEST §R1 | 5 cases | 5 cases | ✓ |
| 2 | Station Catalog & Spurious Prevention | ORIGINAL_REQUEST §R1 | 5 cases | 5 cases | ✓ |
| 3 | Operator Ingestion & History | ORIGINAL_REQUEST §R1 | 5 cases | 5 cases | ✓ |
| 4 | Operator-Station Inference (Consistent) | ORIGINAL_REQUEST §R2 | 5 cases | 5 cases | ✓ |
| 5 | Operator-Station Protection (Multi/Unknown)| ORIGINAL_REQUEST §R2 | 5 cases | 5 cases | ✓ |
| 6 | Photo-Message Bi-directional Association | ORIGINAL_REQUEST §R3 | 5 cases | 5 cases | ✓ |
| 7 | WhatsApp Chat History API | ORIGINAL_REQUEST §R3 | 5 cases | 5 cases | ✓ |
| 8 | WhatsApp Chat Viewer UI Rendering | ORIGINAL_REQUEST §R3 | 5 cases | 5 cases | ✓ |
| 9 | Dashboard Top KPI Removal | ORIGINAL_REQUEST §R4 | 5 cases | 5 cases | ✓ |
| 10 | Interactive Map Catalog & Navigation | ORIGINAL_REQUEST §R3, R4 | 5 cases | 5 cases | ✓ |

## Test Architecture
- Test Runner: `.\venv\Scripts\python.exe -m unittest discover tests` or `pytest tests`
- Test Files:
  - `tests/test_measurement_store.py`: Unit and schema tests
  - `tests/test_measurement_agent.py`: Parser, regex, similarity, and inference tests
  - `tests/test_dashboard_app.py`: HTTP endpoints, chat API, HTML rendering, KPI absence
  - `tests/test_e2e_verification.py`: Complete requirement-driven acceptance suite verifying:
    1. Zero-loss migration and normalized queries
    2. Explicit and inferred operator-station classification
    3. Biunivocal photo-message linkage
    4. WhatsApp chat endpoint response structure
    5. Clean dashboard layout without summary KPI cards

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Expected Outcome |
|---|----------|--------------------|------------------|
| 1 | Historical Migration Simulation | F1, F2, F3, F6 | All 402 mediciones, 534 chats, and 272 photos intact; 0 data lost |
| 2 | Single-Station Operator Daily Report | F4, F6, F7 | Fabio Marin sends "3,45 creciendo" without station name -> assigned to Ayolas |
| 3 | Multi-Station Guard Report Without Station | F5, F7 | Patrol guard sends "3,45" without station -> remains unassigned; not guessed blindly |
| 4 | Photo Sent 3 Minutes After Measurement | F6, F7, F8 | Photo associated to measurement/chat by window; visible in station chat modal |
| 5 | Operator Switching Stations Explicitly | F4, F5, F7 | Operator with history in Coratei explicitly reports Panchito López -> assigned to Panchito López |
| 6 | Full Dashboard Navigation & Chat View | F8, F9, F10 | User opens station on map/catalog, views WhatsApp dark chat, confirms absence of top KPIs |

## Coverage Thresholds
- Tier 1: >= 5 test cases per feature
- Tier 2: >= 5 boundary/corner cases per feature
- Tier 3: Pairwise interaction across DB, Inference, Photos, and UI
- Tier 4: >= 6 realistic real-world hydrometric workflows
- Passing criteria: 100% passing tests with zero regressions.
