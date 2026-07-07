"""
Database setup and session management using SQLAlchemy.
SQLite is used as the default backend (zero-config, file-based).
"""
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# ── Engine ────────────────────────────────────────────────────────────────────
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # needed for SQLite + FastAPI
    echo=False,
)

# Enable WAL mode for better concurrent read performance
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

# ── Session factory ───────────────────────────────────────────────────────────
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── Declarative base ──────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass

# ── Dependency for FastAPI ────────────────────────────────────────────────────
def get_db():
    """Yield a database session; close it when the request is done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _ensure_columns():
    """
    SQLite's create_all() only creates NEW tables — it never alters existing
    ones. When we add columns to an already-deployed table (StrategyOutcome
    gaining source_url/source_platform/source_creator), we have to add them
    by hand or the Railway volume's existing DB file will 500 on first write.
    """
    from sqlalchemy import text
    additions = {
        "strategy_outcomes": [
            ("source_url", "VARCHAR(500)"),
            ("source_platform", "VARCHAR(20)"),
            ("source_creator", "VARCHAR(120)"),
        ],
    }
    with engine.connect() as conn:
        for table, cols in additions.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for col_name, col_type in cols:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    logger.info("Migrated: added %s.%s", table, col_name)
        conn.commit()

def init_db():
    """Create all tables if they don't already exist."""
    import models  # noqa: F401 – ensure models are registered with Base
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    logger.info("✅ Database tables created / verified")
