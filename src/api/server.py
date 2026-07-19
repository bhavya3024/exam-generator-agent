"""
FastAPI server for the LangGraph exam generator agent.
Endpoints:
  POST /generate          — Start exam generation
  GET  /stream/{run_id}   — SSE stream of agent progress
  GET  /paper/{run_id}    — Fetch completed paper
  GET  /papers            — List history
  POST /upload-context    — Confirm a Vercel Blob upload (metadata save)
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import get_graph
from src.agent.state import AgentState, ExamConfig
from src.db.mongo import (
    create_paper_record,
    save_paper,
    update_paper_status,
    get_paper,
    list_papers,
    save_upload_metadata,
)
from src.config import settings

app = FastAPI(
    title="Exam Question Generator Agent — CBSE Pattern",
    description="AI-powered exam question generator using LangGraph + Gemini for CBSE board standards",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Public hackathon project
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from src.api.library import router as library_router
app.include_router(library_router, prefix="/library", tags=["library"])

# In-memory store for active run streams
_active_runs: dict[str, list[dict]] = {}


# ──────────────────────────────────────────────
# Request / Response Models
# ──────────────────────────────────────────────

class GenerateRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=100)
    topic: str = Field(default="", max_length=200)
    cbse_class: str = Field(default="10", min_length=1, max_length=100)
    total_marks: int = Field(default=80, ge=10, le=100)
    duration_minutes: int = Field(default=180, ge=30, le=240)
    
    # CBSE Blueprints
    mcq_count: int = Field(default=10, ge=0, le=50)
    assertion_reason_count: int = Field(default=4, ge=0, le=20)
    very_short_answer_count: int = Field(default=5, ge=0, le=20)
    short_answer_count: int = Field(default=6, ge=0, le=20) # SA-I (2 marks)
    short_answer_ii_count: int = Field(default=7, ge=0, le=20) # SA-II (3 marks)
    long_answer_count: int = Field(default=3, ge=0, le=10) # LA (5 marks)
    case_based_count: int = Field(default=3, ge=0, le=10) # Case/Passage based (4 marks)
    
    easy_percent: int = Field(default=30, ge=0, le=100)
    medium_percent: int = Field(default=50, ge=0, le=100)
    hard_percent: int = Field(default=20, ge=0, le=100)
    document_urls: list[str] = Field(default=[])
    special_instructions: str = Field(default="")


class UploadMetadataRequest(BaseModel):
    blob_url: str
    filename: str
    file_type: str
    size_bytes: int


# ──────────────────────────────────────────────
# Background Task: Run the LangGraph agent
# ──────────────────────────────────────────────

async def run_agent(run_id: str, exam_config: dict):
    """Run the LangGraph agent in the background and emit SSE events."""
    events = _active_runs.setdefault(run_id, [])

    def emit(event_type: str, data: dict):
        events.append({"type": event_type, "data": data, "ts": datetime.now(timezone.utc).isoformat()})

    try:
        emit("status", {"status": "ingesting", "progress": 10, "message": "📂 Loading uploaded documents..."})

        initial_state: AgentState = {
            "run_id": run_id,
            "exam_config": exam_config,
            "messages": [],
            "status": "ingesting",
            "progress": 10,
            "document_chunks": [],
            "retrieved_context": "",
            "draft_questions": [],
            "validated_questions": [],
            "validation_feedback": "",
            "exam_paper": None,
            "error_message": None,
        }

        graph = get_graph()
        config = {"configurable": {"thread_id": run_id}}

        # Stream node-by-node updates
        async for chunk in graph.astream(initial_state, config=config):
            node_name = list(chunk.keys())[0]
            node_state = chunk[node_name]

            status = node_state.get("status", "processing")
            progress = node_state.get("progress", 0)

            node_messages = {
                "ingest_documents": "📂 Ingesting and chunking documents...",
                "retrieve_context": "🔍 Retrieving relevant NCERT context...",
                "generate_questions": "🧠 Generating CBSE questions with AI...",
                "validate_questions": "✅ Vetting CBSE criteria compliance...",
                "format_paper": "📝 Formatting standard CBSE sections...",
            }
            message = node_messages.get(node_name, f"Processing {node_name}...")

            emit("status", {"status": status, "progress": progress, "message": message, "node": node_name})

            # Check if done
            if node_name == "format_paper" and node_state.get("exam_paper"):
                paper = node_state["exam_paper"]
                save_paper(run_id, paper, exam_config)
                emit("complete", {"run_id": run_id, "paper": paper})
                return

        # If stream ended without paper
        emit("error", {"message": "Agent completed but no paper was generated"})
        update_paper_status(run_id, "error", "No paper generated")

    except Exception as e:
        error_msg = str(e)
        emit("error", {"message": error_msg})
        update_paper_status(run_id, "error", error_msg)
        raise


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "exam-generator-agent"}


@app.post("/generate")
async def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    """Start exam paper generation. Returns a run_id to track progress."""
    # Validate difficulty percentages
    total_pct = req.easy_percent + req.medium_percent + req.hard_percent
    if total_pct != 100:
        raise HTTPException(
            status_code=400,
            detail=f"Difficulty percentages must sum to 100 (got {total_pct})"
        )

    # Automatically calculate blueprint (question counts) based on Target Total Marks
    target = req.total_marks
    
    # CBSE standard section weights (proportion of total marks)
    sectionAMarks = round(target * 0.25)      # 1-mark questions (MCQs & AR)
    sectionBMarks = round(target * 0.15)      # 2-mark questions (VSA & SA-I)
    sectionCMarks = round(target * 0.26)      # 3-mark questions (SA-II)
    sectionDMarks = round(target * 0.19)      # 5-mark questions (LA)
    sectionEMarks = target - sectionAMarks - sectionBMarks - sectionCMarks - sectionDMarks # 4-mark questions (Case-based)
    
    # Section A: split into MCQs (80%) and Assertion-Reason (20%)
    mcq = round(sectionAMarks * 0.8)
    ar = sectionAMarks - mcq
    
    # Section B: 2-mark questions
    vsa = sectionBMarks // 2
    
    # Section C: 3-mark questions
    saII = sectionCMarks // 3
    
    # Section D: 5-mark questions
    la = sectionDMarks // 5
    
    # Section E: 4-mark questions
    cb = sectionEMarks // 4

    currentTotal = mcq * 1 + ar * 1 + vsa * 2 + saII * 3 + la * 5 + cb * 4
    iterations = 0
    while currentTotal != target and iterations < 100:
        iterations += 1
        diff = target - currentTotal
        if diff > 0:
            if diff >= 5:
                la += 1
                currentTotal += 5
            elif diff >= 4:
                cb += 1
                currentTotal += 4
            elif diff >= 3:
                saII += 1
                currentTotal += 3
            elif diff >= 2:
                vsa += 1
                currentTotal += 2
            else:
                mcq += 1
                currentTotal += 1
        else:
            if diff <= -5 and la > 0:
                la -= 1
                currentTotal -= 5
            elif diff <= -4 and cb > 0:
                cb -= 1
                currentTotal -= 4
            elif diff <= -3 and saII > 0:
                saII -= 1
                currentTotal -= 3
            elif diff <= -2 and vsa > 0:
                vsa -= 1
                currentTotal -= 2
            elif mcq > 0:
                mcq -= 1
                currentTotal -= 1
            else:
                break

    req.mcq_count = max(0, mcq)
    req.assertion_reason_count = max(0, ar)
    req.very_short_answer_count = max(0, vsa)
    req.short_answer_count = 0
    req.short_answer_ii_count = max(0, saII)
    req.long_answer_count = max(0, la)
    req.case_based_count = max(0, cb)

    run_id = str(uuid.uuid4())
    exam_config = req.model_dump()

    # Create MongoDB record
    try:
        create_paper_record(run_id, exam_config)
    except Exception as e:
        print(f"Warning: Could not create MongoDB record: {e}")

    # Launch agent in background
    _active_runs[run_id] = []
    background_tasks.add_task(run_agent, run_id, exam_config)

    return {"run_id": run_id, "status": "started"}


@app.get("/stream/{run_id}")
async def stream(run_id: str):
    """SSE endpoint — stream agent progress events for a run."""
    async def event_generator() -> AsyncGenerator[dict, None]:
        sent_count = 0
        max_wait = 300  # 5 minutes timeout
        waited = 0

        while waited < max_wait:
            events = _active_runs.get(run_id, [])

            while sent_count < len(events):
                event = events[sent_count]
                yield {"event": event["type"], "data": json.dumps(event["data"])}
                sent_count += 1

                # Stop streaming on terminal events
                if event["type"] in ("complete", "error"):
                    # Cleanup after short delay
                    await asyncio.sleep(5)
                    _active_runs.pop(run_id, None)
                    return

            await asyncio.sleep(0.5)
            waited += 0.5

        yield {"event": "error", "data": json.dumps({"message": "Timeout waiting for agent"})}

    return EventSourceResponse(event_generator(), ping=15)


@app.get("/paper/{run_id}")
async def get_paper_route(run_id: str):
    """Get the generated paper by run_id."""
    paper = get_paper(run_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


@app.get("/papers")
async def list_papers_route(limit: int = 20, skip: int = 0):
    """List recently generated papers."""
    papers = list_papers(limit=limit, skip=skip)
    return {"papers": papers, "count": len(papers)}


@app.post("/upload-metadata")
async def save_upload(req: UploadMetadataRequest):
    """Save metadata for a file uploaded directly to Vercel Blob."""
    doc_id = save_upload_metadata(
        blob_url=req.blob_url,
        filename=req.filename,
        file_type=req.file_type,
        size_bytes=req.size_bytes,
    )
    return {"id": doc_id, "blob_url": req.blob_url}


# ──────────────────────────────────────────────
# Startup / Shutdown
# ──────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    print("🚀 Exam Generator Agent starting up...")
    try:
        from src.db.postgres import setup_postgres
        await setup_postgres()
    except Exception as e:
        print(f"⚠️  PostgreSQL setup skipped: {e}")


@app.on_event("shutdown")
async def shutdown():
    try:
        from src.db.postgres import close_pool
        await close_pool()
    except Exception:
        pass
