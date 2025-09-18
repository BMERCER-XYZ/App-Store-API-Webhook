import os
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

class DiscordNotifier:
    def __init__(self):
        try:
            self.webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
        except KeyError:
            raise RuntimeError("Missing DISCORD_WEBHOOK_URL environment variable")
        self.timeout = float(os.getenv("DISCORD_TIMEOUT", "15"))

    async def send(self, content: str, username: Optional[str] = None) -> bool:
        payload = {"content": content}
        if username:
            payload["username"] = username
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(self.webhook_url, json=payload, timeout=self.timeout)
                if r.status_code >= 400:
                    logger.error("Discord webhook error %s: %s", r.status_code, r.text)
                    return False
                return True
        except Exception as e:  # noqa
            logger.exception("Error sending Discord message: %s", e)
            return False
