#!/usr/bin/env python3
"""
Reset ChromaDB collection with cosine distance metric
"""
import asyncio
import os
import shutil
from MessageDatabase import MessageDatabase

async def reset_chromadb():
    """Reset ChromaDB collection with proper distance metric"""
    print("Resetting ChromaDB with cosine distance metric...")
    
    # Remove existing ChromaDB directory
    chroma_dir = "./chroma_db"
    if os.path.exists(chroma_dir):
        print(f"Removing existing ChromaDB directory: {chroma_dir}")
        shutil.rmtree(chroma_dir)
    
    # Reinitialize and migrate
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return False
    
    print("✅ ChromaDB reinitialized with cosine distance")
    
    # Migrate data
    migrated_count = await db.chroma_service.migrate_from_sqlite(db)
    print(f"✅ Migrated {migrated_count} embeddings")
    
    # Test with a real query
    print("\nTesting with a real query...")
    test_embedding = [0.1] * 1536  # Still dummy, but should work better with cosine
    results = await db.get_similar_messages(test_embedding, limit=3)
    
    print(f"Found {len(results)} results:")
    for i, result in enumerate(results):
        print(f"  {i+1}. Similarity: {result['similarity']:.3f}")
        print(f"     Content: {result['content'][:60]}...")
        print()
    
    return True

if __name__ == "__main__":
    asyncio.run(reset_chromadb())
