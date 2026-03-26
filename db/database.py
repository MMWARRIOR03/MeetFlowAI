"""
Database connection and session management.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

# Get database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://meetflow:meetflow@localhost:5432/meetflow")

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,
    echo=False,
)

# Create session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """Dependency for getting database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


def get_db_session():
    """Context manager for getting database session."""
    return AsyncSessionLocal()
