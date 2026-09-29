# Scenario 1: Reconnaissance

## Overview

| Field | Value |
|---|---|
| **Tactic** | Collection, Discovery |
| **Techniques** | [T0802 - Automated Collection](https://attack.mitre.org/techniques/T0802/), [T0861 - Point & Tag Identification](https://attack.mitre.org/techniques/T0861/) |
| **Target** | Grid Watch outstation over DNP3 |
| **Impact** | None - read-only operations only |

## Objective

Read all data points on the Grid Watch outstation without issuing any control
commands. This gives a baseline view of the breaker and generator controls,
their status inputs, the bus voltage, and the power deficit exposed by the
outstation.

![Grid Watch HMI baseline state](../images/scenario-1-reconnaissance.png)

## Fact Variables

| Fact | Description | Type | Default |
|------|-------------|------|---------|
| `dnp3.server.ip` | IP address of the outstation | string | `127.0.0.1` |
| `dnp3.local.link` | Link-layer address of the master | int | `3` |
| `dnp3.remote.link` | Link-layer address of the outstation | int | `1` |
| `dnp3.data.group` | DNP3 object group to read | int | `1` |
| `dnp3.data.start` | First index in the read range | int | `0` |
| `dnp3.data.end` | Last index in the read range | int | `1` |

## Caldera Operation

Load `docs/sources/grid-watch-simulator-facts.yml` as the fact source, then
build an operation using the following abilities in order:

| Step | Ability | Ability ID | Facts Used |
|------|---------|------------|------------|
| 1 | DNP3 (TCP) - Integrity Poll | `1d412b2f-f4ae-3ed2-822e-55a4490a7d1a` | `dnp3.server.ip`, `dnp3.local.link`, `dnp3.remote.link` |
| 2 | DNP3 (TCP) - Read All | `8d0889f8-6801-4986-baaf-83622bf08ced` | `dnp3.server.ip`, `dnp3.local.link`, `dnp3.remote.link`, `dnp3.data.group` |
| 3 | DNP3 (TCP) - Read | `689ee6dd-9f24-352f-90da-8d06fae7d19c` | `dnp3.server.ip`, `dnp3.local.link`, `dnp3.remote.link`, `dnp3.data.group`, `dnp3.data.start`, `dnp3.data.end` |

![Caldera - DNP3 (TCP) Read ability fact configuration](../images/caldera-read-ability.png)

## Expected Observations

- The outstation accepts a TCP connection without authentication.
- The integrity poll returns all static data: 2 binary inputs, 2 analog inputs, and 2 binary outputs.
- `AI[0]` reads bus voltage, roughly 10 to 12 kV with the breaker closed and the generator on.
- `AI[1]` reads power deficit, roughly 200 to 800 kW depending on generator state.
- `BO[0]` is the breaker control and `BO[1]` is the generator control, both readable without access control.
- The targeted read of group 1, indices 0 and 1, enumerates specific binary input points.
- Read-only operations trigger no alarms.

## See Also

- [Caldera for OT](https://github.com/mitre/caldera-ot)
- [ATT&CK for ICS - T0802](https://attack.mitre.org/techniques/T0802/)
- [ATT&CK for ICS - T0861](https://attack.mitre.org/techniques/T0861/)
