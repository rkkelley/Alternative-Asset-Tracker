"""Pure portfolio and risk calculations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from models import Asset


RISK_PROFILE_DEFAULTS: dict[str, tuple[int, int]] = {
    "NFTs": (10, 30),
    "Crypto": (9, 1),
    "Startups": (8, 730),
    "Sneakers": (7, 60),
    "Trading Cards": (6, 45),
    "Art": (5, 365),
    "Wine": (4, 180),
    "Watches": (3, 30),
    "Real Estate": (2, 90),
    "Cash Equivalents": (1, 1),
}


def calculate_asset_risk(
    asset: Asset,
    total_portfolio_value: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate the app's transparent, heuristic risk indicator."""

    now = now or datetime.utcnow()
    category = asset.category
    asset_class_risk = category.base_risk_score if category else 5
    days_since = max(0, (now - asset.last_updated).days)

    if days_since < 30:
        staleness_risk = 0
    elif days_since < 90:
        staleness_risk = 2
    elif days_since < 180:
        staleness_risk = 5
    else:
        staleness_risk = 8

    liquidity_days = category.liquidity_days if category else 30
    liquidity_risk = min(liquidity_days / 180 * 10, 10.0)

    concentration_risk = (
        asset.current_market_value / total_portfolio_value * 10
        if total_portfolio_value > 0
        else 0
    )

    loss_risk = 0
    if asset.purchase_price > 0:
        return_pct = (asset.current_market_value - asset.purchase_price) / asset.purchase_price
        if return_pct < -0.20:
            loss_risk = 10

    raw_score = (
        0.40 * asset_class_risk
        + 0.20 * loss_risk
        + 0.20 * staleness_risk
        + 0.10 * liquidity_risk
        + 0.10 * concentration_risk
    )

    if raw_score < 4.0:
        label, color = "Low", "green"
    elif raw_score < 7.0:
        label, color = "Med", "yellow"
    else:
        label, color = "High", "red"

    return {
        "score": round(raw_score, 1),
        "label": label,
        "color": color,
        "factors": (
            f"Class:{asset_class_risk} Loss:{loss_risk} "
            f"Stale:{staleness_risk} Liq:{round(liquidity_risk, 1)}"
        ),
    }


def get_allocation_data(assets: Iterable[Asset]) -> dict[str, float]:
    """Return active portfolio value grouped by category."""

    allocation: dict[str, float] = {}
    for asset in assets:
        category_name = asset.category.name if asset.category else "Uncategorized"
        allocation[category_name] = allocation.get(category_name, 0.0) + asset.current_market_value
    return allocation


def build_portfolio_summary(
    assets: Iterable[Asset], now: datetime | None = None
) -> dict[str, Any]:
    """Build dashboard metrics from active assets only."""

    now = now or datetime.utcnow()
    active_assets = [asset for asset in assets if asset.is_active]
    total_cost = sum(asset.purchase_price for asset in active_assets)
    total_value = sum(asset.current_market_value for asset in active_assets)

    for asset in active_assets:
        # SQLModel/Pydantic v2 creates __pydantic_extra__ lazily for table
        # models, so initialize it before exposing calculated display data.
        extra = getattr(asset, "__pydantic_extra__", None)
        if extra is None:
            extra = {}
            object.__setattr__(asset, "__pydantic_extra__", extra)
        extra["risk_data"] = calculate_asset_risk(asset, total_value, now=now)

    allocation = get_allocation_data(active_assets)
    return {
        "assets": active_assets,
        "total_cost": total_cost,
        "total_value": total_value,
        "unrealized_gain": total_value - total_cost,
        "allocation_labels": list(allocation),
        "allocation_values": list(allocation.values()),
        "now": now,
    }
