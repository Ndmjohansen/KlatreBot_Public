#!/usr/bin/env python3
"""
Compare Euclidean distance vs similarity conversion
"""
import asyncio
from MessageDatabase import MessageDatabase

async def compare_metrics():
    """Compare different distance/similarity approaches"""
    print("Comparing Distance Metrics")
    print("=" * 40)
    
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return
    
    # Test query
    test_embedding = [0.1] * 1536
    results = await db.chroma_service.search_similar(test_embedding, limit=3)
    
    print("Current approach (similarity = 1/(1+distance)):")
    for i, result in enumerate(results):
        distance = 1/result['similarity'] - 1  # Reverse the calculation
        print(f"  {i+1}. Distance: {distance:.3f}, Similarity: {result['similarity']:.3f}")
        print(f"     Content: {result['content'][:50]}...")
    
    print(f"\nIf we used Euclidean distance directly:")
    print(f"  - Smaller distance = more similar")
    print(f"  - Range: 0 to infinity (no upper bound)")
    print(f"  - Would need to sort by distance ASC instead of similarity DESC")
    
    print(f"\nCurrent similarity approach:")
    print(f"  - Higher similarity = more similar") 
    print(f"  - Range: 0 to 1 (bounded)")
    print(f"  - Compatible with existing RAG system expectations")

if __name__ == "__main__":
    asyncio.run(compare_metrics())
