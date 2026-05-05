import asyncio
import logging
import os
import sys

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dnp3.master import Master
from dnp3.transport_io.channel import TcpConfig
from dnp3.transport_io.tcp_client import TcpClientChannel

from dnp3_frame import MASTER_ADDR, OUTSTATION_ADDR, decode_frame, encode_frame
from dnp3_read import parse_dnp3_response

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 20000


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


async def main() -> None:
    master = Master()
    channel = TcpClientChannel(config=TcpConfig(host=HOST, port=PORT))
    await channel.open()
    logger.info("Connected to outstation at %s:%d", HOST, PORT)

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
    info = master.process_response(app)
    logger.info("Direct operate response: function=%s", info.function if info else "none")

    await channel.close()
    logger.info("Done")


if __name__ == "__main__":
    asyncio.run(main())
