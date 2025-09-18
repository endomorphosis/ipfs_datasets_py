#!/usr/bin/env python3
"""
Stable runner for the Caselaw Access Project GraphRAG dashboard.

- Disables Flask reloader by running with debug=False
- Accepts host/port and optional CASELAW_CACHE_DIR override
- Optionally skips initialization for faster restarts
"""

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Caselaw GraphRAG Dashboard (stable)")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    parser.add_argument("--max-samples", type=int, default=100, help="Max cases to initialize (default: 100)")
    parser.add_argument("--cache-dir", default=None, help="Override CASELAW_CACHE_DIR")
    parser.add_argument("--no-init", action="store_true", help="Skip dataset initialization on start")
    parser.add_argument("--pid-file", default=None, help="Write server PID to this file")

    args = parser.parse_args()

    # Ensure workspace path is importable
    workspace_root = Path(__file__).resolve().parents[1]
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

    if args.cache_dir:
        os.environ["CASELaw_CACHE_DIR"] = args.cache_dir  # tolerate legacy casing
        os.environ["CASELAW_CACHE_DIR"] = args.cache_dir

    from ipfs_datasets_py.caselaw_dashboard import create_caselaw_dashboard
    import traceback

    dash = create_caselaw_dashboard(debug=False)

    if not args.no_init:
        try:
            print(f"Initializing dataset (max-samples={args.max_samples})...", flush=True)
            init = dash.initialize_data(max_samples=args.max_samples)
            status = init.get("status")
            print(f"Initialization status: {status}", flush=True)
            if status != "success":
                print(f"Initialization warning: {init}", flush=True)
        except Exception:
            print("Initialization failed with exception:", flush=True)
            traceback.print_exc()
            # continue to try serving anyway

    if args.pid_file:
        try:
            with open(args.pid_file, "w") as f:
                f.write(str(os.getpid()))
        except Exception:
            print(f"Warning: failed to write PID file at {args.pid_file}", flush=True)

    print(f"Starting Caselaw Dashboard on http://{args.host}:{args.port} (no-reloader)", flush=True)
    try:
        dash.run(host=args.host, port=args.port, initialize_data=False)
    except Exception:
        print("Server exited with exception:", flush=True)
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
