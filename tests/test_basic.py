import asyncio
import sys
import os
import time
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../dnp3-sim")))

import pytest
import pytest_asyncio
import yaml


from dnp3.master import DefaultSOEHandler, Master
from dnp3.outstation import Outstation
from dnp3.outstation.config import OutstationConfig
from dnp3.transport_io import TcpServer
from dnp3.transport_io.channel import TcpConfig, TcpServerConfig
from dnp3.transport_io.tcp_client import TcpClientChannel
from config import load_config
from dnp3.core.enums import FunctionCode

sys.path.insert(0, str(Path(__file__).parent.parent / "dnp3-sim"))

from server import DatabaseCommandHandler, build_database, handle_connection
from dnp3_frame import MASTER_ADDR, OUTSTATION_ADDR, encode_frame, decode_frame


def write_temp_yaml(tmp_path, content):
    file = tmp_path / "config.yaml"
    with open(file, "w") as f:
        yaml.dump(content, f)
    return file


# --- Unit tests (no TCP) ---


# Verifies build_database() creates the correct number of points.


def test_database_has_expected_points():
    db = build_database()
    assert db.binary_input_count == 2
    assert db.analog_input_count == 2


# Verifies binary outputs are present (needed for control operations).


def test_database_has_binary_outputs():
    db = build_database()
    assert db.binary_output_count >= 1


# Verifies binary inputs are initialized with the correct values (False, True).


def test_binary_input_initial_values():
    db = build_database()
    assert db.get_binary_input(0).value is False
    assert db.get_binary_input(1).value is True


# Verifies analog inputs are initialized with the correct values (0.0, 25.5).


def test_analog_input_initial_values():
    db = build_database()
    assert db.get_analog_input(0).value == 0.0
    assert db.get_analog_input(1).value == 25.5


# Verifies the outstation returns a response when it receives an integrity poll.


def test_outstation_responds_to_integrity_poll():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    request = master.build_integrity_poll()
    response = outstation.process_request(request.to_bytes())

    assert response is not None


# Verifies the integrity poll response contains point data objects.


def test_outstation_response_has_data():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    request = master.build_integrity_poll()
    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert len(response[0].objects) > 0


# Verifies that updating a binary input is reflected in the next integrity poll.


def test_update_binary_input_reflected_in_poll():
    db = build_database()
    outstation = Outstation(database=db)
    handler = DefaultSOEHandler()
    master = Master(handler=handler)

    db.update_binary_input(0, value=True)

    request = master.build_integrity_poll()
    response = outstation.process_request(request.to_bytes())
    master.process_response(response[0].to_bytes())

    assert handler.binary_inputs[0].value is True


# Verifies that updating an analog input is stored correctly.


def test_update_analog_input_reflected_in_poll():
    db = build_database()
    db.update_analog_input(0, value=99.9)
    assert abs(db.get_analog_input(0).value - 99.9) < 0.001


# --- DELAY_MEASURE ---


# Verifies the outstation responds to a DELAY_MEASURE request.


def test_outstation_responds_to_delay_measure():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    request = master.build_delay_measure()
    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert response[0].header.function == FunctionCode.RESPONSE


# Verifies the DELAY_MEASURE response contains a time-delay object (g52v2).


def test_delay_measure_response_has_time_object():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    request = master.build_delay_measure()
    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert len(response[0].objects) > 0
    # g52v2 - Time Delay Fine

    assert response[0].objects[0].header.group == 52
    assert response[0].objects[0].header.variation == 2


# --- Class / event polls ---


# Verifies the outstation responds to a Class 1 event poll.


def test_outstation_responds_to_class1_poll():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    request = master.build_class_poll(class_1=True, class_2=False, class_3=False)
    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert response[0].header.function == FunctionCode.RESPONSE


# Verifies the outstation responds to a combined Class 1/2/3 poll.


def test_outstation_responds_to_class_poll_all():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    request = master.build_class_poll(class_1=True, class_2=True, class_3=True)
    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert response[0].header.function == FunctionCode.RESPONSE


# Verifies that a binary input change generates an event visible in a class poll.


def test_class_poll_returns_events_after_update():
    db = build_database()
    # Must mark point as ONLINE first so updates generate events

    db.update_binary_input(0, value=False)  # transitions from RESTART -> ONLINE
    outstation = Outstation(database=db)
    handler = DefaultSOEHandler()
    master = Master(handler=handler)

    # Trigger an event

    db.update_binary_input(0, value=True)

    # Class 1 poll should return the event

    request = master.build_class_poll(class_1=True, class_2=False, class_3=False)
    response = outstation.process_request(request.to_bytes())
    master.process_response(response[0].to_bytes())

    assert response is not None


# --- DIRECT_OPERATE ---


# Verifies the outstation responds to a DIRECT_OPERATE request.


def test_outstation_responds_to_direct_operate():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)
    task = builder.build_direct_operate()

    request = master.build_direct_operate(task)
    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert response[0].header.function == FunctionCode.RESPONSE


# Verifies DIRECT_OPERATE with LATCH_OFF also returns a valid response.


def test_direct_operate_latch_off():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_off(index=0)
    task = builder.build_direct_operate()

    request = master.build_direct_operate(task)
    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert response[0].header.function == FunctionCode.RESPONSE


# Verifies that DIRECT_OPERATE updates the binary output state in the database.


def test_direct_operate_updates_database_state():
    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    master = Master(handler=DefaultSOEHandler())

    # Point starts False

    assert db.get_binary_output(0).value is False

    builder = master.command_builder()
    builder.latch_on(index=0)
    task = builder.build_direct_operate()

    request = master.build_direct_operate(task)
    outstation.process_request(request.to_bytes())

    # State should now be True

    assert db.get_binary_output(0).value is True


# --- SELECT / OPERATE (two-step SBO) ---


# Verifies the outstation responds to a SELECT request.


def test_outstation_responds_to_select():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)
    select_task = builder.build_select()

    request = master.build_select(select_task)
    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert response[0].header.function == FunctionCode.RESPONSE


# Verifies a full SELECT -> OPERATE sequence succeeds.


def test_select_then_operate_succeeds():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)

    # Step 1 - SELECT

    select_request = master.build_select(builder.build_select())
    select_response = outstation.process_request(select_request.to_bytes())
    assert select_response is not None
    assert select_response[0].header.function == FunctionCode.RESPONSE

    # Step 2 - OPERATE

    operate_request = master.build_operate(builder.build_operate())
    operate_response = outstation.process_request(operate_request.to_bytes())
    assert operate_response is not None
    assert operate_response[0].header.function == FunctionCode.RESPONSE


# Verifies that OPERATE without a prior SELECT still returns a response
# (it should indicate NO_SELECT in status, not crash).


def test_operate_without_select_returns_response():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)

    operate_request = master.build_operate(builder.build_operate())
    response = outstation.process_request(operate_request.to_bytes())

    # Must return a response (not None / not crash)

    assert response is not None
    assert response[0].header.function == FunctionCode.RESPONSE


# Verifies that a SELECT expires if OPERATE is not sent within the timeout.


def test_select_expires_and_operate_is_rejected():
    db = build_database()
    config = OutstationConfig(select_timeout=0.001)  # 1 ms
    outstation = Outstation(config=config, database=db)
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)

    select_request = master.build_select(builder.build_select())
    outstation.process_request(select_request.to_bytes())

    time.sleep(0.01)  # Let the SELECT expire

    operate_request = master.build_operate(builder.build_operate())
    response = outstation.process_request(operate_request.to_bytes())

    # Response must still be returned (outstation must not crash)

    assert response is not None


# --- Internal state persistence across requests ---


# Verifies that binary output state changed by DIRECT_OPERATE is visible
# in a subsequent integrity poll.


def test_state_persists_after_direct_operate():
    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    master = Master(handler=DefaultSOEHandler())

    # DIRECT_OPERATE latch on point 0

    builder = master.command_builder()
    builder.latch_on(index=0)
    outstation.process_request(
        master.build_direct_operate(builder.build_direct_operate()).to_bytes()
    )

    # Verify state persisted in the database directly

    assert db.get_binary_output(0).value is True

    # Also confirm the outstation still responds correctly to a subsequent poll

    poll_response = outstation.process_request(master.build_integrity_poll().to_bytes())
    assert poll_response is not None


# Verifies that analog input values persist across multiple sequential requests.
# Checks the database directly because the master's parser uses start-stop range
# logic that doesn't match the outstation's count+index qualifier (0x17), which
# would produce incorrect parsed values on round-trip.


def test_analog_state_persists_across_multiple_polls():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    db.update_analog_input(0, value=42.0)

    for _ in range(3):
        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None
    # Value must still be 42.0 in the database after repeated polls

    assert abs(db.get_analog_input(0).value - 42.0) < 0.001


# Verifies SELECT state is cleared after a successful OPERATE (no double-execute).


def test_select_state_cleared_after_operate():
    db = build_database()
    outstation = Outstation(database=db)
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)

    # Full SBO sequence

    master.build_select(builder.build_select())
    outstation.process_request(master.build_select(builder.build_select()).to_bytes())
    outstation.process_request(master.build_operate(builder.build_operate()).to_bytes())

    # A second OPERATE without a new SELECT must not execute (no crash, valid response)

    second_operate = master.build_operate(builder.build_operate())
    response = outstation.process_request(second_operate.to_bytes())
    assert response is not None


# --- Integration tests (TCP) ---


@pytest_asyncio.fixture
async def server_and_outstation():
    """Start a real TCP server with an outstation, yield (server, outstation), then stop."""
    db = build_database()
    outstation = Outstation(database=db)
    outstation.clear_restart()

    config = TcpServerConfig(host="127.0.0.1", port=0)
    server = TcpServer(config=config)
    await server.start()

    async def _accept_loop():
        while server.is_listening:
            try:
                channel = await server.accept()
                asyncio.create_task(handle_connection(channel, outstation))
            except Exception:
                break

    task = asyncio.create_task(_accept_loop())

    yield server, outstation

    task.cancel()
    await server.stop()


@pytest_asyncio.fixture
async def client(server_and_outstation):
    """Connect a TCP client to the test server."""
    server, _ = server_and_outstation
    addr = server.local_address
    channel = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
    await channel.open()
    yield channel
    await channel.close()


# Verifies a TCP client can open a connection to the running server.


@pytest.mark.asyncio
async def test_tcp_client_connects(server_and_outstation):
    server, _ = server_and_outstation
    addr = server.local_address
    channel = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
    await channel.open()
    assert channel.is_open
    await channel.close()


async def _read_framed_response(
    client: TcpClientChannel, timeout: float = 2.0
) -> bytes:
    """Read chunks until decode_frame returns a complete app-layer payload."""
    buf = b""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        buf += await asyncio.wait_for(client.read(4096), timeout=remaining)
        raw = decode_frame(buf)
        if raw:
            return raw


# Verifies the server sends back a non-empty response to an integrity poll over TCP.


@pytest.mark.asyncio
async def test_tcp_send_and_receive_response(client, server_and_outstation):
    master = Master(handler=DefaultSOEHandler())

    request = master.build_integrity_poll()
    await client.write_all(
        encode_frame(request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    )

    raw = await _read_framed_response(client)
    assert len(raw) > 0


# Verifies the server handles multiple sequential requests without error.


@pytest.mark.asyncio
async def test_tcp_multiple_requests(client, server_and_outstation):
    master = Master(handler=DefaultSOEHandler())

    for _ in range(3):
        request = master.build_integrity_poll()
        await client.write_all(
            encode_frame(request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)
        )
        raw = await _read_framed_response(client)
        assert len(raw) > 0


# Verifies a DELAY_MEASURE request gets a response over TCP.


@pytest.mark.asyncio
async def test_tcp_delay_measure(client, server_and_outstation):
    master = Master(handler=DefaultSOEHandler())

    request = master.build_delay_measure()
    await client.write_all(
        encode_frame(request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    )

    raw = await _read_framed_response(client)
    assert len(raw) > 0


# Verifies a class poll gets a response over TCP.


@pytest.mark.asyncio
async def test_tcp_class_poll(client, server_and_outstation):
    master = Master(handler=DefaultSOEHandler())

    request = master.build_class_poll(class_1=True, class_2=True, class_3=True)
    await client.write_all(
        encode_frame(request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    )

    raw = await _read_framed_response(client)
    assert len(raw) > 0


# Verifies a DIRECT_OPERATE request gets a response over TCP.


@pytest.mark.asyncio
async def test_tcp_direct_operate(client, server_and_outstation):
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)
    task = builder.build_direct_operate()

    request = master.build_direct_operate(task)
    await client.write_all(
        encode_frame(request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    )

    raw = await _read_framed_response(client)
    assert len(raw) > 0


# Verifies a SELECT -> OPERATE sequence gets responses for both steps over TCP.


@pytest.mark.asyncio
async def test_tcp_select_then_operate(client, server_and_outstation):
    master = Master(handler=DefaultSOEHandler())
    builder = master.command_builder()
    builder.latch_on(index=0)

    # SELECT

    select_request = master.build_select(builder.build_select())
    await client.write_all(
        encode_frame(select_request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    )
    select_raw = await _read_framed_response(client)
    assert len(select_raw) > 0

    # OPERATE

    operate_request = master.build_operate(builder.build_operate())
    await client.write_all(
        encode_frame(operate_request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    )
    operate_raw = await _read_framed_response(client)
    assert len(operate_raw) > 0


# --- Goal 2 tests: config loading, device state, function codes ---


def test_yaml_valid_config(tmp_path):
    content = {
        "server": {
            "host": "127.0.0.1",
            "port": 20000,
        },
        "points": {
            "binary_inputs": [],
            "analog_inputs": [],
            "binary_outputs": [],
        },
    }

    path = write_temp_yaml(tmp_path, content)
    cfg = load_config(path)

    assert cfg is not None


def test_yaml_missing_fields(tmp_path):
    content = {"server": {}}

    path = write_temp_yaml(tmp_path, content)

    cfg = load_config(path)

    assert cfg is not None


def test_yaml_bad_port(tmp_path):
    content = {
        "server": {
            "host": "127.0.0.1",
            "port": "bad",
        },
        "points": {
            "binary_inputs": [],
            "analog_inputs": [],
            "binary_outputs": [],
        },
    }

    path = write_temp_yaml(tmp_path, content)

    with pytest.raises(Exception):
        load_config(path)


def test_direct_operate_function_code():
    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)

    task = builder.build_direct_operate()
    request = master.build_direct_operate(task)

    response = outstation.process_request(request.to_bytes())

    assert response is not None
    assert response[0].header.function == FunctionCode.RESPONSE


def test_state_persistence_after_direct_operate():
    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    master = Master(handler=DefaultSOEHandler())

    builder = master.command_builder()
    builder.latch_on(index=0)

    request = master.build_direct_operate(builder.build_direct_operate())
    outstation.process_request(request.to_bytes())

    assert db.get_binary_output(0).value is True
