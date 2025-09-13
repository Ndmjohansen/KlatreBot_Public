#!/usr/bin/env python3
"""
Check what distance metric ChromaDB is using
"""
import asyncio
from MessageDatabase import MessageDatabase

async def check_metric():
    """Check ChromaDB distance metric"""
    print("Checking ChromaDB distance metric...")
    
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return
    
    # Test with identical vectors (should give distance 0)
    test_embedding = [0.1] * 1536
    
    # Add a test document
    await db.chroma_service.store_embedding(
        999999, test_embedding, "Test content", "TestUser", 
        asyncio.get_event_loop().time(), "text"
    )
    
    # Query with the same embedding
    results = await db.chroma_service.search_similar(test_embedding, limit=1)
    
    if results:
        print(f"Distance to identical vector: {1 - results[0]['similarity']:.6f}")
        print(f"Similarity: {results[0]['similarity']:.6f}")
        
        # If distance is 0, it's cosine similarity
        # If distance is > 0, it's L2 distance
        distance = 1 - results[0]['similarity']
        if abs(distance) < 0.001:
            print("✅ ChromaDB is using cosine similarity")
        else:
            print("❌ ChromaDB is using L2 distance")
    else:
        print("❌ No results found")

if __name__ == "__main__":
    asyncio.run(check_metric())
