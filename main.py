import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import (Depends, FastAPI, Form, HTTPException, Request, Response,
                     status)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer
# Import our models
from models import Asset, Category, User
from sqlmodel import Session, SQLModel, create_engine, select

# --- Configuration ---

sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

# In production, this MUST be an environment variable
SECRET_KEY = "REPLACE_THIS_WITH_A_REAL_SECRET_KEY_IN_PROD"
serializer = URLSafeTimedSerializer(SECRET_KEY)

templates = Jinja2Templates(directory="templates")

# --- Lifecycle & Database Helpers ---


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Authentication Helpers ---


def create_session_token(user_id: int) -> str:
    return serializer.dumps(str(user_id))


def verify_session_token(token: str) -> int | None:
    try:
        user_id_str = serializer.loads(token, max_age=3600)  # 1 hour expiry
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

# --- Routes: Public & Auth ---


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
async def login(
    request: Request,
    session: Session = Depends(get_session),
    email: str = Form(...),
    password: str = Form(...)
):
    statement = select(User).where(User.email == email)
    user = session.exec(statement).first()

    # Simple password check (Upgrade to hashing for prod!)
    if not user or user.hashed_password != password:
        return """<div class="error-message text-red-500 mt-2">❌ Invalid email or password</div>"""

    # TYPE FIX: Ensure user.id is not None before using it
    if user.id is None:
        return """<div class="error-message text-red-500 mt-2">❌ System Error: User has no ID</div>"""

    # Login successful - create session token
    session_token = create_session_token(user.id)

    response = HTMLResponse("""
        <div class="success-message text-green-500 mt-2">✅ Login successful! Redirecting...</div>
        <script>window.location.href = '/dashboard';</script>
    """)
    response.set_cookie(key="session", value=session_token,
                        httponly=True, samesite="lax")
    return response


@app.post("/register", response_class=HTMLResponse)
async def register(
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session)
):
    statement = select(User).where(User.email == email)
    if session.exec(statement).first():
        return "<div class='text-red-500'>Email already registered</div>"

    new_user = User(email=email, hashed_password=password)
    session.add(new_user)
    session.commit()
    return """<div class='text-green-500'>Account created! <a href='/login' class='underline'>Log in here</a></div>"""


@app.post("/logout", response_class=HTMLResponse)
async def logout():
    response = RedirectResponse(
        url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session")
    return response

# --- Routes: Dashboard & Portfolio Logic ---


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # Initial load renders the full page
    total_cost = sum(asset.purchase_price for asset in user.assets)
    total_value = sum(asset.current_market_value for asset in user.assets)
    unrealized_gain = total_value - total_cost

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "total_cost": total_cost,
        "total_value": total_value,
        "unrealized_gain": unrealized_gain
    })

# --- HTMX Fragments: Asset CRUD ---


@app.get("/fragments/assets/new", response_class=HTMLResponse)
async def get_add_asset_form(request: Request, session: Session = Depends(get_session)):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)

    return templates.TemplateResponse("fragments/add_asset_modal.html", {
        "request": request,
        "categories": user.categories
    })


@app.post("/fragments/assets", response_class=HTMLResponse)
async def create_asset(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    purchase_price: float = Form(...),
    purchase_date: str = Form(...),  # Date string from form
    category_id: Optional[int] = Form(None)
):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)

    # TYPE FIX: Ensure user.id is present
    if user.id is None:
        return Response(status_code=500)

    try:
        p_date = datetime.strptime(purchase_date, "%Y-%m-%d").date()
    except ValueError:
        p_date = date.today()  # Fallback

    new_asset = Asset(
        name=name,
        purchase_price=purchase_price,
        current_market_value=purchase_price,  # Default to purchase price
        purchase_date=p_date,
        category_id=category_id if category_id != 0 else None,  # Handle "No Category"
        owner_id=user.id
    )
    session.add(new_asset)
    session.commit()
    session.refresh(new_asset)

    # Return the UPDATED dashboard list + totals (OOB Swap)
    session.refresh(user)  # Refresh user to get new asset in relationship
    total_cost = sum(a.purchase_price for a in user.assets)
    total_value = sum(a.current_market_value for a in user.assets)
    unrealized_gain = total_value - total_cost

    return templates.TemplateResponse("fragments/dashboard_refresh.html", {
        "request": request,
        "user": user,
        "total_cost": total_cost,
        "total_value": total_value,
        "unrealized_gain": unrealized_gain
    })


@app.get("/fragments/assets/{asset_id}/edit", response_class=HTMLResponse)
async def get_edit_asset_row(
    asset_id: int,
    request: Request,
    session: Session = Depends(get_session)
):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)

    # TYPE FIX: Check user.id
    if not user or not asset or user.id is None or asset.owner_id != user.id:
        return Response(status_code=403)

    return templates.TemplateResponse("fragments/edit_asset_row.html", {
        "request": request,
        "asset": asset,
        "categories": user.categories
    })


@app.put("/fragments/assets/{asset_id}", response_class=HTMLResponse)
async def update_asset(
    asset_id: int,
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...),
    current_market_value: float = Form(...),
    category_id: Optional[int] = Form(None)
):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)

    # TYPE FIX: Check user.id
    if not user or not asset or user.id is None or asset.owner_id != user.id:
        return Response(status_code=403)

    asset.name = name
    asset.current_market_value = current_market_value
    asset.category_id = category_id if category_id != 0 else None
    asset.last_updated = datetime.utcnow()

    session.add(asset)
    session.commit()
    session.refresh(user)  # Refresh for totals

    # Recalculate totals for OOB swap
    total_cost = sum(a.purchase_price for a in user.assets)
    total_value = sum(a.current_market_value for a in user.assets)
    unrealized_gain = total_value - total_cost

    return templates.TemplateResponse("fragments/dashboard_refresh.html", {
        "request": request,
        "user": user,
        "total_cost": total_cost,
        "total_value": total_value,
        "unrealized_gain": unrealized_gain
    })


@app.delete("/fragments/assets/{asset_id}", response_class=HTMLResponse)
async def delete_asset(
    asset_id: int,
    request: Request,
    session: Session = Depends(get_session)
):
    user = get_current_user(request, session)
    asset = session.get(Asset, asset_id)

    # TYPE FIX: Check user.id
    if not user or not asset or user.id is None or asset.owner_id != user.id:
        return Response(status_code=403)

    session.delete(asset)
    session.commit()
    session.refresh(user)

    # Recalculate totals
    total_cost = sum(a.purchase_price for a in user.assets)
    total_value = sum(a.current_market_value for a in user.assets)
    unrealized_gain = total_value - total_cost

    return templates.TemplateResponse("fragments/dashboard_refresh.html", {
        "request": request,
        "user": user,
        "total_cost": total_cost,
        "total_value": total_value,
        "unrealized_gain": unrealized_gain
    })

# --- HTMX Fragments: Category CRUD ---


@app.post("/fragments/categories", response_class=HTMLResponse)
async def create_category(
    request: Request,
    session: Session = Depends(get_session),
    name: str = Form(...)
):
    user = get_current_user(request, session)
    if not user:
        return Response(status_code=401)

    # TYPE FIX: Ensure user.id is present
    if user.id is None:
        return Response(status_code=500)

    new_cat = Category(name=name, owner_id=user.id)
    session.add(new_cat)
    session.commit()
    session.refresh(user)

    # Return updated dropdown options
    return templates.TemplateResponse("fragments/category_options.html", {
        "request": request,
        "categories": user.categories
    })
