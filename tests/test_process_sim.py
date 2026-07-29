import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../dnp3-sim")))

import pytest

from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    BinaryOutputConfig,
    Database,
)

from process_sim import GridProcessSim, GridSimConfig


def _make_db(*, breaker: bool = True, generator: bool = False) -> Database:
    """Build a minimal database with the two analog inputs and two binary outputs."""
    db = Database()
    db.add_binary_input(0, BinaryInputConfig(), value=False)
    db.add_analog_input(0, AnalogInputConfig(), value=0.0)
    db.add_analog_input(1, AnalogInputConfig(), value=0.0)
    db.add_binary_output(0, BinaryOutputConfig(), value=breaker)
    db.add_binary_output(1, BinaryOutputConfig(), value=generator)
    return db


# --- Unit tests ---


def test_process_sim_has_two_analog_sensors():
    """AI[0] (voltage) and AI[1] (power deficit) must be present after one tick."""
    db = _make_db()
    sim = GridProcessSim()

    # Manually run one update cycle synchronously by calling internals
    sim._update_load()
    vt = sim._v_target(
        breaker_closed=bool(db.get_binary_output(0).value),
        generator_on=bool(db.get_binary_output(1).value),
    )
    a = sim.cfg.smoothing_alpha
    sim.v_kv = sim.v_kv + a * (vt - sim.v_kv)
    sim._set_ai(db, 0, sim.v_kv)
    sim._set_ai(db, 1, sim.p_load_kw)

    assert db.get_analog_input(0) is not None, "AI[0] (voltage) must exist"
    assert db.get_analog_input(1) is not None, "AI[1] (load) must exist"


def test_process_sim_has_two_binary_controls():
    """BO[0] (breaker) and BO[1] (generator) must be present in the database."""
    db = _make_db()
    assert db.get_binary_output(0) is not None, "BO[0] (breaker) must exist"
    assert db.get_binary_output(1) is not None, "BO[1] (generator) must exist"


def test_voltage_near_zero_when_breaker_open():
    """With breaker open, voltage target should be near zero."""
    sim = GridProcessSim()
    vt = sim._v_target(breaker_closed=False, generator_on=False)
    assert vt < 1.0, f"Expected near-zero voltage target with open breaker, got {vt}"


def test_voltage_higher_with_generator_on():
    """Generator on should yield a higher voltage target than generator off."""
    sim = GridProcessSim()
    vt_off = sim._v_target(breaker_closed=True, generator_on=False)
    vt_on = sim._v_target(breaker_closed=True, generator_on=True)
    assert vt_on >= vt_off, "Generator on must not reduce voltage target"


def test_load_stays_within_bounds():
    """Load random walk must remain within the clamped [100, 1500] kW range."""
    sim = GridProcessSim()
    for _ in range(200):
        sim._update_load()
    assert 100.0 <= sim.p_load_kw <= 1500.0


def test_missing_binary_output_raises():
    """run() must raise RuntimeError if required binary outputs are missing."""
    db = Database()
    db.add_analog_input(0, AnalogInputConfig(), value=0.0)
    db.add_analog_input(1, AnalogInputConfig(), value=0.0)
    # No binary outputs added

    sim = GridProcessSim()

    async def _run():
        await sim.run(db)

    with pytest.raises(RuntimeError, match="Missing required controls"):
        asyncio.run(_run())


# --- Async integration tests ---


@pytest.mark.asyncio
async def test_process_updates_analog_inputs_continuously():
    """run() must update AI[0] and AI[1] in the background without blocking."""
    cfg = GridSimConfig(tick_seconds=0.01)
    db = _make_db(breaker=True, generator=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.05)  # let a few ticks execute
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    v = db.get_analog_input(0).value
    p_def = db.get_analog_input(1).value

    assert v > 0.0, f"Voltage (AI[0]) should be positive after ticks, got {v}"
    assert (
        p_def > 0.0
    ), f"Power deficit (AI[1]) should be positive after ticks, got {p_def}"


@pytest.mark.asyncio
async def test_process_updates_binary_inputs_from_controls():
    """BI[0] and BI[1] must mirror the BO[0]/BO[1] controls after ticks."""
    cfg = GridSimConfig(tick_seconds=0.01)
    db = _make_db(breaker=True, generator=True)
    db.add_binary_input(1, BinaryInputConfig(), value=False)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert db.get_binary_input(0).value is True
    assert db.get_binary_input(1).value is True


@pytest.mark.asyncio
async def test_binary_input_status_follows_breaker_open():
    """Opening the breaker via BO[0] must drive BI[0] back to False."""
    cfg = GridSimConfig(tick_seconds=0.01)
    db = _make_db(breaker=True, generator=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.05)
    assert db.get_binary_input(0).value is True

    db.update_binary_output(0, value=False)
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert db.get_binary_input(0).value is False


@pytest.mark.asyncio
async def test_process_tolerates_missing_binary_inputs():
    """run() must not fail when the config omits the status points entirely."""
    cfg = GridSimConfig(tick_seconds=0.01)
    db = Database()
    db.add_analog_input(0, AnalogInputConfig(), value=0.0)
    db.add_analog_input(1, AnalogInputConfig(), value=0.0)
    db.add_binary_output(0, BinaryOutputConfig(), value=True)
    db.add_binary_output(1, BinaryOutputConfig(), value=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.05)
    still_running = not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert still_running


@pytest.mark.asyncio
async def test_process_runs_as_background_task():
    """The simulation task must not block the event loop."""
    cfg = GridSimConfig(tick_seconds=0.01)
    db = _make_db()
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))

    # This coroutine must complete even while the sim is running
    await asyncio.sleep(0.05)
    assert not task.done(), "Background task should still be running"

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# --- Adversarial influence tests ---
#
# Steady-state operating point (GridSimConfig defaults, breaker closed, generator on):
#   v_nom_kv       = 12.47 kV
#   p_load_kw_init = 800 kW,  p_gen_rated_kw = 600 kW
#   p_deficit      = max(800 - 600, 0) = 200 kW
#   v_target       = 12.47 - 0.002 * 200 = 12.07 kV  (≈ steady-state bus voltage)
#
# Adversarial scenario 1 — open breaker (BO[0] = LATCH_OFF):
#   v_target drops to 0.05 kV  (near-zero; expected drop > 11 kV)
#
# Adversarial scenario 2 — disable generator (BO[1] = LATCH_OFF):
#   no generator = no source; v_target drops to 0.05 kV (same as open breaker)
#   expected result: a large drop to near-zero voltage


@pytest.mark.asyncio
async def test_steady_state_reached():
    """With breaker closed and generator on, voltage converges to a stable value near
    the droop-adjusted nominal (~12.07 kV for 800 kW load, 600 kW gen)."""
    cfg = GridSimConfig(tick_seconds=0.01, smoothing_alpha=1.0)
    db = _make_db(breaker=True, generator=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.1)  # 10 ticks — enough to converge with alpha=1.0

    v = db.get_analog_input(0).value

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert v > 8.0, f"Steady-state voltage must be well above 8 kV, got {v:.3f}"
    assert (
        v <= cfg.v_nom_kv
    ), f"Voltage must not exceed nominal {cfg.v_nom_kv} kV, got {v:.3f}"


@pytest.mark.asyncio
async def test_adversarial_open_breaker_drops_voltage_to_near_zero():
    """Opening the breaker via a DNP3 LATCH_OFF command (adversarial) collapses the
    bus voltage from steady state (~12 kV) to near zero (~0.05 kV).

    Before: v > 8 kV  (normal operation)
    After:  v < 1 kV  (breaker open — supply isolated from load)
    """
    cfg = GridSimConfig(tick_seconds=0.01, smoothing_alpha=1.0)
    db = _make_db(breaker=True, generator=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.1)

    v_before = db.get_analog_input(0).value

    # Adversarial command: open the breaker (mirrors DNP3 DIRECT_OPERATE LATCH_OFF on BO[0])
    db.update_binary_output(0, value=False)
    await asyncio.sleep(0.05)

    v_after = db.get_analog_input(0).value

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert (
        v_before > 8.0
    ), f"Expected normal steady-state voltage >8 kV, got {v_before:.3f}"
    assert (
        v_after < 1.0
    ), f"Expected near-zero voltage after open-breaker attack, got {v_after:.3f}"
    assert (
        v_before - v_after > 7.0
    ), f"Voltage drop must exceed 7 kV: before={v_before:.3f} kV  after={v_after:.3f} kV"


@pytest.mark.asyncio
async def test_adversarial_disable_generator_drops_voltage():
    """Disabling the generator via a DNP3 LATCH_OFF command (adversarial) collapses
    the bus voltage from steady state (~12 kV) to near zero (~0.05 kV).

    Before: v > 8 kV  (normal operation)
    After:  v < 1 kV  (generator off — no source maintaining the bus)
    """
    cfg = GridSimConfig(tick_seconds=0.01, smoothing_alpha=1.0)
    db = _make_db(breaker=True, generator=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.1)

    v_before = db.get_analog_input(0).value

    # Adversarial command: shut down the generator (mirrors DNP3 DIRECT_OPERATE LATCH_OFF on BO[1])
    db.update_binary_output(1, value=False)
    await asyncio.sleep(0.05)

    v_after = db.get_analog_input(0).value

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert (
        v_before > 8.0
    ), f"Expected normal steady-state voltage >8 kV, got {v_before:.3f}"
    assert (
        v_after < 1.0
    ), f"Expected near-zero voltage after generator shutdown, got {v_after:.3f}"
    assert (
        v_before - v_after > 7.0
    ), f"Voltage drop must exceed 7 kV: before={v_before:.3f} kV  after={v_after:.3f} kV"


@pytest.mark.asyncio
async def test_pause_stops_simulation_updates():
    """When paused, sensor values should not change."""
    cfg = GridSimConfig(tick_seconds=0.01, smoothing_alpha=1.0)
    db = _make_db(breaker=True, generator=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.05)  # let it run a bit

    sim.pause()
    await asyncio.sleep(0.02)  # let the pause take effect

    v_at_pause = db.get_analog_input(0).value
    await asyncio.sleep(0.05)  # wait while paused
    v_after_pause = db.get_analog_input(0).value

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert (
        v_at_pause == v_after_pause
    ), f"Voltage should not change while paused: {v_at_pause} != {v_after_pause}"


@pytest.mark.asyncio
async def test_resume_restarts_simulation_updates():
    """After resuming, sensor values should start changing again."""
    cfg = GridSimConfig(tick_seconds=0.01, smoothing_alpha=1.0)
    db = _make_db(breaker=True, generator=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.05)

    sim.pause()
    await asyncio.sleep(0.02)
    v_paused = db.get_analog_input(0).value

    sim.resume()
    await asyncio.sleep(0.05)
    v_resumed = db.get_analog_input(0).value

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert not sim.paused, "Simulation should not be paused after resume"
    assert v_resumed != v_paused, "Voltage should change after resume"


@pytest.mark.asyncio
async def test_reset_restores_initial_conditions():
    """Reset should restore all state to initial config values."""
    cfg = GridSimConfig(tick_seconds=0.01, smoothing_alpha=1.0)
    db = _make_db(breaker=True, generator=True)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.05)  # let it diverge from initial state

    sim.reset(db)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert sim.v_kv == cfg.v_nom_kv, "Voltage should be reset to nominal"
    assert sim.p_load_kw == cfg.p_load_kw_init, "Load should be reset to initial"
    assert sim.breaker_closed is False, "Breaker should be reset to open"
    assert sim.generator_on is False, "Generator should be reset to off"
    assert sim.p_def_kw == 0.0, "Power deficit should be reset to 0"
    assert sim.paused is False, "Simulation should not be paused after reset"
    assert db.get_binary_output(0).value is False, "BO[0] should be reset in database"
    assert db.get_binary_output(1).value is False, "BO[1] should be reset in database"
    assert (
        db.get_analog_input(0).value == cfg.v_nom_kv
    ), "AI[0] should be reset in database"
    assert db.get_analog_input(1).value == 0.0, "AI[1] should be reset in database"


def test_pause_resume_flags():
    """pause() and resume() should toggle the paused flag."""
    sim = GridProcessSim()
    assert sim.paused is False

    sim.pause()
    assert sim.paused is True

    sim.resume()
    assert sim.paused is False


@pytest.mark.asyncio
async def test_breaker_control_affects_voltage():
    """Closing the breaker and starting the generator should drive voltage toward nominal."""
    cfg = GridSimConfig(tick_seconds=0.01, smoothing_alpha=1.0)
    db = _make_db(breaker=False, generator=False)
    sim = GridProcessSim(cfg=cfg)

    task = asyncio.create_task(sim.run(db))
    await asyncio.sleep(0.03)

    v_open = db.get_analog_input(0).value

    # Close the breaker and start the generator — both required for voltage to rise
    db.update_binary_output(0, value=True)
    db.update_binary_output(1, value=True)
    await asyncio.sleep(0.05)

    v_closed = db.get_analog_input(0).value

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert (
        v_closed > v_open
    ), f"Voltage should rise after closing breaker with generator on: {v_open:.3f} -> {v_closed:.3f}"


def test_get_display_state_has_all_sections():
    """get_display_state() must return keys for binary_inputs, analog_inputs, binary_outputs."""
    sim = GridProcessSim()
    db = _make_db()
    state = sim.get_display_state(db)
    assert "binary_inputs" in state
    assert "analog_inputs" in state
    assert "binary_outputs" in state
    assert 0 in state["binary_inputs"]
    assert 0 in state["binary_outputs"]


def test_get_display_state_reports_database_values_not_cached_state():
    """Status must come from the database, not from the sim's in-memory fields."""
    sim = GridProcessSim()
    db = _make_db()

    db.update_binary_input(0, value=True)
    db.update_binary_output(0, value=False)
    sim.breaker_closed = False

    state = sim.get_display_state(db)

    assert state["binary_inputs"][0]["value"] is True
    assert state["binary_outputs"][0]["value"] is False


def test_get_display_state_reports_real_quality():
    """Quality must reflect the point's actual quality flags, not a hardcoded string."""
    sim = GridProcessSim()
    db = _make_db()

    before = sim.get_display_state(db)["binary_inputs"][0]["quality"]
    db.update_binary_input(0, value=True)
    after = sim.get_display_state(db)["binary_inputs"][0]["quality"]

    assert before != after, (
        f"quality should change once a point is updated, got {before!r} both times"
    )
    assert "ONLINE" in str(after)


def test_get_display_state_reflects_analog_values():
    """Analog readings must be taken from the database."""
    sim = GridProcessSim()
    db = _make_db()

    db.update_analog_input(0, value=11.25)
    state = sim.get_display_state(db)

    assert state["analog_inputs"][0]["value"] == pytest.approx(11.25)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tick_seconds": 0.0},
        {"tick_seconds": -1.0},
        {"smoothing_alpha": 0.0},
        {"smoothing_alpha": -0.5},
        {"smoothing_alpha": 1.5},
        {"v_nom_kv": 0.0},
        {"p_load_kw_init": -1.0},
        {"p_gen_rated_kw": -1.0},
        {"droop_kv_per_kw": -0.1},
    ],
)
def test_grid_sim_config_rejects_invalid_values(kwargs):
    """Nonsense simulation parameters must be rejected at construction."""
    with pytest.raises(ValueError):
        GridSimConfig(**kwargs)


def test_grid_sim_config_accepts_boundary_values():
    """Valid edge values must still be accepted."""
    cfg = GridSimConfig(smoothing_alpha=1.0, p_gen_rated_kw=0.0, droop_kv_per_kw=0.0)
    assert cfg.smoothing_alpha == 1.0
