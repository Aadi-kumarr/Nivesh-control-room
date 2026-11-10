# Nivesh Control Room

Personal investment tracker that runs locally on Windows: FastAPI + MongoDB + React.

`data/nivesh-backup.json` is the master copy of the old app's data. Never edit or delete it.

## Start the app

Double-click `start.bat`. It checks MongoDB, starts the server and opens http://localhost:8000.
Close its window to stop the app.

After changing frontend code, run `npm run build` in `frontend/`. For development, `dev.bat`
runs the API and the Vite dev server with hot reload at http://localhost:5173.

## Setup

Needs Python 3.11+, Node 20+ and MongoDB running at `mongodb://localhost:27017`.

```bat
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
cd ..\frontend
npm install
npm run build
```

## Personal files

`data/` and the one-time migration scripts (`import_backup.py`, `phase2_fixes.py`,
`verify_import.py`) hold personal portfolio data, so they stay out of git, along with
`backend/tests/test_personal_data.py`, which tests them.

## Symbol check

```bat
cd backend
.venv\Scripts\python scripts\check_symbols.py
```

`check_symbols.py` only reports; it changes nothing.

## Run the API

```bat
cd backend
.venv\Scripts\python -m uvicorn app.main:app --reload
```

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Health check |
| `GET /api/profiles` | List profiles (default first) with their transaction counts |
| `POST /api/profiles` | Add a profile: `name` (unique, ignoring case) and `colour` (`#rrggbb`) |
| `PATCH`, `DELETE /api/profiles/{id}` | Rename or recolour; delete (not the default) after saving a backup |
| `GET /api/instruments` | Every instrument, shared by all profiles |
| `GET /api/portfolio` | Value, P&L and XIRR; first refreshes the active profile's held instruments whose last attempt is over 15 minutes old |
| `POST /api/prices/refresh` | Fetch prices from Yahoo now, for the active profile's held instruments |
| `GET /api/history?interval=monthly` | Month-end value and net invested, total and per asset class |
| `GET /api/xirr?start=YYYY-MM-DD&end=YYYY-MM-DD` | Returns for a time frame (end optional, default today), total, per asset class and per instrument |
| `GET /api/fx?date=YYYY-MM-DD` | USDINR market rate and the rate used for that date |
| `GET /api/symbols/check` | Preview a symbol's Yahoo price without saving |
| `POST /api/transactions` | Add a transaction |
| `PATCH`, `DELETE /api/transactions/{id}` | Edit or delete a transaction |
| `POST /api/instruments` | Add an instrument |
| `GET`, `PATCH`, `DELETE /api/instruments/{id}` | Read, edit or delete an instrument (delete needs no transactions) |
| `PUT /api/cash` | Set cash |
| `GET /api/backups` | List snapshots |
| `POST /api/export` | Save a full snapshot to `data/backups/exports/` |

Interactive docs: http://localhost:8000/docs

## Profiles

Each person's transactions and cash belong to a profile. Instruments, prices, price history
and FX are shared, and the `FX_DISCOUNT_INR` rule applies to every profile.

- Per-person routes read the `X-Profile-Id` header through one dependency,
  `profiles.get_scope`. A missing or unknown id means the default profile. Its
  `transactions` only ever see that profile's documents, and `tests/test_profiles.py`
  fails if app code queries `db.transactions` directly.
- A profile lists only the instruments it has traded. **Add transaction** (asset class page,
  or **Add first transaction** on an empty dashboard) picks from every instrument.
- The default profile can't be deleted. Deleting another one first saves it and its
  transactions to `data/backups/profiles/`, then removes them.
- The UI remembers the last profile in `localStorage` (`nivesh.activeProfileId`).

### Load

- **Prices** are refreshed only for instruments the active profile holds (quantity not 0),
  plus USDINR. Each instrument has its own 15-minute rule, kept in `price_attempted_at`, which
  records every attempt, failed ones too, so a failing symbol is retried at most every 15
  minutes. A trade that reopens a position (from 0 to held) clears it, so that price is
  fetched on the next load. Closed positions keep their last price; their value is 0 either way.
- **The UI caches** each profile's portfolio and history in memory for up to 15 minutes, so
  switching back to a profile makes no requests. Writes clear what they change: transactions
  and cash clear that profile; instruments and prices, which are shared, clear every profile.
  Switching profile aborts the previous profile's requests, and a late response is never
  shown under another profile.
- **Charts** (recharts, over half the code) are a separate file loaded only when a chart is
  shown, and the history chart is fetched when it scrolls into view.

To add profiles to a database from before this feature, run this once from `backend/`.
It takes a full `mongodump` into `data/backups/pre-profiles-<timestamp>/` first, only adds
fields and documents, and is safe to run again:

```bat
.venv\Scripts\python scripts\migrate_profiles.py
```

## USD transactions

New transactions on US stocks are entered with `price_usd`. The rate is Yahoo's USDINR close for
that date (or the last trading day before it) minus `FX_DISCOUNT_INR` from `backend/.env`, and
`price_inr = price_usd * fx_rate_used`. Send `fx_rate_used` to set the rate yourself. It stays on
that transaction through later edits until you send `fx_rate_used: null`. If Yahoo fails and no
rate is sent, the API returns 422; a rate is never guessed.

A saved trade's rate only changes when its date changes (unless the rate is manual). Editing the
price keeps the rate, so changing `FX_DISCOUNT_INR` never rewrites existing trades.

## P&L and XIRR

Costs use a moving average: a sell removes shares at the current average, and the average
starts over when a position reaches 0.

- Unrealised P&L = current value - cost of current holdings. Its % is of that cost.
- Realised P&L = sell amount - moving-average cost of the shares sold.
- Total P&L = realised + unrealised. `tests/test_pnl.py` checks this on exact fractions.

Cash is not part of P&L or XIRR. XIRR is always shown at its real value, however large, so a
short holding can show a very big number or almost -100%. It shows `-` only when the API returns
null: no trades, or cash that only flows one way. The API also returns `holding_days` (first buy
to today, or to the last sell once nothing is held), which does not affect what's shown.

## Returns for a time frame

The XIRR cards and columns have a time-frame picker: 1M, 3M, 6M, 1Y, YTD (from Dec 31 of the
previous year), All and a custom range. The choice is shared by the dashboard, asset-class and
instrument pages. **All** is the existing all-time XIRR, unchanged and with no extra request.
Any other choice asks `GET /api/xirr` once; the UI keeps the answer per profile and time frame
for up to 15 minutes, and a write clears it like the portfolio.

For a period from S to E, holdings on S are valued at that day's close (the last trading day
before it when S is a holiday) and holdings on E at today's dashboard price, or that day's close
for a past end date. The trades in between are the cash flows. Then:

- ₹ gain = end value + sells - start value - buys.
- Absolute return (Modified Dietz) = gain / (start value + each buy and sell weighted by the
  share of the period it was invested; sells count negative). Money sold and bought back is
  not counted twice. When nothing was at work it shows `—` and only the ₹ gain.
- Annualised (XIRR) = the yearly rate for those flows, with the start value as the first one.
  It uses the same solver as the all-time XIRR.

Under a year the absolute return is the main figure (annualising a few weeks exaggerates it);
from a year on, XIRR is. "from <date>" means the first trade was after S. Manual-price
instruments, and Yahoo ones with no close near the date, are valued at their last trade price
on or before it and listed as estimated.

Daily closes are fetched once per symbol from Yahoo (only for instruments held on a past date)
and cached in the `daily_closes` collection, which only grows to cover earlier dates. Like
`price_history`, it is part of each snapshot.

## Allocation donut

Click an asset class on the dashboard donut (or its legend name) to see its holdings, one slice
per instrument by current value. The 7 largest always get a slice; past those, holdings under 3%
of the class are grouped as Others, and the legend lists every holding. Back, the "All"
breadcrumb, the centre of the donut or Esc return. Cash is not drillable. It uses the portfolio
already loaded, so drilling makes no request.

## Portfolio history

Month-end values use Yahoo's monthly closes, converted back to the as-traded price where a later
split adjusted them, and are cached in the `price_history` collection. Manual instruments and
months with no Yahoo data use the last trade price and are marked estimated. Today's point uses
the same numbers as `GET /api/portfolio`, including cash; earlier points have no cash history.

## Backups

- Deleting a profile saves its data to `data/backups/profiles/` first (never pruned).
- Every API write saves a snapshot to `data/backups/auto/` (newest 50 kept).
- The first API use each day saves one to `data/backups/daily/` (newest 365 kept).
- **Export backup** saves a snapshot to `data/backups/exports/`. These are never deleted or
  mirrored, and `data/` stays out of git.
- Set `BACKUP_MIRROR_DIR` in `backend/.env` to copy each snapshot elsewhere, e.g. OneDrive.
  The same limits apply there, and only to files with these snapshot names.
- If a backup fails, the write still succeeds and the response has a warning.

To restore, run this from `backend/`. It creates a new database and never touches `nivesh`:

```bat
.venv\Scripts\python scripts\restore_backup.py ..\data\backups\auto\<file>.json
```

## Tests

```bat
cd backend
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest tests
```

Tests use mongomock and never touch the real database.

The frontend's cache and profile-switch logic (`src/store.ts`), time-frame dates
(`src/periods.ts`) and donut grouping (`src/allocation.ts`) have their own tests, run by
Node's built-in test runner (Node 22.18+, no extra packages):

```bat
cd frontend
npm test
```

## Layout

| Path | Purpose |
| --- | --- |
| `backend/app/` | FastAPI app, MongoDB connection, live prices, valuation, backups |
| `backend/calc.py` | Portfolio math: holdings, value, P&L, XIRR |
| `backend/scripts/` | Symbol check, restore and startup scripts |
| `backend/tests/` | pytest suite |
| `frontend/` | React + Vite app; `frontend/dist` is served at http://localhost:8000 |
| `docs/screenshots/` | Screenshots of each screen |
| `data/backups/` | JSON backups of the database |

Money is stored in INR unless a field is explicitly USD.
