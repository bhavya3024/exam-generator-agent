"""Neo4j client and operations for GraphRAG."""
import os
from neo4j import GraphDatabase
from src.config import settings

_driver = None

def get_neo4j_driver():
    """Get or create Neo4j driver (singleton)."""
    global _driver
    if _driver is None:
        try:
            _driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_username, settings.neo4j_password))
            # Verify connection
            _driver.verify_connectivity()
        except Exception as e:
            print(f"Warning: Failed to connect to Neo4j at {settings.neo4j_uri}: {e}")
            _driver = None
    return _driver

def get_neo4j_graph():
    """Get Langchain Neo4jGraph instance for easy Cypher and GraphRAG operations."""
    from langchain_neo4j import Neo4jGraph
    
    try:
        graph = Neo4jGraph(
            url=settings.neo4j_uri, 
            username=settings.neo4j_username, 
            password=settings.neo4j_password,
            enhanced_schema=True
        )
        return graph
    except Exception as e:
        print(f"Warning: Failed to initialize Langchain Neo4jGraph: {e}")
        return None
