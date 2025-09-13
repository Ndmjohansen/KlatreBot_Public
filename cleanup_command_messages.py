#!/usr/bin/env python3
"""
Clean up command messages from ChromaDB
"""
import asyncio
from MessageDatabase import MessageDatabase

async def cleanup_command_messages():
    """Remove command messages from ChromaDB"""
    print("Cleaning up command messages from ChromaDB...")
    print("=" * 50)
    
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available")
        return
    
    # Get all messages from ChromaDB
    collection = db.chroma_service.collection
    all_docs = collection.get()
    
    print(f"Total documents in ChromaDB: {len(all_docs['ids'])}")
    
    # Find command messages to remove
    command_ids = []
    for i, content in enumerate(all_docs['documents']):
        if content.startswith('!'):
            command_ids.append(all_docs['ids'][i])
    
    print(f"Found {len(command_ids)} command messages to remove")
    
    if command_ids:
        # Remove command messages
        collection.delete(ids=command_ids)
        print(f"✅ Removed {len(command_ids)} command messages from ChromaDB")
    else:
        print("✅ No command messages found")
    
    # Show updated stats
    updated_docs = collection.get()
    print(f"Updated total: {len(updated_docs['ids'])} documents")
    
    # Test search after cleanup
    print("\nTesting search after cleanup...")
    test_embedding = [0.1] * 1536
    results = await db.get_similar_messages(test_embedding, limit=5)
    
    print(f"Found {len(results)} results after cleanup:")
    for i, result in enumerate(results):
        is_command = result['content'].startswith('!')
        print(f"  {i+1}. Similarity: {result['similarity']:.3f} {'[COMMAND]' if is_command else '[TEXT]'}")
        print(f"     Content: {result['content'][:50]}...")

if __name__ == "__main__":
    asyncio.run(cleanup_command_messages())
