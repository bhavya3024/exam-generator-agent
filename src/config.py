"""Configuration settings for the exam generator agent."""
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # AI Model
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    model_name: str = Field(default="gpt-4o", env="MODEL_NAME")

    # PostgreSQL (LangGraph checkpointer)
    postgres_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/examgen",
        env="POSTGRES_URL",
    )

    # MongoDB
    mongodb_url: str = Field(
        default="mongodb://localhost:27017", env="MONGODB_URL"
    )
    mongodb_db: str = Field(default="examgen", env="MONGODB_DB")

    # Vercel Blob
    blob_read_write_token: str = Field(default="", env="BLOB_READ_WRITE_TOKEN")

    # Server
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "https://*.vercel.app"],
        env="CORS_ORIGINS",
    )

    # Neo4j GraphRAG
    neo4j_uri: str = Field(default="bolt://localhost:7687", env="NEO4J_URI")
    neo4j_username: str = Field(default="neo4j", env="NEO4J_USERNAME")
    neo4j_password: str = Field(default="password", env="NEO4J_PASSWORD")

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
