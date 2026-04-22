import os
from dotenv import load_dotenv
load_dotenv(".env")

from phase_5_ingestion_cli.adapters.chroma_vector_index import ChromaVectorIndex
from phase_4_1_chunk_embed_index.ingestion_pipeline.embedder.embedder import build_embedder

api_key = os.environ.get("CHROMA_API_KEY", "")
tenant = os.environ.get("CHROMA_TENANT", "default_tenant")
database = os.environ.get("CHROMA_DATABASE", "default_database")

chroma = ChromaVectorIndex(api_key=api_key, collection_name="mf_rag", tenant=tenant, database=database)
print(f"Total chunks: {chroma._col.count()}")

embedder = build_embedder({"provider": "bge_local", "model": "BAAI/bge-small-en-v1.5", "dim": 384})
query = "What is the expense ratio of HDFC Mid Cap Fund Direct Growth?"
vec = embedder.embed_batch([query])[0]
print(f"Query vector dim: {len(vec)}")

results = chroma.query(vec, top_k=5)
print(f"Query returned {len(results)} results")
for r in results:
    print(f"  score={r['score']:.4f}  chunk_id={r['chunk_id']}")
    print(f"  text: {r['text'][:80]}")
