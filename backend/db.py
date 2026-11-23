from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Float, Integer, Boolean, BigInteger, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/tradex.db")
if DATABASE_URL.startswith("sqlite:///"):
    db_path = DATABASE_URL.removeprefix("sqlite:///")
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    starting_balance: Mapped[float] = mapped_column(Float, default=10000.0)
    balance: Mapped[float] = mapped_column(Float, default=10000.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    auto_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    active_strategy: Mapped[str] = mapped_column(String(64), default="STR-001")
    risk_pct: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=lambda: int(datetime.now(timezone.utc).timestamp()))

class Position(Base):
    __tablename__ = "paper_positions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    entry: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(16), default="manual")

class Trade(Base):
    __tablename__ = "paper_trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    entry: Mapped[float] = mapped_column(Float)
    exit: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(32))
    opened_at: Mapped[int] = mapped_column(BigInteger)
    closed_at: Mapped[int] = mapped_column(BigInteger)

class CustomStrategy(Base):
    __tablename__ = "custom_strategies"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    symbol: Mapped[str] = mapped_column(String(16))
    fast_ema: Mapped[int] = mapped_column(Integer)
    slow_ema: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[int] = mapped_column(BigInteger)

class Candle(Base):
    __tablename__ = "market_candles"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    time: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(32), default="unknown")

Index("ix_market_candles_symbol_time", Candle.symbol, Candle.time)
def init_db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.get(PaperAccount, 1) is None:
            db.add(PaperAccount(id=1))
            db.commit()
