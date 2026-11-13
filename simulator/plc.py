import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any

from dnp3.core.enums import ControlCode
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    BinaryOutputConfig,
    Database,
)
from dnp3.outstation import DefaultCommandHandler, Outstation
from dnp3.outstation.handler import CommandResult
from dnp3.transport_io import TcpServer
from dnp3.transport_io.channel import TcpServerConfig

from simulator.config import OutstationConfig as SimulatorConfig
from simulator.config import load_config
from simulator.dnp3_frame import (
    OUTSTATION_ADDR,
    MASTER_ADDR,
    decode_frame,
    encode_frame,
    encode_transport_frames,
)
from simulator.sim import GridProcessSim
from simulator.ui.terminal import EventLog, display_loop

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

MAX_BUFFER_BYTES = 32768


class DatabaseCommandHandler(DefaultCommandHandler):
    def __init__(self, database: Database) -> None:
        self._db = database

    def _apply_binary(self, index: int, code: ControlCode) -> CommandResult:
        new_value = code in (ControlCode.LATCH_ON, ControlCode.PULSE_ON)

        logger.info("CONTROL: BO[%d] <- %s (code=%s)", index, new_value, code.name)

        try:
            self._db.update_binary_output(index, value=new_value)
            return CommandResult.success()
        except KeyError:
            return CommandResult.not_supported(f"Binary output {index} not found")

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        if self._db.get_binary_output(index) is None:
            return CommandResult.not_supported(f"Binary output {index} not found")
        return CommandResult.success()

    def operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
        select_sequence: int,
    ) -> CommandResult:
        return self._apply_binary(index, code)

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        return self._apply_binary(index, code)


def build_database(cfg: SimulatorConfig | None = None) -> Database:
    db = Database()

    if cfg is None:
        db.add_binary_input(0, BinaryInputConfig(), value=False)
        db.add_binary_input(1, BinaryInputConfig(), value=True)
        db.add_analog_input(0, AnalogInputConfig(), value=0.0)
        db.add_analog_input(1, AnalogInputConfig(), value=25.5)
        db.add_binary_output(0, BinaryOutputConfig(), value=False)
        db.add_binary_output(1, BinaryOutputConfig(), value=False)
        return db

    for bi in cfg.points.binary_inputs:
        db.add_binary_input(bi.index, BinaryInputConfig(), value=bi.value)

    for ai in cfg.points.analog_inputs:
        db.add_analog_input(ai.index, AnalogInputConfig(), value=ai.value)

    for bo in cfg.points.binary_outputs:
        db.add_binary_output(bo.index, BinaryOutputConfig(), value=bo.value)

    return db


def _interactive() -> bool:
    """Return True when stdin is a terminal this process may read from.

    A background job (process group other than the terminal's) must not read
    stdin, or it is stopped with SIGTTIN. Windows has no process groups.
    """
    try:
        if not sys.stdin.isatty():
            return False
        if not hasattr(os, "tcgetpgrp"):
            return True
        return os.getpgrp() == os.tcgetpgrp(sys.stdin.fileno())
    except (AttributeError, OSError, ValueError):
        return False


def _handle_command(cmd: str, sim: GridProcessSim, db: Database) -> None:
    if cmd == "pause":
        sim.pause()
        logger.info("Simulation paused")

    elif cmd == "resume":
        sim.resume()
        logger.info("Simulation resumed")

    elif cmd == "reset":
        sim.reset(db)
        logger.info("Simulation reset to initial conditions")

    elif cmd == "g":
        _pt = db.get_binary_output(1)
        if _pt is None:
            logger.error("binary output 1 not initialized")
            return
        new_value = not _pt.value
        code = ControlCode.LATCH_ON if new_value else ControlCode.LATCH_OFF
        DatabaseCommandHandler(db)._apply_binary(1, code)
        logger.info("%s", "Turn Generator ON" if new_value else "Turn Generator OFF")

    elif cmd == "b":
        _pt = db.get_binary_output(0)
        if _pt is None:
            logger.error("binary output 0 not initialized")
            return
        new_value = not _pt.value
        code = ControlCode.LATCH_ON if new_value else ControlCode.LATCH_OFF
        DatabaseCommandHandler(db)._apply_binary(0, code)
        logger.info("%s", "Close Breaker" if new_value else "Open Breaker")

    elif cmd:
        logger.info("Unknown command: %s", cmd)


def _read_lines(
    loop: asyncio.AbstractEventLoop, lines: asyncio.Queue[str | None], fd: int
) -> None:
    while True:
        try:
            data = os.read(fd, 1024)
        except OSError:
            data = b""
        items: list[str | None] = (
            list(data.decode(errors="replace").splitlines()) if data else [None]
        )
        for item in items:
            try:
                loop.call_soon_threadsafe(lines.put_nowait, item)
            except RuntimeError:
                return
        if not data:
            return


async def command_listener(sim: GridProcessSim, db: Database) -> None:
    if not _interactive():
        return

    lines: asyncio.Queue[str | None] = asyncio.Queue()
    threading.Thread(
        target=_read_lines,
        args=(asyncio.get_running_loop(), lines, sys.stdin.fileno()),
        daemon=True,
    ).start()
    while (cmd := await lines.get()) is not None:
        _handle_command(cmd.strip().lower(), sim, db)


async def handle_connection(channel: Any, outstation: Outstation) -> None:
    logger.info("Client connected: %s", channel.remote_address)
    buf = b""
    try:
        while True:
            data = await channel.read(4096)
            if not data:
                break

            buf += data
            app_data = decode_frame(buf)
            if not app_data:
                if len(buf) > MAX_BUFFER_BYTES:
                    logger.warning(
                        "Discarding %d buffered bytes from %s: no valid frame",
                        len(buf),
                        channel.remote_address,
                    )
                    buf = b""
                continue
            buf = b""

            has_transport = len(app_data) >= 2 and (app_data[1] & 0x80 != 0)
            if has_transport:
                app_data = app_data[1:]

            for frag in outstation.process_request(app_data):
                resp_bytes = frag.to_bytes()
                if has_transport:
                    framed = encode_transport_frames(
                        resp_bytes,
                        dest=MASTER_ADDR,
                        src=OUTSTATION_ADDR,
                        is_response=True,
                    )
                else:
                    framed = encode_frame(
                        resp_bytes,
                        dest=MASTER_ADDR,
                        src=OUTSTATION_ADDR,
                        is_response=True,
                    )
                await channel.write_all(framed)

    finally:
        await channel.close()


async def serve(cfg: SimulatorConfig) -> None:  # pragma: no cover
    db = build_database(cfg)
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    outstation.clear_restart()
    db.clear_events()  # drop startup events before accepting connections

    server = TcpServer(
        config=TcpServerConfig(host=cfg.server.host, port=cfg.server.port)
    )
    await server.start()

    sim = GridProcessSim()
    tasks = [
        asyncio.create_task(sim.run(db)),
        asyncio.create_task(command_listener(sim, db)),
    ]

    root = logging.getLogger()
    handlers = root.handlers[:]
    if sys.stdout.isatty():
        events = EventLog()
        if handlers:
            events.setFormatter(handlers[0].formatter)
        root.handlers = [events]
        tasks.append(
            asyncio.create_task(display_loop(db, interval=1.0, sim=sim, events=events))
        )

    try:
        async with server:
            while True:
                channel = await server.accept()
                asyncio.create_task(handle_connection(channel, outstation))
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        root.handlers = handlers


def _interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)

    signal.signal(signal.SIGTERM, _interrupt)
    try:
        asyncio.run(serve(load_config(args.config)))
    except KeyboardInterrupt:
        pass
    logger.info("Stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
