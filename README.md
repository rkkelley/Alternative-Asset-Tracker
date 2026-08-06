# Alt-Track: Alternative Asset Portfolio Tracker

Alt-Track is a small portfolio application for tracking alternative assets such as watches, trading cards, art, wine, sneakers, and private-company interests. It is intentionally a straightforward FastAPI/SQLModel/HTMX project that demonstrates practical technology-risk controls: authenticated access, server-side ownership checks, validation, change history, archive/restore workflows, and transparent risk indicators.

Live demo: [alternative-asset-tracker.vercel.app](https://alternative-asset-tracker.vercel.app/) (the deployed environment may differ from this repository).

## Functionality

- Register and log in with an email and password.
- Create, edit, categorize, archive, restore, and review assets.
- Record valuation history when an asset is created, its value changes, or it is archived/restored.
- Exclude archived assets from active portfolio totals and allocation calculations.
- Display total cost basis, current market value, unrealized gain/loss, allocation by category, and heuristic per-asset risk indicators.
- Seed a shared interactive demo account from the landing page.

Valuation history is an application change history. It is not an immutable audit trail, nonrepudiation system, or formal compliance record.

## Architecture

- FastAPI routes and lifecycle management in `main.py`.
- SQLModel models in `models.py` with SQLite locally and PostgreSQL-compatible URLs in deployed environments.
- Password hashing and CSRF primitives in `security.py`.
- Independently testable totals, allocation, and risk calculations in `portfolio.py`.
- Server-rendered Jinja templates with HTMX form interactions and Chart.js allocation visualization.

## Local setup

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
```

Set a real `SECRET_KEY` in `.env` for a persistent local session key. When `DATABASE_URL` is absent, the app creates/uses `database.db` beside `main.py`. Tables are initialized with SQLModel's `create_all` on application startup; this project does not include a migration framework.

Start the app:

```bash
uvicorn main:app --reload
```

Useful environment variables are documented in `.env.example`:

- `SECRET_KEY`: required when `ENVIRONMENT=production`.
- `ENVIRONMENT`: use `production` to enable production cookie settings.
- `DATABASE_URL` or `POSTGRES_URL`: optional database connection string.
- `SESSION_MAX_AGE`: signed session lifetime in seconds; defaults to 3600.
- `COOKIE_SECURE`: optional override for HTTPS-only cookies.

## Security controls

- Registration hashes passwords with Argon2id through `argon2-cffi`; plaintext legacy accounts are not accepted by login.
- Session cookies are signed, time-limited, HttpOnly, SameSite=Lax, and Secure in production. Logout also increments a stored session version so a copied old token stops working.
- State-changing browser requests require a double-submit CSRF token. Forms include the token and HTMX requests send it in `X-CSRF-Token`.
- Asset, category, and valuation-history access is checked against the authenticated owner's ID on the server.
- Category IDs are re-checked before asset creation or editing, preventing cross-user category assignment.
- Monetary values, dates, names, notes, category IDs, and risk scores are validated server-side. Error messages are user-facing and do not include stack traces or database details.

These controls are appropriate for a portfolio project; they are not a claim of enterprise-grade security.

## Portfolio and risk calculations

Active assets contribute to total cost, current market value, unrealized gain/loss, and category allocation. Archived assets remain available for history and restore but do not contribute to active dashboard totals.

The risk indicator is a transparent heuristic, not an investment recommendation. Its weighted score combines asset-class risk (40%), loss proxy (20%), valuation staleness (20%), liquidity (10%), and concentration (10%). Staleness is bucketed at 30, 90, and 180 days; a loss greater than 20% adds the highest loss-proxy score.

## Demo behavior

The “Try Interactive Demo” action resets the shared `demo@alt-track.com` portfolio and reseeds representative active and archived assets each time it is entered. This prevents one visitor's destructive edits from permanently damaging the next visitor's starting point, but concurrent visitors can still observe the shared reset. The demo is intentionally simple and is not isolated per visitor.

## Tests

Install development dependencies and run:

```bash
pytest -q
```

The test suite selects a temporary SQLite database before importing the application, recreates its schema per test, and covers registration/login/logout, hashing, CSRF rejection, ownership enforcement, cross-user category assignment, valuation history, archive/restore idempotency, validation, demo reset behavior, totals, allocation, stale valuation, and concentration calculations.

## Database reset after the security/schema change

The existing local `database.db` may contain plaintext passwords. Local SQLite startup adds the new `session_version` column when it is missing, but a reset is the cleanest way to remove legacy records. Back it up if needed, then stop the app and recreate it before local use:

```powershell
Copy-Item database.db database.db.backup
Remove-Item database.db
uvicorn main:app --reload
```

The demo entry point upgrades an old plaintext demo record before reseeding, but ordinary legacy accounts are intentionally not accepted by login. PostgreSQL deployments need an equivalent schema migration or a fresh database because `create_all` does not alter existing tables.

## Known limitations and tradeoffs

- There is no email verification, login rate limiting, password reset, or external identity provider.
- There are no roles beyond per-user ownership; this is not role-based access control.
- SQLite is suitable for local development, while production database availability and migration operations remain deployment concerns.
- Monetary values remain floats to preserve the existing model; a production accounting system should use a fixed-precision decimal design.
- The demo is shared and reset-on-entry rather than isolated per visitor.
- Third-party UI scripts are loaded from CDNs; a hardened deployment should pin and review those assets or self-host them.

## Screenshots

- `[Screenshot placeholder: landing page and interactive demo button]`
- `[Screenshot placeholder: dashboard metrics, allocation chart, and risk indicators]`
- `[Screenshot placeholder: valuation history modal and archive/restore flow]`

## Portfolio project framing

This project is best presented as a review of a functioning system: identify realistic security and control weaknesses, prioritize remediation, implement server-side safeguards and meaningful tests, preserve useful behavior, and document residual limitations honestly.
