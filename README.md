# Exam Generator Agent

AI-powered exam question generator using **LangGraph** + **Google Gemini 1.5 Pro**.

## Architecture

```
FastAPI Server → LangGraph Graph → Gemini LLM
                     ↓
              RAG Pipeline (Chroma)
                     ↓
              MongoDB (paper storage)
              PostgreSQL (LangGraph checkpointing)
```

## LangGraph Nodes

| Node | Description |
|------|-------------|
| `ingest_documents` | Downloads PDFs/TXT from Vercel Blob, chunks them |
| `retrieve_context` | Semantic search over chunks using embeddings |
| `generate_questions` | LLM generates all question types |
| `validate_questions` | Self-critique quality check |
| `format_paper` | Assembles structured exam paper |

## Setup

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- PostgreSQL 14+
- MongoDB 6+

### 1. Install uv
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install dependencies
```bash
uv sync
```

### 3. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Run with Docker Compose (easiest)
```bash
docker-compose up
```

### 5. Or run locally
```bash
# Start Postgres and MongoDB first, then:
uv run python main.py
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/generate` | Start exam generation |
| `GET` | `/stream/{run_id}` | SSE stream of progress |
| `GET` | `/paper/{run_id}` | Get generated paper |
| `GET` | `/papers` | List history |
| `POST` | `/upload-metadata` | Save upload metadata |
| `GET` | `/health` | Health check |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_API_KEY` | Google AI Studio API key |
| `POSTGRES_URL` | PostgreSQL connection string |
| `MONGODB_URL` | MongoDB connection string |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob token |
