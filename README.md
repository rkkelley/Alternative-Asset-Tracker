# Alt-Track: Alternative Asset Portfolio Tracker

Alt-Track is a full-stack portfolio management application for tracking alternative assets such as watches, trading cards, art, wine, sneakers, and private-company interests.

The application provides portfolio analytics, valuation history, asset categorization, risk indicators, and secure multi-user access through a responsive FastAPI web interface.

**Live demo:** [alternative-asset-tracker.vercel.app](https://alternative-asset-tracker.vercel.app/)

Select **Try Interactive Demo** to explore a prepopulated portfolio without creating an account.

## Features

* Create, edit, categorize, archive, and restore alternative assets
* Track cost basis, current value, and unrealized gain or loss
* Review valuation history and asset changes over time
* Visualize portfolio allocation by asset category
* Identify concentration, liquidity, valuation-staleness, and asset-class risk
* Separate archived assets from active portfolio calculations
* Register and manage an individual portfolio through authenticated access
* Launch a resettable interactive demo from the landing page

## Portfolio analytics

The dashboard calculates:

* Total cost basis
* Current portfolio value
* Unrealized gain or loss
* Category allocation
* Asset concentration
* Valuation staleness
* Per-asset risk indicators

The risk score is a transparent heuristic combining asset-class risk, valuation performance, valuation age, liquidity, and portfolio concentration. It is designed as an informational portfolio-monitoring tool rather than an investment recommendation.

## Technology

* **Backend:** Python, FastAPI, SQLModel
* **Database:** SQLite for local development and PostgreSQL for deployment
* **Frontend:** Jinja, HTMX, CSS, Chart.js
* **Authentication:** Secure password hashing and signed sessions
* **Testing:** Pytest
* **Deployment:** Vercel with Neon PostgreSQL

## Engineering highlights

* Server-side ownership checks isolate each user's portfolio data
* Valuation-history records preserve asset changes over time
* Archive and restore workflows retain historical data while excluding inactive assets from current analytics
* Business calculations are separated into independently testable functions
* Database initialization includes safe, repeatable schema migration handling
* Automated tests cover authentication, authorization, validation, portfolio calculations, history, archival workflows, and demo behavior

## Local development

```bash
python -m venv .venv
```

Activate the environment:

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

Tests cover authentication, data isolation, validation, valuation history, archive and restore behavior, portfolio calculations, database initialization, and safe chart rendering.
