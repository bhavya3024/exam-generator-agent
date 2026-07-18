"""API routes for library/reference management."""
import asyncio
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.agent.graph import get_llm
from src.db.neo4j import get_neo4j_graph
from src.config import settings

router = APIRouter()

class ExtractRequest(BaseModel):
    url: str

@router.post("/extract")
async def extract_knowledge_graph(req: ExtractRequest):
    """Extract Knowledge Graph nodes and relationships from a reference PDF URL."""
    graph = get_neo4j_graph()
    if not graph:
        raise HTTPException(status_code=500, detail="Neo4j Knowledge Graph is not configured.")

    # 1. Fetch PDF Content
    # We will use PyMuPDF or similar via the existing agent logic.
    # To avoid repeating parsing logic, we'll fetch and chunk it simply here.
    all_chunks = []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=200,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            headers = {}
            if "blob.vercel-storage.com" in req.url and settings.blob_read_write_token:
                headers["Authorization"] = f"Bearer {settings.blob_read_write_token}"
            
            response = await client.get(req.url, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")

            if "pdf" in content_type or req.url.lower().endswith(".pdf"):
                from src.agent.graph import _parse_pdf_sync
                chunks = await asyncio.to_thread(_parse_pdf_sync, response.content, splitter)
                all_chunks.extend(chunks)
            else:
                chunks = splitter.split_text(response.text)
                all_chunks.extend(chunks)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch document: {e}")
        
    if not all_chunks:
        raise HTTPException(status_code=400, detail="No content could be extracted from document.")

    # 2. Process with LLMGraphTransformer
    try:
        from langchain_experimental.graph_transformers import LLMGraphTransformer
        llm = get_llm(temperature=0.1)
        llm_transformer = LLMGraphTransformer(llm=llm)
        
        # Process a small subset (first 3 chunks) for quick feedback in demo
        docs = [Document(page_content=c) for c in all_chunks[:3]]
        
        # Extract graph documents
        graph_docs = await asyncio.to_thread(llm_transformer.convert_to_graph_documents, docs)
        
        # Add to Neo4j
        await asyncio.to_thread(graph.add_graph_documents, graph_docs)
        
        # Format the result to send back to the frontend
        extracted_nodes = []
        extracted_relationships = []
        
        for g_doc in graph_docs:
            for node in g_doc.nodes:
                extracted_nodes.append({"id": node.id, "type": node.type})
            for rel in g_doc.relationships:
                extracted_relationships.append({
                    "source": rel.source.id,
                    "target": rel.target.id,
                    "type": rel.type
                })
        
        # Deduplicate
        unique_nodes = {n['id']: n for n in extracted_nodes}.values()
        
        return {
            "status": "success",
            "nodes": list(unique_nodes),
            "relationships": extracted_relationships
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Graph extraction failed: {str(e)}")
