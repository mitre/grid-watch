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
    _encode_single,
    decode_frame,
    encode_frame,
    encode_transport_frames,
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


def test_decode_frame_resyncs_past_leading_junk():
    """A stray byte ahead of a valid frame must not hide the frame."""
    payload = bytes([0xC0, 0x01, 0x3C, 0x01, 0x06])
    frame = encode_frame(payload, dest=1, src=2, is_response=False)
    for junk in (b"\x05", b"\x00", b"\x05" * 64, bytes(range(32))):
        assert decode_frame(junk + frame) == payload


def test_decode_frame_resyncs_past_corrupt_leading_frame():
    """A frame with a bad CRC must not hide a good frame behind it."""
    payload = bytes([0xC0, 0x01, 0x3C, 0x01, 0x06])
    frame = encode_frame(payload, dest=1, src=2, is_response=False)
    corrupt = bytearray(frame)
    corrupt[8] ^= 0xFF  # break the header CRC
    assert decode_frame(bytes(corrupt) + frame) == payload


def test_decode_frame_resyncs_past_bad_length_frame():
    """A frame whose length field is too small must not hide a good frame."""
    payload = bytes([0xC0, 0x01, 0x3C, 0x01, 0x06])
    frame = encode_frame(payload, dest=1, src=2, is_response=False)
    hdr = _build_header(length=4)  # user_data_len = -1
    c = _crc(hdr)
    bad = hdr + bytes([c & 0xFF, (c >> 8) & 0xFF])
    assert decode_frame(bad + frame) == payload


def test_decode_frame_junk_with_no_frame_returns_empty():
    """Resync must still give up when there is no frame to find."""
    assert decode_frame(b"\x05" * 512) == b""
    assert decode_frame(b"\x05\x64" + b"\x00" * 32) == b""


def test_decode_frame_roundtrip_small():
    app = b"\xc0\x01\x00\x00"
    framed = encode_frame(app, dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    assert decode_frame(framed) == app


def test_decode_frame_roundtrip_large_multiframe():
    """Payload larger than 250 bytes is split across multiple frames."""
    app = bytes(range(256))
    framed = encode_frame(app, dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    assert decode_frame(framed) == app


# --- encode_transport_frames ---


def test_encode_transport_frames_single_segment():
    """A payload that fits one segment gets a 0xC0 (FIR|FIN) transport header."""
    app = b"\x81\x00\x00\xde\xad"
    framed = encode_transport_frames(
        app, dest=MASTER_ADDR, src=OUTSTATION_ADDR, is_response=True
    )
    expected = _encode_single(bytes([0xC0]) + app, MASTER_ADDR, OUTSTATION_ADDR, 0x44)
    assert framed == expected
    assert decode_frame(framed) == bytes([0xC0]) + app


def test_encode_transport_frames_multi_segment():
    """A 512-byte payload spans three segments: FIR / middle / FIN headers."""
    app = bytes(range(256)) * 2  # 512 bytes -> 249 + 249 + 14
    framed = encode_transport_frames(
        app, dest=MASTER_ADDR, src=OUTSTATION_ADDR, is_response=True
    )

    seg0, seg1, seg2 = app[0:249], app[249:498], app[498:512]
    expected = (
        _encode_single(bytes([0x40]) + seg0, MASTER_ADDR, OUTSTATION_ADDR, 0x44)
        + _encode_single(bytes([0x01]) + seg1, MASTER_ADDR, OUTSTATION_ADDR, 0x44)
        + _encode_single(bytes([0x82]) + seg2, MASTER_ADDR, OUTSTATION_ADDR, 0x44)
    )
    assert framed == expected
