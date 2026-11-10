#!/usr/bin/env python3
"""Entry point for the Caldera OT DNP3 Simulator."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def run(module: str, extra_args: list[str] | None = None) -> None:
    cmd = [sys.executable, "-m", module] + (extra_args or [])
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{ROOT}{os.pathsep}{existing}" if existing else str(ROOT)
    result = subprocess.run(cmd, env=env)
    sys.exit(result.returncode)


def main() -> None:
    print("Caldera OT DNP3 Simulator")
    print()
    print("Outstation (PLC)")
    print("  1  Start the DNP3 outstation server")
    print()
    print("HMI")
    print("  2  Launch the matplotlib HMI dashboard (requires server running)")
    print()
    print("Testing")
    print("  3  Run the DNP3 test client (requires server running)")
    print()

    choice = input("Enter choice [1-3]: ").strip()

    if choice == "1":
        print()
        config = input("Config file path [default: config.yaml]: ").strip()
        extra = ["--config", config] if config else []
        run("simulator.plc", extra)
    elif choice == "2":
        print()
        host = input("Outstation host [default: 127.0.0.1]: ").strip()
        port = input("DNP3 port [default: 20000]: ").strip()
        extra = []
        if host:
            extra += ["--host", host]
        if port:
            extra += ["--port", port]
        run("simulator.hmi", extra)
    elif choice == "3":
        run("simulator.client")
    else:
        print("Invalid choice.")
        sys.exit(1)


if __name__ == "__main__":
    main()
