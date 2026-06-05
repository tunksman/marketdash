#!/usr/bin/env python3
"""
Dev server entrypoint.
Usage: python scripts/serve.py [--host HOST] [--port PORT]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run(
        "marketdash.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        app_dir=str(Path(__file__).parent.parent / "src"),
    )
