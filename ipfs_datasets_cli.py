#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPFS Datasets CLI Tool

A lightweight command line interface that provides convenient access to the MCP tools
with minimal imports. Only loads what's needed when needed.
"""

import sys
import os
import subprocess
import json
from pathlib import Path


def show_help():
    """Show CLI help without importing anything heavy."""
    help_text = """
ipfs-datasets-cli - IPFS Datasets CLI Tool

Usage:
    ipfs-datasets [command] [subcommand] [options]
    ipfs-datasets --help
    ipfs-datasets --version

Commands:
    info         System information
      status     Show system status
      version    Show version information
            defaults   Show resolved host/port/gateway defaults
    save-defaults  Persist host/port/gateway to config
      
    mcp          MCP server management  
      start      Start MCP server
      stop       Stop MCP server
      status     Show MCP server status
            logs       Tail MCP dashboard logs
      
    tools        Tool management
      categories List available tool categories
      list       List tools in a category
      execute    Execute a specific tool
      
    dataset      Dataset operations
      load       Load a dataset
      convert    Convert dataset format
      
        ipfs         IPFS operations
            pin        Pin data to IPFS
            get        Get data from IPFS (supports --gateway)
      
    vector       Vector operations
      create     Create vector embeddings
      search     Search vectors

Options:
    --help, -h   Show this help message
    --version    Show version information
    --json       Output in JSON format
    --verbose    Verbose output
    --config     Path to CLI config JSON (overrides default)
    --host, -H   Override dashboard host
    --port, -p   Override dashboard port
    --gateway, -g  Override IPFS HTTP gateway (ipfs get)
    
Environment:
    IPFS_DATASETS_HOST  Default dashboard host (e.g., 127.0.0.1)
    IPFS_DATASETS_PORT  Default dashboard port (e.g., 8899)
    IPFS_DATASETS_CLI_CONFIG  Path to CLI config JSON
    IPFS_HTTP_GATEWAY   Default IPFS gateway (e.g., https://ipfs.io)
    IPFS_DATASETS_IPFS_GATEWAY  Alternate env var for gateway

Config:
        ~/.ipfs_datasets/cli.json  Optional defaults for host/port, e.g.:
            {"host": "127.0.0.1", "port": "8899", "gateway": "https://ipfs.io"}
        Precedence: flags > env > config file > hardcoded defaults

Examples:
    ipfs-datasets info status
    ipfs-datasets info defaults --json
    ipfs-datasets ipfs get QmHash --gateway https://ipfs.io --out /tmp/file
    ipfs-datasets mcp start
    ipfs-datasets tools categories
    ipfs-datasets dataset load ./data.json
    
For detailed help on a specific command:
    ipfs-datasets [command] --help
"""
    print(help_text.strip())


def show_version():
    """Show version without importing anything heavy."""
    print("ipfs-datasets CLI v1.0.0")


def show_status():
    """Show basic system status without heavy imports."""
    print("System Status: CLI tool is available")
    print("Version: 1.0.0")
    print("Python:", sys.version.split()[0])
    print("Path:", Path(__file__).parent)


def _load_cli_config(config_override: str | None = None) -> dict:
    """Load optional CLI config from ~/.ipfs_datasets/cli.json.
    Returns empty dict if not present or invalid.
    """
    try:
        if config_override:
            cfg_path = Path(config_override)
        else:
            env_cfg = os.environ.get("IPFS_DATASETS_CLI_CONFIG")
            cfg_path = Path(env_cfg) if env_cfg else (Path.home() / ".ipfs_datasets" / "cli.json")
        if not cfg_path.exists():
            return {}
        data = json.loads(cfg_path.read_text())
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _default_host_port(config_override: str | None = None):
    """Resolve default host/port using precedence: env > config > hardcoded."""
    cfg = _load_cli_config(config_override)
    host = os.environ.get("IPFS_DATASETS_HOST") or cfg.get("host") or "127.0.0.1"
    port = os.environ.get("IPFS_DATASETS_PORT") or cfg.get("port") or "8899"
    return str(host), str(port)


def _default_gateway(config_override: str | None = None, override: str | None = None) -> str | None:
    """Resolve default IPFS HTTP gateway.
    Precedence: explicit override > env (IPFS_HTTP_GATEWAY or IPFS_DATASETS_IPFS_GATEWAY) > config > None.
    """
    if override:
        return override
    gw_env = os.environ.get("IPFS_HTTP_GATEWAY") or os.environ.get("IPFS_DATASETS_IPFS_GATEWAY")
    if gw_env:
        return gw_env
    cfg = _load_cli_config(config_override)
    if isinstance(cfg, dict):
        gw = cfg.get("gateway")
        if gw:
            return gw
    return None


def execute_heavy_command(args):
    """Execute commands that require heavy imports - only import when needed."""
    # Only import heavy modules when actually executing commands
    try:
        import asyncio
        import json
        import importlib
        from typing import Any, Dict, List
        
        # Setup sys path for imports
        current_dir = Path(__file__).parent  
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))
        
        # Detect global JSON flag and strip it from args
        json_output = False
        if '--json' in args:
            json_output = True
            args = [a for a in args if a != '--json']

        # Heavy command execution logic here
        command = args[0] if args else None
        
        if command == "tools":
            subcommand = args[1] if len(args) > 1 else None
            # parse global option --config first
            config_override = None
            if "--config" in args:
                try:
                    idx = args.index("--config")
                    if idx + 1 < len(args):
                        config_override = args[idx + 1]
                        args = args[:idx] + args[idx+2:]
                except Exception:
                    pass
            host, port = _default_host_port(config_override)
            # Parse common options for tools
            extra = args[2:]
            i = 0
            params_json = None
            category_arg = None
            tool_arg = None
            while i < len(extra):
                token = extra[i]
                if token in ("--host", "-H") and i + 1 < len(extra):
                    host = str(extra[i + 1])
                    i += 2
                elif token in ("--port", "-p") and i + 1 < len(extra):
                    port = str(extra[i + 1])
                    i += 2
                elif token in ("--params", "-d") and i + 1 < len(extra):
                    params_json = extra[i + 1]
                    i += 2
                else:
                    # Positional capture for category and tool for list/execute
                    if category_arg is None:
                        category_arg = token
                    elif tool_arg is None:
                        tool_arg = token
                    i += 1

            base = f"http://{host}:{port}/api/mcp"
            try:
                import requests
                if subcommand == "categories":
                    r = requests.get(f"{base}/tools", timeout=3)
                    r.raise_for_status()
                    data = r.json()
                    cats = sorted(list(data.keys())) if isinstance(data, dict) else []
                    if json_output:
                        print(json.dumps({"categories": cats}))
                    else:
                        print("Available tool categories:")
                        for c in cats:
                            print(f"- {c}")
                    return
                elif subcommand == "list":
                    if not category_arg:
                        print("Usage: ipfs-datasets tools list <category> [--host H --port P]")
                        return
                    r = requests.get(f"{base}/tools", timeout=3)
                    r.raise_for_status()
                    data = r.json()
                    tools = data.get(category_arg, []) if isinstance(data, dict) else []
                    if not tools:
                        print(f"No tools found for category '{category_arg}'")
                        return
                    if json_output:
                        print(json.dumps({"category": category_arg, "tools": tools}))
                    else:
                        print(f"Tools in '{category_arg}':")
                        for t in tools:
                            name = t.get("name", "unknown")
                            desc = t.get("description", "")
                            print(f"- {name}: {desc}")
                    return
                elif subcommand == "describe":
                    if not category_arg or not tool_arg:
                        print("Usage: ipfs-datasets tools describe <category> <tool> [--host H --port P]")
                        return
                    url = f"{base}/tools/{category_arg}/{tool_arg}"
                    r = requests.get(url, timeout=5)
                    if r.ok:
                        if json_output:
                            print(r.text)
                        else:
                            try:
                                print(json.dumps(r.json(), indent=2))
                            except Exception:
                                print(r.text)
                    else:
                        print(f"HTTP {r.status_code}: {r.text[:200]}")
                    return
                elif subcommand == "execute":
                    if not category_arg or not tool_arg:
                        print("Usage: ipfs-datasets tools execute <category> <tool> [--params JSON] [--host H --port P]")
                        return
                    try:
                        body = json.loads(params_json) if params_json else {}
                    except Exception as e:
                        print(f"Invalid JSON for --params: {e}")
                        return
                    url = f"{base}/tools/{category_arg}/{tool_arg}/execute"
                    r = requests.post(url, json=body, timeout=15)
                    if r.ok:
                        if json_output:
                            print(r.text)
                        else:
                            try:
                                print(json.dumps(r.json(), indent=2))
                            except Exception:
                                print(r.text)
                    else:
                        print(f"HTTP {r.status_code}: {r.text[:200]}")
                    return
            except Exception as e:
                print(f"Tools command failed: {e}")
                return
        
        if command == "ipfs":
            subcommand = args[1] if len(args) > 1 else None
            config_override = None
            if "--config" in args:
                try:
                    idx = args.index("--config")
                    if idx + 1 < len(args):
                        config_override = args[idx + 1]
                        args = args[:idx] + args[idx+2:]
                except Exception:
                    pass
            host, port = _default_host_port(config_override)
            extra = args[2:]
            i = 0
            out_path = None
            path_arg = None
            cid_arg = None
            gateway = None
            # load default gateway from env or config
            if not gateway:
                gw_env = os.environ.get("IPFS_HTTP_GATEWAY") or os.environ.get("IPFS_DATASETS_IPFS_GATEWAY")
                if gw_env:
                    gateway = gw_env
                else:
                    cfg = _load_cli_config(config_override)
                    gateway = cfg.get("gateway") if isinstance(cfg, dict) else None
            while i < len(extra):
                token = extra[i]
                if token in ("--host", "-H") and i + 1 < len(extra):
                    host = str(extra[i + 1])
                    i += 2
                elif token in ("--port", "-p") and i + 1 < len(extra):
                    port = str(extra[i + 1])
                    i += 2
                elif token in ("--out", "-o") and i + 1 < len(extra):
                    out_path = extra[i + 1]
                    i += 2
                elif token in ("--gateway", "-g") and i + 1 < len(extra):
                    gateway = extra[i + 1]
                    i += 2
                else:
                    # positional capture
                    if cid_arg is None and subcommand == "get":
                        cid_arg = token
                    elif path_arg is None and subcommand == "pin":
                        path_arg = token
                    i += 1

            base = f"http://{host}:{port}/api/mcp/tools"
            try:
                import requests
                if subcommand == "get":
                    if not cid_arg:
                        print("Usage: ipfs-datasets ipfs get <cid> [--out PATH] [--host H --port P]")
                        return
                    url = f"{base}/ipfs_tools/get_from_ipfs/execute"
                    body = {"cid": cid_arg}
                    if out_path:
                        body["output_path"] = out_path
                    if gateway:
                        body["gateway"] = gateway
                    r = requests.post(url, json=body, timeout=30)
                    if r.ok:
                        if json_output:
                            print(r.text)
                        else:
                            try:
                                print(json.dumps(r.json(), indent=2))
                            except Exception:
                                print(r.text)
                    else:
                        print(f"HTTP {r.status_code}: {r.text[:200]}")
                    return
                elif subcommand == "pin":
                    if not path_arg:
                        print("Usage: ipfs-datasets ipfs pin <path> [--host H --port P]")
                        return
                    url = f"{base}/ipfs_tools/pin_to_ipfs/execute"
                    body = {"content_source": path_arg}
                    r = requests.post(url, json=body, timeout=60)
                    if r.ok:
                        if json_output:
                            print(r.text)
                        else:
                            try:
                                print(json.dumps(r.json(), indent=2))
                            except Exception:
                                print(r.text)
                    else:
                        print(f"HTTP {r.status_code}: {r.text[:200]}")
                    return
            except Exception as e:
                print(f"IPFS command failed: {e}")
                return
        
        if command == "mcp":
            subcommand = args[1] if len(args) > 1 else None
            if subcommand == "start":
                config_override = None
                if "--config" in args:
                    try:
                        idx = args.index("--config")
                        if idx + 1 < len(args):
                            config_override = args[idx + 1]
                            args = args[:idx] + args[idx+2:]
                    except Exception:
                        pass
                host, port = _default_host_port(config_override)
                blocking = False
                extra = args[2:]
                i = 0
                while i < len(extra):
                    token = extra[i]
                    if token in ("--host", "-H") and i + 1 < len(extra):
                        host = str(extra[i + 1])
                        i += 2
                    elif token in ("--port", "-p") and i + 1 < len(extra):
                        port = str(extra[i + 1])
                        i += 2
                    elif token in ("--blocking", "-b"):
                        blocking = True
                        i += 1
                    else:
                        i += 1

                env = os.environ.copy()
                env["MCP_DASHBOARD_HOST"] = host
                env["MCP_DASHBOARD_PORT"] = str(port)
                if blocking:
                    env["MCP_DASHBOARD_BLOCKING"] = "1"

                cmd = [sys.executable, "-m", "ipfs_datasets_py.mcp_dashboard"]
                try:
                    if blocking:
                        print(f"Starting MCP dashboard (blocking) at http://{host}:{port}/mcp ...")
                        subprocess.run(cmd, env=env, check=False)
                    else:
                        print(f"Starting MCP dashboard at http://{host}:{port}/mcp (background)...")
                        # Write logs to a file so crashes aren't silent
                        logs_dir = Path.home() / ".ipfs_datasets"
                        logs_dir.mkdir(parents=True, exist_ok=True)
                        log_path = logs_dir / "mcp_dashboard.log"
                        log_fh = open(log_path, "a")
                        proc = subprocess.Popen(cmd, env=env, stdout=log_fh, stderr=log_fh)
                        # Quick readiness probe so users get fast feedback
                        import time as _time
                        import urllib.request as _url
                        ready = False
                        status_url = f"http://{host}:{port}/api/mcp/status"
                        for _ in range(20):  # ~5s total
                            try:
                                with _url.urlopen(status_url, timeout=0.25) as r:
                                    if r.status == 200:
                                        ready = True
                                        break
                            except Exception:
                                _time.sleep(0.25)
                        if ready:
                            print(f"MCP dashboard is up: {status_url}")
                        else:
                            print("MCP dashboard did not respond yet. It may still be booting or failed to start.")
                            print(f"Tip: tail -n 100 {log_path} to see logs, or run 'ipfs-datasets mcp start --blocking' for diagnostics.")
                            # If process exited immediately, surface that
                            _time.sleep(0.2)
                            if proc.poll() is not None:
                                print(f"Warning: dashboard process exited with code {proc.returncode}. See logs: {log_path}")
                    return
                except Exception as e:
                    print(f"Failed to start MCP dashboard: {e}")
                    print("Tip: try 'python -m ipfs_datasets_py.mcp_dashboard' for diagnostics")
                    return

            elif subcommand == "stop":
                # Best-effort stop via pkill on the dashboard module
                try:
                    # Prefer graceful stop in future; for now use pkill
                    subprocess.run(["pkill", "-f", "ipfs_datasets_py.mcp_dashboard"], check=False)
                    print("MCP dashboard stop signal sent (pkill).")
                except Exception as e:
                    print(f"Failed to stop MCP dashboard: {e}")
                return

            elif subcommand == "status":
                # Lightweight status check via HTTP if requests is available
                config_override = None
                if "--config" in args:
                    try:
                        idx = args.index("--config")
                        if idx + 1 < len(args):
                            config_override = args[idx + 1]
                            args = args[:idx] + args[idx+2:]
                    except Exception:
                        pass
                host, port = _default_host_port(config_override)
                extra = args[2:]
                i = 0
                while i < len(extra):
                    token = extra[i]
                    if token in ("--host", "-H") and i + 1 < len(extra):
                        host = str(extra[i + 1])
                        i += 2
                    elif token in ("--port", "-p") and i + 1 < len(extra):
                        port = str(extra[i + 1])
                        i += 2
                    else:
                        i += 1
                try:
                    import requests
                    url = f"http://{host}:{port}/api/mcp/status"
                    r = requests.get(url, timeout=2)
                    if r.ok:
                        if json_output:
                            print(r.text)
                        else:
                            print(f"MCP Dashboard status at {url}: {r.status_code}")
                            try:
                                data = r.json()
                                print(json.dumps({
                                    "status": data.get("status"),
                                    "tools_available": data.get("tools_available")
                                }, indent=2))
                            except Exception:
                                print(r.text[:300])
                    else:
                        print(f"MCP Dashboard not healthy (HTTP {r.status_code}) at {url}")
                except Exception as e:
                    print(f"MCP status check failed: {e}")
                return

            elif subcommand == "logs":
                # Tail the MCP dashboard log file
                # Options: --lines N (default 200), --follow
                lines = 200
                follow = False
                extra = args[2:]
                i = 0
                while i < len(extra):
                    token = extra[i]
                    if token in ("--lines", "-n") and i + 1 < len(extra):
                        try:
                            lines = int(extra[i + 1])
                        except Exception:
                            pass
                        i += 2
                    elif token in ("--follow", "-f"):
                        follow = True
                        i += 1
                    else:
                        i += 1

                log_path = Path.home() / ".ipfs_datasets" / "mcp_dashboard.log"
                if not log_path.exists():
                    print(f"No log file found at {log_path}. Start the dashboard first with 'ipfs-datasets mcp start'.")
                    return

                # Print last N lines
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.readlines()
                        start = max(0, len(content) - lines)
                        for line in content[start:]:
                            print(line.rstrip("\n"))

                    if not follow:
                        return

                    # Follow mode
                    print("-- following -- (Ctrl+C to stop)")
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        # Seek to end
                        f.seek(0, 2)
                        import time as _time
                        while True:
                            pos = f.tell()
                            line = f.readline()
                            if not line:
                                _time.sleep(0.25)
                                f.seek(pos)
                            else:
                                print(line.rstrip("\n"))
                except KeyboardInterrupt:
                    return
                except Exception as e:
                    print(f"Error reading logs: {e}")
                return
        
        print(f"Command '{' '.join(args)}' requires full system - importing modules...")
        
        # For complex operations, import the full original functionality
    # Heavy subsystem imports would go here when needed
        # Continue with heavy operations...
        
    except ImportError as e:
        print(f"Error: Missing dependencies for command '{' '.join(args)}': {e}")
        print("Try: pip install -e . to install all dependencies")
    except Exception as e:
        print(f"Error executing command: {e}")


def main():
    """Main CLI entry point - lightweight by default."""
    args = sys.argv[1:]
    # Global format flag support
    json_output = False
    if '--format' in args:
        try:
            idx = args.index('--format')
            if idx + 1 < len(args) and args[idx + 1].lower() == 'json':
                json_output = True
                # Remove the pair from args
                args = args[:idx] + args[idx+2:]
        except Exception:
            pass
    if '--json' in args:
        json_output = True
        args = [a for a in args if a != '--json']
    
    # Handle help and version immediately without any imports
    if not args or args[0] in ['-h', '--help', 'help']:
        show_help()
        return
        
    if args[0] in ['--version', 'version']:
        show_version()
        return
    
    # Handle basic info commands without heavy imports
    if args[0] == 'info':
        if len(args) > 1:
            sub = args[1]
            if sub == 'status':
                # Parse optional overrides to reflect resolved defaults in JSON
                config_override = None
                host_override = None
                port_override = None
                gateway_override = None
                extra = args[2:]
                i = 0
                while i < len(extra):
                    token = extra[i]
                    if token == '--config' and i + 1 < len(extra):
                        config_override = extra[i + 1]
                        i += 2
                    elif token in ('--host', '-H') and i + 1 < len(extra):
                        host_override = str(extra[i + 1])
                        i += 2
                    elif token in ('--port', '-p') and i + 1 < len(extra):
                        port_override = str(extra[i + 1])
                        i += 2
                    elif token in ('--gateway', '-g') and i + 1 < len(extra):
                        gateway_override = extra[i + 1]
                        i += 2
                    else:
                        i += 1

                host_res, port_res = _default_host_port(config_override)
                if host_override:
                    host_res = host_override
                if port_override:
                    port_res = port_override
                gateway_res = _default_gateway(config_override, gateway_override)

                if json_output:
                    out = {
                        "status": "success",
                        "message": "CLI available",
                        "version": "1.0.0",
                        "python": sys.version.split()[0],
                        "host": host_res,
                        "port": port_res,
                        "gateway": gateway_res,
                        "dashboard_status_url": f"http://{host_res}:{port_res}/api/mcp/status",
                        "dashboard_url": f"http://{host_res}:{port_res}/mcp"
                    }
                    print(json.dumps(out))
                else:
                    print("Success! CLI is available")
                    print("System Status: CLI tool is available")
                    print("Version: 1.0.0")
                    print("Python:", sys.version.split()[0])
                    print(f"Host: {host_res}")
                    print(f"Port: {port_res}")
                    print(f"Gateway: {gateway_res or 'None'}")
                    print(f"Dashboard: http://{host_res}:{port_res}/mcp")
                    print(f"Status API: http://{host_res}:{port_res}/api/mcp/status")
                return
            if sub == 'version':
                if json_output:
                    print(json.dumps({"version": "1.0.0"}))
                else:
                    show_version()
                return
            if sub == 'defaults':
                # Parse options for host/port/gateway/config
                config_override = None
                host_override = None
                port_override = None
                gateway_override = None
                extra = args[2:]
                i = 0
                while i < len(extra):
                    token = extra[i]
                    if token == '--config' and i + 1 < len(extra):
                        config_override = extra[i + 1]
                        i += 2
                    elif token in ('--host', '-H') and i + 1 < len(extra):
                        host_override = str(extra[i + 1])
                        i += 2
                    elif token in ('--port', '-p') and i + 1 < len(extra):
                        port_override = str(extra[i + 1])
                        i += 2
                    elif token in ('--gateway', '-g') and i + 1 < len(extra):
                        gateway_override = extra[i + 1]
                        i += 2
                    else:
                        i += 1

                # Resolve with precedence: flags > env > config > defaults
                host, port = _default_host_port(config_override)
                if host_override:
                    host = host_override
                if port_override:
                    port = port_override
                gateway = _default_gateway(config_override, gateway_override)

                if json_output:
                    print(json.dumps({
                        "host": host,
                        "port": port,
                        "gateway": gateway
                    }))
                else:
                    print(f"Host: {host}")
                    print(f"Port: {port}")
                    print(f"Gateway: {gateway or 'None'}")
                return
            if sub == 'save-defaults':
                # Persist host/port/gateway to config file
                config_path = None
                host_val = None
                port_val = None
                gateway_val = None
                extra = args[2:]
                i = 0
                while i < len(extra):
                    token = extra[i]
                    if token == '--config' and i + 1 < len(extra):
                        config_path = extra[i + 1]
                        i += 2
                    elif token in ('--host', '-H') and i + 1 < len(extra):
                        host_val = str(extra[i + 1])
                        i += 2
                    elif token in ('--port', '-p') and i + 1 < len(extra):
                        port_val = str(extra[i + 1])
                        i += 2
                    elif token in ('--gateway', '-g') and i + 1 < len(extra):
                        gateway_val = extra[i + 1]
                        i += 2
                    else:
                        i += 1

                # Resolve current defaults then override with provided values
                default_host, default_port = _default_host_port(config_path)
                resolved_host = host_val or default_host
                resolved_port = port_val or default_port
                resolved_gateway = _default_gateway(config_path, gateway_val)

                # Determine config file path
                if not config_path:
                    env_cfg = os.environ.get("IPFS_DATASETS_CLI_CONFIG")
                    config_path = env_cfg if env_cfg else str(Path.home() / ".ipfs_datasets" / "cli.json")

                try:
                    cfg_path = Path(config_path)
                    cfg_path.parent.mkdir(parents=True, exist_ok=True)
                    data = {
                        "host": str(resolved_host),
                        "port": str(resolved_port),
                        **({"gateway": str(resolved_gateway)} if resolved_gateway else {})
                    }
                    cfg_path.write_text(json.dumps(data, indent=2))
                    if json_output:
                        print(json.dumps({"status": "saved", "path": str(cfg_path), **data}))
                    else:
                        print(f"Saved defaults to {cfg_path}")
                        print(f"Host: {resolved_host}")
                        print(f"Port: {resolved_port}")
                        print(f"Gateway: {resolved_gateway or 'None'}")
                except Exception as e:
                    if json_output:
                        print(json.dumps({"status": "error", "error": str(e)}))
                    else:
                        print(f"Failed to save defaults: {e}")
                return
            if sub in ['list-tools', 'listtools', 'tools']:
                # Minimal categories view without heavy imports
                cats = [
                    'dataset_tools', 'ipfs_tools', 'vector_tools', 'analysis_tools'
                ]
                if json_output:
                    print(json.dumps({"categories": cats}))
                else:
                    print("Available tool categories:")
                    for c in cats:
                        print(f"- {c}")
                return
    
    # For other known command families, use heavy import function
    if args[0] in ['mcp', 'tools', 'ipfs', 'dataset', 'vector']:
        execute_heavy_command(args)
        return

    # Unknown command
    print(f"Error: unknown command: {' '.join(args)}")
    sys.exit(2)


def cli_main():
    """Entry point wrapper for console scripts."""
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()