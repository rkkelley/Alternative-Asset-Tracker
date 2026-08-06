from __future__ import annotations

import html
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, BadTimeSignature, URLSafeTimedSerializer
from sqlmodel import Session, select

from models import Asset, Category, User, ValuationHistory
from portfolio import RISK_PROFILE_DEFAULTS, build_portfolio_summary
from database import (
    create_database_engine,
    initialize_database,
    resolve_database_url,
)
from security import (
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
    password_needs_rehash,
    require_csrf,
    verify_password,
)


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT == "production"
SECRET_KEY = os.environ.get("SECRET_KEY")
if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be configured when ENVIRONMENT=production.")
# A missing development key should invalidate sessions on restart rather than
# use a predictable signing key. Set SECRET_KEY for persistent local sessions.
SECRET_KEY = SECRET_KEY or secrets.token_urlsafe(32)
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", "3600"))
COOKIE_SECURE = IS_PRODUCTION or os.environ.get("COOKIE_SECURE", "").lower() == "true"
serializer = URLSafeTimedSerializer(SECRET_KEY)

database_url = resolve_database_url(BASE_DIR)
engine = create_database_engine(database_url)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

MAX_MONEY = 1_000_000_000_000
MAX_NAME_LENGTH = 120
MAX_NOTE_LENGTH = 500
DEMO_RETENTION = timedelta(hours=24)


def create_db_and_tables() -> None:
    initialize_database(engine)


def get_session():
    with Session(engine) as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# --- Security and response helpers ---


def create_session_token(user_id: int, session_version: int = 1) -> str:
    return serializer.dumps({"user_id": user_id, "version": session_version}, salt="session")


def verify_session_token(token: str) -> tuple[int, int] | None:
    try:
        payload = serializer.loads(token, max_age=SESSION_MAX_AGE, salt="session")
        if not isinstance(payload, dict):
            return None
        user_id = int(payload["user_id"])
        version = int(payload["version"])
        return user_id, version
    except (BadSignature, BadTimeSignature, KeyError, TypeError, ValueError):
        return None


def get_current_user(request: Request, session: Session) -> User | None:
    token = request.cookies.get("session")
    if not token:
        return None
    token_data = verify_session_token(token)
    if not token_data:
        return None
    user_id, session_version = token_data
    user = session.get(User, user_id)
    if not user or user.session_version != session_version:
        return None
    return user


def csrf_token_for(request: Request) -> str:
    return request.cookies.get(CSRF_COOKIE_NAME) or generate_csrf_token()


def set_csrf_cookie(response: Response, request: Request, token: str | None = None) -> Response:
    if not request.cookies.get(CSRF_COOKIE_NAME):
        response.set_cookie(
            CSRF_COOKIE_NAME,
            token or generate_csrf_token(),
            max_age=SESSION_MAX_AGE,
            httponly=False,
            secure=COOKIE_SECURE,
            samesite="lax",
            path="/",
        )
    return response


def set_session_cookie(response: Response, request: Request, token: str) -> Response:
    response.set_cookie(
        "session",
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return set_csrf_cookie(response, request)


def render_template(request: Request, template_name: str, context: dict[str, Any]) -> Response:
    token = csrf_token_for(request)
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"request": request, "csrf_token": token, **context},
    )
    return set_csrf_cookie(response, request, token)


def error_response(message: str, status_code: int = 422) -> HTMLResponse:
    safe_message = html.escape(message)
    return HTMLResponse(
        f'<div class="error-message text-red-600 mt-2">{safe_message}</div>',
        status_code=status_code,
    )


def dashboard_context(user: User, session: Session) -> dict[str, Any]:
    session.refresh(user)
    return {"user": user, **build_portfolio_summary(user.assets)}


def render_dashboard_fragment(request: Request, user: User, session: Session) -> Response:
    return render_template(
        request,
        "fragments/dashboard_refresh.html",
        dashboard_context(user, session),
    )


# --- Validation and ownership helpers ---


def normalized_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("Enter a valid email address.")
    return email


def validated_password(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(value) > 128:
        raise ValueError("Password must be 128 characters or fewer.")
    return value


def parse_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("Name is required.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Name must be {MAX_NAME_LENGTH} characters or fewer.")
    return name


def parse_money(value: str, field_name: str) -> float:
    try:
        amount = Decimal(value.strip())
    except (AttributeError, InvalidOperation):
        raise ValueError(f"{field_name} must be a valid number.") from None
    if not amount.is_finite() or amount < 0 or amount > MAX_MONEY:
        raise ValueError(f"{field_name} must be between $0 and ${MAX_MONEY:,.0f}.")
    return round(float(amount), 2)


def parse_purchase_date(value: str) -> date:
    try:
        purchase_date = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (AttributeError, ValueError):
        raise ValueError("Purchase date must use YYYY-MM-DD format.") from None
    if purchase_date < date(1900, 1, 1) or purchase_date > date.today():
        raise ValueError("Purchase date must be between 1900 and today.")
    return purchase_date


def parse_optional_id(value: Optional[str]) -> int | None:
    if value is None or not value.strip() or value.strip() == "0":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("Category selection is invalid.") from None
    if parsed <= 0:
        raise ValueError("Category selection is invalid.")
    return parsed


def parse_note(value: Optional[str], required: bool = False) -> str | None:
    note = (value or "").strip()
    if required and not note:
        raise ValueError("A reason is required for archiving an asset.")
    if len(note) > MAX_NOTE_LENGTH:
        raise ValueError(f"Notes must be {MAX_NOTE_LENGTH} characters or fewer.")
    return note or None


def owned_asset(session: Session, user: User, asset_id: int) -> Asset:
    asset = session.get(Asset, asset_id)
    if not asset or asset.owner_id != user.id:
        raise HTTPException(status_code=403, detail="That asset is not available to this account.")
    return asset


def owned_category(session: Session, user: User, category_id: int | None) -> Category | None:
    if category_id is None:
        return None
    category = session.get(Category, category_id)
    if not category or category.owner_id != user.id:
        raise HTTPException(status_code=403, detail="That category is not available to this account.")
    return category


# --- Public and authentication routes ---


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: Session = Depends(get_session)):
    if get_current_user(request, session):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return render_template(request, "index.html", {})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Session = Depends(get_session)):
    if get_current_user(request, session):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return render_template(request, "login.html", {})


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    session: Session = Depends(get_session),
    email: str = Form(...),
    password: str = Form(...),
    _csrf: Any = Depends(require_csrf),
):
    try:
        email = normalized_email(email)
    except ValueError:
        return error_response("Invalid email or password.", status_code=401)

    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not verify_password(password, user.hashed_password):
        return error_response("Invalid email or password.", status_code=401)

    if password_needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)
        session.add(user)
        session.commit()

    if user.id is None:
        return error_response("Unable to start the session.", status_code=500)

    token = create_session_token(user.id, user.session_version)
    response = HTMLResponse(
        '<div class="text-green-500 mt-2">Login successful! Redirecting...</div>'
        "<script>window.location.href = '/dashboard';</script>"
    )
    return set_session_cookie(response, request, token)


@app.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
    _csrf: Any = Depends(require_csrf),
):
    try:
        email = normalized_email(email)
        password = validated_password(password)
    except ValueError as exc:
        return error_response(str(exc))

    if session.exec(select(User).where(User.email == email)).first():
        return error_response("Email already registered.")

    new_user = User(email=email, hashed_password=hash_password(password))
    session.add(new_user)
    session.commit()
    session.refresh(new_user)

    if new_user.id is not None:
        for name, (score, days) in RISK_PROFILE_DEFAULTS.items():
            session.add(
                Category(
                    name=name,
                    base_risk_score=score,
                    liquidity_days=days,
                    owner_id=new_user.id,
                )
            )
        session.commit()

    return HTMLResponse(
        "<div class='text-green-500'>Account created! "
        "<a href='/login' class='underline'>Log in here</a></div>"
    )


@app.post("/logout", response_class=HTMLResponse)
async def logout(
    request: Request,
    session: Session = Depends(get_session),
    _csrf: Any = Depends(require_csrf),
):
    user = get_current_user(request, session)
    if user:
        user.session_version += 1
        session.add(user)
        session.commit()

    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session", path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return response


# --- Temporary demo accounts ---


def cleanup_expired_demo_users(session: Session, now: datetime | None = None) -> int:
    """Delete expired demo users and their dependent portfolio records."""

    cutoff = (now or datetime.utcnow()) - DEMO_RETENTION
    expired_users = session.exec(
        select(User).where(User.is_demo == True, User.created_at < cutoff)
    ).all()

    for demo_user in expired_users:
        if demo_user.id is None:
            continue
        assets = session.exec(select(Asset).where(Asset.owner_id == demo_user.id)).all()
        for asset in assets:
            histories = session.exec(
                select(ValuationHistory).where(ValuationHistory.asset_id == asset.id)
            ).all()
            for history in histories:
                session.delete(history)
            session.delete(asset)
        categories = session.exec(
            select(Category).where(Category.owner_id == demo_user.id)
        ).all()
        for category in categories:
            session.delete(category)
        session.delete(demo_user)

    if expired_users:
        session.commit()
    return len(expired_users)


@app.post("/demo", response_class=HTMLResponse)
async def try_demo(
    request: Request,
    session: Session = Depends(get_session),
    _csrf: Any = Depends(require_csrf),
):
    cleanup_expired_demo_users(session)
    demo_user = User(
        email=f"demo-{secrets.token_hex(16)}@alt-track.local",
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        is_demo=True,
    )
    session.add(demo_user)
    session.commit()
    session.refresh(demo_user)

    if demo_user.id is None:
        return error_response("Unable to prepare the demo account.", status_code=500)

    categories: dict[str, int] = {}
    for name, (score, days) in RISK_PROFILE_DEFAULTS.items():
        category = Category(
            name=name,
            base_risk_score=score,
            liquidity_days=days,
            owner_id=demo_user.id,
        )
        session.add(category)
        session.flush()
        categories[name] = category.id

    today = datetime.utcnow()
    a1 = Asset(
        name="Rolex Submariner",
        category_id=categories["Watches"],
        purchase_price=8500,
        current_market_value=14500,
        purchase_date=date(2019, 5, 10),
        last_updated=today,
        owner_id=demo_user.id,
    )
    a2 = Asset(
        name="Bored Ape NFT #8817",
        category_id=categories["NFTs"],
        purchase_price=120000,
        current_market_value=45000,
        purchase_date=date(2021, 11, 1),
        last_updated=today - timedelta(days=45),
        owner_id=demo_user.id,
    )
    a3 = Asset(
        name="Series B Startup Shares",
        category_id=categories["Startups"],
        purchase_price=50000,
        current_market_value=50000,
        purchase_date=date(2022, 1, 15),
        last_updated=today - timedelta(days=145),
        owner_id=demo_user.id,
    )
    a4 = Asset(
        name="Rental Property Fund",
        category_id=categories["Real Estate"],
        purchase_price=10000,
        current_market_value=13500,
        purchase_date=date(2023, 6, 1),
        last_updated=today,
        owner_id=demo_user.id,
    )
    a5 = Asset(
        name="Chateau Margaux 2015",
        category_id=categories["Wine"],
        purchase_price=500,
        current_market_value=800,
        purchase_date=date(2018, 2, 1),
        last_updated=today - timedelta(days=300),
        is_active=False,
        owner_id=demo_user.id,
    )
    a6 = Asset(
        name="Charizard 1st Edition (Raw)",
        category_id=categories["Trading Cards"],
        purchase_price=2000,
        current_market_value=0,
        purchase_date=date(2023, 1, 1),
        last_updated=today,
        is_active=False,
        owner_id=demo_user.id,
    )
    session.add_all([a1, a2, a3, a4, a5, a6])
    session.commit()

    histories = [
        ValuationHistory(asset_id=a1.id, old_value=0, new_value=8500, note="Initial Purchase"),
        ValuationHistory(asset_id=a1.id, old_value=8500, new_value=14500, note="Appraisal Update"),
        ValuationHistory(
            asset_id=a2.id,
            old_value=120000,
            new_value=45000,
            change_date=today - timedelta(days=45),
            note="Market Correction",
        ),
        ValuationHistory(asset_id=a4.id, old_value=10000, new_value=11000, change_date=today - timedelta(days=180), note="Q2 Valuation Update"),
        ValuationHistory(asset_id=a4.id, old_value=11000, new_value=12500, change_date=today - timedelta(days=90), note="Q3 Market Adjustment"),
        ValuationHistory(asset_id=a4.id, old_value=12500, new_value=13500, change_date=today, note="Year-End Appraisal"),
        ValuationHistory(asset_id=a5.id, old_value=0, new_value=500, change_date=today - timedelta(days=800), note="Initial Creation"),
        ValuationHistory(asset_id=a5.id, old_value=500, new_value=800, change_date=today - timedelta(days=100), note="Appraisal Update"),
        ValuationHistory(asset_id=a5.id, old_value=800, new_value=800, change_date=today - timedelta(days=10), note="Asset Archived: Sold at Auction"),
        ValuationHistory(asset_id=a6.id, old_value=0, new_value=2000, change_date=today - timedelta(days=200), note="Initial Creation"),
        ValuationHistory(asset_id=a6.id, old_value=2000, new_value=0, change_date=today, note="Asset Archived: Determined to be Counterfeit"),
    ]
    session.add_all(histories)
    session.commit()

    token = create_session_token(demo_user.id, demo_user.session_version)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return set_session_cookie(response, request, token)


# --- Dashboard and asset routes ---


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return render_template(request, "dashboard.html", dashboard_context(user, session))


@app.get("/fragments/assets/{asset_id}/history", response_class=HTMLResponse)
async def get_asset_history(asset_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    asset = owned_asset(session, user, asset_id)
    history = sorted(
        session.exec(select(ValuationHistory).where(ValuationHistory.asset_id == asset.id)).all(),
        key=lambda entry: entry.change_date,
        reverse=True,
    )
    return render_template(
        request,
        "fragments/asset_history_modal.html",
        {"asset": asset, "history": history},
    )


@app.get("/fragments/audit/deleted", response_class=HTMLResponse)
async def get_deleted_assets_modal(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    deleted_assets = [asset for asset in user.assets if not asset.is_active]
    return render_template(
        request,
        "fragments/deleted_assets_modal.html",
        {"deleted_assets": deleted_assets},
    )


@app.post("/fragments/assets/{asset_id}/restore", response_class=HTMLResponse)
async def restore_asset(
    asset_id: int,
    request: Request,
    session: Session = Depends(get_session),
    _csrf: Any = Depends(require_csrf),
):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    asset = owned_asset(session, user, asset_id)
    if asset.is_active:
        return render_template(
            request,
            "fragments/deleted_assets_modal.html",
            {"deleted_assets": [item for item in user.assets if not item.is_active]},
        )

    asset.is_active = True
    session.add(asset)
    session.add(
        ValuationHistory(
            asset_id=asset.id,
            old_value=asset.current_market_value,
            new_value=asset.current_market_value,
            note="Asset Restored from Archive",
        )
    )
    session.commit()
    return render_template(
        request,
        "fragments/deleted_assets_modal.html",
        {"deleted_assets": [item for item in user.assets if not item.is_active]},
    )


@app.get("/fragments/assets/new", response_class=HTMLResponse)
async def get_add_asset_form(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    return render_template(request, "fragments/add_asset_modal.html", {"categories": user.categories})


@app.post("/fragments/assets", response_class=HTMLResponse)
async def create_asset(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    purchase_price: str = Form(...),
    purchase_date: str = Form(...),
    category_id: Optional[str] = Form(None),
    current_market_value: Optional[str] = Form(None),
    _csrf: Any = Depends(require_csrf),
):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    try:
        clean_name = parse_name(name)
        clean_purchase_price = parse_money(purchase_price, "Purchase price")
        clean_date = parse_purchase_date(purchase_date)
        clean_category_id = parse_optional_id(category_id)
        clean_value = (
            clean_purchase_price
            if current_market_value is None or not current_market_value.strip()
            else parse_money(current_market_value, "Current market value")
        )
        category = owned_category(session, user, clean_category_id)
    except ValueError as exc:
        return error_response(str(exc))

    asset = Asset(
        name=clean_name,
        purchase_price=clean_purchase_price,
        current_market_value=clean_value,
        purchase_date=clean_date,
        category_id=category.id if category else None,
        owner_id=user.id,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    session.add(
        ValuationHistory(
            asset_id=asset.id,
            old_value=0,
            new_value=clean_value,
            note="Initial Asset Creation / Purchase",
        )
    )
    session.commit()
    return render_dashboard_fragment(request, user, session)


@app.get("/fragments/assets/{asset_id}/edit", response_class=HTMLResponse)
async def get_edit_asset_row(asset_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    asset = owned_asset(session, user, asset_id)
    return render_template(
        request,
        "fragments/edit_asset_row.html",
        {"asset": asset, "categories": user.categories},
    )


@app.put("/fragments/assets/{asset_id}", response_class=HTMLResponse)
async def update_asset(
    asset_id: int,
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    current_market_value: str = Form(...),
    category_id: Optional[str] = Form(None),
    audit_note: Optional[str] = Form(None),
    _csrf: Any = Depends(require_csrf),
):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    asset = owned_asset(session, user, asset_id)
    try:
        clean_name = parse_name(name)
        clean_value = parse_money(current_market_value, "Current market value")
        clean_category_id = parse_optional_id(category_id)
        clean_note = parse_note(audit_note)
        category = owned_category(session, user, clean_category_id)
    except ValueError as exc:
        return error_response(str(exc))

    if asset.id is None:
        return error_response("Unable to update that asset.", status_code=500)
    if asset.current_market_value != clean_value:
        session.add(
            ValuationHistory(
                asset_id=asset.id,
                old_value=asset.current_market_value,
                new_value=clean_value,
                note=clean_note or "Manual Update",
            )
        )

    asset.name = clean_name
    asset.current_market_value = clean_value
    asset.category_id = category.id if category else None
    asset.last_updated = datetime.utcnow()
    session.add(asset)
    session.commit()
    return render_dashboard_fragment(request, user, session)


@app.get("/fragments/assets/{asset_id}/delete", response_class=HTMLResponse)
async def get_delete_asset_row(asset_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    asset = owned_asset(session, user, asset_id)
    return render_template(request, "fragments/delete_asset_row.html", {"asset": asset})


@app.delete("/fragments/assets/{asset_id}", response_class=HTMLResponse)
async def delete_asset(
    asset_id: int,
    request: Request,
    session: Session = Depends(get_session),
    deletion_note: Optional[str] = Form(None),
    _csrf: Any = Depends(require_csrf),
):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    asset = owned_asset(session, user, asset_id)
    try:
        note = parse_note(deletion_note, required=True)
    except ValueError as exc:
        return error_response(str(exc))

    if asset.is_active:
        asset.is_active = False
        session.add(asset)
        session.add(
            ValuationHistory(
                asset_id=asset.id,
                old_value=asset.current_market_value,
                new_value=asset.current_market_value,
                note=f"Asset Archived: {note}",
            )
        )
        session.commit()
    return render_dashboard_fragment(request, user, session)


# --- Category routes ---


@app.get("/fragments/categories/manage", response_class=HTMLResponse)
async def get_manage_categories_modal(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    return render_template(request, "fragments/manage_categories_modal.html", {"categories": user.categories})


@app.get("/fragments/categories/new", response_class=HTMLResponse)
async def get_add_category_form(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    return render_template(request, "fragments/add_category_modal.html", {})


@app.post("/fragments/categories", response_class=HTMLResponse)
async def create_category(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    base_risk_score: str = Form(...),
    _csrf: Any = Depends(require_csrf),
):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    try:
        clean_name = parse_name(name)
        risk_score = int(base_risk_score)
        if not 1 <= risk_score <= 10:
            raise ValueError
    except (TypeError, ValueError):
        return error_response("Risk score must be a whole number from 1 to 10.")

    duplicate = session.exec(
        select(Category).where(
            Category.owner_id == user.id,
            Category.name == clean_name,
        )
    ).first()
    if duplicate:
        return error_response("That category already exists.")

    session.add(
        Category(
            name=clean_name,
            base_risk_score=risk_score,
            liquidity_days=30,
            owner_id=user.id,
        )
    )
    session.commit()
    return render_dashboard_fragment(request, user, session)


@app.delete("/fragments/categories/{category_id}", response_class=HTMLResponse)
async def delete_category(
    category_id: int,
    request: Request,
    session: Session = Depends(get_session),
    _csrf: Any = Depends(require_csrf),
):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    category = owned_category(session, user, category_id)
    if not category:
        return error_response("Category not found.", status_code=404)

    for asset in session.exec(
        select(Asset).where(
            Asset.category_id == category_id,
            Asset.owner_id == user.id,
        )
    ).all():
        asset.category_id = None
        session.add(asset)
    session.delete(category)
    session.commit()
    return render_dashboard_fragment(request, user, session)
