# Scenario 4: Grid Attack and Verify

## Overview

| Field | Value |
|---|---|
| **Tactic** | Impact, Collection, Inhibit Response Function |
| **Techniques** | [T0855 - Unauthorized Command Message](https://attack.mitre.org/techniques/T0855/), [T0861 - Point & Tag Identification](https://attack.mitre.org/techniques/T0861/), [T0816 - Device Restart/Shutdown](https://attack.mitre.org/techniques/T0816/) |
| **Target** | DNP3 outstation on TCP :20000 |
| **Impact** | Operate breaker/generator controls then verify state changes via read-back |

## Objective

Combine a control operation with an immediate read-back verification chain.
Demonstrates that an attacker can not only send commands but confirm their
effect without any authentication.

## Fact Variables

| Fact | Description | Type | Default |
|------|-------------|------|---------|
| `dnp3.server.ip` | IP address of the outstation | string | `127.0.0.1` |
| `dnp3.local.link` | Link-layer address of the master | int | `3` |
| `dnp3.remote.link` | Link-layer address of the outstation | int | `1` |
| `dnp3.operate.indices` | Binary output indices to operate (comma-separated) | string | `0` (breaker), `1` (generator) |
| `dnp3.operate.mode` | DNP3 operate mode | string | `DIRECT_OPERATE` |
| `dnp3.operate.type` | Control relay output block type | string | `LATCH_ON`, `LATCH_OFF` |
| `dnp3.operate.tcc` | Trip-close code | string | `NUL` |
| `dnp3.data.group` | DNP3 object group to read | int | `1` |
| `dnp3.data.start` | First index in the read range | int | `0` |
| `dnp3.data.end` | Last index in the read range | int | `1` |

## Caldera Operation

Load `docs/sources/grid-simulator-facts.yml` as the fact source, then
build an operation using the following abilities in order:

| Step | Ability | Ability ID | Description |
|------|---------|------------|-------------|
| 1 | DNP3 (TCP) - Operate | `5a073c32-e022-3724-85ad-7192464287b8` | Send CROB to breaker/generator controls |
| 2 | DNP3 (TCP) - Read | `689ee6dd-9f24-352f-90da-8d06fae7d19c` | Read back a specific group/range to verify |
| 3 | DNP3 (TCP) - Read All | `8d0889f8-6801-4986-baaf-83622bf08ced` | Read all points in a group |
| 4 | DNP3 (TCP) - Integrity Poll | `1d412b2f-f4ae-3ed2-822e-55a4490a7d1a` | Full Class 0 poll of all data |
| 5 | DNP3 (TCP) - Warm Restart | `fe8403ab-e37c-40b6-8f0e-6b0b4192f675` | Reset the outstation |

## Expected Observations

- Step 1: Control command accepted without authentication (T0855) - breaker or generator state changes
- Step 2: Targeted read confirms the operated point reflects the new state (T0861)
- Step 3: Read All returns all points in the group, showing the full updated picture
- Step 4: Integrity poll shows updated binary outputs, binary inputs, and analog inputs
- Step 5: Warm restart accepted without authentication (T0816) - outstation reinitializes and returns to default state

![HMI during grid attack and verify](../images/scenario-4-grid-attack-verify.png)

## See Also

- [MITRE Caldera for OT](https://github.com/mitre/caldera-ot)
- [ATT&CK for ICS - T0855](https://attack.mitre.org/techniques/T0855/)
- [ATT&CK for ICS - T0861](https://attack.mitre.org/techniques/T0861/)
- [ATT&CK for ICS - T0816](https://attack.mitre.org/techniques/T0816/)
