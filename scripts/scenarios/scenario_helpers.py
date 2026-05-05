"""Shared helpers for adversary simulation scenarios.

Provides functions for connecting to the outstation, sending DNP3 commands,
and writing structured results.

NOTE: The dnp3py master's DefaultSOEHandler does not correctly parse
integrity poll responses over TCP (known qualifier mismatch — see
test_basic.py line 417). State changes from control commands are verified
via the outstation's terminal monitor and the unit test suite. The
scenarios focus on command execution and response validation.
"""

import asyncio
import datetime
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "dnp3-sim"))

from dnp3.master import DefaultSOEHandler, Master
from dnp3.transport_io.channel import TcpConfig
from dnp3.transport_io.tcp_client import TcpClientChannel
from dnp3_frame import MASTER_ADDR, OUTSTATION_ADDR, decode_frame, encode_frame

HOST = os.environ.get("OUTSTATION_HOST", "127.0.0.1")
PORT = int(os.environ.get("OUTSTATION_PORT", "20000"))

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "scenarios"


@dataclass
class ScenarioStep:
    """One step in a scenario execution log."""

    action: str
    detail: str
    response: str = ""
    timestamp: str = ""


@dataclass
class ScenarioResult:
    """Complete result of a scenario run."""

    name: str
    description: str
    attck_tactic: str
    timestamp: str = ""
    steps: list[ScenarioStep] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    passed: bool = False


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


async def connect(host: str = HOST, port: int = PORT) -> TcpClientChannel:
    """Open a TCP connection to the outstation."""
    channel = TcpClientChannel(config=TcpConfig(host=host, port=port))
    await channel.open()
    return channel


async def _recv_framed(channel: TcpClientChannel, timeout: float = 5.0) -> bytes:
    """Read chunks until a complete link-layer frame arrives; return app-layer bytes."""
    buf = bytearray()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        remaining = deadline - loop.time()
        chunk = await asyncio.wait_for(channel.read(4096), timeout=remaining)
        if not chunk:
            break
        buf.extend(chunk)
        app_data = decode_frame(bytes(buf))
        if app_data:
            if len(app_data) >= 2 and (app_data[1] & 0x80 != 0):
                app_data = app_data[1:]
            return app_data
    return b""


def _send_framed(request_bytes: bytes) -> bytes:
    return encode_frame(request_bytes, dest=OUTSTATION_ADDR, src=MASTER_ADDR)


async def send_integrity_poll(channel: TcpClientChannel) -> str:
    """Send an integrity poll and return the response function name."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    request = master.build_integrity_poll()
    await channel.write_all(_send_framed(request.to_bytes()))
    app_data = await _recv_framed(channel)
    info = master.process_response(app_data)
    return info.function.name if info else "none"


async def direct_operate_binary(
    channel: TcpClientChannel, index: int, latch_on: bool
) -> str:
    """Send a DIRECT_OPERATE command to a binary output.

    Returns the response function name.
    """
    handler = DefaultSOEHandler()
    master = Master(handler=handler)

    builder = master.command_builder()
    if latch_on:
        builder.latch_on(index=index)
    else:
        builder.latch_off(index=index)

    request = master.build_direct_operate(builder.build_direct_operate())
    await channel.write_all(_send_framed(request.to_bytes()))
    app_data = await _recv_framed(channel)
    info = master.process_response(app_data)
    return info.function.name if info else "none"


async def select_operate_binary(
    channel: TcpClientChannel, index: int, latch_on: bool
) -> tuple[str, str]:
    """Send a SELECT then OPERATE sequence to a binary output.

    Returns (select_response, operate_response) function names.
    """
    handler = DefaultSOEHandler()
    master = Master(handler=handler)

    builder = master.command_builder()
    if latch_on:
        builder.latch_on(index=index)
    else:
        builder.latch_off(index=index)

    # SELECT
    select_req = master.build_select(builder.build_select())
    await channel.write_all(_send_framed(select_req.to_bytes()))
    sel_data = await _recv_framed(channel)
    sel_info = master.process_response(sel_data)

    # OPERATE
    operate_req = master.build_operate(builder.build_operate())
    await channel.write_all(_send_framed(operate_req.to_bytes()))
    op_data = await _recv_framed(channel)
    op_info = master.process_response(op_data)

    return (
        sel_info.function.name if sel_info else "none",
        op_info.function.name if op_info else "none",
    )


async def send_class_poll(
    channel: TcpClientChannel,
    class_1: bool = True,
    class_2: bool = True,
    class_3: bool = True,
) -> str:
    """Send a class poll and return the response function name."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    request = master.build_class_poll(class_1=class_1, class_2=class_2, class_3=class_3)
    await channel.write_all(_send_framed(request.to_bytes()))
    app_data = await _recv_framed(channel)
    info = master.process_response(app_data)
    return info.function.name if info else "none"


async def send_delay_measure(channel: TcpClientChannel) -> str:
    """Send a DELAY_MEASURE request and return the response function name."""
    handler = DefaultSOEHandler()
    master = Master(handler=handler)
    request = master.build_delay_measure()
    await channel.write_all(_send_framed(request.to_bytes()))
    app_data = await _recv_framed(channel)
    info = master.process_response(app_data)
    return info.function.name if info else "none"


def save_result(result: ScenarioResult) -> Path:
    """Write a scenario result to tests/scenarios/ as JSON."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = result.name.lower().replace(" ", "_").replace("-", "_")
    path = RESULTS_DIR / f"{slug}.json"
    data = asdict(result)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    return path
