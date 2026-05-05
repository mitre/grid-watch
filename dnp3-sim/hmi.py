"""Matplotlib-based live HMI for the DNP3 grid simulator.

Reads state from the outstation via DNP3 integrity polls and sends button
commands over DNP3 DIRECT_OPERATE. All traffic is link-layer framed so it
is visible in Wireshark on port 20000.

Usage:
    python run.py          (option 2)
    python dnp3-sim/hmi.py [--host 127.0.0.1] [--port 20000]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import queue
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle
from matplotlib.widgets import Button

from dnp3.master import Master
from dnp3.transport_io.channel import TcpConfig
from dnp3.transport_io.tcp_client import TcpClientChannel
from dnp3_frame import MASTER_ADDR, OUTSTATION_ADDR, decode_frame, encode_frame
from dnp3_read import parse_dnp3_response

V_NOM_KV = 12.47
HISTORY_SECONDS = 60
POLL_INTERVAL = 1.0

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("hmi")


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
        except (ConnectionError, OSError) as e:
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
            raw = await asyncio.wait_for(channel.read(4096), timeout=2.0)
            decode_frame(raw)  # strip framing; response not inspected by HMI
            logger.info("DIRECT_OPERATE %s -> %s", point, "ON" if on else "OFF")
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


def _bus_color(v_kv: float) -> str:
    if v_kv > 0.7 * V_NOM_KV:
        return "#2ecc71"
    if v_kv > 0.3 * V_NOM_KV:
        return "#f39c12"
    return "#e74c3c"


def draw_schematic(ax: Axes, s: GridState) -> None:
    ax.clear()
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Grid Schematic", fontsize=13, fontweight="bold", pad=12)

    # Rounded panel background
    ax.add_patch(
        FancyBboxPatch(
            (0.35, 1.35),
            9.3,
            4.0,
            boxstyle="round,pad=0.02,rounding_size=0.2",
            facecolor="#f8f9fa",
            edgecolor="#cfd8dc",
            linewidth=1.2,
            zorder=0,
        )
    )

    line_y = 3.3
    energized_up = s.generator_on
    energized_down = s.breaker_closed and s.generator_on
    live_col = "#1a1a1a"
    dead_col = "#b2bec3"
    up_col = live_col if energized_up else dead_col
    down_col = live_col if energized_down else dead_col

    def wire(x0: float, x1: float, color: str, live: bool = False) -> None:
        ax.plot(
            [x0, x1],
            [line_y, line_y],
            color=color,
            linewidth=2.5,
            solid_capstyle="round",
            zorder=2,
        )
        if live and (x1 - x0) > 0.6:
            ax.plot(
                (x0 + x1) / 2,
                line_y,
                marker=">",
                markersize=9,
                color=color,
                markeredgecolor=color,
                zorder=3,
            )

    # Generator
    gen_color = "#27ae60" if s.generator_on else "#95a5a6"
    ax.add_patch(
        Circle(
            (1.2, line_y),
            0.55,
            facecolor=gen_color,
            edgecolor="#1b4332",
            linewidth=1.8,
            zorder=3,
        )
    )
    ax.text(
        1.2,
        line_y,
        "G",
        ha="center",
        va="center",
        fontsize=20,
        fontweight="bold",
        color="white",
        zorder=4,
    )
    ax.text(
        1.2,
        2.25,
        f"Generator\n{'ON' if s.generator_on else 'OFF'}",
        ha="center",
        va="top",
        fontsize=10,
        fontweight="bold",
        color="#27ae60" if s.generator_on else "#7f8c8d",
    )

    # Wire: generator -> breaker
    wire(1.75, 3.1, up_col, live=energized_up)

    # Breaker
    brk_color = "#27ae60" if s.breaker_closed else "#c0392b"
    ax.add_patch(
        Rectangle(
            (3.1, line_y - 0.45),
            0.9,
            0.9,
            facecolor=brk_color,
            edgecolor="#2c3e50",
            linewidth=1.8,
            zorder=3,
        )
    )
    ax.text(
        3.55,
        line_y,
        "CB",
        ha="center",
        va="center",
        fontsize=13,
        fontweight="bold",
        color="white",
        zorder=4,
    )
    ax.text(
        3.55,
        2.25,
        f"Breaker\n{'CLOSED' if s.breaker_closed else 'OPEN'}",
        ha="center",
        va="top",
        fontsize=10,
        fontweight="bold",
        color="#27ae60" if s.breaker_closed else "#c0392b",
    )

    # Wire: breaker -> bus
    if s.breaker_closed:
        wire(4.0, 5.7, down_col, live=energized_down)
    else:
        wire(4.0, 4.55, dead_col)
        for dy1, dy2 in [(-0.18, 0.18), (0.18, -0.18)]:
            ax.plot(
                [4.65, 5.1],
                [line_y + dy1, line_y + dy2],
                color="#c0392b",
                linewidth=2.8,
                zorder=2,
            )
        wire(5.2, 5.7, dead_col)

    # Busbar
    bus_col = _bus_color(s.voltage_kv)
    ax.add_patch(
        Rectangle(
            (5.7, line_y - 0.1),
            2.2,
            0.2,
            facecolor=bus_col,
            edgecolor="#2c3e50",
            linewidth=1.2,
            zorder=3,
        )
    )
    for x_tick in (5.7, 7.9):
        ax.plot(
            [x_tick, x_tick],
            [line_y - 0.28, line_y + 0.28],
            color="#2c3e50",
            linewidth=1.5,
            zorder=3,
        )

    # Bus voltage label
    pct = (s.voltage_kv / V_NOM_KV) * 100.0
    pct_color = "#27ae60" if pct > 70 else "#d68910" if pct > 30 else "#c0392b"
    ax.text(
        6.8,
        4.55,
        f"Bus: {s.voltage_kv:.2f} kV",
        ha="center",
        fontsize=12,
        fontweight="bold",
    )
    ax.text(
        6.8,
        4.15,
        f"{pct:.0f}% of nominal",
        ha="center",
        fontsize=9,
        style="italic",
        color=pct_color,
        fontweight="bold",
    )

    # Wire: bus -> load
    wire(7.9, 8.55, down_col, live=energized_down)

    # Load
    ax.add_patch(
        Rectangle(
            (8.55, line_y - 0.45),
            0.9,
            0.9,
            fill=False,
            edgecolor="#2c3e50",
            linewidth=1.8,
            zorder=3,
        )
    )
    ax.text(
        9.0,
        line_y,
        "L",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
        color="#2c3e50",
    )
    ax.text(
        9.0,
        2.25,
        "Load",
        ha="center",
        va="top",
        fontsize=10,
        fontweight="bold",
        color="#2c3e50",
    )


def _style_timeseries(ax: Axes) -> None:
    ax.grid(True, linestyle=":", linewidth=0.8, color="#b0bec5", alpha=0.6)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color("#78909c")
    ax.spines["bottom"].set_color("#78909c")
    ax.tick_params(colors="#546e7a", labelsize=9)


def draw_voltage(ax: Axes, s: GridState) -> None:
    ax.clear()
    ax.set_title("Bus Voltage", fontsize=12, fontweight="bold", pad=8)
    ax.set_ylabel("kV", fontsize=10)
    ax.set_xlabel("seconds", fontsize=10)
    _style_timeseries(ax)
    ax.set_ylim(-0.3, V_NOM_KV * 1.15)

    ax.axhspan(
        0.7 * V_NOM_KV, V_NOM_KV * 1.15, facecolor="#2ecc71", alpha=0.06, zorder=0
    )
    ax.axhspan(
        0.3 * V_NOM_KV, 0.7 * V_NOM_KV, facecolor="#f39c12", alpha=0.06, zorder=0
    )
    ax.axhspan(-0.3, 0.3 * V_NOM_KV, facecolor="#e74c3c", alpha=0.06, zorder=0)
    ax.axhline(
        V_NOM_KV,
        linestyle="--",
        color="#546e7a",
        alpha=0.8,
        linewidth=1.2,
        label=f"Nominal {V_NOM_KV} kV",
    )

    if s.t_history:
        t = list(s.t_history)
        v = list(s.v_history)
        t_end = t[-1]
        ax.set_xlim(max(0, t_end - HISTORY_SECONDS), max(HISTORY_SECONDS, t_end))
        color = _bus_color(v[-1])
        ax.plot(t, v, color=color, linewidth=2.2, zorder=3)
        ax.fill_between(t, 0, v, color=color, alpha=0.18, zorder=2)
    ax.legend(loc="lower left", fontsize=8, framealpha=0.9)


def draw_deficit(ax: Axes, s: GridState) -> None:
    ax.clear()
    ax.set_title("Power Deficit", fontsize=12, fontweight="bold", pad=8)
    ax.set_ylabel("kW", fontsize=10)
    ax.set_xlabel("seconds", fontsize=10)
    _style_timeseries(ax)

    if s.t_history:
        t = list(s.t_history)
        p = list(s.p_history)
        t_end = t[-1]
        ax.set_xlim(max(0, t_end - HISTORY_SECONDS), max(HISTORY_SECONDS, t_end))
        ax.plot(t, p, color="#e67e22", linewidth=2.2, zorder=3)
        ax.fill_between(t, 0, p, color="#e67e22", alpha=0.18, zorder=2)
        ax.set_ylim(0, max(1500, max(p) * 1.1))


def draw_status(ax: Axes, s: GridState) -> None:
    ax.clear()
    ax.axis("off")
    ax.set_title("Status", fontsize=12, fontweight="bold")

    conn_color = "#2ecc71" if s.connected else "#e74c3c"
    conn_text = "● CONNECTED" if s.connected else "● DISCONNECTED"

    lines = [
        (conn_text, conn_color, 14, "bold"),
        ("", "black", 10, "normal"),
        (f"Voltage:       {s.voltage_kv:>7.2f} kV", "black", 12, "normal"),
        (f"Power deficit: {s.power_deficit_kw:>7.1f} kW", "black", 12, "normal"),
        (
            f"Breaker:       {'CLOSED' if s.breaker_closed else 'OPEN':>7}",
            "#2ecc71" if s.breaker_closed else "#e74c3c",
            12,
            "bold",
        ),
        (
            f"Generator:     {'ON' if s.generator_on else 'OFF':>7}",
            "#2ecc71" if s.generator_on else "#95a5a6",
            12,
            "bold",
        ),
    ]
    y = 0.95
    for text, color, size, weight in lines:
        ax.text(
            0.05,
            y,
            text,
            fontsize=size,
            color=color,
            fontweight=weight,
            family="monospace",
            transform=ax.transAxes,
            va="top",
        )
        y -= 0.11


def main() -> None:
    parser = argparse.ArgumentParser(description="Live HMI for DNP3 grid simulator")
    parser.add_argument("--host", default="127.0.0.1", help="Outstation host")
    parser.add_argument("--port", type=int, default=20000, help="DNP3 port")
    args = parser.parse_args()

    state = GridState()
    lock = threading.Lock()
    cmd_q: queue.Queue[tuple[str, bool]] = queue.Queue()

    def run_loop() -> None:
        asyncio.run(run_io(state, lock, cmd_q, host=args.host, port=args.port))

    threading.Thread(target=run_loop, daemon=True).start()

    fig = plt.figure(figsize=(14, 9))
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
    plt.show()


if __name__ == "__main__":
    main()
