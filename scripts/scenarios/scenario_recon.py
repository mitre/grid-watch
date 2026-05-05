#!/usr/bin/env python3
"""Scenario 1 — Reconnaissance

ATT&CK for ICS Tactic: Collection / Discovery
Technique: T0802 — Automated Collection, T0846 — Remote System Discovery

The adversary connects to the DNP3 outstation and probes it using an
integrity poll, class polls, and a delay measure — standard DNP3 read
operations that reveal the outstation's data model and timing.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scenario_helpers import (
    ScenarioResult,
    ScenarioStep,
    connect,
    save_result,
    send_class_poll,
    send_delay_measure,
    send_integrity_poll,
    _now,
)


async def run() -> ScenarioResult:
    result = ScenarioResult(
        name="Reconnaissance",
        description=(
            "Passive enumeration of the DNP3 outstation. Probes the device "
            "using integrity polls, class polls, and delay measure to discover "
            "data points and timing characteristics."
        ),
        attck_tactic="Collection / Discovery (T0802, T0846)",
        timestamp=_now(),
    )

    print("=" * 60)
    print("SCENARIO 1: Reconnaissance")
    print("=" * 60)

    # Step 1: Connect
    print("\n[1] Connecting to outstation ...")
    channel = await connect()
    result.steps.append(
        ScenarioStep(
            action="connect",
            detail="TCP connection established to outstation",
            timestamp=_now(),
        )
    )
    print("    Connected.")

    # Step 2: Integrity poll
    print("[2] Sending integrity poll (full data read) ...")
    resp = await send_integrity_poll(channel)
    result.steps.append(
        ScenarioStep(
            action="integrity_poll",
            detail="Requested all static data (Class 0, 1, 2, 3)",
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Response: {resp}")

    # Step 3: Class polls
    print("[3] Sending class polls (event enumeration) ...")
    for cls in [1, 2, 3]:
        resp = await send_class_poll(
            channel,
            class_1=(cls == 1),
            class_2=(cls == 2),
            class_3=(cls == 3),
        )
        result.steps.append(
            ScenarioStep(
                action=f"class_{cls}_poll",
                detail=f"Class {cls} event poll",
                response=resp,
                timestamp=_now(),
            )
        )
        print(f"    Class {cls} poll response: {resp}")

    # Step 4: Delay measure
    print("[4] Sending delay measure (timing fingerprint) ...")
    resp = await send_delay_measure(channel)
    result.steps.append(
        ScenarioStep(
            action="delay_measure",
            detail="DELAY_MEASURE request for timing characterization",
            response=resp,
            timestamp=_now(),
        )
    )
    print(f"    Delay measure response: {resp}")

    await channel.close()

    # All steps should have returned RESPONSE
    all_responded = all(s.response == "RESPONSE" for s in result.steps if s.response)
    result.passed = all_responded

    result.observations = [
        "Outstation accepted TCP connection without authentication",
        "Integrity poll returned RESPONSE — outstation data is readable",
        "Class polls returned RESPONSE — event data is accessible",
        "Delay measure returned RESPONSE — timing fingerprint obtained",
        "Outstation exposes: 2 binary inputs (BI), 2 analog inputs (AI), "
        "2 binary outputs (BO) — per config.yaml",
        "AI[0] = bus voltage (kV), AI[1] = power deficit (kW)",
        "BO[0] = breaker control, BO[1] = generator control",
    ]

    print(f"\n{'PASS' if result.passed else 'FAIL'}: Reconnaissance complete.")
    for obs in result.observations:
        print(f"  - {obs}")

    return result


def main() -> None:
    result = asyncio.run(run())
    path = save_result(result)
    print(f"\nResults saved to: {path}")


if __name__ == "__main__":
    main()
