#!/usr/bin/env python3
"""
Test ChromaDB with specific Danish query about climbing
"""
import asyncio
from MessageDatabase import MessageDatabase
from RAGEmbeddingService import RAGEmbeddingService
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv

async def test_specific_query():
    """Test with the specific Danish query"""
    print("Testing ChromaDB with specific query...")
    print("=" * 50)
    
    # Load environment
    load_dotenv()
    openai_key = os.getenv('openaikey')
    
    if not openai_key:
        print("❌ OpenAI key not found")
        return
    
    # Initialize services
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return
    
    client = AsyncOpenAI(api_key=openai_key)
    embedding_service = RAGEmbeddingService(client, db)
    
    # The specific query
    query = "Hvornår brokkede sig Pelle om at nogen ikke dukkede op til klatring?"
    print(f"Query: '{query}'")
    print()
    
    # Generate embedding
    print("Generating embedding...")
    query_embedding = await embedding_service.generate_embedding(query)
    if not query_embedding:
        print("❌ Failed to generate embedding")
        return
    
    print(f"✅ Generated embedding with {len(query_embedding)} dimensions")
    print()
    
    # Search for similar messages
    print("Searching for similar messages...")
    results = await db.get_similar_messages(query_embedding, limit=10)
    
    print(f"Found {len(results)} similar messages:")
    print("-" * 50)
    
    for i, result in enumerate(results):
        print(f"{i+1:2d}. Similarity: {result['similarity']:.3f}")
        print(f"    User: {result['display_name']}")
        print(f"    Time: {result['timestamp']}")
        print(f"    Content: {result['content']}")
        print()
    
    # Check if we found the exact message
    exact_match = None
    for result in results:
        if "brokkede sig" in result['content'].lower() and "pelle" in result['content'].lower():
            exact_match = result
            break
    
    if exact_match:
        print("🎯 FOUND EXACT MATCH!")
        print(f"   Similarity: {exact_match['similarity']:.3f}")
        print(f"   Content: {exact_match['content']}")
    else:
        print("❌ No exact match found")
    
    # Show ChromaDB stats
    stats = await db.chroma_service.get_collection_stats()
    print(f"\nChromaDB Stats: {stats['total_embeddings']} total embeddings")

if __name__ == "__main__":
    asyncio.run(test_specific_query())
