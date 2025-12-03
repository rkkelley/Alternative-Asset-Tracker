import random
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Dict, Optional

from fastapi import (Depends, FastAPI, Form, Header, HTTPException, Request,
                     Response, status)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer
from models import Asset, Category, User, ValuationHistory
from sqlmodel import Session, SQLModel, create_engine, select

# --- Configuration ---
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

SECRET_KEY = "REPLACE_THIS_WITH_A_REAL_SECRET_KEY_IN_PROD"
serializer = URLSafeTimedSerializer(SECRET_KEY)
templates = Jinja2Templates(directory="templates")

# --- RISK ENGINE CONFIGURATION ---
RISK_PROFILE = {
    "NFTs": 10, "Crypto": 9, "Startups": 8, "Sneakers": 7, "Trading Cards": 6,
    "Art": 5, "Wine": 4, "Watches": 3, "Real Estate": 2, "Cash Equivalents": 1
}

# --- Lifecycle ---


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Auth Helpers ---


def create_session_token(user_id: int) -> str:
    return serializer.dumps(str(user_id))


def verify_session_token(token: str) -> int | None:
    try:
        user_id_str = serializer.loads(token, max_age=3600)
        return int(user_id_str)
    except:
        return None


def get_current_user(request: Request, session: Session) -> User | None:
    session_token = request.cookies.get("session")
    if not session_token:
        return None
    user_id = verify_session_token(session_token)
    if not user_id:
        return None
    return session.get(User, user_id)

# --- Risk Calculation Helper ---


def calculate_asset_risk(asset: Asset, total_portfolio_value: float) -> Dict[str, Any]:
    # 1. Asset Class Risk (ACR)
    acr = asset.category.base_risk_score if asset.category else 5

    # 2. Valuation Staleness Risk (VSR)
    days_since = (datetime.utcnow() - asset.last_updated).days
    if days_since < 30:
        vsr = 0
    elif days_since < 90:
        vsr = 2
    elif days_since < 180:
        vsr = 5
    else:
        vsr = 8

    # 3. Concentration Risk (CR)
    if total_portfolio_value > 0:
        concentration = asset.current_market_value / total_portfolio_value
        cr = concentration * 10
    else:
        cr = 0

    # 4. Volatility/Loss Proxy (VP)
    vp = 0
    if asset.purchase_price > 0:
        return_pct = (asset.current_market_value -
                      asset.purchase_price) / asset.purchase_price
        if return_pct < -0.20:
            vp = 5

    # Adjusted Formula: Heavier weight on Asset Class (0.40) to allow High Risk scores
    raw_score = (0.40 * acr) + (0.30 * vsr) + (0.20 * cr) + (0.10 * vp)

    if raw_score < 3.5:
        label, color = "Low", "green"
    elif raw_score < 6.0:
        label, color = "Med", "yellow"
    else:
        label, color = "High", "red"

    return {
        "score": round(raw_score, 1),
        "label": label,
        "color": color,
        "factors": f"Class:{acr} Stale:{vsr} Conc:{cr:.1f}"
    }

# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Session = Depends(get_session)):
    if get_current_user(request, session):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, session: Session = Depends(get_session), email: str = Form(...), password: str = Form(...)):
    statement = select(User).where(User.email == email)
    user = session.exec(statement).first()
    if not user or user.hashed_password != password:
        return """<div class="error-message text-red-500 mt-2">❌ Invalid email or password</div>"""
    if user.id is None:
        return """<div class="text-red-500">System Error</div>"""

    session_token = create_session_token(user.id)
    response = HTMLResponse(
        """<div class="text-green-500 mt-2">✅ Login successful! Redirecting...</div><script>window.location.href = '/dashboard';</script>""")
    response.set_cookie(key="session", value=session_token,
                        httponly=True, samesite="lax")
    return response


@app.post("/register", response_class=HTMLResponse)
async def register(email: str = Form(...), password: str = Form(...), session: Session = Depends(get_session)):
    if session.exec(select(User).where(User.email == email)).first():
        return "<div class='text-red-500'>Email already registered</div>"

    new_user = User(email=email, hashed_password=password)
    session.add(new_user)
    session.commit()
    session.refresh(new_user)

    if new_user.id:
        defaults = {
            "NFTs": 10, "Crypto": 9, "Startups": 8, "Sneakers": 7, "Trading Cards": 6,
            "Art": 5, "Wine": 4, "Watches": 3, "Real Estate": 2, "Cash Equivalents": 1
        }
        for name, score in defaults.items():
            session.add(
                Category(name=name, base_risk_score=score, owner_id=new_user.id))
        session.commit()

    return """<div class='text-green-500'>Account created! <a href='/login' class='underline'>Log in here</a></div>"""


@app.post("/logout", response_class=HTMLResponse)
async def logout():
    response = RedirectResponse(
        url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session")
    return response

# --- Demo Logic (S-Tier Seeding) ---


@app.post("/demo", response_class=HTMLResponse)
async def try_demo(session: Session = Depends(get_session)):
    demo_email = "demo@alt-track.com"
    demo_user = session.exec(select(User).where(
        User.email == demo_email)).first()

    if not demo_user:
        demo_user = User(email=demo_email, hashed_password="demo_password_123")
        session.add(demo_user)
        session.commit()
        session.refresh(demo_user)

    if demo_user.id is None:
        return Response(status_code=500)

    # WIPE
    existing_assets = session.exec(select(Asset).where(
        Asset.owner_id == demo_user.id)).all()
    for asset in existing_assets:
        history = session.exec(select(ValuationHistory).where(
            ValuationHistory.asset_id == asset.id)).all()
        for h in history:
            session.delete(h)
        session.delete(asset)

    existing_cats = session.exec(select(Category).where(
        Category.owner_id == demo_user.id)).all()
    for c in existing_cats:
        session.delete(c)
    session.commit()

    # RE-SEED Categories
    cat_map = {}
    defaults = {
        "NFTs": 10, "Crypto": 9, "Startups": 8, "Sneakers": 7, "Trading Cards": 6,
        "Art": 5, "Wine": 4, "Watches": 3, "Real Estate": 2, "Cash Equivalents": 1
    }
    for name, score in defaults.items():
        c = Category(name=name, base_risk_score=score, owner_id=demo_user.id)
        session.add(c)
        session.commit()
        session.refresh(c)
        cat_map[name] = c.id

    today = datetime.utcnow()

    # 1. The Winner (Rolex) - Low Risk
    a1 = Asset(name="Rolex Submariner", category_id=cat_map["Watches"], purchase_price=8500, current_market_value=14500, purchase_date=date(
        2019, 5, 10), last_updated=today, owner_id=demo_user.id)
    session.add(a1)

    # 2. The Loser (Bored Ape) - High Risk (Crypto + Loss + Stale)
    a2 = Asset(name="Bored Ape NFT #8817", category_id=cat_map["Crypto"], purchase_price=120000, current_market_value=45000, purchase_date=date(
        2021, 11, 1), last_updated=today - timedelta(days=45), owner_id=demo_user.id)
    session.add(a2)
    session.commit()
    session.refresh(a2)
    if a2.id is not None:
        h_crypto = ValuationHistory(asset_id=a2.id, old_value=120000, new_value=45000,
                                    change_date=today-timedelta(days=45), note="Market Correction")
        session.add(h_crypto)

    # 3. The Risk Flag (Startup) - High Risk (Stale > 180 days)
    stale_date = today - timedelta(days=200)
    a3 = Asset(name="Series B Startup Shares", category_id=cat_map["Startups"], purchase_price=50000, current_market_value=50000, purchase_date=date(
        2022, 1, 15), last_updated=stale_date, owner_id=demo_user.id)
    session.add(a3)

    # 4. The Audit Star (Real Estate) - Low/Med Risk
    a4 = Asset(name="Rental Property Fund", category_id=cat_map["Real Estate"], purchase_price=10000, current_market_value=13500, purchase_date=date(
        2023, 6, 1), last_updated=today, owner_id=demo_user.id)
    session.add(a4)

    # --- ARCHIVED ASSETS (Soft Deleted) ---

    # 5. Archived: Sold Wine
    a5 = Asset(name="Chateau Margaux 2015", category_id=cat_map["Wine"], purchase_price=500, current_market_value=800, purchase_date=date(
        2018, 2, 1), last_updated=today-timedelta(days=300), is_active=False, owner_id=demo_user.id)
    session.add(a5)
    session.commit()
    session.refresh(a5)
    if a5.id:
        session.add(ValuationHistory(asset_id=a5.id, old_value=0, new_value=500,
                    note="Initial Creation", change_date=today-timedelta(days=800)))
        session.add(ValuationHistory(asset_id=a5.id, old_value=500, new_value=800,
                    note="Appraisal Update", change_date=today-timedelta(days=100)))
        session.add(ValuationHistory(asset_id=a5.id, old_value=800, new_value=800,
                    note="Asset Archived: Sold at Auction", change_date=today-timedelta(days=10)))

    # 6. Archived: Fake Card
    a6 = Asset(name="Charizard 1st Edition (Raw)", category_id=cat_map["Trading Cards"], purchase_price=2000, current_market_value=0, purchase_date=date(
        2023, 1, 1), last_updated=today, is_active=False, owner_id=demo_user.id)
    session.add(a6)
    session.commit()
    session.refresh(a6)
    if a6.id:
        session.add(ValuationHistory(asset_id=a6.id, old_value=0, new_value=2000,
                    note="Initial Creation", change_date=today-timedelta(days=200)))
        session.add(ValuationHistory(asset_id=a6.id, old_value=2000, new_value=0,
                    note="Asset Archived: Determined to be Counterfeit", change_date=today))

    # History for Asset 4 (Active)
    if a4.id is not None:
        session.add(ValuationHistory(asset_id=a4.id, old_value=10000, new_value=11000,
                    change_date=today-timedelta(days=180), note="Q2 Valuation Update"))
        session.add(ValuationHistory(asset_id=a4.id, old_value=11000, new_value=12500,
                    change_date=today-timedelta(days=90), note="Q3 Market Adjustment"))
        session.add(ValuationHistory(asset_id=a4.id, old_value=12500,
                    new_value=13500, change_date=today, note="Year-End Audit"))

    session.commit()

    session_token = create_session_token(demo_user.id)
    response = RedirectResponse(
        url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="session", value=session_token,
                        httponly=True, samesite="lax")
    return response

# --- Dashboard & CRUD ---


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    active_assets = [a for a in user.assets if a.is_active]

    total_cost = sum(asset.purchase_price for asset in active_assets)
    total_value = sum(asset.current_market_value for asset in active_assets)
    unrealized_gain = total_value - total_cost

    for asset in active_assets:
        if asset.__pydantic_extra__ is None:
            asset.__pydantic_extra__ = {}
        asset.__pydantic_extra__[
            "risk_data"] = calculate_asset_risk(asset, total_value)

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "assets": active_assets, "total_cost": total_cost,
        "total_value": total_value, "unrealized_gain": unrealized_gain,
        "now": datetime.utcnow()
    })


@app.get("/fragments/assets/{asset_id}/history", response_class=HTMLResponse)
async def get_asset_history(asset_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)
    if not user or not asset or asset.owner_id != user.id:
        return Response(status_code=403)
    history = sorted(asset.valuation_history,
                     key=lambda x: x.change_date, reverse=True)
    return templates.TemplateResponse("fragments/asset_history_modal.html", {"request": request, "asset": asset, "history": history})


@app.get("/fragments/audit/deleted", response_class=HTMLResponse)
async def get_deleted_assets_modal(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    deleted_assets = [a for a in user.assets if not a.is_active]
    return templates.TemplateResponse("fragments/deleted_assets_modal.html", {"request": request, "deleted_assets": deleted_assets})


@app.get("/fragments/assets/new", response_class=HTMLResponse)
async def get_add_asset_form(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    return templates.TemplateResponse("fragments/add_asset_modal.html", {"request": request, "categories": user.categories})


@app.post("/fragments/assets", response_class=HTMLResponse)
async def create_asset(request: Request, session: Session = Depends(get_session), name: str = Form(...), purchase_price: float = Form(...), purchase_date: str = Form(...), category_id: Optional[int] = Form(None)):
    user = get_current_user(request, session)
    if not user or user.id is None:
        return Response(status_code=401)
    try:
        p_date = datetime.strptime(purchase_date, "%Y-%m-%d").date()
    except:
        p_date = date.today()
    new_asset = Asset(name=name, purchase_price=purchase_price, current_market_value=purchase_price,
                      purchase_date=p_date, category_id=category_id if category_id != 0 else None, owner_id=user.id)
    session.add(new_asset)
    session.commit()
    session.refresh(new_asset)

    if new_asset.id:
        genesis_log = ValuationHistory(asset_id=new_asset.id, old_value=0, new_value=purchase_price,
                                       note="Initial Asset Creation / Purchase", change_date=datetime.utcnow())
        session.add(genesis_log)
        session.commit()

    session.refresh(user)

    active_assets = [a for a in user.assets if a.is_active]
    total_cost = sum(a.purchase_price for a in active_assets)
    total_value = sum(a.current_market_value for a in active_assets)
    unrealized_gain = total_value - total_cost
    for asset in active_assets:
        if asset.__pydantic_extra__ is None:
            asset.__pydantic_extra__ = {}
        asset.__pydantic_extra__[
            "risk_data"] = calculate_asset_risk(asset, total_value)

    return templates.TemplateResponse("fragments/dashboard_refresh.html", {"request": request, "user": user, "assets": active_assets, "total_cost": total_cost, "total_value": total_value, "unrealized_gain": unrealized_gain, "now": datetime.utcnow()})


@app.get("/fragments/assets/{asset_id}/edit", response_class=HTMLResponse)
async def get_edit_asset_row(asset_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)
    if not user or not asset or asset.owner_id != user.id:
        return Response(status_code=403)
    return templates.TemplateResponse("fragments/edit_asset_row.html", {"request": request, "asset": asset, "categories": user.categories})


@app.put("/fragments/assets/{asset_id}", response_class=HTMLResponse)
async def update_asset(asset_id: int, request: Request, session: Session = Depends(get_session), name: str = Form(...), current_market_value: float = Form(...), category_id: Optional[int] = Form(None), audit_note: Optional[str] = Form(None)):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)
    if not user or not asset or user.id is None or asset.owner_id != user.id:
        return Response(status_code=403)
    if asset.id is None:
        return Response(status_code=500)

    if asset.current_market_value != current_market_value:
        history = ValuationHistory(
            asset_id=asset.id, old_value=asset.current_market_value, new_value=current_market_value,
            note=audit_note or "Manual Update", change_date=datetime.utcnow()
        )
        session.add(history)

    asset.name = name
    asset.current_market_value = current_market_value
    asset.category_id = category_id if category_id != 0 else None
    asset.last_updated = datetime.utcnow()
    session.add(asset)
    session.commit()
    session.refresh(user)

    active_assets = [a for a in user.assets if a.is_active]
    total_cost = sum(a.purchase_price for a in active_assets)
    total_value = sum(a.current_market_value for a in active_assets)
    unrealized_gain = total_value - total_cost
    for asset in active_assets:
        if asset.__pydantic_extra__ is None:
            asset.__pydantic_extra__ = {}
        asset.__pydantic_extra__[
            "risk_data"] = calculate_asset_risk(asset, total_value)

    return templates.TemplateResponse("fragments/dashboard_refresh.html", {"request": request, "user": user, "assets": active_assets, "total_cost": total_cost, "total_value": total_value, "unrealized_gain": unrealized_gain, "now": datetime.utcnow()})


@app.get("/fragments/assets/{asset_id}/delete", response_class=HTMLResponse)
async def get_delete_asset_row(asset_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)
    if not user or not asset or user.id is None or asset.owner_id != user.id:
        return Response(status_code=403)
    return templates.TemplateResponse("fragments/delete_asset_row.html", {"request": request, "asset": asset})


@app.delete("/fragments/assets/{asset_id}", response_class=HTMLResponse)
async def delete_asset(asset_id: int, request: Request, session: Session = Depends(get_session), deletion_note: Optional[str] = Form(None)):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)
    if not user or not asset or user.id is None or asset.owner_id != user.id:
        return Response(status_code=403)
    if asset.id is None:
        return Response(status_code=500)

    asset.is_active = False
    session.add(asset)

    history = ValuationHistory(
        asset_id=asset.id, old_value=asset.current_market_value, new_value=asset.current_market_value,
        note=f"Asset Archived: {deletion_note or 'No reason provided'}", change_date=datetime.utcnow()
    )
    session.add(history)
    session.commit()
    session.refresh(user)

    active_assets = [a for a in user.assets if a.is_active]
    total_cost = sum(a.purchase_price for a in active_assets)
    total_value = sum(a.current_market_value for a in active_assets)
    unrealized_gain = total_value - total_cost
    for asset in active_assets:
        if asset.__pydantic_extra__ is None:
            asset.__pydantic_extra__ = {}
        asset.__pydantic_extra__[
            "risk_data"] = calculate_asset_risk(asset, total_value)

    return templates.TemplateResponse("fragments/dashboard_refresh.html", {"request": request, "user": user, "assets": active_assets, "total_cost": total_cost, "total_value": total_value, "unrealized_gain": unrealized_gain, "now": datetime.utcnow()})


@app.post("/fragments/assets/{asset_id}/restore", response_class=HTMLResponse)
async def restore_asset(asset_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)
    if not user or not asset or user.id is None or asset.owner_id != user.id:
        return Response(status_code=403)
    if asset.id is None:
        return Response(status_code=500)

    asset.is_active = True
    session.add(asset)

    history = ValuationHistory(
        asset_id=asset.id, old_value=asset.current_market_value, new_value=asset.current_market_value,
        note="Asset Restored from Archive", change_date=datetime.utcnow()
    )
    session.add(history)
    session.commit()

    deleted_assets = [a for a in user.assets if not a.is_active]
    return templates.TemplateResponse("fragments/deleted_assets_modal.html", {"request": request, "deleted_assets": deleted_assets})


@app.get("/fragments/categories/manage", response_class=HTMLResponse)
async def get_manage_categories_modal(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    return templates.TemplateResponse("fragments/manage_categories_modal.html", {"request": request, "categories": user.categories})


@app.get("/fragments/categories/new", response_class=HTMLResponse)
async def get_add_category_form(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)
    return templates.TemplateResponse("fragments/add_category_modal.html", {"request": request})


@app.post("/fragments/categories", response_class=HTMLResponse)
async def create_category(request: Request, session: Session = Depends(get_session), name: str = Form(...), base_risk_score: int = Form(...)):
    user = get_current_user(request, session)
    if not user or user.id is None:
        return Response(status_code=500)
    new_cat = Category(
        name=name, base_risk_score=base_risk_score, owner_id=user.id)
    session.add(new_cat)
    session.commit()
    session.refresh(user)

    active_assets = [a for a in user.assets if a.is_active]
    total_cost = sum(a.purchase_price for a in active_assets)
    total_value = sum(a.current_market_value for a in active_assets)
    unrealized_gain = total_value - total_cost
    for asset in active_assets:
        if asset.__pydantic_extra__ is None:
            asset.__pydantic_extra__ = {}
        asset.__pydantic_extra__[
            "risk_data"] = calculate_asset_risk(asset, total_value)

    return templates.TemplateResponse("fragments/dashboard_refresh.html", {"request": request, "user": user, "assets": active_assets, "total_cost": total_cost, "total_value": total_value, "unrealized_gain": unrealized_gain, "now": datetime.utcnow()})


@app.delete("/fragments/categories/{category_id}", response_class=HTMLResponse)
async def delete_category(category_id: int, request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user or user.id is None:
        return Response(status_code=403)
    category = session.get(Category, category_id)
    if not category or category.owner_id != user.id:
        return Response(status_code=403)
    assets_in_cat = session.exec(select(Asset).where(
        Asset.category_id == category_id)).all()
    for asset in assets_in_cat:
        asset.category_id = None
        session.add(asset)
    session.delete(category)
    session.commit()
    session.refresh(user)

    active_assets = [a for a in user.assets if a.is_active]
    total_cost = sum(a.purchase_price for a in active_assets)
    total_value = sum(a.current_market_value for a in active_assets)
    unrealized_gain = total_value - total_cost
    for asset in active_assets:
        if asset.__pydantic_extra__ is None:
            asset.__pydantic_extra__ = {}
        asset.__pydantic_extra__[
            "risk_data"] = calculate_asset_risk(asset, total_value)

    return templates.TemplateResponse("fragments/dashboard_refresh.html", {"request": request, "user": user, "assets": active_assets, "total_cost": total_cost, "total_value": total_value, "unrealized_gain": unrealized_gain, "now": datetime.utcnow()})
