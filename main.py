"""Entry point for the exam generator agent server."""
import uvicorn
from src.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "src.api.server:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level="info",
    )
