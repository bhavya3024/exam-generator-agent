"""PostgreSQL connection for LangGraph checkpointing."""
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver
from src.config import settings

_pool: ThreadedConnectionPool | None = None


def get_connection_pool() -> ThreadedConnectionPool:
    """Get or create a thread-safe PostgreSQL connection pool."""
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=settings.postgres_url,
        )
    return _pool


def get_checkpointer() -> PostgresSaver:
    """Create a LangGraph PostgresSaver checkpointer."""
    pool = get_connection_pool()
    conn = pool.getconn()
    checkpointer = PostgresSaver(conn)
    return checkpointer


def setup_postgres():
    """Initialize PostgreSQL schema for LangGraph checkpointing."""
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        checkpointer = PostgresSaver(conn)
        checkpointer.setup()
        print("✅ PostgreSQL checkpointer schema ready")
    finally:
        pool.putconn(conn)


def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
