"""Process entry for `inspectio-worker`. Replace per plans/IMPLEMENTATION_PHASES.md."""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("inspectio.worker")


async def _run() -> None:
    log.info("inspectio-worker placeholder — implement consumer + scheduler per plans/")
    while True:
        await asyncio.sleep(3600.0)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
