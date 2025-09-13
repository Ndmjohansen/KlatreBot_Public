#!/usr/bin/env python3
"""
Test ChromaDB with a real query
"""
import asyncio
from MessageDatabase import MessageDatabase
from RAGEmbeddingService import RAGEmbeddingService

async def test_real_query():
    """Test with a real query using OpenAI embeddings"""
    print("Testing ChromaDB with real query...")
    
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return
    
    # Create embedding service
    from openai import AsyncOpenAI
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    openai_key = os.getenv('openaikey')
    
    if not openai_key:
        print("❌ OpenAI key not found")
        return
    
    client = AsyncOpenAI(api_key=openai_key)
    embedding_service = RAGEmbeddingService(client, db)
    
    # Test with a real query
    test_query = "klatring climbing"
    print(f"Query: '{test_query}'")
    
    # Generate embedding for the query
    query_embedding = await embedding_service.generate_embedding(test_query)
    if not query_embedding:
        print("❌ Failed to generate embedding")
        return
    
    print(f"Generated embedding with {len(query_embedding)} dimensions")
    
    # Search for similar messages
    results = await db.get_similar_messages(query_embedding, limit=5)
    
    print(f"\nFound {len(results)} similar messages:")
    for i, result in enumerate(results):
        print(f"  {i+1}. Similarity: {result['similarity']:.3f}")
        print(f"     User: {result['display_name']}")
        print(f"     Content: {result['content'][:80]}...")
        print()

if __name__ == "__main__":
    asyncio.run(test_real_query())
