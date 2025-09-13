#!/usr/bin/env python3
"""
Test that command messages are filtered out from embeddings
"""
import asyncio
from MessageDatabase import MessageDatabase

async def test_command_filtering():
    """Test that command messages are not embedded"""
    print("Testing command message filtering...")
    print("=" * 40)
    
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return
    
    # Test query
    test_query = "klatring climbing"
    print(f"Query: '{test_query}'")
    print()
    
    # Generate embedding for the query
    from RAGEmbeddingService import RAGEmbeddingService
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
    
    query_embedding = await embedding_service.generate_embedding(test_query)
    if not query_embedding:
        print("❌ Failed to generate embedding")
        return
    
    # Search for similar messages
    results = await db.get_similar_messages(query_embedding, limit=10)
    
    print(f"Found {len(results)} similar messages:")
    print("-" * 50)
    
    command_count = 0
    text_count = 0
    
    for i, result in enumerate(results):
        is_command = result['content'].startswith('!')
        if is_command:
            command_count += 1
        else:
            text_count += 1
            
        print(f"{i+1:2d}. Similarity: {result['similarity']:.3f} {'[COMMAND]' if is_command else '[TEXT]'}")
        print(f"    User: {result['display_name']}")
        print(f"    Content: {result['content'][:60]}...")
        print()
    
    print(f"Summary:")
    print(f"  Text messages: {text_count}")
    print(f"  Command messages: {command_count}")
    
    if command_count == 0:
        print("✅ Perfect! No command messages in results")
    else:
        print(f"⚠️  Found {command_count} command messages - filtering may not be working")

if __name__ == "__main__":
    asyncio.run(test_command_filtering())
