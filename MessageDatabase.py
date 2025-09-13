import sqlite3
import aiosqlite
import datetime
import asyncio
from typing import Optional, List, Dict, Any
import logging

class MessageDatabase:
    def __init__(self, db_path: str = "klatrebot.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
    
    async def initialize(self):
        """Initialize database and create tables if they don't exist"""
        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for better concurrency
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    discord_user_id INTEGER PRIMARY KEY,
                    display_name TEXT,
                    message_count INTEGER DEFAULT 0,
                    is_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    discord_message_id INTEGER PRIMARY KEY,
                    discord_channel_id INTEGER,
                    discord_user_id INTEGER,
                    content TEXT,
                    message_type TEXT DEFAULT 'text',
                    timestamp TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (discord_user_id) REFERENCES users(discord_user_id)
                )
            """)
            
            # Create indexes for RAG optimization
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
            
            await db.commit()
            
            # Set default admin user
            await self._create_default_admin(db)
            
            self.logger.info("Database initialized successfully")
    
    async def _create_default_admin(self, db):
        """Create default admin user if it doesn't exist"""
        try:
            # Check if default admin already exists
            cursor = await db.execute(
                "SELECT discord_user_id FROM users WHERE discord_user_id = ?", 
                (135463962316636160,)
            )
            admin_exists = await cursor.fetchone()
            
            if not admin_exists:
                # Create default admin user
                await db.execute("""
                    INSERT INTO users (discord_user_id, display_name, is_admin, created_at, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (135463962316636160, "Default Admin", True))
                
                await db.commit()
                self.logger.info("Default admin user created: 135463962316636160")
            else:
                # Ensure existing user is admin
                await db.execute("""
                    UPDATE users 
                    SET is_admin = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE discord_user_id = ?
                """, (135463962316636160,))
                await db.commit()
                self.logger.info("Default admin user confirmed: 135463962316636160")
                
        except Exception as e:
            self.logger.error(f"Error creating default admin: {e}")
    
    async def upsert_user(self, discord_user_id: int, display_name: Optional[str] = None, 
                         is_admin: bool = False) -> bool:
        """Insert or update user, return True if user was created"""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user exists
            cursor = await db.execute(
                "SELECT discord_user_id FROM users WHERE discord_user_id = ?", 
                (discord_user_id,)
            )
            user_exists = await cursor.fetchone()
            
            if user_exists:
                # Update existing user
                await db.execute("""
                    UPDATE users 
                    SET display_name = COALESCE(?, display_name),
                        is_admin = COALESCE(?, is_admin),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE discord_user_id = ?
                """, (display_name, is_admin, discord_user_id))
                await db.commit()
                return False
            else:
                # Insert new user
                await db.execute("""
                    INSERT INTO users (discord_user_id, display_name, is_admin)
                    VALUES (?, ?, ?)
                """, (discord_user_id, display_name, is_admin))
                await db.commit()
                return True
    
    async def log_message(self, discord_message_id: int, discord_channel_id: int, 
                         discord_user_id: int, content: str, message_type: str = 'text',
                         timestamp: Optional[datetime.datetime] = None) -> bool:
        """Log a message to the database"""
        if timestamp is None:
            timestamp = datetime.datetime.now()
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Enable WAL mode for better concurrency
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                await db.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
                
                # Ensure user exists
                await db.execute("""
                    INSERT OR IGNORE INTO users (discord_user_id, display_name, is_admin, created_at, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (discord_user_id, None, False))
                
                # Insert message
                await db.execute("""
                    INSERT OR IGNORE INTO messages 
                    (discord_message_id, discord_channel_id, discord_user_id, content, message_type, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (discord_message_id, discord_channel_id, discord_user_id, content, message_type, timestamp))
                
                # Update user message count
                await db.execute("""
                    UPDATE users 
                    SET message_count = message_count + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE discord_user_id = ?
                """, (discord_user_id,))
                
                await db.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"Error logging message: {e}")
            return False
    
    async def batch_log_messages(self, messages: List[Dict[str, Any]]) -> int:
        """Batch insert messages for migration"""
        success_count = 0
        
        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for better concurrency
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            
            # First, ensure all users exist
            user_ids = set(message['discord_user_id'] for message in messages)
            for user_id in user_ids:
                await db.execute("""
                    INSERT OR IGNORE INTO users (discord_user_id, display_name, is_admin)
                    VALUES (?, ?, ?)
                """, (user_id, None, False))
            
            # Then insert all messages
            for message in messages:
                try:
                    await db.execute("""
                        INSERT OR IGNORE INTO messages 
                        (discord_message_id, discord_channel_id, discord_user_id, content, message_type, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        message['discord_message_id'],
                        message['discord_channel_id'],
                        message['discord_user_id'],
                        message['content'],
                        message.get('message_type', 'text'),
                        message['timestamp']
                    ))
                    
                    success_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Error batch logging message {message.get('discord_message_id', 'unknown')}: {e}")
            
            # Update user message counts in batch
            user_counts = {}
            for message in messages:
                user_id = message['discord_user_id']
                user_counts[user_id] = user_counts.get(user_id, 0) + 1
            
            for user_id, count in user_counts.items():
                await db.execute("""
                    UPDATE users 
                    SET message_count = message_count + ?
                    WHERE discord_user_id = ?
                """, (count, user_id))
            
            await db.commit()
        
        return success_count
    
    async def set_display_name(self, discord_user_id: int, display_name: str) -> bool:
        """Set display name for a user"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Enable WAL mode for better concurrency
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                await db.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
                
                # Check if user exists first
                cursor = await db.execute(
                    "SELECT discord_user_id FROM users WHERE discord_user_id = ?", 
                    (discord_user_id,)
                )
                user_exists = await cursor.fetchone()
                
                if user_exists:
                    # Update existing user
                    await db.execute("""
                        UPDATE users 
                        SET display_name = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE discord_user_id = ?
                    """, (display_name, discord_user_id))
                else:
                    # Create new user
                    await db.execute("""
                        INSERT INTO users (discord_user_id, display_name, is_admin, created_at, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (discord_user_id, display_name, False))
                
                await db.commit()
                return True
                    
        except Exception as e:
            self.logger.error(f"Error setting display name: {e}")
            return False
    
    async def make_admin(self, discord_user_id: int) -> bool:
        """Grant admin access to a user"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Enable WAL mode for better concurrency
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA synchronous=NORMAL")
                await db.execute("PRAGMA busy_timeout=30000")  # 30 second timeout
                
                # Check if user exists first
                cursor = await db.execute(
                    "SELECT discord_user_id FROM users WHERE discord_user_id = ?", 
                    (discord_user_id,)
                )
                user_exists = await cursor.fetchone()
                
                if user_exists:
                    # Update existing user
                    await db.execute("""
                        UPDATE users 
                        SET is_admin = TRUE, updated_at = CURRENT_TIMESTAMP
                        WHERE discord_user_id = ?
                    """, (discord_user_id,))
                else:
                    # Create new user as admin
                    await db.execute("""
                        INSERT INTO users (discord_user_id, display_name, is_admin, created_at, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (discord_user_id, None, True))
                
                await db.commit()
                return True
                    
        except Exception as e:
            self.logger.error(f"Error making user admin: {e}")
            return False
    
    async def is_admin(self, discord_user_id: int) -> bool:
        """Check if user is admin"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT is_admin FROM users WHERE discord_user_id = ?
                """, (discord_user_id,))
                result = await cursor.fetchone()
                return result[0] if result else False
        except Exception as e:
            self.logger.error(f"Error checking admin status: {e}")
            return False
    
    async def get_user_stats(self) -> List[Dict[str, Any]]:
        """Get user statistics"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT discord_user_id, display_name, message_count, is_admin, created_at
                    FROM users 
                    ORDER BY message_count DESC
                """)
                rows = await cursor.fetchall()
                
                return [
                    {
                        'discord_user_id': row[0],
                        'display_name': row[1],
                        'message_count': row[2],
                        'is_admin': bool(row[3]),
                        'created_at': row[4]
                    }
                    for row in rows
                ]
        except Exception as e:
            self.logger.error(f"Error getting user stats: {e}")
            return []
    
    async def get_db_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Get message count
                cursor = await db.execute("SELECT COUNT(*) FROM messages")
                message_count = (await cursor.fetchone())[0]
                
                # Get user count
                cursor = await db.execute("SELECT COUNT(*) FROM users")
                user_count = (await cursor.fetchone())[0]
                
                # Get admin count
                cursor = await db.execute("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
                admin_count = (await cursor.fetchone())[0]
                
                # Get oldest message
                cursor = await db.execute("SELECT MIN(timestamp) FROM messages")
                oldest_message = (await cursor.fetchone())[0]
                
                # Get newest message
                cursor = await db.execute("SELECT MAX(timestamp) FROM messages")
                newest_message = (await cursor.fetchone())[0]
                
                return {
                    'message_count': message_count,
                    'user_count': user_count,
                    'admin_count': admin_count,
                    'oldest_message': oldest_message,
                    'newest_message': newest_message
                }
        except Exception as e:
            self.logger.error(f"Error getting db stats: {e}")
            return {}
    
    async def get_messages_for_rag(self, limit: int = 1000, 
                                  start_date: Optional[datetime.datetime] = None,
                                  end_date: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
        """Get messages formatted for RAG processing"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                query = """
                    SELECT m.content, u.display_name, m.timestamp, m.message_type
                    FROM messages m
                    JOIN users u ON m.discord_user_id = u.discord_user_id
                    WHERE u.display_name IS NOT NULL
                """
                params = []
                
                if start_date:
                    query += " AND m.timestamp >= ?"
                    params.append(start_date)
                
                if end_date:
                    query += " AND m.timestamp <= ?"
                    params.append(end_date)
                
                query += " ORDER BY m.timestamp DESC LIMIT ?"
                params.append(limit)
                
                cursor = await db.execute(query, params)
                rows = await cursor.fetchall()
                
                return [
                    {
                        'content': row[0],
                        'display_name': row[1],
                        'timestamp': row[2],
                        'message_type': row[3]
                    }
                    for row in rows
                ]
        except Exception as e:
            self.logger.error(f"Error getting messages for RAG: {e}")
            return []
