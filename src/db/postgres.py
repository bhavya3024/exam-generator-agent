"""PostgreSQL connection for LangGraph checkpointing."""
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from src.config import settings

_pool: AsyncConnectionPool | None = None


def get_connection_pool() -> AsyncConnectionPool:
    """Get or create a thread-safe PostgreSQL connection pool."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=settings.postgres_url,
            min_size=1,
            max_size=10,
        )
    return _pool


def get_checkpointer() -> AsyncPostgresSaver:
    """Create a LangGraph PostgresSaver checkpointer."""
    pool = get_connection_pool()
    checkpointer = AsyncPostgresSaver(pool)
    return checkpointer


async def setup_postgres():
    """Initialize PostgreSQL schema for LangGraph checkpointing."""
    pool = get_connection_pool()
    async with pool.connection() as conn:
        await conn.set_autocommit(True)
        checkpointer = AsyncPostgresSaver(conn)
        await checkpointer.asetup()
        print("✅ PostgreSQL checkpointer schema ready")


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
