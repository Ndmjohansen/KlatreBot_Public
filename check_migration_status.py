#!/usr/bin/env python3
"""
Check migration status between SQLite and ChromaDB
"""
import asyncio
import aiosqlite
from MessageDatabase import MessageDatabase

async def check_migration_status():
    """Check what was migrated and what's still in SQLite"""
    print("Migration Status Check")
    print("=" * 40)
    
    # Check ChromaDB
    db = MessageDatabase()
    await db.initialize()
    
    if db.vector_available:
        chroma_stats = await db.chroma_service.get_collection_stats()
        chroma_count = chroma_stats.get('total_embeddings', 0)
        print(f"✅ ChromaDB: {chroma_count} embeddings")
    else:
        print("❌ ChromaDB not available")
        chroma_count = 0
    
    # Check SQLite
    try:
        async with aiosqlite.connect('klatrebot.db') as conn:
            cursor = await conn.execute('SELECT COUNT(*) FROM message_embeddings WHERE embedding IS NOT NULL')
            sqlite_count = (await cursor.fetchone())[0]
            print(f"✅ SQLite: {sqlite_count} embeddings")
            
            # Check if messages have embeddings flag
            cursor = await conn.execute('SELECT COUNT(*) FROM messages WHERE has_embedding = TRUE')
            flagged_count = (await cursor.fetchone())[0]
            print(f"✅ Messages flagged with embeddings: {flagged_count}")
            
    except Exception as e:
        print(f"❌ Error checking SQLite: {e}")
        sqlite_count = 0
        flagged_count = 0
    
    print(f"\nMigration Status:")
    print(f"  ChromaDB: {chroma_count} embeddings")
    print(f"  SQLite: {sqlite_count} embeddings")
    print(f"  Flagged: {flagged_count} messages")
    
    if chroma_count == sqlite_count:
        print("✅ Complete migration - all embeddings in both systems")
    elif chroma_count < sqlite_count:
        print(f"⚠️  Partial migration - {sqlite_count - chroma_count} embeddings not in ChromaDB")
    else:
        print("🤔 ChromaDB has more embeddings than SQLite (unexpected)")

if __name__ == "__main__":
    asyncio.run(check_migration_status())
