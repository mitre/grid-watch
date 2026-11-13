import asyncio
import datetime
import logging
from collections import deque
from collections.abc import Iterable
from enum import IntFlag

from dnp3.database import Database

from simulator.sim import GridProcessSim

logger = logging.getLogger(__name__)


class EventLog(logging.Handler):
    def __init__(self, size: int = 8) -> None:
        super().__init__()
        self.lines: deque[str] = deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


_CHANGED = "\033[1;33m"
_RESET = "\033[0m"


def _quality_str(quality: IntFlag) -> str:
    parts = [flag.name or hex(int(flag)) for flag in quality]
    return "|".join(parts) if parts else "NONE"


def _fmt_row(changed: bool, idx: int, value_str: str, quality_str: str) -> str:
    marker = "*" if changed else " "
    line = f"  {marker} {idx:>5}  {value_str}  {quality_str}"
    return f"{_CHANGED}{line}{_RESET}" if changed else line


_Snapshot = dict[tuple[str, int], tuple[bool | float, int]]


def _render_display(
    db: Database, prev: _Snapshot, sim_status: str = "", events: Iterable[str] = ()
) -> _Snapshot:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur: _Snapshot = {}

    status_str = f"  [{sim_status}]" if sim_status else ""
    lines = [
        f"DNP3 Outstation Monitor  [{now}]{status_str}",
        "=" * 50,
        "",
        "Binary Inputs",
        f"  {'':1} {'IDX':>5}  {'VALUE':<6}  QUALITY",
        f"  {'':1} {'---':>5}  {'-----':<6}  -------",
    ]

    for bi in db.get_all_binary_inputs():
        key = ("bi", bi.index)
        cur[key] = (bi.value, int(bi.quality))
        changed = key in prev and prev[key] != cur[key]
        lines.append(
            _fmt_row(changed, bi.index, f"{str(bi.value):<6}", _quality_str(bi.quality))
        )

    lines += [
        "",
        "Analog Inputs",
        f"  {'':1} {'IDX':>5}  {'VALUE':>10}  QUALITY",
        f"  {'':1} {'---':>5}  {'----------':>10}  -------",
    ]
    for ai in db.get_all_analog_inputs():
        key = ("ai", ai.index)
        cur[key] = (ai.value, int(ai.quality))
        changed = key in prev and prev[key] != cur[key]
        lines.append(
            _fmt_row(changed, ai.index, f"{ai.value:>10.3f}", _quality_str(ai.quality))
        )

    lines += [
        "",
        "Binary Outputs",
        f"  {'':1} {'IDX':>5}  {'VALUE':<6}  QUALITY",
        f"  {'':1} {'---':>5}  {'-----':<6}  -------",
    ]
    for bo in db.get_all_binary_outputs():
        key = ("bo", bo.index)
        cur[key] = (bo.value, int(bo.quality))
        changed = key in prev and prev[key] != cur[key]
        lines.append(
            _fmt_row(changed, bo.index, f"{str(bo.value):<6}", _quality_str(bo.quality))
        )

    _gen_pt = db.get_binary_output(1)
    _brk_pt = db.get_binary_output(0)
    if _gen_pt is None or _brk_pt is None:
        logger.error("binary output points not initialized")
        return prev
    generator = _gen_pt.value
    breaker = _brk_pt.value

    lines += [
        "",
        "Controls",
        "[Turn Generator OFF]" if generator else "[Turn Generator ON]",
        "[Open Breaker]" if breaker else "[Close Breaker]",
        "",
        "Commands: pause | resume | reset | g | b",
    ]
    events = list(events)
    if events:
        lines += ["", "Events", *events]

    print("\033[2J\033[H" + "\n".join(lines), flush=True)
    return cur


async def display_loop(
    db: Database,
    interval: float = 1.0,
    sim: GridProcessSim | None = None,
    events: EventLog | None = None,
) -> None:
    prev: _Snapshot = {}
    try:
        while True:
            status = ""
            if sim is not None:
                status = "PAUSED" if sim.paused else "RUNNING"
            lines = events.lines if events is not None else ()
            prev = _render_display(db, prev, sim_status=status, events=lines)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise
