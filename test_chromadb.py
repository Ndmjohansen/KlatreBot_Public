#!/usr/bin/env python3
"""
Test ChromaDB integration
"""
import asyncio
from MessageDatabase import MessageDatabase

async def test_chromadb():
    """Test ChromaDB functionality"""
    print("Testing ChromaDB integration...")
    
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return False
    
    print("✅ ChromaDB is available")
    
    # Test similarity search
    test_embedding = [0.1] * 1536  # Dummy embedding
    results = await db.get_similar_messages(test_embedding, limit=3)
    
    print(f"Found {len(results)} results:")
    for i, result in enumerate(results):
        print(f"  {i+1}. Similarity: {result['similarity']:.3f}")
        print(f"     Content: {result['content'][:80]}...")
        print(f"     User: {result['display_name']}")
        print()
    
    # Test collection stats
    stats = await db.chroma_service.get_collection_stats()
    print(f"ChromaDB Stats: {stats}")
    
    return True

if __name__ == "__main__":
    asyncio.run(test_chromadb())
