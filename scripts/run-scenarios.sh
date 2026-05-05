#!/bin/bash
# Run all adversary simulation scenarios against the live outstation.
#
# Usage:
#   bash scripts/run-scenarios.sh                    # outstation on localhost:20000
#   OUTSTATION_HOST=outstation bash scripts/run-scenarios.sh  # docker-compose
#
# Prerequisites:
#   - The DNP3 outstation (dnp3-sim/server.py) must be running
#   - Python virtual environment with dnp3py installed
#
# Optional: If tcpdump is available and run with sufficient privileges,
# DNP3 traffic is captured to tests/scenarios/captures/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RESULTS_DIR="${PROJECT_DIR}/tests/scenarios"
CAPTURE_DIR="${RESULTS_DIR}/captures"
SCENARIOS_DIR="${SCRIPT_DIR}/scenarios"

OUTSTATION_HOST="${OUTSTATION_HOST:-127.0.0.1}"
OUTSTATION_PORT="${OUTSTATION_PORT:-20000}"
PYTHON="${PYTHON:-python3}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

mkdir -p "${RESULTS_DIR}" "${CAPTURE_DIR}"

# ── Check outstation is reachable ────────────────────────────────────
echo -e "${CYAN}Checking outstation at ${OUTSTATION_HOST}:${OUTSTATION_PORT} ...${NC}"
if ! "${PYTHON}" -c "
import socket
s = socket.create_connection(('${OUTSTATION_HOST}', ${OUTSTATION_PORT}), 3)
s.close()
" 2>/dev/null; then
    echo -e "${RED}ERROR: Cannot connect to outstation at ${OUTSTATION_HOST}:${OUTSTATION_PORT}${NC}"
    echo "Make sure the server is running: python dnp3-sim/server.py"
    exit 1
fi
echo -e "${GREEN}Outstation is reachable.${NC}"

# ── Start packet capture (if tcpdump is available) ───────────────────
TCPDUMP_PID=""
PCAP_FILE="${CAPTURE_DIR}/scenarios_$(date +%Y%m%d_%H%M%S).pcap"

if command -v tcpdump >/dev/null 2>&1; then
    echo -e "${CYAN}Starting packet capture -> ${PCAP_FILE}${NC}"
    tcpdump -i any -w "${PCAP_FILE}" "tcp port ${OUTSTATION_PORT}" >/dev/null 2>&1 &
    TCPDUMP_PID=$!
    sleep 1
    if kill -0 "${TCPDUMP_PID}" 2>/dev/null; then
        echo -e "${GREEN}Packet capture running (PID ${TCPDUMP_PID}).${NC}"
    else
        echo -e "${YELLOW}WARNING: tcpdump failed to start (may need sudo). Continuing without capture.${NC}"
        TCPDUMP_PID=""
    fi
else
    echo -e "${YELLOW}NOTE: tcpdump not found — skipping packet capture.${NC}"
    echo "  Install tcpdump for DNP3 traffic capture, or run with sudo."
fi

# ── Run scenarios ────────────────────────────────────────────────────
PASSED=0
FAILED=0

run_scenario() {
    local name="$1"
    local script="$2"

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}Running: ${name}${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    if OUTSTATION_HOST="${OUTSTATION_HOST}" OUTSTATION_PORT="${OUTSTATION_PORT}" \
       "${PYTHON}" "${script}"; then
        echo -e "\n${GREEN}[PASS] ${name}${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "\n${RED}[FAIL] ${name}${NC}"
        FAILED=$((FAILED + 1))
    fi

    # Brief pause between scenarios to let the sim settle
    sleep 2
}

run_scenario "Scenario 1: Reconnaissance" \
    "${SCENARIOS_DIR}/scenario_recon.py"

run_scenario "Scenario 2: Unauthorized Control Commands" \
    "${SCENARIOS_DIR}/scenario_unauthorized_control.py"

run_scenario "Scenario 3: Grid Disruption" \
    "${SCENARIOS_DIR}/scenario_grid_disruption.py"

# ── Stop packet capture ─────────────────────────────────────────────
if [ -n "${TCPDUMP_PID}" ]; then
    echo ""
    echo -e "${CYAN}Stopping packet capture ...${NC}"
    kill "${TCPDUMP_PID}" 2>/dev/null || true
    wait "${TCPDUMP_PID}" 2>/dev/null || true
    if [ -f "${PCAP_FILE}" ]; then
        echo -e "${GREEN}Capture saved: ${PCAP_FILE}${NC}"
    fi
fi

# ── Summary ──────────────────────────────────────────────────────────
TOTAL=$((PASSED + FAILED))
echo ""
echo "============================================"
echo -e "  Scenarios run:   ${TOTAL}"
echo -e "  Passed:          ${GREEN}${PASSED}${NC}"
echo -e "  Failed:          ${RED}${FAILED}${NC}"
echo -e "  Results:         ${RESULTS_DIR}/"
if [ -n "${TCPDUMP_PID}" ] && [ -f "${PCAP_FILE}" ]; then
    echo -e "  Packet capture:  ${PCAP_FILE}"
fi
echo "============================================"

if [ "${FAILED}" -gt 0 ]; then
    exit 1
fi
