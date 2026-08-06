# Alt-Track: Alternative Asset Portfolio Tracker

Alt-Track is a full-stack portfolio management application for tracking alternative assets such as watches, trading cards, art, wine, sneakers, and private-company interests.

The application combines portfolio analytics, valuation history, asset organization, risk indicators, and secure multi-user access in a responsive FastAPI web interface.

**Live demo:** [alternative-asset-tracker.vercel.app](https://alternative-asset-tracker.vercel.app/)

Select **Try Interactive Demo** to launch an isolated, prepopulated portfolio without creating an account.

## Features

* Create, edit, categorize, archive, and restore alternative assets
* Track cost basis, current value, and unrealized gain or loss
* Review valuation history and asset changes over time
* Visualize portfolio allocation by asset category
* Identify concentration, liquidity, valuation-staleness, and asset-class risk
* Exclude archived assets from active portfolio calculations while preserving their history
* Register and manage an individual portfolio through authenticated access
* Launch an isolated interactive demo with prepopulated sample data

## Portfolio analytics

The dashboard calculates:

* Total cost basis
* Current portfolio value
* Unrealized gain or loss
* Category allocation
* Asset concentration
* Valuation staleness
* Per-asset risk indicators

The risk indicator combines asset-class risk, valuation performance, valuation age, liquidity, and portfolio concentration. It is designed as an informational portfolio-monitoring tool rather than an investment recommendation.

## Technology

* **Backend:** Python, FastAPI, SQLModel
* **Database:** SQLite for local development and Neon PostgreSQL for deployment
* **Frontend:** Jinja, HTMX, CSS, Chart.js
* **Authentication:** Argon2 password hashing and signed sessions
* **Testing:** Pytest
* **Deployment:** Vercel

## Engineering highlights

* Server-side ownership checks isolate each user's portfolio data
* Temporary demo portfolios prevent visitors from affecting one another
* Valuation-history records preserve asset changes over time
* Archive and restore workflows retain historical data while excluding inactive assets from current analytics
* Business calculations are separated into independently testable functions
* Database initialization includes safe, repeatable schema migration handling
* Automated tests cover authentication, authorization, validation, portfolio calculations, valuation history, archival workflows, demo isolation, and database initialization

## Local development

Create and activate a virtual environment:

```bash
python -m venv .venv
```

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements-dev.txt
```

Create the local environment file:

```bash
# Windows
copy .env.example .env

# macOS/Linux
cp .env.example .env
```

Start the application:

```bash
uvicorn main:app --reload
```

When no external database URL is configured, Alt-Track automatically uses a local SQLite database.

## Testing

Run the automated test suite with:

```bash
pytest -q
```

Tests cover authentication, user-data isolation, validation, valuation history, archive and restore behavior, portfolio calculations, demo isolation, database initialization, and safe chart rendering.
