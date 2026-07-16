"""Database configuration and connection setup."""

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from ..core.logging_config import logger
from .base import Base
from ..config import DATABASE_URL, SQL_ECHO

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=SQL_ECHO,
    future=True,
    pool_pre_ping=True,      # Automatically drops dead/stale connections
    pool_size=10,            # Maintain up to 10 persistent connections
    max_overflow=20,         # Allow bursting up to 20 additional temporary connections
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine, 
    expire_on_commit=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection with strict lifecycle rollback boundaries."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            # 💡 Guarantee database state integrity if service logic crashes downstream
            await session.rollback()
            raise
        finally:
            # Clean close ensures connection is safely returned to the pool immediately
            await session.close()


async def init_db() -> None:
    """Initialize database tables."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize database tables", exc_info=e)
        raise
