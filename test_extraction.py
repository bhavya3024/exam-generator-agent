import asyncio
from src.config import settings
from src.agent.graph import get_llm
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_core.documents import Document

async def test_extraction():
    try:
        print("Setting up LLM...")
        llm = get_llm(temperature=0.1)
        print("Model used:", llm.model_name)
        
        llm_transformer = LLMGraphTransformer(llm=llm)
        docs = [Document(page_content="Albert Einstein formulated the theory of relativity. He was born in Germany.")]
        
        print("Extracting...")
        graph_docs = await asyncio.to_thread(llm_transformer.convert_to_graph_documents, docs)
        
        print(f"Extracted {len(graph_docs[0].nodes)} nodes and {len(graph_docs[0].relationships)} relationships.")
    except Exception as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_extraction())
