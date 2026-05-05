import asyncio
import os
import struct
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../dnp3-sim")))

from dnp3_read import DNP3Points, parse_dnp3_response

# ---------------------------------------------------------------------------
# Helpers — build synthetic DNP3 application-layer response bytes
# ---------------------------------------------------------------------------

# Standard response header: AC=0xC0 (FIR|FIN), FC=0x81 (RESPONSE), IIN=0x0000
_HDR = bytes([0xC0, 0x81, 0x00, 0x00])


def _block_0x17(group: int, variation: int, objects: list[tuple[int, bytes]]) -> bytes:
    """Build an object block with qualifier 0x17 (1-byte count, 1-byte index prefix)."""
    payload = b"".join(bytes([idx]) + data for idx, data in objects)
    return bytes([group, variation, 0x17, len(objects)]) + payload


def _block_0x28(group: int, variation: int, objects: list[tuple[int, bytes]]) -> bytes:
    """Build an object block with qualifier 0x28 (2-byte count, 2-byte index prefix)."""
    payload = b"".join(idx.to_bytes(2, "little") + data for idx, data in objects)
    count = len(objects).to_bytes(2, "little")
    return bytes([group, variation, 0x28]) + count + payload


def _block_0x00(group: int, variation: int, start: int, objects: list[bytes]) -> bytes:
    """Build an object block with qualifier 0x00 (1-byte start/stop, no prefix).

    Indices are implicit: start, start+1, ... start+len(objects)-1.
    """
    stop = start + len(objects) - 1
    return bytes([group, variation, 0x00, start, stop]) + b"".join(objects)


def _block_0x01(group: int, variation: int, start: int, objects: list[bytes]) -> bytes:
    """Build an object block with qualifier 0x01 (2-byte start/stop, no prefix)."""
    stop = start + len(objects) - 1
    return (
        bytes([group, variation, 0x01])
        + start.to_bytes(2, "little")
        + stop.to_bytes(2, "little")
        + b"".join(objects)
    )


def _ai(value: int, quality: int = 0x01) -> bytes:
    """g30v1 object data: 1 quality byte + 4-byte signed int32 LE."""
    return bytes([quality]) + struct.pack("<i", value)


def _bi(state: bool, quality: int = 0x01) -> bytes:
    """g1v2 / g10v2 object data: 1 flags byte (bit 7 = state)."""
    return bytes([(0x80 if state else 0x00) | quality])


def _event_ai(value: int, quality: int = 0x01) -> bytes:
    """g32v1 object data: same encoding as g30v1."""
    return _ai(value, quality)


# ---------------------------------------------------------------------------
# Unit tests — no server required
# ---------------------------------------------------------------------------


def test_empty_bytes_returns_empty_points():
    result = parse_dnp3_response(b"")
    assert result == DNP3Points()


def test_short_header_returns_empty_points():
    """Fewer than 4 bytes → can't even read the app header."""
    for n in range(4):
        result = parse_dnp3_response(bytes(n))
        assert result == DNP3Points(), f"failed for {n} bytes"


def test_header_only_returns_empty_points():
    """4-byte app header with no object blocks."""
    result = parse_dnp3_response(_HDR)
    assert result == DNP3Points()


def test_single_analog_input():
    data = _HDR + _block_0x17(30, 1, [(0, _ai(12))])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {0: 12.0}
    assert pts.binary_inputs == {}
    assert pts.binary_outputs == {}


def test_multiple_analog_inputs():
    data = _HDR + _block_0x17(30, 1, [(0, _ai(12)), (1, _ai(800))])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {0: 12.0, 1: 800.0}


def test_negative_analog_value():
    data = _HDR + _block_0x17(30, 1, [(0, _ai(-42))])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs[0] == -42.0


def test_zero_analog_value():
    data = _HDR + _block_0x17(30, 1, [(0, _ai(0))])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs[0] == 0.0


def test_max_int32_analog_value():
    data = _HDR + _block_0x17(30, 1, [(0, _ai(2**31 - 1))])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs[0] == float(2**31 - 1)


def test_binary_input_state_true():
    data = _HDR + _block_0x17(1, 2, [(0, _bi(True))])
    pts = parse_dnp3_response(data)
    assert pts.binary_inputs == {0: True}


def test_binary_input_state_false():
    data = _HDR + _block_0x17(1, 2, [(0, _bi(False))])
    pts = parse_dnp3_response(data)
    assert pts.binary_inputs == {0: False}


def test_binary_output_state_true():
    data = _HDR + _block_0x17(10, 2, [(0, _bi(True))])
    pts = parse_dnp3_response(data)
    assert pts.binary_outputs == {0: True}


def test_binary_output_state_false():
    data = _HDR + _block_0x17(10, 2, [(0, _bi(False))])
    pts = parse_dnp3_response(data)
    assert pts.binary_outputs == {0: False}


def test_multiple_binary_outputs():
    data = _HDR + _block_0x17(10, 2, [(0, _bi(True)), (1, _bi(False))])
    pts = parse_dnp3_response(data)
    assert pts.binary_outputs == {0: True, 1: False}


def test_all_types_in_one_response():
    data = (
        _HDR
        + _block_0x17(1, 2, [(0, _bi(False)), (1, _bi(True))])
        + _block_0x17(10, 2, [(0, _bi(True)), (1, _bi(True))])
        + _block_0x17(30, 1, [(0, _ai(12)), (1, _ai(800))])
    )
    pts = parse_dnp3_response(data)
    assert pts.binary_inputs == {0: False, 1: True}
    assert pts.binary_outputs == {0: True, 1: True}
    assert pts.analog_inputs == {0: 12.0, 1: 800.0}


def test_analog_events_are_skipped():
    """g32v1 events must not land in analog_inputs; g30v1 static values must follow."""
    data = (
        _HDR
        + _block_0x17(32, 1, [(0, _event_ai(999)), (1, _event_ai(888))])
        + _block_0x17(30, 1, [(0, _ai(12)), (1, _ai(54))])
    )
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {0: 12.0, 1: 54.0}


def test_binary_input_events_are_skipped():
    """g2v1 binary events are skipped; static g1v2 values follow."""
    data = (
        _HDR
        + _block_0x17(2, 1, [(0, _bi(True)), (1, _bi(True))])
        + _block_0x17(1, 2, [(0, _bi(False)), (1, _bi(True))])
    )
    pts = parse_dnp3_response(data)
    assert pts.binary_inputs == {0: False, 1: True}


def test_realistic_response_order():
    """Mirrors the actual outstation response: g32v1 events, g1v2, g10v2, g30v1."""
    data = (
        _HDR
        + _block_0x17(32, 1, [(i, _event_ai(i * 10)) for i in range(10)])
        + _block_0x17(1, 2, [(0, _bi(False))])
        + _block_0x17(10, 2, [(0, _bi(True)), (1, _bi(True))])
        + _block_0x17(30, 1, [(0, _ai(12)), (1, _ai(200))])
    )
    pts = parse_dnp3_response(data)
    assert pts.binary_inputs == {0: False}
    assert pts.binary_outputs == {0: True, 1: True}
    assert pts.analog_inputs == {0: 12.0, 1: 200.0}


def test_zero_count_block_is_handled():
    """A block with count=0 must not produce any points and parsing continues."""
    data = (
        _HDR
        + _block_0x17(32, 1, [])  # count=0 event block
        + _block_0x17(30, 1, [(0, _ai(7))])
    )
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {0: 7.0}


def test_unknown_qualifier_stops_parsing_early():
    """An unrecognised qualifier (e.g. 0x06 = all-objects) stops the loop.
    Any points decoded before the unknown block are preserved."""
    # Qualifier 0x06 = all-objects (no count, no range) — not supported here
    bad_block = bytes([30, 1, 0x06])
    data = (
        _HDR
        + _block_0x17(10, 2, [(0, _bi(True))])
        + bad_block
        + _block_0x17(30, 1, [(0, _ai(99))])  # should not be reached
    )
    pts = parse_dnp3_response(data)
    assert pts.binary_outputs == {0: True}
    assert pts.analog_inputs == {}  # not reached after bad block


def test_unknown_group_variation_stops_parsing():
    """An unknown (group, variation) stops the loop to avoid advancing past
    an unknown-size object. Previously decoded values are preserved."""
    data = (
        _HDR
        + _block_0x17(10, 2, [(0, _bi(True))])
        + _block_0x17(99, 99, [(0, b"\x00")])  # unknown g99v99
        + _block_0x17(30, 1, [(0, _ai(5))])  # should not be reached
    )
    pts = parse_dnp3_response(data)
    assert pts.binary_outputs == {0: True}
    assert pts.analog_inputs == {}


def test_truncated_data_mid_block_header():
    """If the data ends in the middle of an object block header, return what we have."""
    full = _HDR + _block_0x17(30, 1, [(0, _ai(12))])
    # Cut off after app header + 1 byte of object header (only group byte)
    truncated = full[:5]  # 4-byte app header + 1 byte of the 3-byte obj header
    pts = parse_dnp3_response(truncated)
    assert pts.analog_inputs == {}


def test_truncated_data_mid_object():
    """If the data ends partway through an object, partial object is discarded."""
    full = _HDR + _block_0x17(30, 1, [(0, _ai(12)), (1, _ai(800))])
    # Keep everything up to the first complete object + partial second
    # Full: hdr(4) + g/v/q(3) + count(1) + obj0(6) + partial obj1 = 14+some
    truncated = full[:-3]  # cut last 3 bytes of obj1
    pts = parse_dnp3_response(truncated)
    # obj0 (index 0) is complete, obj1 is incomplete — only obj0 should decode
    assert pts.analog_inputs == {0: 12.0}


def test_qualifier_0x28_two_byte_index():
    """Qualifier 0x28 uses 2-byte count and 2-byte index; must parse correctly."""
    data = _HDR + _block_0x28(30, 1, [(256, _ai(42)), (257, _ai(99))])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {256: 42.0, 257: 99.0}


def test_qualifier_0x28_binary_output():
    data = _HDR + _block_0x28(10, 2, [(300, _bi(True)), (301, _bi(False))])
    pts = parse_dnp3_response(data)
    assert pts.binary_outputs == {300: True, 301: False}


def test_non_contiguous_indices():
    """Points at non-sequential indices must map to their explicit index."""
    data = _HDR + _block_0x17(30, 1, [(0, _ai(10)), (5, _ai(50)), (9, _ai(90))])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {0: 10.0, 5: 50.0, 9: 90.0}


def test_quality_byte_does_not_affect_value():
    """Different quality bytes should not change the decoded integer value."""
    data_online = _HDR + _block_0x17(30, 1, [(0, _ai(12, quality=0x01))])
    data_offline = _HDR + _block_0x17(30, 1, [(0, _ai(12, quality=0x00))])
    assert parse_dnp3_response(data_online).analog_inputs[0] == 12.0
    assert parse_dnp3_response(data_offline).analog_inputs[0] == 12.0


def test_only_flags_bit7_determines_binary_state():
    """Bits 0-6 of the flags byte are quality; only bit 7 is the state."""
    # 0x7F = all quality bits set, state = False
    data_false = _HDR + _block_0x17(10, 2, [(0, bytes([0x7F]))])
    # 0xFF = all bits set, state = True
    data_true = _HDR + _block_0x17(10, 2, [(0, bytes([0xFF]))])
    assert parse_dnp3_response(data_false).binary_outputs[0] is False
    assert parse_dnp3_response(data_true).binary_outputs[0] is True


def test_returns_dnp3points_type():
    result = parse_dnp3_response(_HDR)
    assert isinstance(result, DNP3Points)


def test_qualifier_0x00_binary_input_range():
    """Qualifier 0x00: indices implicit from start/stop, no per-object prefix."""
    data = _HDR + _block_0x00(1, 2, start=0, objects=[_bi(False), _bi(True)])
    pts = parse_dnp3_response(data)
    assert pts.binary_inputs == {0: False, 1: True}


def test_qualifier_0x00_binary_output_range():
    data = _HDR + _block_0x00(10, 2, start=0, objects=[_bi(True), _bi(False)])
    pts = parse_dnp3_response(data)
    assert pts.binary_outputs == {0: True, 1: False}


def test_qualifier_0x00_analog_input_range():
    data = _HDR + _block_0x00(30, 1, start=0, objects=[_ai(12), _ai(800)])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {0: 12.0, 1: 800.0}


def test_qualifier_0x00_non_zero_start():
    """Implicit indices begin at the start byte, not at 0."""
    data = _HDR + _block_0x00(30, 1, start=5, objects=[_ai(50), _ai(60)])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {5: 50.0, 6: 60.0}


def test_qualifier_0x01_two_byte_range():
    """Qualifier 0x01: 2-byte start/stop, no per-object prefix."""
    data = _HDR + _block_0x01(30, 1, start=300, objects=[_ai(7), _ai(8)])
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {300: 7.0, 301: 8.0}


def test_outstation_response_layout():
    """Mirrors the actual outstation: g32v1 events (0x17), then static
    g1v2 / g10v2 / g30v1 in 0x00 range format. Previously the parser bailed
    at the first 0x00 block and returned no points."""
    data = (
        _HDR
        + _block_0x17(32, 1, [(0, _event_ai(999))])
        + _block_0x00(1, 2, start=0, objects=[_bi(False), _bi(True)])
        + _block_0x00(10, 2, start=0, objects=[_bi(True), _bi(True)])
        + _block_0x00(30, 1, start=0, objects=[_ai(12), _ai(800)])
    )
    pts = parse_dnp3_response(data)
    assert pts.binary_inputs == {0: False, 1: True}
    assert pts.binary_outputs == {0: True, 1: True}
    assert pts.analog_inputs == {0: 12.0, 1: 800.0}


def test_truncated_before_count_byte_returns_empty():
    """Block has group/var/qualifier but count byte is missing → break."""
    # _HDR (4 bytes) + group(1)+var(1)+qual(1) but no count byte
    data = _HDR + bytes([30, 1, 0x17])  # 7 bytes total, count byte absent
    pts = parse_dnp3_response(data)
    assert pts.analog_inputs == {}


# ---------------------------------------------------------------------------
# Integration test — requires the simulator server on 127.0.0.1:20000
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_integrity_poll_returns_sensible_values():
    """Connect to the running outstation, send an integrity poll, and verify
    the decoded values fall within expected operating ranges."""
    from dnp3.master import Master
    from dnp3.transport_io.channel import TcpConfig
    from dnp3.transport_io.tcp_client import TcpClientChannel

    import os
    import sys

    sys.path.insert(
        0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../dnp3-sim"))
    )
    from dnp3_frame import MASTER_ADDR, OUTSTATION_ADDR, decode_frame, encode_frame

    if os.environ.get("RUN_LIVE_DNP3_TESTS") != "1":
        pytest.skip("set RUN_LIVE_DNP3_TESTS=1 to run live outstation tests")

    host = os.environ.get("OUTSTATION_HOST", "127.0.0.1")
    port = int(os.environ.get("OUTSTATION_PORT", "20000"))

    master = Master()
    channel = TcpClientChannel(config=TcpConfig(host=host, port=port))

    try:
        await asyncio.wait_for(channel.open(), timeout=5.0)
    except Exception:
        pytest.skip(f"Outstation not reachable on {host}:{port}")

    try:
        framed_req = encode_frame(
            master.build_integrity_poll().to_bytes(),
            dest=OUTSTATION_ADDR,
            src=MASTER_ADDR,
        )
        await channel.write_all(framed_req)
        # Read in a loop until the FIN bit (0x40) is set in the decoded app
        # control byte — strips link-layer framing added for Wireshark visibility.
        raw = b""
        data = b""
        while True:
            chunk = await asyncio.wait_for(channel.read(16384), timeout=5.0)
            raw += chunk
            app = decode_frame(raw)
            if app and app[0] & 0x40:
                data = app
                break
    finally:
        await channel.close()

    pts = parse_dnp3_response(data)

    # Must have decoded both analog inputs
    assert 0 in pts.analog_inputs, "AI[0] (voltage) missing"
    assert 1 in pts.analog_inputs, "AI[1] (load) missing"

    # Voltage: 0 kV (open breaker/no gen) to 13 kV (nominal ~12.47 kV)
    v = pts.analog_inputs[0]
    assert 0.0 <= v <= 13.0, f"AI[0] voltage out of range: {v}"

    # Load: 100–1500 kW per the simulator clamp
    p = pts.analog_inputs[1]
    assert 0.0 <= p <= 1500.0, f"AI[1] load out of range: {p}"

    # Must have both binary outputs (breaker and generator)
    assert 0 in pts.binary_outputs, "BO[0] (breaker) missing"
    assert 1 in pts.binary_outputs, "BO[1] (generator) missing"

    assert isinstance(pts.binary_outputs[0], bool)
    assert isinstance(pts.binary_outputs[1], bool)
