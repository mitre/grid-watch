"""YAML configuration loader for the DNP3 outstation simulator.

Loads server settings and point definitions from a YAML file and
validates them before the outstation starts.

Expected schema:

    server:
      host: 0.0.0.0
      port: 20000
      dnp3_address: 1

    points:
      binary_inputs:
        - index: 0
          value: false
        - index: 1
          value: true
      analog_inputs:
        - index: 0
          value: 0.0
        - index: 1
          value: 25.5
      binary_outputs:          # optional
        - index: 0
          value: false
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# --- Dataclasses that mirror the YAML schema ---


@dataclass
class BinaryInputDef:
    index: int
    value: bool = False


@dataclass
class AnalogInputDef:
    index: int
    value: float = 0.0


@dataclass
class BinaryOutputDef:
    index: int
    value: bool = False


@dataclass
class PointsDef:
    binary_inputs: list[BinaryInputDef] = field(default_factory=list)
    analog_inputs: list[AnalogInputDef] = field(default_factory=list)
    binary_outputs: list[BinaryOutputDef] = field(default_factory=list)


@dataclass
class ServerDef:
    host: str = "0.0.0.0"
    port: int = 20000
    dnp3_address: int = 1


@dataclass
class OutstationConfig:
    server: ServerDef = field(default_factory=ServerDef)
    points: PointsDef = field(default_factory=PointsDef)


# --- Loader + validator ---


def load_config(path: str | Path) -> OutstationConfig:
    """Load and validate an outstation config from a YAML file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Validated OutstationConfig.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is invalid YAML or fails validation.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(
            f"Config file must contain a YAML mapping, got {type(raw).__name__}"
        )

    return _parse_config(raw, source=str(path))


def _parse_config(raw: dict[str, Any], source: str) -> OutstationConfig:
    """Parse and validate a raw config dict."""
    server = _parse_server(raw.get("server") or {}, source)
    points = _parse_points(raw.get("points") or {}, source)
    return OutstationConfig(server=server, points=points)


def _parse_server(raw: Any, source: str) -> ServerDef:
    if not isinstance(raw, dict):
        raise ValueError(f"[{source}] 'server' must be a mapping")

    host = raw.get("host", "0.0.0.0")
    if not isinstance(host, str) or not host:
        raise ValueError(
            f"[{source}] server.host must be a non-empty string, got {host!r}"
        )

    port = raw.get("port", 20000)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError(
            f"[{source}] server.port must be an integer 1-65535, got {port!r}"
        )

    dnp3_address = raw.get("dnp3_address", 1)
    if not isinstance(dnp3_address, int) or not (0 <= dnp3_address <= 65535):
        raise ValueError(
            f"[{source}] server.dnp3_address must be an integer 0-65535, got {dnp3_address!r}"
        )

    return ServerDef(host=host, port=port, dnp3_address=dnp3_address)


def _parse_points(raw: Any, source: str) -> PointsDef:
    if not isinstance(raw, dict):
        raise ValueError(f"[{source}] 'points' must be a mapping")

    binary_inputs = _parse_binary_inputs(raw.get("binary_inputs") or [], source)
    analog_inputs = _parse_analog_inputs(raw.get("analog_inputs") or [], source)
    binary_outputs = _parse_binary_outputs(raw.get("binary_outputs") or [], source)

    _check_unique_indices("binary_inputs", [p.index for p in binary_inputs], source)
    _check_unique_indices("analog_inputs", [p.index for p in analog_inputs], source)
    _check_unique_indices("binary_outputs", [p.index for p in binary_outputs], source)

    return PointsDef(
        binary_inputs=binary_inputs,
        analog_inputs=analog_inputs,
        binary_outputs=binary_outputs,
    )


def _parse_binary_inputs(raw: Any, source: str) -> list[BinaryInputDef]:
    if not isinstance(raw, list):
        raise ValueError(f"[{source}] points.binary_inputs must be a list")
    result = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"[{source}] points.binary_inputs[{i}] must be a mapping")
        index = _require_int(item, "index", f"binary_inputs[{i}]", source)
        value = _require_bool(
            item, "value", f"binary_inputs[{i}]", source, default=False
        )
        result.append(BinaryInputDef(index=index, value=value))
    return result


def _parse_analog_inputs(raw: Any, source: str) -> list[AnalogInputDef]:
    if not isinstance(raw, list):
        raise ValueError(f"[{source}] points.analog_inputs must be a list")
    result = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"[{source}] points.analog_inputs[{i}] must be a mapping")
        index = _require_int(item, "index", f"analog_inputs[{i}]", source)
        value = _require_number(
            item, "value", f"analog_inputs[{i}]", source, default=0.0
        )
        result.append(AnalogInputDef(index=index, value=float(value)))
    return result


def _parse_binary_outputs(raw: Any, source: str) -> list[BinaryOutputDef]:
    if not isinstance(raw, list):
        raise ValueError(f"[{source}] points.binary_outputs must be a list")
    result = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"[{source}] points.binary_outputs[{i}] must be a mapping")
        index = _require_int(item, "index", f"binary_outputs[{i}]", source)
        value = _require_bool(
            item, "value", f"binary_outputs[{i}]", source, default=False
        )
        result.append(BinaryOutputDef(index=index, value=value))
    return result


# --- Field helpers ---


def _require_int(d: dict[str, Any], key: str, ctx: str, source: str) -> int:
    if key not in d:
        raise ValueError(f"[{source}] {ctx} is missing required field '{key}'")
    val = d[key]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ValueError(f"[{source}] {ctx}.{key} must be an integer, got {val!r}")
    return val


def _require_bool(
    d: dict[str, Any], key: str, ctx: str, source: str, default: bool
) -> bool:
    val = d.get(key, default)
    if not isinstance(val, bool):
        raise ValueError(f"[{source}] {ctx}.{key} must be a boolean, got {val!r}")
    return val


def _require_number(
    d: dict[str, Any], key: str, ctx: str, source: str, default: float
) -> float:
    val = d.get(key, default)
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise ValueError(f"[{source}] {ctx}.{key} must be a number, got {val!r}")
    return val


def _check_unique_indices(name: str, indices: list[int], source: str) -> None:
    seen: set[int] = set()
    for idx in indices:
        if idx in seen:
            raise ValueError(f"[{source}] points.{name} has duplicate index {idx}")
        seen.add(idx)
