import secrets
from contextlib import asynccontextmanager
from typing import Annotated

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

# Database Setup (SQLite for development)
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)

# Security Setup
# In production, this should be an environment variable!
SECRET_KEY = secrets.token_hex(32)
serializer = URLSafeTimedSerializer(SECRET_KEY)

# Templates Setup
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

# Mount static files (CSS, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Authentication Logic (Adapted from your class notes) ---


def create_session_token(user_id: int) -> str:
    """Create a secure session token for a user ID"""
    # We sign the User ID (int) converted to string
    return serializer.dumps(str(user_id))


def verify_session_token(token: str) -> int | None:
    """Verify a session token and return the user_id"""
    try:
        # Token expires after 1 hour (3600 seconds)
        user_id_str = serializer.loads(token, max_age=3600)
        return int(user_id_str)
    except:
        return None


def get_current_user(request: Request, session: Session) -> User | None:
    """
    Get the currently logged-in user from the session cookie.
    This function now queries the SQL database instead of a dictionary.
    """
    session_token = request.cookies.get("session")
    if not session_token:
        return None

    user_id = verify_session_token(session_token)
    if not user_id:
        return None

    # Fetch the real user from the database
    user = session.get(User, user_id)
    return user

# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: Session = Depends(get_session)):
    """Home page - redirects based on login status"""
    user = get_current_user(request, session)

    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    else:
        # Show a landing page with "Login" or "Try Demo" buttons
        return templates.TemplateResponse("index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session: Session = Depends(get_session)):
    """Show the login page"""
    user = get_current_user(request, session)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    email: str = Form(...),
    password: str = Form(...)
):
    """Handle login form submission"""

    # Query the database for the user
    statement = select(User).where(User.email == email)
    results = session.exec(statement)
    user = results.first()

    # Verify password (simplistic for MVP - use hashing in production!)
    if not user or user.hashed_password != password:
        return """
        <div class="error-message" style="color: red;">
            ❌ Invalid email or password
        </div>
        """

    # Login successful - create session token
    session_token = create_session_token(user.id)

    # Return success message with redirect instruction
    html_response = HTMLResponse("""
        <div class="success-message" style="color: green;">
            ✅ Login successful! Redirecting...
        </div>
        <script>
            setTimeout(() => window.location.href = '/dashboard', 1000);
        </script>
    """)

    # Set the session cookie on the response object
    html_response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        secure=False,  # Set to True in production
        samesite="lax"
    )

    return html_response


@app.post("/logout", response_class=HTMLResponse)
async def logout():
    """Handle logout"""
    response = RedirectResponse(
        url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("session")
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    """Protected dashboard - requires login"""
    user = get_current_user(request, session)

    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    # Calculate Portfolio Metrics (The Finance Logic)
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

# --- Registration Endpoint (To create users) ---


@app.post("/register", response_class=HTMLResponse)
async def register(
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session)
):
    # Check if user already exists
    statement = select(User).where(User.email == email)
    existing_user = session.exec(statement).first()

    if existing_user:
        return "<div class='error'>Email already registered</div>"

    # Create new user
    # Note: For MVP we are storing plain password. UPGRADE THIS LATER.
    new_user = User(email=email, hashed_password=password)
    session.add(new_user)
    session.commit()
    session.refresh(new_user)

    return """
    <div class='success'>
        Account created! <a href='/login'>Log in here</a>
    </div>
    """
