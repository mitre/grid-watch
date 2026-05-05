"""Custom DNP3 response parser for the grid simulator outstation.

The outstation responds with a mix of qualifiers depending on the object:
event blocks use the indexed-count format (0x17), while static binary and
analog blocks use the start/stop range format (0x00) with no per-object
index prefix. The parser handles both, plus their 2-byte variants.

Supported group/variations:

  g1v2  — Binary Input with flags      (1 byte per object)
  g10v2 — Binary Output with flags     (1 byte per object)
  g30v1 — Analog Input 32-bit w/flag   (5 bytes: 1 quality + 4 int32 LE)
  g32v1 — Analog Input Event 32-bit    (5 bytes, skipped)
  g2v1  — Binary Input Event           (1 byte,  skipped)

Supported qualifiers:

  0x00 — 1-byte start + 1-byte stop, no per-object index prefix
  0x01 — 2-byte start + 2-byte stop, no per-object index prefix
  0x17 — 1-byte count  + 1-byte index prefix per object
  0x28 — 2-byte count  + 2-byte index prefix per object

Analog values are truncated to int32 by the outstation's g30v1 encoding,
so voltage reads as a whole-number kV (e.g. 12 instead of 12.47).

This module replaces the broken qualifier parsing in the dnp3py library.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Response application header: AC (1) + FC (1) + IIN (2) = 4 bytes
_APP_HEADER = 4
# Object block header: group (1) + variation (1) + qualifier (1) = 3 bytes
_OBJ_HEADER = 3

# Binary state bit in the flags byte
_STATE_BIT = 0x80

# Data bytes per object for every group/variation this outstation sends.
# Events are included so we can skip past them cleanly.
_OBJ_SIZE: dict[tuple[int, int], int] = {
    (1, 2): 1,  # g1v2:  binary input with flags
    (2, 1): 1,  # g2v1:  binary input event
    (10, 2): 1,  # g10v2: binary output with flags
    (11, 1): 1,  # g11v1: binary output event
    (20, 1): 5,  # g20v1: counter 32-bit with flags
    (22, 1): 5,  # g22v1: counter event 32-bit
    (30, 1): 5,  # g30v1: analog input 32-bit with flags
    (32, 1): 5,  # g32v1: analog input event 32-bit
}


@dataclass
class DNP3Points:
    """Point values decoded from a DNP3 response.

    Attributes:
        analog_inputs:  index -> float (g30v1, truncated to int by outstation)
        binary_inputs:  index -> bool  (g1v2)
        binary_outputs: index -> bool  (g10v2)
    """

    analog_inputs: dict[int, float] = field(default_factory=dict)
    binary_inputs: dict[int, bool] = field(default_factory=dict)
    binary_outputs: dict[int, bool] = field(default_factory=dict)


def parse_dnp3_response(data: bytes) -> DNP3Points:
    """Parse point values from a DNP3 application-layer response.

    Handles the start/stop range format (qualifier 0x00 / 0x01) and the
    indexed-count format (qualifier 0x17 / 0x28). Parsing stops early on an
    unrecognised qualifier, unknown group/variation, or truncated object.

    Args:
        data: Raw application-layer bytes from TcpClientChannel.read().

    Returns:
        DNP3Points populated with whatever values were decoded.
    """
    result = DNP3Points()

    if len(data) < _APP_HEADER:
        return result

    offset = _APP_HEADER

    while offset + _OBJ_HEADER <= len(data):
        group = data[offset]
        variation = data[offset + 1]
        qualifier = data[offset + 2]
        offset += _OBJ_HEADER

        obj_size = _OBJ_SIZE.get((group, variation))
        if obj_size is None:
            break

        range_code = qualifier & 0x0F
        prefix_code = (qualifier >> 4) & 0x07

        # Determine count, per-object prefix size, and (for range qualifiers)
        # the explicit index list to use when objects carry no index prefix.
        indices: list[int] | None = None
        if prefix_code == 0x01 and range_code == 0x07:
            # 0x17: 1-byte count + 1-byte index prefix per object
            if offset + 1 > len(data):
                break
            count = data[offset]
            offset += 1
            prefix_size = 1
        elif prefix_code == 0x02 and range_code == 0x08:
            # 0x28: 2-byte count + 2-byte index prefix per object
            if offset + 2 > len(data):
                break
            count = int.from_bytes(data[offset : offset + 2], "little")
            offset += 2
            prefix_size = 2
        elif prefix_code == 0x00 and range_code == 0x00:
            # 0x00: 1-byte start + 1-byte stop, no per-object prefix
            if offset + 2 > len(data):
                break
            start, stop = data[offset], data[offset + 1]
            offset += 2
            count = stop - start + 1
            prefix_size = 0
            indices = list(range(start, stop + 1))
        elif prefix_code == 0x00 and range_code == 0x01:
            # 0x01: 2-byte start + 2-byte stop, no per-object prefix
            if offset + 4 > len(data):
                break
            start = int.from_bytes(data[offset : offset + 2], "little")
            stop = int.from_bytes(data[offset + 2 : offset + 4], "little")
            offset += 4
            count = stop - start + 1
            prefix_size = 0
            indices = list(range(start, stop + 1))
        else:
            break

        for i in range(count):
            if offset + prefix_size + obj_size > len(data):
                return result

            if indices is not None:
                idx = indices[i]
            elif prefix_size == 1:
                idx = data[offset]
            else:
                idx = int.from_bytes(data[offset : offset + 2], "little")
            offset += prefix_size

            obj = data[offset : offset + obj_size]
            offset += obj_size

            if group == 30 and variation == 1:  # g30v1: analog input
                result.analog_inputs[idx] = float(
                    int.from_bytes(obj[1:5], "little", signed=True)
                )
            elif group == 1 and variation == 2:  # g1v2: binary input
                result.binary_inputs[idx] = bool(obj[0] & _STATE_BIT)
            elif group == 10 and variation == 2:  # g10v2: binary output
                result.binary_outputs[idx] = bool(obj[0] & _STATE_BIT)
            # Event objects (g32v1, g2v1, etc.) are skipped

    return result
