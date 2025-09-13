#!/usr/bin/env python3
"""
Database Schema Migration Script

This script migrates the existing database to add the missing has_embedding column
and other RAG-related schema changes.
"""

import asyncio
import aiosqlite
import logging
from MessageDatabase import MessageDatabase

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def migrate_database(db_path: str = "klatrebot.db"):
    """Migrate the database to add missing RAG columns"""
    try:
        async with aiosqlite.connect(db_path) as db:
            logger.info("Starting database migration...")
            
            # Check if has_embedding column exists
            cursor = await db.execute("PRAGMA table_info(messages)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            
            if 'has_embedding' not in column_names:
                logger.info("Adding has_embedding column to messages table...")
                await db.execute("ALTER TABLE messages ADD COLUMN has_embedding BOOLEAN DEFAULT FALSE")
                logger.info("✅ Added has_embedding column")
            else:
                logger.info("✅ has_embedding column already exists")
            
            # Check if message_embeddings table exists
            cursor = await db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='message_embeddings'
            """)
            if not await cursor.fetchone():
                logger.info("Creating message_embeddings table...")
                await db.execute("""
                    CREATE TABLE message_embeddings (
                        discord_message_id INTEGER PRIMARY KEY,
                        embedding BLOB,
                        embedding_model TEXT DEFAULT 'text-embedding-3-small',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (discord_message_id) REFERENCES messages(discord_message_id)
                    )
                """)
                logger.info("✅ Created message_embeddings table")
            else:
                logger.info("✅ message_embeddings table already exists")
            
            # Check if user_personality_embeddings table exists
            cursor = await db.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='user_personality_embeddings'
            """)
            if not await cursor.fetchone():
                logger.info("Creating user_personality_embeddings table...")
                await db.execute("""
                    CREATE TABLE user_personality_embeddings (
                        discord_user_id INTEGER PRIMARY KEY,
                        personality_embedding BLOB,
                        personality_text TEXT,
                        embedding_model TEXT DEFAULT 'text-embedding-3-small',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (discord_user_id) REFERENCES users(discord_user_id)
                    )
                """)
                logger.info("✅ Created user_personality_embeddings table")
            else:
                logger.info("✅ user_personality_embeddings table already exists")
            
            # Create indexes for RAG optimization
            logger.info("Creating RAG indexes...")
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_timestamp 
                ON messages(timestamp)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user_timestamp 
                ON messages(discord_user_id, timestamp)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_content 
                ON messages(content)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_embeddings_model 
                ON message_embeddings(embedding_model)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_personality_embeddings_model 
                ON user_personality_embeddings(embedding_model)
            """)
            logger.info("✅ Created RAG indexes")
            
            await db.commit()
            logger.info("🎉 Database migration completed successfully!")
            
            # Show current schema
            logger.info("\n=== Current Database Schema ===")
            cursor = await db.execute("PRAGMA table_info(messages)")
            columns = await cursor.fetchall()
            logger.info("Messages table columns:")
            for col in columns:
                logger.info(f"  - {col[1]} ({col[2]})")
            
            # Show table counts
            cursor = await db.execute("SELECT COUNT(*) FROM messages")
            message_count = (await cursor.fetchone())[0]
            logger.info(f"\nMessages in database: {message_count}")
            
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            user_count = (await cursor.fetchone())[0]
            logger.info(f"Users in database: {user_count}")
            
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

async def main():
    """Main migration function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate database schema for RAG system")
    parser.add_argument("--db-path", default="klatrebot.db", help="SQLite database path")
    
    args = parser.parse_args()
    
    logger.info(f"Migrating database: {args.db_path}")
    await migrate_database(args.db_path)

if __name__ == "__main__":
    asyncio.run(main())
