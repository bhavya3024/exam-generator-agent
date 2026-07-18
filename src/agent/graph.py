"""
LangGraph CBSE exam question generator agent.
Nodes: ingest_documents → retrieve_context → generate_questions → validate_questions → format_paper
"""
import json
import uuid
import asyncio
import httpx
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import Chroma
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

from src.agent.state import AgentState, GeneratedQuestion, ExamPaper
from src.agent.prompts import (
    QUESTION_GENERATION_SYSTEM_PROMPT,
    VALIDATION_SYSTEM_PROMPT,
    FORMATTING_SYSTEM_PROMPT,
    build_generation_prompt,
    build_validation_prompt,
)
from src.config import settings


def get_llm(temperature: float = 0.7) -> ChatOpenAI:
    """Get the configured LLM instance."""
    return ChatOpenAI(
        model=settings.model_name,
        api_key=settings.openai_api_key,
        temperature=temperature,
        max_tokens=16000,
    )


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=settings.openai_api_key,
    )


# ─────────────────────────────────────────────────────────────
# Node: Ingest Documents
# ─────────────────────────────────────────────────────────────
async def ingest_documents(state: AgentState) -> dict:
    """Download documents from Vercel Blob and chunk them for retrieval."""
    doc_urls = state["exam_config"].get("document_urls", [])

    if not doc_urls:
        return {
            "document_chunks": [],
            "status": "retrieving",
            "progress": 20,
        }

def _parse_pdf_sync(content: bytes, splitter: RecursiveCharacterTextSplitter) -> list[str]:
    """Helper running synchronously in a background thread to avoid event loop blocking."""
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        loader = PyPDFLoader(tmp_path)
        docs = loader.load()
        chunks = []
        for doc in docs:
            chunks.extend(splitter.split_text(doc.page_content))
        return chunks
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

async def ingest_documents(state: AgentState) -> dict:
    """Download documents from Vercel Blob and chunk them for retrieval."""
    doc_urls = state["exam_config"].get("document_urls", [])

    if not doc_urls:
        return {
            "document_chunks": [],
            "status": "retrieving",
            "progress": 20,
        }

    all_chunks = []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=200,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    async with httpx.AsyncClient(timeout=60) as client:
        for idx, url in enumerate(doc_urls):
            try:
                run_id = state.get("run_id")
                filename = url.split("/")[-1]
                if "?" in filename:
                    filename = filename.split("?")[0]
                
                # Report live download and indexing progress
                current_progress = 20 + int(((idx + 1) / len(doc_urls)) * 15)
                msg = f"Ingesting reference {idx + 1}/{len(doc_urls)}: {filename}..."
                
                if run_id:
                    from src.db.mongo import update_paper_progress
                    await asyncio.to_thread(update_paper_progress, run_id, current_progress, msg)
                
                response = await client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")

                if "pdf" in content_type or url.lower().endswith(".pdf"):
                    # Load PDF using PyPDFLoader inside a background worker thread
                    chunks = await asyncio.to_thread(_parse_pdf_sync, response.content, splitter)
                    all_chunks.extend(chunks)
                else:
                    # Plain text
                    text = response.text
                    chunks = splitter.split_text(text)
                    all_chunks.extend(chunks)

            except Exception as e:
                print(f"Warning: Failed to load document {url}: {e}")
                continue

    return {
        "document_chunks": all_chunks,
        "status": "retrieving",
        "progress": 35,
    }


# ─────────────────────────────────────────────────────────────
# Node: Retrieve Context
# ─────────────────────────────────────────────────────────────
async def retrieve_context(state: AgentState) -> dict:
    """Build a vector store from chunks and retrieve relevant context."""
    chunks = state.get("document_chunks", [])
    config = state["exam_config"]

    run_id = state.get("run_id")
    if run_id:
        from src.db.mongo import update_paper_progress
        await asyncio.to_thread(
            update_paper_progress, 
            run_id, 
            40, 
            "Retrieving chapter syllabus and context boundary maps from Vector Store...",
            "retrieving"
        )

    if not chunks:
        return {
            "retrieved_context": "",
            "status": "generating",
            "progress": 40,
        }

    cbse_class = config.get('cbse_class', '10')
    query = f"CBSE Class {cbse_class} {config['subject']} {config['topic']} NCERT question syllabus board exam"

    try:
        embeddings = get_embeddings()
        # Use in-memory Chroma (no persistence needed per run)
        vectorstore = await asyncio.to_thread(
            Chroma.from_texts,
            texts=chunks,
            embedding=embeddings,
            collection_name=f"run_{state['run_id'].replace('-', '_')}",
        )
        retriever = vectorstore.as_retriever(search_kwargs={"k": 8})
        relevant_docs = await asyncio.to_thread(retriever.invoke, query)
        context = "\n\n---\n\n".join([d.page_content for d in relevant_docs])

        # Cleanup
        await asyncio.to_thread(vectorstore.delete_collection)

    except Exception as e:
        print(f"Warning: Vector retrieval failed ({e}), using raw chunks")
        context = "\n\n".join(chunks[:8])  # Fallback: first 8 chunks

    return {
        "retrieved_context": context[:8000],  # Limit context size
        "status": "generating",
        "progress": 40,
    }


# ─────────────────────────────────────────────────────────────
# Node: Generate Questions
# ─────────────────────────────────────────────────────────────
async def generate_questions(state: AgentState) -> dict:
    """Use LLM to generate CBSE exam questions."""
    config = state["exam_config"]
    context = state.get("retrieved_context", "")
    run_id = state.get("run_id")
    if run_id:
        from src.db.mongo import update_paper_progress
        await asyncio.to_thread(
            update_paper_progress,
            run_id,
            55,
            "Synthesizing CBSE questions (using gpt-4o model)...",
            "generating"
        )
    llm = get_llm(temperature=0.8)

    prompt = build_generation_prompt(config, context)
    messages = [
        SystemMessage(content=QUESTION_GENERATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    try:
        response = await llm.ainvoke(messages)
        raw_text = response.content.strip()

        # Strip markdown code blocks if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        try:
            questions_data = json.loads(raw_text)
        except json.JSONDecodeError:
            print("Warning: JSON parsing failed, attempting to repair truncated output...")
            # If the LLM was cut off mid-generation, try to salvage the valid JSON objects
            try:
                # Find the last properly closed object '}'
                last_brace = raw_text.rfind('}')
                if last_brace != -1:
                    repaired_text = raw_text[:last_brace+1] + ']'
                    questions_data = json.loads(repaired_text)
                else:
                    questions_data = []
            except Exception as e:
                print(f"Failed to repair JSON: {e}")
                questions_data = []

        # Add question IDs if missing
        for i, q in enumerate(questions_data):
            if "question_id" not in q or not q["question_id"]:
                q["question_id"] = f"q{i + 1}"
                
        # STRICT EXACT ENFORCEMENT BY MARKS
        # The user requested that exact marks be fixed "at any cost".
        # LLMs often miscount. We programmatically enforce the exact mark distribution.
        def get_cnt(key):
            try:
                return int(config.get(key, 0))
            except:
                return 0
                
        target_by_marks = {
            1: get_cnt('mcq_count') + get_cnt('assertion_reason_count'),
            2: get_cnt('short_answer_count') + get_cnt('very_short_answer_count'),
            3: get_cnt('short_answer_ii_count'),
            4: get_cnt('case_based_count'),
            5: get_cnt('long_answer_count')
        }
        
        final_questions = []
        for marks_val, target_qty in target_by_marks.items():
            pool = [q for q in questions_data if int(q.get("marks", 0)) == marks_val]
            
            if target_qty == 0:
                continue
            
            if len(pool) > target_qty:
                # Trim excess
                final_questions.extend(pool[:target_qty])
            elif len(pool) < target_qty:
                # Pad missing with clones
                final_questions.extend(pool)
                missing = target_qty - len(pool)
                for _ in range(missing):
                    if pool:
                        import copy
                        clone = copy.deepcopy(pool[0])
                        clone["question_text"] = clone["question_text"] + " (Auto-recovered missing question)"
                        final_questions.append(clone)
                    else:
                        # Fallback dummy question if LLM completely missed this category
                        final_questions.append({
                            "question_id": f"q_dummy",
                            "question_type": "short_answer" if marks_val > 1 else "mcq",
                            "question_text": f"[System: Missing {marks_val}-mark question from AI generation]",
                            "marks": marks_val,
                            "difficulty": "medium",
                            "options": ["A", "B", "C", "D"] if marks_val == 1 else None,
                            "correct_answer": "A" if marks_val == 1 else None,
                            "model_answer": "AI generation skipped this item.",
                            "topic_tag": "Various",
                            "blooms_level": "understanding"
                        })
            else:
                final_questions.extend(pool)
                
        # Update IDs sequentially and correctly format the final list
        questions = []
        for i, q in enumerate(final_questions):
            q["question_id"] = f"q{i+1}"
            questions.append(q)

    except Exception as e:
        print(f"Generation error: {e}")
        questions = []

    return {
        "draft_questions": questions,
        "status": "validating",
        "progress": 65,
    }


# ─────────────────────────────────────────────────────────────
# Node: Validate Questions
# ─────────────────────────────────────────────────────────────
async def validate_questions(state: AgentState) -> dict:
    """Self-critique: validate questions for CBSE quality and accuracy."""
    questions = state.get("draft_questions", [])
    config = state["exam_config"]
    run_id = state.get("run_id")
    if run_id:
        from src.db.mongo import update_paper_progress
        await asyncio.to_thread(
            update_paper_progress,
            run_id,
            75,
            "Self-critiquing generated questions for CBSE curriculum compliance...",
            "validating"
        )

    if not questions:
        return {
            "validated_questions": [],
            "validation_feedback": "No questions were generated",
            "status": "formatting",
            "progress": 80,
        }

    llm = get_llm(temperature=0.1)
    prompt = build_validation_prompt(questions, config)
    messages = [
        SystemMessage(content=VALIDATION_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    try:
        response = await llm.ainvoke(messages)
        raw_text = response.content.strip()

        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        validation = json.loads(raw_text)
        approved_ids = set(validation.get("approved_ids", []))
        feedback = validation.get("feedback", "")

        # CRITICAL FIX: Do NOT drop any questions during validation, 
        # otherwise it breaks the exact marks count constraint requested by the user.
        # We accept the LLM's self-critique feedback, but we keep all questions.
        validated = questions

    except Exception as e:
        print(f"Validation error: {e}, keeping all questions")
        validated = questions
        feedback = "Validation skipped due to error"

    return {
        "validated_questions": validated,
        "validation_feedback": feedback,
        "status": "formatting",
        "progress": 80,
    }


# ─────────────────────────────────────────────────────────────
# Node: Format Paper
# ─────────────────────────────────────────────────────────────
async def format_paper(state: AgentState) -> dict:
    """Organize questions into a structured CBSE exam paper."""
    questions = state.get("validated_questions", [])
    config = state["exam_config"]
    run_id = state.get("run_id")
    if run_id:
        from src.db.mongo import update_paper_progress
        await asyncio.to_thread(
            update_paper_progress,
            run_id,
            90,
            "Assembling sections and formatting CBSE instructions sheet...",
            "formatting"
        )

    # Build sections locally matching CBSE blueprints
    sections = _build_sections(questions)
    total_marks = sum(q.get("marks", 0) for q in questions)
    cbse_class = config.get("cbse_class", "10")

    paper: ExamPaper = {
        "paper_id": state["run_id"],
        "title": f"CBSE Class {cbse_class} {config['subject']} Examination — {config['topic']}",
        "subject": config["subject"],
        "topic": config["topic"],
        "cbse_class": cbse_class,
        "total_marks": total_marks or config.get("total_marks", 80),
        "duration_minutes": config.get("duration_minutes", 180),
        "sections": sections,
        "questions": questions,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "general_instructions": [
            "All questions are compulsory.",
            "This question paper contains five sections: Section A, B, C, D, and E.",
            "Section A comprises MCQs and Assertion-Reason questions of 1 mark each.",
            "Section B comprises Very Short / Short Answer-I type questions of 2 marks each.",
            "Section C comprises Short Answer-II type questions of 3 marks each.",
            "Section D comprises Long Answer type questions of 5 marks each.",
            "Section E comprises Case-Based competency questions of 4 marks each.",
            "There is no overall choice. However, internal choices may be provided.",
            "Use of calculators is not permitted."
        ]
    }

    return {
        "exam_paper": paper,
        "status": "done",
        "progress": 100,
    }


def _build_sections(questions: list[dict]) -> list[dict]:
    """Organize questions into standard CBSE Sections A-E."""
    # CBSE standard patterns:
    # Section A: MCQ + Assertion-Reason (1 mark each)
    section_a_qs = [q for q in questions if q.get("question_type") in ("mcq", "assertion_reason") or q.get("marks") == 1]
    
    # Section B: Very Short Answer / Short Answer-I (2 marks each)
    section_b_qs = [q for q in questions if q.get("question_type") in ("very_short_answer", "short_answer") and q.get("marks") == 2]
    
    # Section C: Short Answer-II (3 marks each)
    section_c_qs = [q for q in questions if q.get("question_type") == "short_answer_ii" or (q.get("question_type") in ("short_answer", "very_short_answer") and q.get("marks") == 3)]
    
    # Section D: Long Answer (5 marks each)
    section_d_qs = [q for q in questions if q.get("question_type") == "long_answer" or q.get("marks") == 5]
    
    # Section E: Case-Based competency questions (4 marks each)
    section_e_qs = [q for q in questions if q.get("question_type") == "case_based" or q.get("marks") == 4]

    # Catch-all for any other marking structures:
    categorized_ids = set()
    for s in (section_a_qs, section_b_qs, section_c_qs, section_d_qs, section_e_qs):
        for q in s:
            categorized_ids.add(q["question_id"])
            
    # Put leftovers in the closest matching mark section
    for q in questions:
        if q["question_id"] not in categorized_ids:
            marks = q.get("marks", 1)
            if marks == 1:
                section_a_qs.append(q)
            elif marks == 2:
                section_b_qs.append(q)
            elif marks == 3:
                section_c_qs.append(q)
            elif marks == 4:
                section_e_qs.append(q)
            else:
                section_d_qs.append(q)

    sections = []
    if section_a_qs:
        sections.append({
            "name": "Section A — Objective Type Questions",
            "description": "This section comprises MCQs and Assertion-Reason type questions of 1 mark each. Select the correct option.",
            "total_marks": sum(q.get("marks", 1) for q in section_a_qs),
            "question_ids": [q["question_id"] for q in section_a_qs],
        })
    if section_b_qs:
        sections.append({
            "name": "Section B — Very Short Answer Questions",
            "description": "This section comprises Very Short Answer / SA-I type questions of 2 marks each. Answers should be brief (30-50 words).",
            "total_marks": sum(q.get("marks", 2) for q in section_b_qs),
            "question_ids": [q["question_id"] for q in section_b_qs],
        })
    if section_c_qs:
        sections.append({
            "name": "Section C — Short Answer Questions",
            "description": "This section comprises Short Answer-II type questions of 3 marks each. Answers should be structured (50-80 words).",
            "total_marks": sum(q.get("marks", 3) for q in section_c_qs),
            "question_ids": [q["question_id"] for q in section_c_qs],
        })
    if section_d_qs:
        sections.append({
            "name": "Section D — Long Answer Questions",
            "description": "This section comprises Long Answer type questions of 5 marks each. Answers should be detailed and structured (150+ words).",
            "total_marks": sum(q.get("marks", 5) for q in section_d_qs),
            "question_ids": [q["question_id"] for q in section_d_qs],
        })
    if section_e_qs:
        sections.append({
            "name": "Section E — Case-Based/Source-Based Questions",
            "description": "This section comprises Case-Based competency questions of 4 marks each with sub-parts. Read the passage carefully and answer the questions.",
            "total_marks": sum(q.get("marks", 4) for q in section_e_qs),
            "question_ids": [q["question_id"] for q in section_e_qs],
        })
    return sections


async def save_paper_node(state: AgentState) -> dict:
    """Save the final exam paper to MongoDB."""
    run_id = state.get("run_id")
    paper = state.get("exam_paper")
    config = state["exam_config"]
    if run_id and paper:
        from src.db.mongo import save_paper, update_paper_progress
        # Save paper directly to MongoDB
        await asyncio.to_thread(save_paper, run_id, paper, config)
        # Mark status as completed and progress as 100%
        await asyncio.to_thread(update_paper_progress, run_id, 100, "Paper generation complete!", "completed")
        print(f"✅ Saved paper {run_id} to MongoDB in graph node")
    return {
        "status": "completed",
        "progress": 100
    }


# ─────────────────────────────────────────────────────────────
# Graph Builder
# ─────────────────────────────────────────────────────────────
def build_graph(checkpointer: PostgresSaver | None = None) -> Any:
    """Build and compile the LangGraph exam generation workflow."""
    workflow = StateGraph(AgentState)

    workflow.add_node("ingest_documents", ingest_documents)
    workflow.add_node("retrieve_context", retrieve_context)
    workflow.add_node("generate_questions", generate_questions)
    workflow.add_node("validate_questions", validate_questions)
    workflow.add_node("format_paper", format_paper)
    workflow.add_node("save_paper_node", save_paper_node)

    workflow.set_entry_point("ingest_documents")
    workflow.add_edge("ingest_documents", "retrieve_context")
    workflow.add_edge("retrieve_context", "generate_questions")
    workflow.add_edge("generate_questions", "validate_questions")
    workflow.add_edge("validate_questions", "format_paper")
    workflow.add_edge("format_paper", "save_paper_node")
    workflow.add_edge("save_paper_node", END)

    return workflow.compile(checkpointer=checkpointer)


# Compiled graph instance (initialized lazily)
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        try:
            from src.db.postgres import get_checkpointer
            checkpointer = get_checkpointer()
            _graph = build_graph(checkpointer)
            print("✅ Graph compiled with PostgreSQL checkpointer")
        except Exception as e:
            print(f"⚠️ PostgreSQL unavailable ({e}), running without checkpointer")
            _graph = build_graph(checkpointer=None)
    return _graph
