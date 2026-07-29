"""Tests for YAML configuration loading
Covers:
- Binary/analog inputs and binary outputs defined in YAML
- Server host, port, and dnp3_address configurable
- Config applied to database on startup
- Invalid config produces clear error messages
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "dnp3-sim"))

from config import (
    AnalogInputDef,
    BinaryInputDef,
    BinaryOutputDef,
    OutstationConfig,
    load_config,
)
from server import build_database

# --- Helpers ---


def write_yaml(tmp_path: Path, content: str) -> Path:
    """Write a YAML string to a temp file and return its path."""
    p = tmp_path / "config.yaml"
    p.write_text(content)
    return p


VALID_YAML = """
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
  binary_outputs:
    - index: 0
      value: false
"""


# --- load_config: happy path ---


def test_load_config_returns_outstation_config(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert isinstance(cfg, OutstationConfig)


def test_load_config_server_host(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert cfg.server.host == "0.0.0.0"


def test_load_config_server_port(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert cfg.server.port == 20000


def test_load_config_server_dnp3_address(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert cfg.server.dnp3_address == 1


def test_load_config_binary_inputs_count(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert len(cfg.points.binary_inputs) == 2


def test_load_config_binary_input_values(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert cfg.points.binary_inputs[0] == BinaryInputDef(index=0, value=False)
    assert cfg.points.binary_inputs[1] == BinaryInputDef(index=1, value=True)


def test_load_config_analog_inputs_count(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert len(cfg.points.analog_inputs) == 2


def test_load_config_analog_input_values(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert cfg.points.analog_inputs[0] == AnalogInputDef(index=0, value=0.0)
    assert abs(cfg.points.analog_inputs[1].value - 25.5) < 0.001


def test_load_config_binary_outputs_count(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert len(cfg.points.binary_outputs) == 1


def test_load_config_binary_output_value(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    assert cfg.points.binary_outputs[0] == BinaryOutputDef(index=0, value=False)


# --- load_config: optional sections have sensible defaults ---


def test_load_config_missing_binary_outputs_defaults_to_empty(tmp_path):
    yaml = """
server:
  host: 127.0.0.1
  port: 19999
  dnp3_address: 2
points:
  binary_inputs:
    - index: 0
      value: false
  analog_inputs: []
"""
    cfg = load_config(write_yaml(tmp_path, yaml))
    assert cfg.points.binary_outputs == []


def test_load_config_missing_server_section_uses_defaults(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs: []
"""
    cfg = load_config(write_yaml(tmp_path, yaml))
    assert cfg.server.host == "0.0.0.0"
    assert cfg.server.port == 20000
    assert cfg.server.dnp3_address == 1


def test_load_config_custom_host_and_port(tmp_path):
    yaml = """
server:
  host: 192.168.1.100
  port: 19999
  dnp3_address: 5
points:
  binary_inputs: []
  analog_inputs: []
"""
    cfg = load_config(write_yaml(tmp_path, yaml))
    assert cfg.server.host == "192.168.1.100"
    assert cfg.server.port == 19999
    assert cfg.server.dnp3_address == 5


# --- build_database — config applied correctly ---


def test_build_database_from_config_binary_input_count(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    db = build_database(cfg)
    assert db.binary_input_count == 2


def test_build_database_from_config_analog_input_count(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    db = build_database(cfg)
    assert db.analog_input_count == 2


def test_build_database_from_config_binary_output_count(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    db = build_database(cfg)
    assert db.binary_output_count == 1


def test_build_database_from_config_binary_input_values(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    db = build_database(cfg)
    assert db.get_binary_input(0).value is False
    assert db.get_binary_input(1).value is True


def test_build_database_from_config_analog_input_values(tmp_path):
    cfg = load_config(write_yaml(tmp_path, VALID_YAML))
    db = build_database(cfg)
    assert db.get_analog_input(0).value == 0.0
    assert abs(db.get_analog_input(1).value - 25.5) < 0.001


def test_build_database_from_config_nondefault_values(tmp_path):
    yaml = """
points:
  binary_inputs:
    - index: 0
      value: true
    - index: 5
      value: false
  analog_inputs:
    - index: 2
      value: 99.9
  binary_outputs: []
"""
    cfg = load_config(write_yaml(tmp_path, yaml))
    db = build_database(cfg)
    assert db.get_binary_input(0).value is True
    assert db.get_binary_input(5).value is False
    assert abs(db.get_analog_input(2).value - 99.9) < 0.001


def test_build_database_no_config_preserves_defaults():
    """build_database(None) still returns the hardcoded defaults for unit tests."""
    db = build_database(None)
    assert db.binary_input_count == 2
    assert db.analog_input_count == 2
    assert db.binary_output_count == 2


# --- load_config — error cases produce clear messages ---


def test_load_config_missing_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config("/nonexistent/path/config.yaml")


def test_load_config_invalid_yaml_raises_value_error(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text(":\tnot: valid: yaml: {{{")
    with pytest.raises(ValueError, match="Invalid YAML"):
        load_config(bad)


def test_load_config_non_mapping_root_raises_value_error(tmp_path):
    bad = write_yaml(tmp_path, "- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        load_config(bad)


def test_load_config_invalid_port_too_high_raises_value_error(tmp_path):
    yaml = """
server:
  host: 0.0.0.0
  port: 99999
  dnp3_address: 1
points:
  binary_inputs: []
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="server.port"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_invalid_port_zero_raises_value_error(tmp_path):
    yaml = """
server:
  port: 0
points:
  binary_inputs: []
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="server.port"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_invalid_host_empty_raises_value_error(tmp_path):
    yaml = """
server:
  host: ""
  port: 20000
  dnp3_address: 1
points:
  binary_inputs: []
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="server.host"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_missing_index_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs:
    - value: true
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="missing required field 'index'"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_negative_binary_input_index_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs:
    - index: -5
      value: true
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="must be a non-negative integer"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_negative_analog_input_index_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs:
    - index: -1
      value: 1.0
"""
    with pytest.raises(ValueError, match="must be a non-negative integer"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_negative_binary_output_index_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs: []
  binary_outputs:
    - index: -2
      value: false
"""
    with pytest.raises(ValueError, match="must be a non-negative integer"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_zero_index_is_accepted(tmp_path):
    yaml = """
points:
  binary_inputs:
    - index: 0
      value: true
  analog_inputs: []
"""
    cfg = load_config(write_yaml(tmp_path, yaml))
    assert cfg.points.binary_inputs[0].index == 0


def test_load_config_duplicate_binary_input_index_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs:
    - index: 0
      value: false
    - index: 0
      value: true
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="duplicate index"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_duplicate_analog_input_index_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs:
    - index: 1
      value: 1.0
    - index: 1
      value: 2.0
"""
    with pytest.raises(ValueError, match="duplicate index"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_analog_value_not_a_number_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs:
    - index: 0
      value: "not_a_number"
"""
    with pytest.raises(ValueError, match="must be a number"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_binary_value_not_bool_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs:
    - index: 0
      value: 1
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="must be a boolean"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_server_not_a_mapping_raises_value_error(tmp_path):
    yaml = """
server: 42
points:
  binary_inputs: []
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="'server' must be a mapping"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_invalid_dnp3_address_raises_value_error(tmp_path):
    yaml = """
server:
  host: 0.0.0.0
  port: 20000
  dnp3_address: -1
points:
  binary_inputs: []
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="server.dnp3_address"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_points_not_a_mapping_raises_value_error(tmp_path):
    yaml = """
server:
  host: 0.0.0.0
  port: 20000
points: 42
"""
    with pytest.raises(ValueError, match="'points' must be a mapping"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_binary_inputs_not_list_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: "bad"
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="binary_inputs must be a list"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_binary_input_item_not_mapping_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs:
    - 42
  analog_inputs: []
"""
    with pytest.raises(ValueError, match=r"binary_inputs\[0\] must be a mapping"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_analog_inputs_not_list_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs: "bad"
"""
    with pytest.raises(ValueError, match="analog_inputs must be a list"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_analog_input_item_not_mapping_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs:
    - 42
"""
    with pytest.raises(ValueError, match=r"analog_inputs\[0\] must be a mapping"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_binary_outputs_not_list_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs: []
  binary_outputs: "bad"
"""
    with pytest.raises(ValueError, match="binary_outputs must be a list"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_binary_output_item_not_mapping_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs: []
  analog_inputs: []
  binary_outputs:
    - 42
"""
    with pytest.raises(ValueError, match=r"binary_outputs\[0\] must be a mapping"):
        load_config(write_yaml(tmp_path, yaml))


def test_load_config_index_is_bool_raises_value_error(tmp_path):
    yaml = """
points:
  binary_inputs:
    - index: true
      value: false
  analog_inputs: []
"""
    with pytest.raises(ValueError, match="must be an integer"):
        load_config(write_yaml(tmp_path, yaml))
