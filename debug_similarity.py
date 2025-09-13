#!/usr/bin/env python3
"""
Debug similarity calculation in ChromaDB
"""
import asyncio
from MessageDatabase import MessageDatabase

async def debug_similarity():
    """Debug the similarity calculation"""
    print("Debugging ChromaDB similarity calculation...")
    
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return
    
    # Test with a dummy embedding
    test_embedding = [0.1] * 1536
    
    # Get raw results from ChromaDB
    results = await db.chroma_service.search_similar(test_embedding, limit=5)
    
    print(f"Raw ChromaDB results: {len(results)}")
    for i, result in enumerate(results):
        print(f"Result {i+1}:")
        print(f"  Similarity: {result['similarity']}")
        print(f"  Content: {result['content'][:50]}...")
        print()
    
    # Let's also check what ChromaDB is actually returning
    try:
        # Access ChromaDB directly to see raw distances
        collection = db.chroma_service.collection
        raw_results = collection.query(
            query_embeddings=[test_embedding],
            n_results=5
        )
        
        print("Raw ChromaDB query results:")
        print(f"Distances: {raw_results['distances'][0]}")
        print(f"IDs: {raw_results['ids'][0]}")
        
        # Calculate similarity manually
        for i, distance in enumerate(raw_results['distances'][0]):
            similarity_1 = 1.0 - distance
            similarity_2 = max(0.0, min(1.0, 1.0 - distance))
            print(f"Distance {i+1}: {distance:.6f}")
            print(f"  1.0 - distance: {similarity_1:.6f}")
            print(f"  Clamped: {similarity_2:.6f}")
            print()
            
    except Exception as e:
        print(f"Error accessing raw results: {e}")

if __name__ == "__main__":
    asyncio.run(debug_similarity())
