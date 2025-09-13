#!/usr/bin/env python3
"""
Migration script to move from BLOB embeddings to sqlite-vec
"""
import asyncio
import logging
import aiosqlite
from MessageDatabase import MessageDatabase

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def migrate_embeddings():
    """Migrate existing embeddings to vector table"""
    db = MessageDatabase()
    
    # Initialize database to check vector availability
    await db.initialize()
    
    if not db.vector_available:
        print("Vector extension not available. Please install sqlite-vec package.")
        return False
    
    print("Starting embedding migration...")
    
    # Get all existing embeddings using aiosqlite
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT me.discord_message_id, me.embedding
            FROM message_embeddings me
            JOIN messages m ON me.discord_message_id = m.discord_message_id
            WHERE m.has_embedding = TRUE
        """)
        
        rows = await cursor.fetchall()
        migrated_count = 0
        total_count = len(rows)
        
        print(f"Found {total_count} embeddings to migrate...")
        
        # Use synchronous connection for vector operations
        import sqlite3
        with sqlite3.connect(db.db_path) as sync_conn:
            load(sync_conn)
            
            for message_id, embedding_blob in rows:
                try:
                    import pickle
                    embedding = pickle.loads(embedding_blob)
                    
                    # Store in vector table
                    sync_conn.execute("""
                        INSERT OR REPLACE INTO message_vectors (discord_message_id, embedding)
                        VALUES (?, ?)
                    """, (message_id, embedding))
                    
                    migrated_count += 1
                    
                    if migrated_count % 100 == 0:
                        print(f"Migrated {migrated_count}/{total_count} embeddings...")
                        
                except Exception as e:
                    print(f"Error migrating message {message_id}: {e}")
                    continue
            
            sync_conn.commit()
            print(f"Migration complete. Migrated {migrated_count}/{total_count} embeddings.")
            return True

async def test_vector_search():
    """Test vector search functionality after migration"""
    print("\nTesting vector search functionality...")
    
    db = MessageDatabase()
    await db.initialize()
    
    if not db.vector_available:
        print("Vector extension not available for testing.")
        return False
    
    # Test with a dummy embedding
    test_embedding = [0.1] * 1536  # OpenAI embedding dimension
    
    try:
        results = await db.get_similar_messages(test_embedding, limit=5)
        print(f"Vector search test successful. Found {len(results)} results.")
        return True
    except Exception as e:
        print(f"Vector search test failed: {e}")
        return False

if __name__ == "__main__":
    async def main():
        print("SQLite-Vec Migration Script")
        print("=" * 40)
        
        # Run migration
        success = await migrate_embeddings()
        
        if success:
            # Test functionality
            test_success = await test_vector_search()
            
            if test_success:
                print("\n✅ Migration completed successfully!")
                print("Vector search is now available and working.")
            else:
                print("\n⚠️ Migration completed but vector search test failed.")
        else:
            print("\n❌ Migration failed.")
    
    asyncio.run(main())
