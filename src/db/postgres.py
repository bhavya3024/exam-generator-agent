"""PostgreSQL connection for LangGraph checkpointing."""
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
from src.config import settings

_pool: ConnectionPool | None = None


def get_connection_pool() -> ConnectionPool:
    """Get or create a thread-safe PostgreSQL connection pool."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.postgres_url,
            min_size=1,
            max_size=10,
        )
    return _pool


def get_checkpointer() -> PostgresSaver:
    """Create a LangGraph PostgresSaver checkpointer."""
    pool = get_connection_pool()
    checkpointer = PostgresSaver(pool)
    return checkpointer


def setup_postgres():
    """Initialize PostgreSQL schema for LangGraph checkpointing."""
    pool = get_connection_pool()
    with pool.connection() as conn:
        checkpointer = PostgresSaver(conn)
        checkpointer.setup()
        print("✅ PostgreSQL checkpointer schema ready")


def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None
