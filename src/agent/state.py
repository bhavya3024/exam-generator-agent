"""LangGraph state schema for the CBSE exam question generator."""
from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class ExamConfig(TypedDict):
    """Configuration for CBSE exam generation provided by the user."""
    subject: str
    topic: str
    cbse_class: str  # "9", "10", "11", "12"
    total_marks: int
    duration_minutes: int
    # CBSE question type distribution
    mcq_count: int
    assertion_reason_count: int
    very_short_answer_count: int
    short_answer_count: int       # SA-I (2 marks)
    short_answer_ii_count: int    # SA-II (3 marks)
    long_answer_count: int        # LA (5 marks)
    case_based_count: int         # Case/Source based (4 marks)
    # Difficulty distribution (percentages, must sum to 100)
    easy_percent: int
    medium_percent: int
    hard_percent: int
    # Uploaded document URLs from Vercel Blob
    document_urls: list[str]
    # Optional instructions
    special_instructions: str


class GeneratedQuestion(TypedDict):
    """A single generated CBSE exam question."""
    question_id: str
    question_type: str  # mcq | assertion_reason | very_short_answer | short_answer | long_answer | case_based
    question_text: str
    marks: int
    difficulty: str  # easy | medium | hard
    options: list[str] | None  # For MCQ / assertion_reason
    correct_answer: str | None  # For MCQ / assertion_reason
    model_answer: str | None  # Expected answer
    topic_tag: str
    blooms_level: str | None  # remembering | understanding | applying | analysing | evaluating | creating


class ExamPaper(TypedDict):
    """The complete generated CBSE exam paper."""
    paper_id: str
    title: str
    subject: str
    topic: str
    cbse_class: str
    total_marks: int
    duration_minutes: int
    sections: list[dict[str, Any]]
    questions: list[GeneratedQuestion]
    created_at: str
    general_instructions: list[str]


class AgentState(TypedDict):
    """Complete state for the LangGraph CBSE exam generation workflow."""
    # Input
    run_id: str
    exam_config: ExamConfig

    # Processing state
    messages: Annotated[list, add_messages]
    status: str  # pending | ingesting | retrieving | generating | validating | formatting | done | error
    progress: int  # 0-100

    # Document context
    document_chunks: list[str]
    retrieved_context: str

    # Generation
    draft_questions: list[GeneratedQuestion]
    validated_questions: list[GeneratedQuestion]
    validation_feedback: str

    # Output
    exam_paper: ExamPaper | None
    error_message: str | None
