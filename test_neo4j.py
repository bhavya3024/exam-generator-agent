from neo4j import GraphDatabase

uri = "neo4j+s://e89249a1.databases.neo4j.io"
user = "e89249a1"
password = "dYNCD641K4JpUYfUEJ4LQpvwtsoUykA2dDWVzWs_SeY"

try:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
