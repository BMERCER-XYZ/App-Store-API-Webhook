import asyncio
import logging
import os
from datetime import datetime, timezone

from .appstore import AppStoreClient
from .discord import DiscordNotifier

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

async def run():
    client = AppStoreClient()
    notifier = DiscordNotifier()

    periods = {"24h": 1, "7d": 7, "30d": 30}
    results = {}
    # Obtain anchor date once by asking for aggregate 1 day (which internally finds anchor) but we also need anchor logic.
    # We'll call the private determination helper indirectly by reusing aggregate for 1 day then re-determining.
    # Simplest: call protected method via name (acceptable here for internal script).
    try:
        anchor_date = await client._determine_latest_available_date()  # type: ignore
    except Exception:
        anchor_date = None
    for label, days in periods.items():
        units = await client.aggregate_units(days)
        results[label] = units

    lines = [":iphone: App Store Download Units Summary"]
    if anchor_date:
        lines.append(f"Data through: {anchor_date.isoformat()} (UTC)")
    else:
        lines.append("Data through: UNKNOWN (anchor date not found)")
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    for label, units in results.items():
        val = str(units) if units is not None else 'N/A'
        lines.append(f"• Period {label}: {val}")
    lines.append(f"Timestamp: {timestamp}")

    content = "\n".join(lines)
    ok = await notifier.send(content)
    if ok:
        logger.info("Discord message sent successfully")
    else:
        logger.error("Failed to send Discord message")


def main():
    asyncio.run(run())

if __name__ == "__main__":
    main()
