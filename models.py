from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    assets: List["Asset"] = Relationship(back_populates="owner")
    categories: List["Category"] = Relationship(back_populates="owner")


class Category(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    base_risk_score: int = Field(default=5)
    # NEW: Average days to sell (used for Liquidity Risk Factor)
    liquidity_days: int = Field(default=30)
    owner_id: int = Field(foreign_key="user.id")

    owner: User = Relationship(back_populates="categories")
    assets: List["Asset"] = Relationship(back_populates="category")


class ValuationHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_id: int = Field(foreign_key="asset.id")
    old_value: float
    new_value: float
    change_date: datetime = Field(default_factory=datetime.utcnow)
    note: Optional[str] = None

    asset: "Asset" = Relationship(back_populates="valuation_history")


class Asset(SQLModel, table=True):
    # Allow extra fields like risk_data at runtime
    class Config:
        extra = "allow"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    purchase_price: float
    purchase_date: date
    current_market_value: float
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Soft Delete Field
    is_active: bool = Field(default=True)

    owner_id: int = Field(foreign_key="user.id")

    owner: User = Relationship(back_populates="assets")
    category: Optional[Category] = Relationship(back_populates="assets")
    valuation_history: List["ValuationHistory"] = Relationship(
        back_populates="asset")
