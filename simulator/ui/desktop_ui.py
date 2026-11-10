from __future__ import annotations

from typing import TYPE_CHECKING

from matplotlib.axes import Axes
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

if TYPE_CHECKING:
    from simulator.hmi import GridState

V_NOM_KV = 12.47
HISTORY_SECONDS = 60


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


def _webagg_fill_window():
    # Size the WebAgg figure to the browser window instead of a fixed canvas
    # that scrolls. mpl.js already re-renders the figure when its canvas
    # container resizes, so we just size that container to the window.
    import io
    from matplotlib.backends import backend_webagg_core as wac

    js = """
(function(){
  function fit(){
    var c=document.querySelector('.mpl-canvas');if(!c)return false;
    var cd=c.parentElement;
    var de=document.documentElement;de.style.height='100%';de.style.overflow='hidden';
    var b=document.body.style;b.margin='0';b.height='100%';b.overflow='hidden';
    var figs=document.getElementById('figures');if(figs)figs.style.margin='0';
    var root=document.getElementById('figure-div');if(root){root.style.display='block';root.style.width='100%';}
    if(cd.parentElement){cd.parentElement.style.display='block';cd.parentElement.style.width='100%';}
    cd.style.width=Math.max(200,window.innerWidth-2)+'px';
    cd.style.height=Math.max(150,window.innerHeight-84)+'px';
    return true;
  }
  window.addEventListener('resize',fit);
  var done=0,n=0,iv=setInterval(function(){
    var c=document.querySelector('.mpl-canvas');n++;
    if(c&&c.width>0){fit();if(++done>=3)clearInterval(iv);}
    if(n>200)clearInterval(iv);
  },150);
})();
"""
    orig = wac.FigureManagerWebAgg.get_javascript.__func__

    def patched(cls, stream=None):
        buf = io.StringIO()
        orig(cls, buf)
        out = buf.getvalue() + js
        if stream is None:
            return out
        stream.write(out)

    wac.FigureManagerWebAgg.get_javascript = classmethod(patched)
