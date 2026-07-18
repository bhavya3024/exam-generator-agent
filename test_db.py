from pymongo import MongoClient

url = "mongodb+srv://db-agent-user:a48xMXygMC3bxal6@sample-database.5idkcp1.mongodb.net/"
client = MongoClient(url)
db = client['examgen']
papers = list(db.papers.find().sort("created_at", -1).limit(1))

if papers:
    paper = papers[0]
    config = paper.get('config', {})
    doc_urls = config.get('document_urls', [])
    print(f"LATEST PAPER ({paper.get('id')}):")
    print(f"Subject: {config.get('subject')}")
    print(f"Doc URLs ({len(doc_urls)}): {doc_urls}")
else:
    print("No papers found.")
