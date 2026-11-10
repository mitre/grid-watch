import argparse
import asyncio
import logging
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
from simulator.ui.terminal import display_loop

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


async def command_listener(sim: GridProcessSim, db: Database) -> None:
    import sys
    import os

    # Skip the interactive command listener when stdin is not a controlling terminal
    # or when the process is in the background (os.getpgrp() != os.tcgetpgrp(0)).
    # This prevents SIGTTIN suspension when the server is started as a background job.
    try:
        if not sys.stdin.isatty() or os.getpgrp() != os.tcgetpgrp(sys.stdin.fileno()):
            return
    except OSError:
        return

    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                cmd = await loop.run_in_executor(None, input)
            except EOFError:
                return
            cmd = cmd.strip().lower()

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
                    continue
                current = _pt.value
                new_value = not current
                code = ControlCode.LATCH_ON if new_value else ControlCode.LATCH_OFF
                DatabaseCommandHandler(db)._apply_binary(1, code)
                logger.info(
                    "%s", "Turn Generator ON" if new_value else "Turn Generator OFF"
                )

            elif cmd == "b":
                _pt = db.get_binary_output(0)
                if _pt is None:
                    logger.error("binary output 0 not initialized")
                    continue
                current = _pt.value
                new_value = not current
                code = ControlCode.LATCH_ON if new_value else ControlCode.LATCH_OFF
                DatabaseCommandHandler(db)._apply_binary(0, code)
                logger.info("%s", "Close Breaker" if new_value else "Open Breaker")

            elif cmd:
                logger.info("Unknown command: %s", cmd)

    except (EOFError, asyncio.CancelledError):
        pass


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


async def main(config_path: Path = DEFAULT_CONFIG_PATH) -> None:  # pragma: no cover
    cfg = load_config(config_path)

    db = build_database(cfg)
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    outstation.clear_restart()
    db.clear_events()  # drop startup events before accepting connections

    server = TcpServer(
        config=TcpServerConfig(host=cfg.server.host, port=cfg.server.port)
    )
    await server.start()

    sim = GridProcessSim()
    display_task = asyncio.create_task(display_loop(db, interval=1.0, sim=sim))
    sim_task = asyncio.create_task(sim.run(db))
    cmd_task = asyncio.create_task(command_listener(sim, db))

    try:
        async with server:
            while True:
                channel = await server.accept()
                asyncio.create_task(handle_connection(channel, outstation))
    finally:
        display_task.cancel()
        sim_task.cancel()
        cmd_task.cancel()
        await asyncio.gather(display_task, sim_task, cmd_task, return_exceptions=True)


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    asyncio.run(main(config_path=args.config))
