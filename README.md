# App Store Connect Download Metrics to Discord

Daily GitHub Action that retrieves App Store Connect Sales & Trends report data and posts summary stats (last 24h, 7d, 30d unit downloads) to a Discord channel via webhook.

## Features
- Scheduled (cron) + manual dispatch
- Secure: All sensitive values provided as GitHub Secrets
- Lightweight: Pure Python + httpx

## GitHub Secrets Required
Create these repository secrets (Settings > Secrets and variables > Actions):

| Secret | Description |
| ------ | ----------- |
| APPSTORE_ISSUER_ID | App Store Connect API Key Issuer ID (UUID) |
| APPSTORE_KEY_ID | App Store Connect API Key ID (e.g. ABCDE12345) |
| APPSTORE_PRIVATE_KEY | Contents of the `.p8` private key (paste full text including BEGIN/END) |
| APPSTORE_VENDOR_NUMBER | Your Vendor Number (from Payments and Financial Reports) |
| DISCORD_WEBHOOK_URL | Discord webhook URL to post the message |

Optional:
| Variable | Description |
| -------- | ----------- |
| APPSTORE_TIMEOUT | Override HTTP timeout seconds (default 30) |
| APPSTORE_DEBUG | Set to `1` to log decoded header snippet for diagnostics |
| APPSTORE_LAG_DAYS | Manual lag days from today to assume last available date (default 1) |
| APPSTORE_AUTO_LATEST | If `1` (default) probe backwards to find latest available report up to `APPSTORE_MAX_PROBE_DAYS` |
| APPSTORE_MAX_PROBE_DAYS | Max extra days to probe when auto latest enabled (default 5) |

## Generating App Store API Credentials
1. In App Store Connect, go to Users and Access > Keys (under **App Store Connect API**).
2. Create an API key with Sales and Reports access.
3. Download the `.p8` key file (you cannot re-download later). Open it and copy the entire contents to the `APPSTORE_PRIVATE_KEY` secret.
4. Note the Issuer ID and Key ID and add them as secrets.
5. Find your Vendor Number in Payments and Financial Reports.

## Local Development
Create a `.env` (DO NOT COMMIT) or export env vars:
```
APPSTORE_ISSUER_ID=...
APPSTORE_KEY_ID=...
APPSTORE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
APPSTORE_VENDOR_NUMBER=...
DISCORD_WEBHOOK_URL=...
```
Install deps and run:
```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

## How It Works
- Builds a JWT (ES256) required by App Store Connect APIs
- Fetches Sales & Trends report in TSV (Units) for needed days (1,7,30) using appropriate date parameters
- Aggregates unit counts for your vendor
- Posts a formatted message to Discord

## Data Availability, Timezones & Lag
Apple's Sales & Trends daily report often appears several hours into the next UTC day. If you are far ahead of UTC (e.g. Australia) you may observe that today's run still only has data up to two days prior. To mitigate:

1. The script now determines the latest available date automatically (probing backwards) when `APPSTORE_AUTO_LATEST=1`.
2. You can set `APPSTORE_LAG_DAYS` (e.g. `2`) if you prefer a fixed anchor lag.
3. The Discord message includes a "Data through: YYYY-MM-DD" line so you know what the anchor date is.

If no report is found within the probe window, periods will display `N/A`.

## Limitations / Notes
- Reports appear mid/late morning UTC; schedule the Action later if you see frequent lag.
- Missing report yields `N/A` but does not fail the workflow.
- GitHub Action scheduled daily at 13:00 UTC by default (adjust in workflow if needed).

## GitHub Action Workflow
See `.github/workflows/daily-report.yml`. Add secrets before enabling.

## Future Improvements
- Cache / store historical values
- Include revenue estimates
- Add retries / backoff on 5xx

## License
MIT
