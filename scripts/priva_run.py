"""
Priva live ingestion worker — run as a standalone long-running process.

Streams the building's temperature sensors over SignalR and writes one
TelemetryReading per variable every PRIVA_FLUSH_MINUTES (15 by default), on a
fixed grid. Auto-reconnects; refresh the BFF cookie in .env when it 401s.

This is the same routine the FastAPI lifespan runs, but force-enabled so it can
run as a dedicated worker (e.g. its own container / systemd unit) decoupled from
the API. Requires the building file to have a valid comfortosBuildingId pointing
at an existing ComfortOS building.

Usage (from backend/):
  python -m scripts.priva_run
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.priva_ingestion import start_priva_ingestion  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

if __name__ == "__main__":
    try:
        asyncio.run(start_priva_ingestion(force=True))
    except KeyboardInterrupt:
        pass
