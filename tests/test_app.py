from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlmodel import Session, select

from models import Asset, Category, User, ValuationHistory
from portfolio import build_portfolio_summary, calculate_asset_risk, get_allocation_data


def csrf(client) -> str:
    if "csrf_token" not in client.cookies:
        client.get("/login")
    return client.cookies["csrf_token"]


def csrf_request(client, method: str, url: str, data: dict | None = None):
    if method.upper() == "GET":
        return client.get(url)
    token = csrf(client)
    payload = dict(data or {})
    payload.setdefault("csrf_token", token)
    return client.request(
        method,
        url,
        data=payload,
        headers={"X-CSRF-Token": token},
    )


def register(client, email: str | None = None, password: str = "correct-horse-1") -> str:
    email = email or f"{uuid4().hex}@example.com"
    response = csrf_request(
        client,
        "POST",
        "/register",
        {"email": email, "password": password},
    )
    assert response.status_code == 200
    return email


def login(client, email: str, password: str = "correct-horse-1"):
    return csrf_request(
        client,
        "POST",
        "/login",
        {"email": email, "password": password},
    )


def logout(client):
    return csrf_request(client, "POST", "/logout")


def user_record(app, email: str) -> User:
    with Session(app_module_engine()) as session:
        return session.exec(select(User).where(User.email == email)).one()


def app_module_engine():
    import main

    return main.engine


def create_asset(client, name: str = "Rolex", value: str = "120"):
    return csrf_request(
        client,
        "POST",
        "/fragments/assets",
        {
            "name": name,
            "purchase_price": "100",
            "purchase_date": "2024-01-01",
            "current_market_value": value,
            "category_id": "0",
        },
    )


def asset_record(asset_id: int) -> Asset:
    with Session(app_module_engine()) as session:
        return session.get(Asset, asset_id)


def history_count(asset_id: int) -> int:
    with Session(app_module_engine()) as session:
        return len(session.exec(select(ValuationHistory).where(ValuationHistory.asset_id == asset_id)).all())


def test_registration_hashes_password_and_login_works(client, app):
    email = register(client)
    user = user_record(app, email)

    assert user.hashed_password.startswith("$argon2")
    assert user.hashed_password != "correct-horse-1"
    assert login(client, email).status_code == 200
    assert login(client, email, "wrong-password").status_code == 401


def test_session_cookie_has_expected_flags(client):
    email = register(client)
    response = login(client, email)
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_csrf_rejects_missing_token_and_accepts_valid_submission(client):
    client.get("/login")
    response = client.post(
        "/register",
        data={"email": "missing-token@example.com", "password": "correct-horse-1"},
    )
    assert response.status_code == 403

    assert register(client, "valid-token@example.com") == "valid-token@example.com"


def test_unauthenticated_dashboard_redirects_and_logout_invalidates_session(client):
    response = client.get("/dashboard")
    assert response.url.path == "/login"

    email = register(client)
    assert login(client, email).status_code == 200
    old_token = client.cookies["session"]
    assert client.get("/dashboard").url.path == "/dashboard"

    logout(client)
    client.cookies.set("session", old_token)
    assert client.get("/dashboard").url.path == "/login"


def test_cross_user_asset_operations_and_history_are_denied(client, app):
    first_email = register(client)
    login(client, first_email)
    assert create_asset(client).status_code == 200
    first_user = user_record(app, first_email)
    with Session(app_module_engine()) as session:
        asset_id = session.exec(select(Asset).where(Asset.owner_id == first_user.id)).one().id
    logout(client)

    second_email = register(client)
    login(client, second_email)
    for method, url, data in [
        ("GET", f"/fragments/assets/{asset_id}/history", None),
        ("GET", f"/fragments/assets/{asset_id}/edit", None),
        ("GET", f"/fragments/assets/{asset_id}/delete", None),
        ("POST", f"/fragments/assets/{asset_id}/restore", None),
        ("PUT", f"/fragments/assets/{asset_id}", {"name": "Nope", "current_market_value": "1", "category_id": "0"}),
        ("DELETE", f"/fragments/assets/{asset_id}", {"deletion_note": "Nope"}),
    ]:
        response = csrf_request(client, method, url, data)
        assert response.status_code == 403


def test_cross_user_category_assignment_is_denied(client, app):
    first_email = register(client)
    first_user = user_record(app, first_email)
    with Session(app_module_engine()) as session:
        category_id = session.exec(select(Category).where(Category.owner_id == first_user.id)).first().id
    logout(client)

    second_email = register(client)
    login(client, second_email)
    response = csrf_request(
        client,
        "POST",
        "/fragments/assets",
        {
            "name": "Foreign Category Asset",
            "purchase_price": "10",
            "purchase_date": "2024-01-01",
            "current_market_value": "10",
            "category_id": str(category_id),
        },
    )
    assert response.status_code == 403


def test_archive_restore_are_owner_scoped_and_idempotent(client, app):
    email = register(client)
    login(client, email)
    create_asset(client)
    user = user_record(app, email)
    with Session(app_module_engine()) as session:
        asset_id = session.exec(select(Asset).where(Asset.owner_id == user.id)).one().id

    assert csrf_request(
        client, "DELETE", f"/fragments/assets/{asset_id}", {"deletion_note": "Sold"}
    ).status_code == 200
    assert asset_record(asset_id).is_active is False
    assert history_count(asset_id) == 2

    # A repeated archive request is a safe no-op.
    csrf_request(client, "DELETE", f"/fragments/assets/{asset_id}", {"deletion_note": "Sold again"})
    assert history_count(asset_id) == 2

    assert csrf_request(client, "POST", f"/fragments/assets/{asset_id}/restore").status_code == 200
    assert asset_record(asset_id).is_active is True
    assert history_count(asset_id) == 3

    # A repeated restore request is also a safe no-op.
    csrf_request(client, "POST", f"/fragments/assets/{asset_id}/restore")
    assert history_count(asset_id) == 3


def test_validation_rejects_bad_money_dates_and_names(client, app):
    email = register(client)
    login(client, email)
    for data in [
        {"name": "Bad", "purchase_price": "-1", "purchase_date": "2024-01-01", "category_id": "0"},
        {"name": "Bad", "purchase_price": "1", "purchase_date": "not-a-date", "category_id": "0"},
        {"name": " ", "purchase_price": "1", "purchase_date": "2024-01-01", "category_id": "0"},
        {"name": "Bad", "purchase_price": "NaN", "purchase_date": "2024-01-01", "category_id": "0"},
    ]:
        assert csrf_request(client, "POST", "/fragments/assets", data).status_code == 422

    user = user_record(app, email)
    with Session(app_module_engine()) as session:
        assert session.exec(select(Asset).where(Asset.owner_id == user.id)).all() == []


def test_valuation_history_is_created_only_for_real_changes(client, app):
    email = register(client)
    login(client, email)
    create_asset(client, value="120")
    user = user_record(app, email)
    with Session(app_module_engine()) as session:
        asset_id = session.exec(select(Asset).where(Asset.owner_id == user.id)).one().id
    assert history_count(asset_id) == 1

    update = {"name": "Updated", "current_market_value": "130", "category_id": "0", "audit_note": "Appraisal"}
    assert csrf_request(client, "PUT", f"/fragments/assets/{asset_id}", update).status_code == 200
    assert history_count(asset_id) == 2
    update["current_market_value"] = "130"
    csrf_request(client, "PUT", f"/fragments/assets/{asset_id}", update)
    assert history_count(asset_id) == 2


def test_demo_entry_resets_shared_demo_data(client, app):
    response = csrf_request(client, "POST", "/demo")
    assert response.status_code == 200
    with Session(app_module_engine()) as session:
        demo = session.exec(select(User).where(User.email == "demo@alt-track.com")).one()
        assert len(session.exec(select(Asset).where(Asset.owner_id == demo.id)).all()) == 6

    create_asset(client, name="Temporary Demo Asset")
    csrf_request(client, "POST", "/demo")
    with Session(app_module_engine()) as session:
        demo = session.exec(select(User).where(User.email == "demo@alt-track.com")).one()
        assets = session.exec(select(Asset).where(Asset.owner_id == demo.id)).all()
        assert len(assets) == 6
        assert all(asset.name != "Temporary Demo Asset" for asset in assets)


def test_portfolio_totals_allocation_staleness_and_concentration():
    now = datetime(2026, 1, 1)
    watches = Category(name="Watches", base_risk_score=3, liquidity_days=30, owner_id=1)
    art = Category(name="Art", base_risk_score=5, liquidity_days=365, owner_id=1)
    fresh = Asset(name="Watch", purchase_price=100, current_market_value=150, purchase_date=date(2020, 1, 1), last_updated=now - timedelta(days=10), is_active=True, owner_id=1, category=watches)
    stale = Asset(name="Painting", purchase_price=100, current_market_value=50, purchase_date=date(2020, 1, 1), last_updated=now - timedelta(days=100), is_active=True, owner_id=1, category=art)
    archived = Asset(name="Archived", purchase_price=1000, current_market_value=1000, purchase_date=date(2020, 1, 1), last_updated=now, is_active=False, owner_id=1, category=watches)

    summary = build_portfolio_summary([fresh, stale, archived], now=now)
    assert summary["total_cost"] == 200
    assert summary["total_value"] == 200
    assert summary["unrealized_gain"] == 0
    assert summary["allocation_labels"] == ["Watches", "Art"]
    assert get_allocation_data([fresh, stale]) == {"Watches": 150, "Art": 50}
    assert "Stale:5" in stale.risk_data["factors"]

    concentrated = calculate_asset_risk(fresh, total_portfolio_value=150, now=now)
    diversified = calculate_asset_risk(fresh, total_portfolio_value=1500, now=now)
    assert concentrated["score"] > diversified["score"]
