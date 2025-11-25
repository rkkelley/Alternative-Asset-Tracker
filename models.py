from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

# Database Models


class User(SQLModel, table=True):
    """
    User model for authentication and data ownership.
    This aligns with Deliverable 3: Data Model Diagram.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str

    # Relationship to Assets
    assets: list["Asset"] = Relationship(back_populates="owner")
    # Relationship to Categories
    categories: list["Category"] = Relationship(back_populates="owner")


class Category(SQLModel, table=True):
    """
    Category model for organizing assets (e.g., Sneakers, Watches).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    owner_id: int = Field(foreign_key="user.id")

    # Relationships
    owner: User = Relationship(back_populates="categories")
    assets: list["Asset"] = Relationship(back_populates="category")


class Asset(SQLModel, table=True):
    """
    Asset model for the individual items being tracked.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    purchase_price: float
    purchase_date: Optional[date] = None
    current_market_value: float

    # Audit Trail fields (Future proofing for Risk/Audit features)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Ownerships
    owner_id: int = Field(foreign_key="user.id")

    # Relationships
    owner: User = Relationship(back_populates="assets")
    category: Optional[Category] = Relationship(back_populates="assets")
