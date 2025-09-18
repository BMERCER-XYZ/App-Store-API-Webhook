import os
import time
import json
import base64
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import jwt  # PyJWT
from dateutil import tz

logger = logging.getLogger(__name__)

APPSTORE_API_BASE = "https://api.appstoreconnect.apple.com"
SALES_REPORT_BASE = "https://api.appstoreconnect.apple.com/v1/salesReports"

class AppStoreClient:
    def __init__(self):
        try:
            self.issuer_id = os.environ["APPSTORE_ISSUER_ID"]
            self.key_id = os.environ["APPSTORE_KEY_ID"]
            self.private_key = os.environ["APPSTORE_PRIVATE_KEY"].encode()
            self.vendor_number = os.environ["APPSTORE_VENDOR_NUMBER"]
        except KeyError as e:
            raise RuntimeError(f"Missing required environment variable: {e.args[0]}")
        self.timeout = float(os.getenv("APPSTORE_TIMEOUT", "30"))

    def _create_jwt(self) -> str:
        now = int(time.time())
        # 15 minute token window (max 20 per docs)
        payload = {
            'iss': self.issuer_id,
            'exp': now + 15 * 60,
            'aud': 'appstoreconnect-v1'
        }
        token = jwt.encode(payload, self.private_key, algorithm='ES256', headers={'kid': self.key_id, 'typ': 'JWT'})
        return token

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._create_jwt()}"}

    async def fetch_units_for_date(self, client: httpx.AsyncClient, target_date: datetime) -> Optional[int]:
        """Fetch total units for a single date (UTC date) from Sales & Trends API.
        Apple Sales Reports use DAILY frequency with filters.
        Returns integer units or None if unavailable.
        """
        # Report date format is YYYY-MM-DD per new API docs (v1) using filters
        date_str = target_date.strftime('%Y-%m-%d')
        params = {
            'filter[frequency]': 'DAILY',
            'filter[reportDate]': date_str,
            'filter[reportSubType]': 'SUMMARY',
            'filter[reportType]': 'SALES',
            'filter[vendorNumber]': self.vendor_number,
            'filter[version]': '1_0'
        }
        try:
            r = await client.get(SALES_REPORT_BASE, params=params, headers=self._auth_headers(), timeout=self.timeout)
            if r.status_code == 404:
                logger.warning("Report not found for date %s", date_str)
                return None
            r.raise_for_status()
            data = r.json()
            # Expect data['data'][0]['attributes']['reportContent'] base64 TSV
            items = data.get('data', [])
            if not items:
                logger.warning("Empty data array for date %s", date_str)
                return None
            content_b64 = items[0]['attributes'].get('reportContent')
            if not content_b64:
                logger.warning("Missing reportContent for date %s", date_str)
                return None
            tsv_bytes = base64.b64decode(content_b64)
            text = tsv_bytes.decode('utf-8', errors='replace')
            return self._parse_units_from_tsv(text)
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching report %s: %s", date_str, e)
        except Exception as e:  # noqa
            logger.exception("Unexpected error fetching report %s: %s", date_str, e)
        return None

    @staticmethod
    def _parse_units_from_tsv(tsv: str) -> Optional[int]:
        """Parse units from Sales & Trends summary report TSV.
        Typical header includes 'Units'. Sum units column across rows (excluding header)."""
        lines = [l for l in tsv.splitlines() if l.strip()]
        if not lines:
            return None
        header = lines[0].split('\t')
        try:
            units_idx = header.index('Units')
        except ValueError:
            # Fallback attempt (some older reports use 'units')
            units_idx = next((i for i, h in enumerate(header) if h.lower() == 'units'), None)
            if units_idx is None:
                return None
        total = 0
        for row in lines[1:]:
            cols = row.split('\t')
            if len(cols) <= units_idx:
                continue
            val = cols[units_idx].strip()
            if not val:
                continue
            try:
                total += int(val)
            except ValueError:
                continue
        return total

    async def aggregate_units(self, days: int) -> Optional[int]:
        """Aggregate total units over the previous N days (excluding today)."""
        end_date = datetime.now(timezone.utc).date()  # today (excluded)
        dates = [datetime.combine(end_date - timedelta(days=i), datetime.min.time(), tzinfo=timezone.utc) for i in range(1, days+1)]
        async with httpx.AsyncClient(base_url=APPSTORE_API_BASE) as client:
            results = []
            for d in dates:
                units = await self.fetch_units_for_date(client, d)
                if units is not None:
                    results.append(units)
            if not results:
                return None
            return sum(results)
