from datetime import date, datetime
from typing import List, Optional

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
    owner_id: int = Field(foreign_key="user.id")
    owner: User = Relationship(back_populates="categories")
    assets: List["Asset"] = Relationship(back_populates="category")


class ValuationHistory(SQLModel, table=True):
    """
    Immutable Audit Trail for Asset Valuations.
    Stores a log of every price change.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    asset_id: int = Field(foreign_key="asset.id")
    old_value: float
    new_value: float
    change_date: datetime = Field(default_factory=datetime.utcnow)
    note: Optional[str] = None  # "Why did you change the price?"

    asset: "Asset" = Relationship(back_populates="valuation_history")


class Asset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    purchase_price: float
    purchase_date: date
    current_market_value: float

    # Critical for Risk Management (Stale Price Logic)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    owner_id: int = Field(foreign_key="user.id")

    owner: User = Relationship(back_populates="assets")
    category: Optional[Category] = Relationship(back_populates="assets")
    valuation_history: List["ValuationHistory"] = Relationship(
        back_populates="asset")
