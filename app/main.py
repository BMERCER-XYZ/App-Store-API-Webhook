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
    for label, days in periods.items():
        units = await client.aggregate_units(days)
        results[label] = units

    lines = [":iphone: App Store Download Units Summary"]
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    for label, units in results.items():
        val = str(units) if units is not None else 'N/A'
        lines.append(f"• Last {label}: {val}")
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
