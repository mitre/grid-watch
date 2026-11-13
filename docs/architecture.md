# Architecture

The PLC runs as one Python process with three cooperating components. The HMI is a separate process that polls the PLC over DNP3, like any other client.

```mermaid
flowchart TD
    A["DNP3 Client\n(Caldera / Tooling)"]
    B["DNP3 Outstation\n(plc.py)"]
    C["DatabaseCommandHandler\n(processes control commands)"]
    D["Database - Binary Outputs\n(breaker, generator controls)"]
    E["GridProcessSim\n(sim.py)"]
    F["Database - Analog and Binary Inputs\n(bus voltage, power deficit, status)"]
    G["HMI\n(hmi.py)"]

    A -->|"DNP3 over TCP :20000"| B
    G -->|"DNP3 over TCP :20000"| B
    B --> C
    C -->|"writes control state"| D
    D --> E
    E -->|"recalculates voltage & load"| F
    F -->|"served on next read"| B
```

## Data Flow

1. Caldera (or any DNP3 master) connects to the outstation on TCP port 20000
2. A control request (Operate) is dispatched to `DatabaseCommandHandler`
3. The handler writes the new binary output state (e.g. breaker tripped, generator off)
4. `GridProcessSim` reads the updated controls and recalculates grid state using an EMA model
5. Recalculated analog inputs (bus voltage, power deficit) and the status binary inputs are written back to the database
6. Subsequent DNP3 reads (Integrity Poll, Read All) return the updated values
7. The HMI sends an integrity poll every second and shows the result
