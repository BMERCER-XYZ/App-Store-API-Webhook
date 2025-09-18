import os
import time
import json
import base64
import logging
import gzip
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import jwt  # PyJWT

logger = logging.getLogger(__name__)

APPSTORE_API_BASE = "https://api.appstoreconnect.apple.com"
SALES_REPORT_BASE = f"{APPSTORE_API_BASE}/v1/salesReports"
VENDOR_INFO_ENDPOINT = f"{APPSTORE_API_BASE}/v1/vendorInformation"

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
        self.debug = os.getenv("APPSTORE_DEBUG") == "1"
        # Configurable lag: number of days to step back from 'today' before starting aggregation
        # Example: if Apple data available only up to UTC yesterday-1 for your timezone, set 2
        self.lag_days = int(os.getenv("APPSTORE_LAG_DAYS", "1"))  # default assume previous day is ready
        # If enabled, auto-detect latest available date by probing backwards up to max_probe_days
        self.auto_latest = os.getenv("APPSTORE_AUTO_LATEST", "1") == "1"
        self.max_probe_days = int(os.getenv("APPSTORE_MAX_PROBE_DAYS", "5"))

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
            # Some reports may be gzipped (Apple sometimes compresses larger payloads)
            if tsv_bytes.startswith(b"\x1f\x8b"):
                try:
                    tsv_bytes = gzip.decompress(tsv_bytes)
                except Exception:
                    logger.warning("Failed to decompress gzip report for %s, using raw bytes", date_str)
            text = tsv_bytes.decode('utf-8', errors='replace')
            if self.debug:
                snippet = '\n'.join(text.splitlines()[:3])
                logger.debug("Decoded report %s snippet:\n%s", date_str, snippet)
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
        """Aggregate total units over the previous N days ending at latest available date.

        Strategy:
        1. Determine anchor date (latest available) either by configured lag or by probing.
        2. Sum units for anchor - (days-1) .. anchor inclusive.
        """
        anchor_date = await self._determine_latest_available_date()
        if anchor_date is None:
            logger.warning("Could not determine latest available anchor date")
            return None
        dates = [datetime.combine(anchor_date - timedelta(days=i), datetime.min.time(), tzinfo=timezone.utc) for i in range(0, days)]
        async with httpx.AsyncClient() as client:
            results = []
            for d in dates:
                units = await self.fetch_units_for_date(client, d)
                if units is not None:
                    results.append(units)
            if not results:
                return None
            return sum(results)

    async def _determine_latest_available_date(self) -> Optional[datetime.date]:
        """Determine the most recent date for which a report is available.

        If auto_latest disabled, we simply take (today - lag_days).
        If enabled, we probe backwards from today - lag_days up to max_probe_days additional days
        until we find a date with a report.
        """
        today = datetime.now(timezone.utc).date()
        base_candidate = today - timedelta(days=self.lag_days)
        if not self.auto_latest:
            return base_candidate
        async with httpx.AsyncClient() as client:
            for offset in range(0, self.max_probe_days + 1):
                candidate = base_candidate - timedelta(days=offset)
                dt = datetime.combine(candidate, datetime.min.time(), tzinfo=timezone.utc)
                units = await self.fetch_units_for_date(client, dt)
                if units is not None:
                    if offset > 0:
                        logger.info("Latest available report lag detected: %d extra day(s)", offset)
                    return candidate
            return None

    async def verify_vendor_access(self) -> bool:
        """Optional call to confirm the vendorNumber is valid and accessible with current credentials."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(VENDOR_INFO_ENDPOINT, headers=self._auth_headers(), timeout=self.timeout)
                if r.status_code == 403:
                    logger.error("Access forbidden to vendorInformation endpoint (check API key roles)")
                    return False
                r.raise_for_status()
                data = r.json()
                vendors = [v.get('attributes', {}).get('vendorNumber') for v in data.get('data', [])]
                if self.vendor_number not in vendors:
                    logger.warning("Configured vendor %s not in accessible list: %s", self.vendor_number, vendors)
                else:
                    logger.debug("Vendor %s confirmed accessible", self.vendor_number)
                return True
        except Exception as e:  # noqa
            logger.exception("Error verifying vendor access: %s", e)
            return False
