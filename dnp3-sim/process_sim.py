import asyncio
import random
from dataclasses import dataclass

from dnp3.database import Database


@dataclass
class GridSimConfig:
    # how often to update the “plant”
    tick_seconds: float = 0.5

    # nominal grid settings
    v_nom_kv: float = 12.47  # rated bus voltage (kV) when fully loaded by gen
    p_load_kw_init: float = 800.0  # starting load before the random walk kicks in
    p_gen_rated_kw: float = 600.0  # max output of the generator when it's on

    # droop: voltage drops linearly as the power deficit grows
    # smoothing_alpha: EMA coefficient — lower = slower response to changes
    droop_kv_per_kw: float = 0.002
    smoothing_alpha: float = 0.15


class GridProcessSim:
    """Simplified electrical grid process simulation.

    Sensors mapped to DNP3 Analog Inputs:
      AI[0] = bus voltage (kV)
      AI[1] = power deficit (kW)

    Controls mapped to DNP3 Binary Outputs:
      BO[0] = breaker_closed (True=closed, False=open)
      BO[1] = generator_on   (True=on, False=off)

    The system trends toward a steady state by converging voltage toward a target
    that depends on breaker/gen/load.
    """

    def get_display_state(self) -> dict[str, dict[int, dict[str, bool | float | str]]]:
        return {
            "binary_inputs": {
                0: {"value": self.breaker_closed, "quality": "ONLINE"},
                1: {"value": self.generator_on, "quality": "ONLINE"},
            },
            "analog_inputs": {
                0: {"value": self.v_kv, "quality": "ONLINE"},
                1: {"value": self.p_def_kw, "quality": "ONLINE"},
            },
            "binary_outputs": {
                0: {"value": self.breaker_closed, "quality": "ONLINE"},
                1: {"value": self.generator_on, "quality": "ONLINE"},
            },
        }

    def __init__(self, cfg: GridSimConfig | None = None):
        self.cfg = cfg or GridSimConfig()
        self.v_kv = self.cfg.v_nom_kv
        self.p_load_kw = self.cfg.p_load_kw_init
        self.breaker_closed = False
        self.generator_on = False
        self.p_def_kw = 0.0
        self.paused = False

    def pause(self) -> None:
        """Pause the simulation. The run loop will skip updates while paused."""
        self.paused = True

    def resume(self) -> None:
        """Resume the simulation after a pause."""
        self.paused = False

    def reset(self, db: Database) -> None:
        """Reset the simulation and database to initial conditions."""
        self.v_kv = self.cfg.v_nom_kv
        self.p_load_kw = self.cfg.p_load_kw_init
        self.breaker_closed = False
        self.generator_on = False
        self.p_def_kw = 0.0
        self.paused = False

        db.update_analog_input(0, value=self.v_kv)
        db.update_analog_input(1, value=self.p_def_kw)
        db.update_binary_output(0, value=False)
        db.update_binary_output(1, value=False)

    @staticmethod
    def _bo(db: Database, index: int) -> bool:
        bo = db.get_binary_output(index)
        return bool(bo.value) if bo is not None else False  # treat missing point as off

    @staticmethod
    def _set_ai(db: Database, index: int, value: float) -> None:
        db.update_analog_input(index, value=float(value))

    def _update_load(self) -> None:
        # Random-walk load, clamped to a reasonable range
        self.p_load_kw += random.uniform(-20.0, 20.0)
        self.p_load_kw = max(100.0, min(self.p_load_kw, 1500.0))

    def _power_deficit_kw(self, breaker_closed: bool, generator_on: bool) -> float:
        if not breaker_closed:
            return self.p_load_kw
        p_gen = self.cfg.p_gen_rated_kw if generator_on else 0.0
        return max(self.p_load_kw - p_gen, 0.0)

    def _v_target(self, breaker_closed: bool, generator_on: bool) -> float:
        if not breaker_closed or not generator_on:
            return 0.05  # near-zero voltage if breaker is open or generator is off

        # power deficit = how much load the generator can't cover
        p_def = max(self.p_load_kw - self.cfg.p_gen_rated_kw, 0.0)

        # simple droop model: voltage sags proportionally to the deficit
        v = self.cfg.v_nom_kv - self.cfg.droop_kv_per_kw * p_def
        return max(0.0, min(v, self.cfg.v_nom_kv))

    async def run(self, db: Database) -> None:
        # Make missing mappings obvious early
        if db.get_binary_output(0) is None or db.get_binary_output(1) is None:
            raise RuntimeError("Missing required controls: BO[0] and BO[1]")

        while True:
            if self.paused:
                await asyncio.sleep(self.cfg.tick_seconds)
                continue

            breaker_closed = self._bo(db, 0)
            generator_on = self._bo(db, 1)
            self.breaker_closed = breaker_closed
            self.generator_on = generator_on

            self._update_load()
            p_def = self._power_deficit_kw(breaker_closed, generator_on)
            self.p_def_kw = p_def
            vt = self._v_target(breaker_closed, generator_on)

            # EMA step: nudge current voltage toward the target each tick
            a = self.cfg.smoothing_alpha
            self.v_kv = self.v_kv + a * (vt - self.v_kv)

            # Publish sensors into the outstation database in real time
            self._set_ai(db, 0, self.v_kv)
            self._set_ai(db, 1, p_def)

            await asyncio.sleep(self.cfg.tick_seconds)
