"""Tests for _compat.py — verifies the qualifier-fix monkey-patch on Outstation.

Covers:
- Qualifier 0x00 (1-byte start/stop) for indices 0-255
- Qualifier 0x01 (2-byte start/stop) for max_index > 255
- Gap-fill for non-contiguous indices (sparse point maps)
- Empty-list early return in both patched builder functions
"""

import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../dnp3-sim"))
)

import _compat  # noqa: F401 — must import to apply the patch before Outstation is used
from _compat import _build_binary_input_blocks, _build_binary_output_blocks

from dnp3.database import (
    BinaryInputConfig,
    BinaryOutputConfig,
    Database,
)
from dnp3.master import DefaultSOEHandler, Master
from dnp3.outstation import Outstation


def _build_db_bi(*indices: int) -> Database:
    """Create a database with BinaryInputs at the given indices."""
    db = Database()
    for i, idx in enumerate(indices):
        db.add_binary_input(idx, BinaryInputConfig(), value=(i % 2 == 1))
    return db


def _build_db_bo(*indices: int) -> Database:
    """Create a database with BinaryOutputs at the given indices."""
    db = Database()
    for i, idx in enumerate(indices):
        db.add_binary_output(idx, BinaryOutputConfig(), value=(i % 2 == 1))
    return db


def _integrity_poll_response(db: Database):
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())
    request = master.build_integrity_poll()
    return outstation.process_request(request.to_bytes())


# --- Binary Input blocks ---


def test_binary_input_low_index_uses_qualifier_0x00():
    """Indices 0-255 → qualifier 0x00 (1-byte start/stop range)."""
    db = _build_db_bi(0, 1)
    resp = _integrity_poll_response(db)
    bi_block = next(b for b in resp.objects if b.header.group == 1)
    assert bi_block.header.qualifier == 0x00


def test_binary_input_high_index_uses_qualifier_0x01():
    """Max index > 255 → qualifier 0x01 (2-byte start/stop range)."""
    db = _build_db_bi(0, 300)
    resp = _integrity_poll_response(db)
    bi_block = next(b for b in resp.objects if b.header.group == 1)
    assert bi_block.header.qualifier == 0x01


def test_binary_input_sparse_indices_fills_gaps():
    """Non-contiguous indices (0 and 3) → gap bytes inserted for indices 1, 2."""
    db = _build_db_bi(0, 3)
    resp = _integrity_poll_response(db)
    bi_block = next(b for b in resp.objects if b.header.group == 1)
    # range = [0..3] = 4 points; data starts after the 2-byte start/stop range header
    # 1-byte qualifier → 1+1=2 byte range; 4 one-byte flags = 4 bytes
    assert bi_block.header.qualifier == 0x00
    # The data encodes 4 flags (index 0, gap 1, gap 2, index 3)
    range_and_data = bi_block.data
    # start/stop are each 1 byte → first 2 bytes are 0x00 and 0x03
    assert range_and_data[0] == 0  # start
    assert range_and_data[1] == 3  # stop
    assert len(range_and_data) == 6  # 2-byte range + 4 flag bytes


def test_binary_input_high_sparse_indices():
    """High indices (256+) with a gap — exercises both >255 range and gap fill."""
    db = _build_db_bi(256, 260)
    resp = _integrity_poll_response(db)
    bi_block = next(b for b in resp.objects if b.header.group == 1)
    assert bi_block.header.qualifier == 0x01  # 2-byte start/stop


# --- Binary Output blocks ---


def test_binary_output_low_index_uses_qualifier_0x00():
    """Indices 0-255 → qualifier 0x00."""
    db = _build_db_bo(0, 1)
    resp = _integrity_poll_response(db)
    bo_block = next(b for b in resp.objects if b.header.group == 10)
    assert bo_block.header.qualifier == 0x00


def test_binary_output_high_index_uses_qualifier_0x01():
    """Max index > 255 → qualifier 0x01."""
    db = _build_db_bo(0, 300)
    resp = _integrity_poll_response(db)
    bo_block = next(b for b in resp.objects if b.header.group == 10)
    assert bo_block.header.qualifier == 0x01


def test_binary_output_sparse_indices_fills_gaps():
    """Non-contiguous indices (0 and 3) → gap bytes inserted."""
    db = _build_db_bo(0, 3)
    resp = _integrity_poll_response(db)
    bo_block = next(b for b in resp.objects if b.header.group == 10)
    assert bo_block.header.qualifier == 0x00
    range_and_data = bo_block.data
    assert range_and_data[0] == 0  # start
    assert range_and_data[1] == 3  # stop
    assert len(range_and_data) == 6  # 2-byte range + 4 flag bytes


def test_binary_output_high_sparse_indices():
    """High indices with a gap — exercises >255 range and gap fill."""
    db = _build_db_bo(256, 260)
    resp = _integrity_poll_response(db)
    bo_block = next(b for b in resp.objects if b.header.group == 10)
    assert bo_block.header.qualifier == 0x01


def test_no_binary_inputs_returns_empty_block_list():
    """A database with no binary inputs produces an empty binary-input block list."""
    db = _build_db_bo(0)  # only binary outputs, no binary inputs
    resp = _integrity_poll_response(db)
    # There should be no group-1 block in the response
    bi_blocks = [b for b in resp.objects if b.header.group == 1]
    assert bi_blocks == []


def test_no_binary_outputs_returns_empty_block_list():
    """A database with no binary outputs produces an empty binary-output block list."""
    db = _build_db_bi(0)  # only binary inputs, no binary outputs
    resp = _integrity_poll_response(db)
    # There should be no group-10 block in the response
    bo_blocks = [b for b in resp.objects if b.header.group == 10]
    assert bo_blocks == []


# --- Direct invocation of patched builder functions with empty inputs ---


def test_build_binary_input_blocks_empty_list_returns_empty():
    """Calling the patched builder directly with [] returns []."""
    db = _build_db_bi(0)
    outstation = Outstation(database=db)
    result = _build_binary_input_blocks(outstation, [])
    assert result == []


def test_build_binary_output_blocks_empty_list_returns_empty():
    """Calling the patched builder directly with [] returns []."""
    db = _build_db_bo(0)
    outstation = Outstation(database=db)
    result = _build_binary_output_blocks(outstation, [])
    assert result == []
