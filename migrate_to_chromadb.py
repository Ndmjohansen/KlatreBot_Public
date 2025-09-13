#!/usr/bin/env python3
"""
Migration script to move from SQLite BLOB embeddings to ChromaDB
"""
import asyncio
import logging
from MessageDatabase import MessageDatabase

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def migrate_to_chromadb():
    """Migrate existing embeddings to ChromaDB"""
    print("ChromaDB Migration Script")
    print("=" * 40)
    
    db = MessageDatabase()
    
    # Initialize database and ChromaDB
    await db.initialize()
    
    if not db.vector_available:
        print("❌ ChromaDB not available. Please check installation.")
        return False
    
    print("✅ ChromaDB initialized successfully")
    print("Starting migration from SQLite to ChromaDB...")
    
    # Migrate embeddings
    migrated_count = await db.chroma_service.migrate_from_sqlite(db)
    
    if migrated_count > 0:
        print(f"✅ Migration completed successfully!")
        print(f"Migrated {migrated_count} embeddings to ChromaDB")
        
        # Test the migration
        print("\nTesting ChromaDB functionality...")
        await test_chromadb_functionality(db)
        
        return True
    else:
        print("❌ No embeddings were migrated")
        return False

async def test_chromadb_functionality(db):
    """Test ChromaDB functionality after migration"""
    try:
        # Get collection stats
        stats = await db.chroma_service.get_collection_stats()
        print(f"ChromaDB Stats: {stats}")
        
        # Test with a dummy embedding
        test_embedding = [0.1] * 1536  # OpenAI embedding dimension
        
        results = await db.get_similar_messages(test_embedding, limit=5)
        print(f"✅ Similarity search test successful. Found {len(results)} results.")
        
        if results:
            print("Sample result:")
            sample = results[0]
            print(f"  Message ID: {sample['discord_message_id']}")
            print(f"  Content: {sample['content'][:100]}...")
            print(f"  Similarity: {sample['similarity']:.3f}")
        
        return True
        
    except Exception as e:
        print(f"❌ ChromaDB test failed: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(migrate_to_chromadb())
