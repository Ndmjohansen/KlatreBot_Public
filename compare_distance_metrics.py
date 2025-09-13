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
    
    print("Current approach (using Euclidean distance directly):")
    for i, result in enumerate(results):
        print(f"  {i+1}. Distance: {result['similarity']:.3f}")
        print(f"     Content: {result['content'][:50]}...")
    
    print(f"\nEuclidean distance approach:")
    print(f"  - Smaller distance = more similar")
    print(f"  - Range: 0 to infinity (no upper bound)")
    print(f"  - Sorted by distance ASC (lower is better)")
    print(f"  - Much better separation between relevant and irrelevant results")
    
    print(f"\nPrevious compressed similarity approach:")
    print(f"  - Used 1/(1+distance) which compressed the range too much")
    print(f"  - Range: 0 to 1 (bounded but compressed)")
    print(f"  - Made it hard to distinguish between relevant and irrelevant")

if __name__ == "__main__":
    asyncio.run(compare_metrics())
