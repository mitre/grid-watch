import argparse
import asyncio
import logging

from dnp3.core.exceptions import DNP3Error
from dnp3.master import Master
from dnp3.transport_io.channel import ChannelError, TcpConfig
from dnp3.transport_io.tcp_client import TcpClientChannel

from simulator import SIM
from simulator.config import configure_logging, port_number
from simulator.dnp3_frame import (
    MASTER_ADDR,
    OUTSTATION_ADDR,
    decode_frame,
    encode_frame,
)
from simulator.dnp3_read import parse_dnp3_response

logger = logging.getLogger(__name__)

PROTOCOL = SIM["protocols"]["dnp3"]


async def _send_recv(channel: TcpClientChannel, raw_bytes: bytes) -> bytes:
    framed = encode_frame(raw_bytes, dest=OUTSTATION_ADDR, src=MASTER_ADDR)
    await channel.write_all(framed)
    buf = bytearray()
    while True:
        chunk = await asyncio.wait_for(channel.read(16384), timeout=5.0)
        if not chunk:
            raise ConnectionError("outstation closed connection")
        buf.extend(chunk)
        app = decode_frame(bytes(buf))
        if app and app[0] & 0x40:
            return app


async def run(host: str, port: int) -> None:
    master = Master()
    channel = TcpClientChannel(config=TcpConfig(host=host, port=port))
    await channel.open()
    logger.info("Connected to outstation at %s:%d", host, port)

    # Integrity poll
    logger.info("Sending integrity poll...")
    app = await _send_recv(channel, master.build_integrity_poll().to_bytes())
    pts = parse_dnp3_response(app)
    logger.info("Binary inputs:  %s", {k: v for k, v in pts.binary_inputs.items()})
    logger.info("Analog inputs:  %s", {k: round(v, 3) for k, v in pts.analog_inputs.items()})
    logger.info("Binary outputs: %s", {k: v for k, v in pts.binary_outputs.items()})

    # Direct operate - LATCH_ON breaker (index 0)
    logger.info("Sending direct operate (LATCH_ON index 0)...")
    builder = master.command_builder()
    builder.latch_on(index=0)
    app = await _send_recv(channel, master.build_direct_operate(builder.build_direct_operate()).to_bytes())
    status = parse_dnp3_response(app).command_statuses.get(0)
    logger.info("Direct operate response: status=%s", status)

    await channel.close()
    logger.info("Done")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m simulator.client",
        description=f"{SIM['name']} test client: polls the outstation, then closes the breaker."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        metavar="HOST",
        help="PLC to connect to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=port_number,
        default=PROTOCOL["port"],
        metavar="PORT",
        help=f"PLC port (default: {PROTOCOL['port']})",
    )
    parser.add_argument("--debug", action="store_true", help="debug logging")
    args = parser.parse_args()
    configure_logging(args.debug)
    try:
        asyncio.run(run(args.host, args.port))
    except KeyboardInterrupt:
        pass
    except (ChannelError, DNP3Error, OSError) as exc:
        logger.error("Could not reach the outstation at %s:%d: %s", args.host, args.port, exc)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
