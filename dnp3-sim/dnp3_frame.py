"""DNP3 link-layer framing for TCP transport.

Wraps application-layer bytes in DNP3 link-layer frames so that
Wireshark's built-in DNP3 dissector can decode traffic on port 20000.

A large app-layer payload is split across as many frames as needed; each
frame carries up to 250 bytes of user data (the DNP3 link-layer maximum).

Frame structure (one frame):
  [0x05][0x64][len][ctrl][dest_lo][dest_hi][src_lo][src_hi][crc_lo][crc_hi]
  [data block 0: up to 16 bytes][crc_lo][crc_hi]
  ...
  [data block N: up to 16 bytes][crc_lo][crc_hi]

  len  = 5 (ctrl+dest+src) + number of user-data bytes in THIS frame
  ctrl = 0xC4  master->outstation  (UNCONFIRMED_USER_DATA, primary)
       = 0x44  outstation->master  (UNCONFIRMED_USER_DATA, secondary)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# DNP3 CRC-16 (poly 0xA6BC, reflected form of 0x3D65, init=0, XorOut=0xFFFF)
# ---------------------------------------------------------------------------

_CRC_TABLE: list[int] = []
for _i in range(256):
    _v = _i
    for _ in range(8):
        _v = (_v >> 1) ^ 0xA6BC if (_v & 1) else _v >> 1
    _CRC_TABLE.append(_v)


def _crc(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = _CRC_TABLE[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return (~crc) & 0xFFFF


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_START = bytes([0x05, 0x64])
_BLOCK_SIZE = 16  # user-data bytes per block before its 2-byte CRC
_MAX_DATA = 250  # max user-data bytes per link-layer frame (spec limit)

# Control byte values for unconfirmed user data
_CTRL_PRIMARY = 0xC4  # master  -> outstation  (DIR=1 PRM=1 FCV=0 FCB=0 FC=4)
_CTRL_SECONDARY = 0x44  # outstation -> master   (DIR=1 PRM=0 FCV=0 FCB=0 FC=4)

# Default DNP3 addresses used by this simulator
MASTER_ADDR = 3
OUTSTATION_ADDR = 1  # matches dnp3_address in config.yaml


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _encode_single(chunk: bytes, dest: int, src: int, ctrl: int) -> bytes:
    """Encode one link-layer frame for up to 250 bytes of user data."""
    length = 5 + len(chunk)  # ctrl(1) + dest(2) + src(2) + data
    header = _START + bytes(
        [
            length,
            ctrl,
            dest & 0xFF,
            (dest >> 8) & 0xFF,
            src & 0xFF,
            (src >> 8) & 0xFF,
        ]
    )
    hcrc = _crc(header)
    frame = header + bytes([hcrc & 0xFF, (hcrc >> 8) & 0xFF])
    for i in range(0, len(chunk), _BLOCK_SIZE):
        block = chunk[i : i + _BLOCK_SIZE]
        bcrc = _crc(block)
        frame += block + bytes([bcrc & 0xFF, (bcrc >> 8) & 0xFF])
    return frame


def _frame_wire_size(user_data_len: int) -> int:
    """Return the total byte length of a single frame carrying user_data_len bytes."""
    n_full, leftover = divmod(user_data_len, _BLOCK_SIZE)
    n_blocks = n_full + (1 if leftover else 0)
    return 10 + user_data_len + n_blocks * 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def encode_frame(
    app_bytes: bytes,
    dest: int = OUTSTATION_ADDR,
    src: int = MASTER_ADDR,
    is_response: bool = False,
) -> bytes:
    """Wrap app-layer bytes in one or more DNP3 link-layer frames.

    Payloads larger than 250 bytes are split across multiple frames
    (each up to 250 bytes of user data) sent back-to-back on the wire.

    Args:
        app_bytes:   Raw DNP3 application-layer payload.
        dest:        Destination DNP3 address (2 bytes).
        src:         Source DNP3 address (2 bytes).
        is_response: True when the outstation is responding to the master.

    Returns:
        One or more concatenated link-layer frames ready to write to the socket.
    """
    ctrl = _CTRL_SECONDARY if is_response else _CTRL_PRIMARY
    result = b""
    # Split into 250-byte chunks; each becomes one link-layer frame
    for i in range(0, max(1, len(app_bytes)), _MAX_DATA):
        result += _encode_single(app_bytes[i : i + _MAX_DATA], dest, src, ctrl)
    return result


def decode_frame(data: bytes) -> bytes:
    """Strip DNP3 link-layer framing and return the reassembled app-layer payload.

    Processes as many consecutive frames as are present in *data*, validating
    start bytes and CRCs for each.  Returns b"" if the first frame is invalid
    or *data* is too short to contain even a header.
    """
    app_bytes = b""
    pos = 0

    while pos < len(data):
        # Need at least a 10-byte header
        if pos + 10 > len(data):
            break
        if data[pos] != 0x05 or data[pos + 1] != 0x64:
            break

        # Verify header CRC (covers the 8 bytes before the CRC pair)
        header_end = pos + 8
        if _crc(data[pos:header_end]) != int.from_bytes(
            data[header_end : header_end + 2], "little"
        ):
            break

        length = data[pos + 2]
        user_data_len = length - 5  # subtract ctrl(1) + dest(2) + src(2)
        if user_data_len < 0:
            break

        # Decode data blocks for this frame
        block_pos = pos + 10
        remaining = user_data_len
        while remaining > 0:
            block_len = min(remaining, _BLOCK_SIZE)
            if block_pos + block_len + 2 > len(data):
                return app_bytes if app_bytes else b""  # truncated mid-frame
            block = data[block_pos : block_pos + block_len]
            block_crc = int.from_bytes(
                data[block_pos + block_len : block_pos + block_len + 2], "little"
            )
            if _crc(block) != block_crc:
                return app_bytes if app_bytes else b""  # CRC error
            app_bytes += block
            block_pos += block_len + 2
            remaining -= block_len

        pos = block_pos  # advance past this frame

    return app_bytes
