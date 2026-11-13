"""Matplotlib-based live HMI for the DNP3 grid simulator.

Reads state from the outstation via DNP3 integrity polls and sends button
commands over DNP3 DIRECT_OPERATE. All traffic is link-layer framed so it
is visible in Wireshark on port 20000.

Usage:
    python run.py
    python -m simulator.hmi [--host 127.0.0.1] [--port 20000] [--web] [--web-port 8090] [--debug]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import queue
import signal
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import matplotlib

from dnp3.master import Master
from dnp3.transport_io.channel import TcpConfig
from dnp3.transport_io.tcp_client import TcpClientChannel
from simulator import SIM
from simulator.config import configure_logging, port_number
from simulator.dnp3_frame import (
    MASTER_ADDR,
    OUTSTATION_ADDR,
    decode_frame,
    encode_frame,
)
from simulator.dnp3_read import parse_dnp3_response
from simulator.ui.desktop_ui import (
    _webagg_fill_window,
    draw_deficit,
    draw_schematic,
    draw_status,
    draw_voltage,
)

POLL_INTERVAL = 1.0
PROTOCOL = SIM["protocols"]["dnp3"]
TITLE = f"{PROTOCOL['name']} - {SIM['name']}"

logger = logging.getLogger(__name__)


@dataclass
class GridState:
    voltage_kv: float = 0.0
    power_deficit_kw: float = 0.0
    breaker_closed: bool = False
    generator_on: bool = False
    connected: bool = False
    t_history: deque[float] = field(default_factory=lambda: deque(maxlen=240))
    v_history: deque[float] = field(default_factory=lambda: deque(maxlen=240))
    p_history: deque[float] = field(default_factory=lambda: deque(maxlen=240))


async def dnp3_poller(
    state: GridState, lock: threading.Lock, host: str, port: int, t0: float
) -> None:
    """Poll the outstation with DNP3 integrity polls and update GridState.

    Sends a framed integrity poll every POLL_INTERVAL seconds, strips the
    link-layer response, and parses point values with parse_dnp3_response.
    Reconnects automatically on error.
    """
    master = Master()
    while True:
        channel = TcpClientChannel(config=TcpConfig(host=host, port=port))
        try:
            await channel.open()
            with lock:
                state.connected = True
            logger.info("DNP3 poller connected: %s:%d", host, port)

            while True:
                request = master.build_integrity_poll()
                framed = encode_frame(
                    request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR
                )
                await channel.write_all(framed)

                # Accumulate chunks until the FIN bit is set in the app control byte
                raw = b""
                while True:
                    chunk = await asyncio.wait_for(channel.read(16384), timeout=5.0)
                    if not chunk:
                        raise ConnectionError("outstation closed connection")
                    raw += chunk
                    app = decode_frame(raw)
                    if app and app[0] & 0x40:  # FIN bit
                        break

                pts = parse_dnp3_response(app)
                with lock:
                    if 0 in pts.analog_inputs:
                        state.voltage_kv = pts.analog_inputs[0]
                    if 1 in pts.analog_inputs:
                        state.power_deficit_kw = pts.analog_inputs[1]
                    if 0 in pts.binary_outputs:
                        state.breaker_closed = pts.binary_outputs[0]
                    if 1 in pts.binary_outputs:
                        state.generator_on = pts.binary_outputs[1]
                    t = time.monotonic() - t0
                    state.t_history.append(t)
                    state.v_history.append(state.voltage_kv)
                    state.p_history.append(state.power_deficit_kw)

                await asyncio.sleep(POLL_INTERVAL)

        except asyncio.TimeoutError:
            logger.warning("DNP3 poll timed out — reconnecting in 2s")
        except Exception as e:
            logger.warning("DNP3 poll error: %s — reconnecting in 2s", e)
        finally:
            await channel.close()

        with lock:
            state.connected = False
        await asyncio.sleep(2.0)


async def command_sender(
    cmd_q: queue.Queue[tuple[str, bool]], host: str, port: int
) -> None:
    while True:
        try:
            point, on = cmd_q.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.1)
            continue
        channel = TcpClientChannel(config=TcpConfig(host=host, port=port))
        try:
            master = Master()
            await channel.open()
            b = master.command_builder()
            index = 0 if point == "breaker" else 1
            (b.latch_on if on else b.latch_off)(index=index)
            req = master.build_direct_operate(b.build_direct_operate())
            await channel.write_all(
                encode_frame(req.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)
            )
            raw = b""
            while True:
                chunk = await asyncio.wait_for(channel.read(4096), timeout=2.0)
                if not chunk:
                    raise ConnectionError("outstation closed connection")
                raw += chunk
                app = decode_frame(raw)
                if app and app[0] & 0x40:  # FIN bit
                    break
            status = parse_dnp3_response(app).command_statuses.get(index)
            if status == 0:
                logger.info("DIRECT_OPERATE %s -> %s", point, "ON" if on else "OFF")
            else:
                logger.error(
                    "DIRECT_OPERATE %s -> %s rejected (status %s)",
                    point,
                    "ON" if on else "OFF",
                    status,
                )
        except Exception as e:
            logger.error("Command failed (%s=%s): %s", point, on, e)
        finally:
            await channel.close()


async def run_io(
    state: GridState,
    lock: threading.Lock,
    cmd_q: queue.Queue[tuple[str, bool]],
    host: str,
    port: int,
) -> None:
    t0 = time.monotonic()
    await asyncio.gather(
        dnp3_poller(state, lock, host, port, t0),
        command_sender(cmd_q, host, port),
    )


def _interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m simulator.hmi",
        description=f"{SIM['name']} HMI: polls the outstation over {PROTOCOL['name']}."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="HOST",
        help="PLC to poll (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=port_number,
        default=PROTOCOL["port"],
        metavar="PORT",
        help=f"PLC port (default: {PROTOCOL['port']})",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="serve the HMI as a web page instead of a desktop window",
    )
    parser.add_argument(
        "--web-port",
        type=port_number,
        default=8090,
        metavar="PORT",
        help="web HMI port (default: 8090)",
    )
    parser.add_argument("--debug", action="store_true", help="debug logging")
    args = parser.parse_args()
    configure_logging(args.debug)

    if args.web:
        matplotlib.use("WebAgg")
        matplotlib.rcParams["webagg.address"] = "0.0.0.0"
        matplotlib.rcParams["webagg.port"] = args.web_port
        matplotlib.rcParams["webagg.open_in_browser"] = False
        logging.getLogger("tornado.access").setLevel(logging.WARNING)
        _webagg_fill_window(TITLE)
        warnings.filterwarnings(
            "ignore", message="Animation was deleted without rendering anything"
        )

        from matplotlib.backends.backend_webagg import WebAggApplication

        try:
            WebAggApplication.initialize()
        except (OSError, SystemExit) as exc:
            logger.error("Web HMI could not start on port %d: %s", args.web_port, exc)
            raise SystemExit(1)
        logger.info("Web HMI at http://0.0.0.0:%d", WebAggApplication.port)

    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.widgets import Button

    state = GridState()
    lock = threading.Lock()
    cmd_q: queue.Queue[tuple[str, bool]] = queue.Queue()

    def run_loop() -> None:
        asyncio.run(run_io(state, lock, cmd_q, host=args.host, port=args.port))

    threading.Thread(target=run_loop, daemon=True).start()
    logger.info("Polling PLC at %s:%d", args.host, args.port)

    fig = plt.figure(num=TITLE, figsize=(14, 9))
    fig.suptitle("DNP3 Grid HMI", fontsize=15, fontweight="bold")
    gs = fig.add_gridspec(3, 4, height_ratios=[3, 3, 0.6], hspace=0.45, wspace=0.35)
    ax_schematic = fig.add_subplot(gs[0, 0:2])
    ax_voltage = fig.add_subplot(gs[0, 2:4])
    ax_deficit = fig.add_subplot(gs[1, 0:2])
    ax_status = fig.add_subplot(gs[1, 2:4])
    ax_bt_breaker = fig.add_subplot(gs[2, 0:2])
    ax_bt_generator = fig.add_subplot(gs[2, 2:4])

    btn_breaker = Button(
        ax_bt_breaker, "Close Breaker", color="#d5f5e3", hovercolor="#abebc6"
    )
    btn_generator = Button(
        ax_bt_generator, "Turn Generator On", color="#d5f5e3", hovercolor="#abebc6"
    )

    def on_breaker_click(_event: object) -> None:
        with lock:
            currently_closed = state.breaker_closed
        cmd_q.put(("breaker", not currently_closed))

    def on_generator_click(_event: object) -> None:
        with lock:
            currently_on = state.generator_on
        cmd_q.put(("generator", not currently_on))

    btn_breaker.on_clicked(on_breaker_click)
    btn_generator.on_clicked(on_generator_click)

    _ON_COLOR, _ON_HOVER = "#d5f5e3", "#abebc6"
    _OFF_COLOR, _OFF_HOVER = "#fadbd8", "#f5b7b1"

    def _set_btn_color(btn: Button, on: bool) -> None:
        btn.color = _ON_COLOR if on else _OFF_COLOR
        btn.hovercolor = _ON_HOVER if on else _OFF_HOVER
        btn.ax.set_facecolor(btn.color)

    def update(_frame: int) -> list[Any]:
        with lock:
            snap = GridState(
                voltage_kv=state.voltage_kv,
                power_deficit_kw=state.power_deficit_kw,
                breaker_closed=state.breaker_closed,
                generator_on=state.generator_on,
                connected=state.connected,
                t_history=deque(state.t_history),
                v_history=deque(state.v_history),
                p_history=deque(state.p_history),
            )
        draw_schematic(ax_schematic, snap)
        draw_voltage(ax_voltage, snap)
        draw_deficit(ax_deficit, snap)
        draw_status(ax_status, snap)
        btn_breaker.label.set_text(
            "Breaker: CLOSED" if snap.breaker_closed else "Breaker: OPEN"
        )
        btn_generator.label.set_text(
            "Generator: ON" if snap.generator_on else "Generator: OFF"
        )
        _set_btn_color(btn_breaker, on=snap.breaker_closed)
        _set_btn_color(btn_generator, on=snap.generator_on)
        return []

    _anim = FuncAnimation(fig, update, interval=500, cache_frame_data=False)
    signal.signal(signal.SIGTERM, _interrupt)
    try:
        plt.show()
    except KeyboardInterrupt:
        pass
    logger.info("Stopped")


if __name__ == "__main__":
    main()
