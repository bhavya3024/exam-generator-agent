"""API routes for library/reference management."""
import asyncio
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.agent.graph import get_llm
from src.config import settings

router = APIRouter()

class ExtractRequest(BaseModel):
    url: str

@router.post("/extract")
async def extract_knowledge_graph(req: ExtractRequest):
    """Extraction disabled as Neo4j GraphRAG was removed."""
    return {"message": "Knowledge Graph Extraction is disabled.", "nodes": [], "relationships": []}
