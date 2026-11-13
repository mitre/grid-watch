import asyncio

import pytest

from dnp3.core.enums import ControlCode
from dnp3.core.flags import AnalogQuality, BinaryQuality

from simulator.plc import (
    DatabaseCommandHandler,
    build_database,
    command_listener,
    handle_connection,
)
from simulator.ui.terminal import (
    EventLog,
    _fmt_row,
    _quality_str,
    _render_display,
    display_loop,
)
from dnp3.outstation import Outstation
from simulator.dnp3_frame import MASTER_ADDR, OUTSTATION_ADDR, encode_frame
from simulator.sim import GridProcessSim

# --- _quality_str ---


def test_quality_str_binary_restart():
    assert _quality_str(BinaryQuality.RESTART) == "RESTART"


def test_quality_str_binary_online():
    assert _quality_str(BinaryQuality.ONLINE) == "ONLINE"


def test_quality_str_analog_restart():
    assert _quality_str(AnalogQuality.RESTART) == "RESTART"


def test_quality_str_analog_online():
    assert _quality_str(AnalogQuality.ONLINE) == "ONLINE"


# --- _fmt_row ---


def test_fmt_row_unchanged_has_no_marker():
    row = _fmt_row(False, 0, "False ", "RESTART")
    assert "*" not in row


def test_fmt_row_unchanged_contains_data():
    row = _fmt_row(False, 2, "True  ", "ONLINE")
    assert "2" in row
    assert "ONLINE" in row


def test_fmt_row_changed_has_marker():
    row = _fmt_row(True, 1, "True  ", "ONLINE")
    assert "*" in row


def test_fmt_row_changed_has_bold_yellow():
    row = _fmt_row(True, 1, "True  ", "ONLINE")
    assert "\033[1;33m" in row


# --- _render_display ---


def test_render_display_returns_snapshot_for_all_point_types(capsys):
    db = build_database()
    snapshot = _render_display(db, {})
    capsys.readouterr()
    assert ("bi", 0) in snapshot
    assert ("bi", 1) in snapshot
    assert ("ai", 0) in snapshot
    assert ("ai", 1) in snapshot
    assert ("bo", 0) in snapshot
    assert ("bo", 1) in snapshot


def test_render_display_snapshot_binary_input_values(capsys):
    db = build_database()
    snapshot = _render_display(db, {})
    capsys.readouterr()
    value, _ = snapshot[("bi", 0)]
    assert value is False
    value, _ = snapshot[("bi", 1)]
    assert value is True


def test_render_display_snapshot_analog_input_value(capsys):
    db = build_database()
    snapshot = _render_display(db, {})
    capsys.readouterr()
    value, _ = snapshot[("ai", 1)]
    assert abs(float(value) - 25.5) < 0.001


def test_render_display_no_highlight_on_first_render(capsys):
    db = build_database()
    _render_display(db, {})
    out = capsys.readouterr().out
    assert "\033[1;33m" not in out


def test_render_display_highlights_changed_row(capsys):
    db = build_database()
    prev = _render_display(db, {})
    capsys.readouterr()

    db.update_binary_input(0, value=True)
    _render_display(db, prev)
    out = capsys.readouterr().out

    assert "\033[1;33m" in out


def test_render_display_unchanged_row_not_highlighted(capsys):
    db = build_database()
    prev = _render_display(db, {})
    capsys.readouterr()

    # Only update index 0; index 1 should remain unchanged
    db.update_binary_input(0, value=True)
    cur = _render_display(db, prev)
    capsys.readouterr()

    # Snapshot for unchanged index 1 should match prev
    assert cur[("bi", 1)] == prev[("bi", 1)]


def test_render_display_output_contains_section_headers(capsys):
    db = build_database()
    _render_display(db, {})
    out = capsys.readouterr().out
    assert "Binary Inputs" in out
    assert "Analog Inputs" in out
    assert "Binary Outputs" in out


def test_render_display_snapshot_reflects_updated_value(capsys):
    db = build_database()
    prev = _render_display(db, {})
    capsys.readouterr()

    db.update_binary_input(0, value=True)
    cur = _render_display(db, prev)
    capsys.readouterr()

    value, _ = cur[("bi", 0)]
    assert value is True


def test_render_display_missing_binary_outputs_returns_prev():
    """When binary output points are absent, _render_display logs and returns prev."""
    from dnp3.database import Database

    db = Database()
    sentinel: dict = {("sentinel", 0): (True, 0)}
    result = _render_display(db, sentinel)
    assert result is sentinel


# --- display_loop ---


@pytest.mark.asyncio
async def test_display_loop_runs_and_cancels(capsys):
    db = build_database()
    task = asyncio.create_task(display_loop(db, interval=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_display_loop_renders_multiple_times(capsys):
    db = build_database()
    task = asyncio.create_task(display_loop(db, interval=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    out = capsys.readouterr().out
    # Should have rendered at least twice given 0.05s / 0.01s interval
    assert out.count("Binary Inputs") >= 2


# --- DatabaseCommandHandler edge cases ---


def test_apply_binary_invalid_index_returns_not_supported():
    db = build_database()
    handler = DatabaseCommandHandler(db)
    result = handler.direct_operate_binary_output(
        index=99, code=ControlCode.LATCH_ON, count=1, on_time=0, off_time=0
    )
    assert not result.is_success


def test_select_binary_output_invalid_index_returns_not_supported():
    db = build_database()
    handler = DatabaseCommandHandler(db)
    result = handler.select_binary_output(
        index=99, code=ControlCode.LATCH_ON, count=1, on_time=0, off_time=0
    )
    assert not result.is_success


def test_operate_binary_output_valid_index_returns_success():
    db = build_database()
    handler = DatabaseCommandHandler(db)
    result = handler.operate_binary_output(
        index=0,
        code=ControlCode.LATCH_ON,
        count=1,
        on_time=0,
        off_time=0,
        select_sequence=0,
    )
    assert result.is_success


def test_select_binary_output_valid_index_returns_success():
    db = build_database()
    handler = DatabaseCommandHandler(db)
    result = handler.select_binary_output(
        index=0, code=ControlCode.LATCH_ON, count=1, on_time=0, off_time=0
    )
    assert result.is_success


# --- display_loop with sim ---


@pytest.mark.asyncio
async def test_display_loop_with_running_sim(capsys):
    db = build_database()
    sim = GridProcessSim()
    # sim.paused is False by default → status = "RUNNING"
    task = asyncio.create_task(display_loop(db, interval=0.01, sim=sim))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_display_loop_with_paused_sim(capsys):
    db = build_database()
    sim = GridProcessSim()
    sim.pause()  # sim.paused = True → status = "PAUSED"
    task = asyncio.create_task(display_loop(db, interval=0.01, sim=sim))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# --- handle_connection ---


class _MockChannel:
    """Async mock channel for handle_connection tests."""

    def __init__(self, data_chunks: list[bytes]) -> None:
        self._iter = iter(data_chunks)
        self.remote_address = "127.0.0.1:9999"
        self.written: list[bytes] = []
        self.closed = False

    async def read(self, n: int) -> bytes:
        try:
            return next(self._iter)
        except StopIteration:
            return b""

    async def write_all(self, data: bytes) -> None:
        self.written.append(data)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_handle_connection_eof_closes_channel():
    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    channel = _MockChannel([b""])  # EOF immediately
    await handle_connection(channel, outstation)
    assert channel.closed


@pytest.mark.asyncio
async def test_handle_connection_partial_then_eof_continues():
    """Partial data → decode_frame returns b'' → continue (line 273)."""
    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    # Send a single invalid/incomplete byte then EOF
    channel = _MockChannel([b"\x05", b""])
    await handle_connection(channel, outstation)
    assert channel.closed


@pytest.mark.asyncio
async def test_handle_connection_discards_oversized_junk_buffer(monkeypatch):
    """Junk that never decodes must not accumulate without bound."""
    from simulator import plc

    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))

    seen: list[int] = []
    real_decode = plc.decode_frame

    def _spy(buf: bytes) -> bytes:
        seen.append(len(buf))
        return real_decode(buf)

    monkeypatch.setattr(plc, "decode_frame", _spy)

    chunk = b"\x05" * 4096
    chunks = [chunk] * (plc.MAX_BUFFER_BYTES // len(chunk) + 4)
    channel = _MockChannel(chunks + [b""])

    await handle_connection(channel, outstation)

    assert seen, "decode_frame should have been called"
    assert max(seen) <= plc.MAX_BUFFER_BYTES + len(chunk), (
        f"buffer grew to {max(seen)} bytes, expected it to be discarded near "
        f"{plc.MAX_BUFFER_BYTES}"
    )


@pytest.mark.asyncio
async def test_handle_connection_valid_frame_after_junk_still_responds():
    """Clearing the junk buffer must not break a following valid frame."""
    from simulator.dnp3_frame import MASTER_ADDR, OUTSTATION_ADDR, encode_frame
    from simulator.plc import MAX_BUFFER_BYTES

    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    outstation.clear_restart()
    db.clear_events()

    chunk = b"\x05" * 4096
    junk = [chunk] * (MAX_BUFFER_BYTES // len(chunk) + 2)
    frame = encode_frame(
        bytes([0xC0, 0x01, 0x3C, 0x01, 0x06]),
        dest=OUTSTATION_ADDR,
        src=MASTER_ADDR,
        is_response=False,
    )
    channel = _MockChannel(junk + [frame, b""])

    await handle_connection(channel, outstation)

    assert channel.written, "outstation must still answer a valid frame after junk"


@pytest.mark.asyncio
async def test_handle_connection_valid_frame_sends_response():
    """Valid DNP3 frame → decode succeeds → response written."""
    from dnp3.master import Master, DefaultSOEHandler

    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    outstation.clear_restart()

    master = Master(handler=DefaultSOEHandler())
    request = master.build_integrity_poll()
    framed = encode_frame(request.to_bytes(), dest=OUTSTATION_ADDR, src=MASTER_ADDR)

    channel = _MockChannel([framed, b""])
    await handle_connection(channel, outstation)

    assert channel.closed
    assert len(channel.written) > 0


@pytest.mark.asyncio
async def test_handle_connection_transport_header_stripped():
    """Frame with transport header byte → has_transport = True → byte stripped."""
    from dnp3.master import Master, DefaultSOEHandler

    db = build_database()
    outstation = Outstation(database=db, handler=DatabaseCommandHandler(db))
    outstation.clear_restart()

    master = Master(handler=DefaultSOEHandler())
    request = master.build_integrity_poll()
    app_bytes = request.to_bytes()

    # Prepend a transport header byte (0xC0 = FIR+FIN single segment)
    # app_bytes[0] = 0xC0 (app control) → app_data[1] = 0xC0 → 0xC0 & 0x80 = 0x80 != 0
    # → has_transport = True
    payload_with_transport = bytes([0xC0]) + app_bytes
    framed = encode_frame(payload_with_transport, dest=OUTSTATION_ADDR, src=MASTER_ADDR)

    channel = _MockChannel([framed, b""])
    await handle_connection(channel, outstation)

    assert channel.closed
    assert len(channel.written) > 0


# --- command_listener ---


class _MockStdin:
    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 0


def _feed(monkeypatch, commands):
    from simulator import plc

    data = "".join(command + "\n" for command in commands).encode()
    chunks = iter([data, OSError("closed")])

    def mock_read(fd: int, size: int) -> bytes:
        chunk = next(chunks)
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    monkeypatch.setattr(plc.os, "read", mock_read)


def _foreground(monkeypatch):
    import os as _os
    import sys as _sys

    monkeypatch.setattr(_sys, "stdin", _MockStdin())
    monkeypatch.setattr(_os, "getpgrp", lambda: 0, raising=False)
    monkeypatch.setattr(_os, "tcgetpgrp", lambda fd: 0, raising=False)


@pytest.mark.asyncio
async def test_command_listener_exits_when_not_tty(monkeypatch):
    """When stdin is not a tty, command_listener returns immediately."""
    import sys as _sys

    monkeypatch.setattr(_sys.stdin, "isatty", lambda: False)

    db = build_database()
    sim = GridProcessSim()
    await command_listener(sim, db)


@pytest.mark.asyncio
async def test_command_listener_exits_on_os_error(monkeypatch):
    """OSError from isatty/tcgetpgrp causes immediate return."""
    import sys as _sys

    def _raise():
        raise OSError("no controlling terminal")

    monkeypatch.setattr(_sys.stdin, "isatty", _raise)

    db = build_database()
    sim = GridProcessSim()
    await command_listener(sim, db)


def test_interactive_without_stdin(monkeypatch):
    import sys as _sys

    from simulator.plc import _interactive

    monkeypatch.setattr(_sys, "stdin", None)
    assert _interactive() is False


def test_interactive_in_background(monkeypatch):
    import os as _os
    import sys as _sys

    from simulator.plc import _interactive

    monkeypatch.setattr(_sys, "stdin", _MockStdin())
    monkeypatch.setattr(_os, "getpgrp", lambda: 1, raising=False)
    monkeypatch.setattr(_os, "tcgetpgrp", lambda fd: 2, raising=False)
    assert _interactive() is False


def test_interactive_without_process_groups(monkeypatch):
    """Windows has no os.tcgetpgrp; a console stdin is still interactive."""
    import os as _os
    import sys as _sys

    from simulator.plc import _interactive

    monkeypatch.setattr(_sys, "stdin", _MockStdin())
    monkeypatch.delattr(_os, "tcgetpgrp", raising=False)
    assert _interactive() is True


@pytest.mark.asyncio
async def test_command_listener_processes_all_commands(monkeypatch):
    """With a mocked tty, command_listener processes each command branch."""
    _foreground(monkeypatch)
    _feed(monkeypatch, ["pause", "resume", "reset", "g", "b", "xyz"])

    db = build_database()
    sim = GridProcessSim()
    await asyncio.wait_for(command_listener(sim, db), timeout=5)
    # After "pause" then "resume", the sim should not be paused
    assert sim.paused is False
    assert db.get_binary_output(0).value is True
    assert db.get_binary_output(1).value is True


@pytest.mark.asyncio
async def test_command_listener_missing_binary_outputs(monkeypatch, caplog):
    """'g' and 'b' log an error and continue when binary output points are absent."""
    from dnp3.database import Database

    _foreground(monkeypatch)
    _feed(monkeypatch, ["g", "b"])

    db = Database()
    sim = GridProcessSim()
    with caplog.at_level("ERROR"):
        await asyncio.wait_for(command_listener(sim, db), timeout=5)

    assert "binary output 1 not initialized" in caplog.text
    assert "binary output 0 not initialized" in caplog.text


def test_read_lines_stops_when_loop_is_closed(monkeypatch):
    """The stdin thread exits quietly once the event loop has gone away."""
    from simulator.plc import _read_lines

    _feed(monkeypatch, ["pause"])
    loop = asyncio.new_event_loop()
    loop.close()
    lines: asyncio.Queue = asyncio.Queue()
    _read_lines(loop, lines, 0)
    assert lines.empty()


# --- EventLog ---


def test_event_log_keeps_latest_lines():
    import logging

    events = EventLog(size=2)
    events.setFormatter(logging.Formatter("%(message)s"))
    for text in ("one", "two", "three"):
        events.emit(logging.makeLogRecord({"msg": text}))
    assert list(events.lines) == ["two", "three"]


def test_render_display_shows_events(capsys):
    db = build_database()
    _render_display(db, {}, events=["CONTROL: BO[0] <- False"])
    out = capsys.readouterr().out
    assert "Events" in out
    assert "CONTROL: BO[0] <- False" in out


@pytest.mark.asyncio
async def test_display_loop_shows_events(capsys):
    db = build_database()
    events = EventLog()
    events.lines.append("Client connected: 127.0.0.1:9999")
    task = asyncio.create_task(display_loop(db, interval=0.01, events=events))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "Client connected: 127.0.0.1:9999" in capsys.readouterr().out


# --- main ---


def test_main_missing_config_exits_1(tmp_path, monkeypatch, caplog):
    from simulator import plc

    monkeypatch.setattr(plc.signal, "signal", lambda *args: None)
    with caplog.at_level("ERROR"):
        assert plc.main(["--config", str(tmp_path / "missing.yaml")]) == 1
    assert "PLC failed to start" in caplog.text


def test_main_bind_error_exits_1(monkeypatch, caplog):
    from simulator import plc

    async def _fail(cfg):
        raise plc.StartError("Failed to start server: address already in use")

    monkeypatch.setattr(plc.signal, "signal", lambda *args: None)
    monkeypatch.setattr(plc, "serve", _fail)
    with caplog.at_level("ERROR"):
        assert plc.main([]) == 1
    assert "PLC failed to start" in caplog.text


def test_main_runtime_error_exits_1(monkeypatch, caplog):
    from simulator import plc

    async def _fail(cfg):
        from dnp3.transport_io.channel import ChannelError

        raise ChannelError("accept failed")

    monkeypatch.setattr(plc.signal, "signal", lambda *args: None)
    monkeypatch.setattr(plc, "serve", _fail)
    with caplog.at_level("ERROR"):
        assert plc.main([]) == 1
    assert "PLC error: accept failed" in caplog.text
    assert "failed to start" not in caplog.text


def test_main_interrupt_exits_0(monkeypatch, caplog):
    from simulator import plc

    async def _interrupted(cfg):
        raise KeyboardInterrupt

    monkeypatch.setattr(plc.signal, "signal", lambda *args: None)
    monkeypatch.setattr(plc, "serve", _interrupted)
    with caplog.at_level("INFO"):
        assert plc.main([]) == 0
    assert "Stopped" in caplog.text


def test_sigterm_handler_raises_keyboard_interrupt():
    from simulator.plc import _interrupt

    with pytest.raises(KeyboardInterrupt):
        _interrupt(15, None)


def test_main_host_and_port_override_config(monkeypatch):
    from simulator import plc

    seen = {}

    async def _capture(cfg):
        seen["host"], seen["port"] = cfg.server.host, cfg.server.port
        raise KeyboardInterrupt

    monkeypatch.setattr(plc.signal, "signal", lambda *args: None)
    monkeypatch.setattr(plc, "serve", _capture)
    assert plc.main(["--host", "127.0.0.1", "--port", "20001"]) == 0
    assert seen == {"host": "127.0.0.1", "port": 20001}


def test_main_defaults_come_from_config(monkeypatch):
    from simulator import SIM, plc

    seen = {}

    async def _capture(cfg):
        seen["host"], seen["port"] = cfg.server.host, cfg.server.port
        raise KeyboardInterrupt

    monkeypatch.setattr(plc.signal, "signal", lambda *args: None)
    monkeypatch.setattr(plc, "serve", _capture)
    assert plc.main([]) == 0
    dnp3 = SIM["protocols"]["dnp3"]
    assert seen == {"host": dnp3["bind"], "port": dnp3["port"]}


@pytest.mark.parametrize("text", ["0", "65536", "port"])
def test_main_rejects_bad_port(text):
    from simulator import plc

    with pytest.raises(SystemExit) as exc:
        plc.main(["--port", text])
    assert exc.value.code == 2


def test_configure_logging_levels(monkeypatch):
    import logging

    from simulator.config import LOG_FORMAT, configure_logging

    calls = []
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: calls.append(kwargs))
    configure_logging()
    configure_logging(debug=True)
    assert calls == [
        {"format": LOG_FORMAT, "level": logging.INFO},
        {"format": LOG_FORMAT, "level": logging.DEBUG},
    ]
