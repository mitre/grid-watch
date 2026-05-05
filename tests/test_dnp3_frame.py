"""Tests for DNP3 link-layer framing (encode_frame / decode_frame / _frame_wire_size)."""

import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../dnp3-sim"))
)

from dnp3_frame import (
    MASTER_ADDR,
    OUTSTATION_ADDR,
    _BLOCK_SIZE,
    _crc,
    decode_frame,
    encode_frame,
    _frame_wire_size,
)

# --- _frame_wire_size ---


def test_frame_wire_size_exact_multiple_of_block():
    """user_data_len that is an exact multiple of _BLOCK_SIZE."""
    n_blocks = 3
    user_data_len = _BLOCK_SIZE * n_blocks
    expected = 10 + user_data_len + n_blocks * 2
    assert _frame_wire_size(user_data_len) == expected


def test_frame_wire_size_with_leftover():
    """user_data_len with a partial block at the end."""
    user_data_len = _BLOCK_SIZE * 2 + 5  # 2 full blocks + 5 leftover
    n_blocks = 3
    expected = 10 + user_data_len + n_blocks * 2
    assert _frame_wire_size(user_data_len) == expected


def test_frame_wire_size_zero():
    """Zero user-data bytes → 0 data blocks."""
    assert _frame_wire_size(0) == 10


# --- decode_frame: error paths ---


def _build_header(length: int, ctrl: int = 0x44) -> bytes:
    """Build an 8-byte DNP3 header (no CRC)."""
    return bytes(
        [
            0x05,
            0x64,
            length,
            ctrl,
            OUTSTATION_ADDR & 0xFF,
            (OUTSTATION_ADDR >> 8) & 0xFF,
            MASTER_ADDR & 0xFF,
            (MASTER_ADDR >> 8) & 0xFF,
        ]
    )


def _header_with_crc(length: int, ctrl: int = 0x44) -> bytes:
    """Return the 10-byte header (8 bytes + 2-byte CRC)."""
    hdr = _build_header(length, ctrl)
    c = _crc(hdr)
    return hdr + bytes([c & 0xFF, (c >> 8) & 0xFF])


def test_decode_frame_empty_returns_empty():
    """Empty input → empty output (no bytes at all)."""
    assert decode_frame(b"") == b""


def test_decode_frame_too_short_for_header_returns_empty():
    """Only 5 bytes → pos + 10 > len(data) → break → returns b''."""
    data = b"\x05\x64\x0a\x44\x01"  # 5 bytes, need 10
    assert decode_frame(data) == b""


def test_decode_frame_wrong_start_byte_returns_empty():
    """First byte is not 0x05 → break immediately."""
    data = b"\x00\x64\x0a\x44\x01\x00\x03\x00\x00\x00"
    assert decode_frame(data) == b""


def test_decode_frame_wrong_second_start_byte_returns_empty():
    """Second byte is not 0x64 → break immediately."""
    data = b"\x05\x00\x0a\x44\x01\x00\x03\x00\x00\x00"
    assert decode_frame(data) == b""


def test_decode_frame_bad_header_crc_returns_empty():
    """Valid header bytes but with a corrupted CRC → break."""
    hdr = _build_header(length=6)  # 5 + 1 byte of user data
    bad_crc = bytes([0x00, 0x00])  # deliberately wrong
    assert decode_frame(hdr + bad_crc) == b""


def test_decode_frame_negative_user_data_len_returns_empty():
    """length field = 4 → user_data_len = 4 - 5 = -1 → break."""
    hdr = _build_header(length=4)
    c = _crc(hdr)
    data = hdr + bytes([c & 0xFF, (c >> 8) & 0xFF])
    assert decode_frame(data) == b""


def test_decode_frame_truncated_data_block_returns_empty():
    """Header claims 1 byte of data but block+CRC bytes are absent."""
    # length = 5 + 1 → 1 byte of user data expected
    header = _header_with_crc(length=6)
    # Provide no data block bytes at all → block_pos + 1 + 2 > 10
    assert decode_frame(header) == b""


def test_decode_frame_bad_block_crc_returns_empty():
    """Valid frame but with a corrupted data-block CRC → returns b''."""
    app = b"\xab"
    framed = list(encode_frame(app, dest=OUTSTATION_ADDR, src=MASTER_ADDR))
    # The data block starts at byte 10; CRC is at bytes 11-12 (block is 1 byte)
    framed[11] ^= 0xFF  # flip bits in the block CRC
    assert decode_frame(bytes(framed)) == b""


# --- decode_frame: happy paths (sanity checks) ---


def test_decode_frame_roundtrip_small():
    app = b"\xc0\x01\x00\x00"
    framed = encode_frame(app, dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    assert decode_frame(framed) == app


def test_decode_frame_roundtrip_large_multiframe():
    """Payload larger than 250 bytes is split across multiple frames."""
    app = bytes(range(256))
    framed = encode_frame(app, dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    assert decode_frame(framed) == app
