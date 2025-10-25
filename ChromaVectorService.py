"""
ChromaDB Vector Service

This service handles vector storage and similarity search using ChromaDB.
It provides a clean interface for storing and querying message embeddings.
"""

import chromadb
import logging
from typing import List, Dict, Any, Optional
import datetime
import os

class ChromaVectorService:
    def __init__(self, persist_directory: str = "./chroma_db"):
        self.persist_directory = persist_directory
        self.logger = logging.getLogger(__name__)
        self.client = None
        self.collection = None
        self.initialized = False
        
    async def initialize(self):
        """Initialize ChromaDB client and collection"""
        try:
            # Create persist directory if it doesn't exist
            os.makedirs(self.persist_directory, exist_ok=True)
            
            # Initialize ChromaDB client
            self.client = chromadb.PersistentClient(path=self.persist_directory)
            
            # Get or create collection for message embeddings
            self.collection = self.client.get_or_create_collection(
                name="message_embeddings",
                metadata={"description": "Discord message embeddings for RAG"}
            )
            
            self.initialized = True
            self.logger.info("ChromaDB initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize ChromaDB: {e}")
            self.initialized = False
    
    async def store_embedding(self, message_id: int, embedding: List[float], 
                            content: str, display_name: str, timestamp: datetime.datetime,
                            message_type: str = 'text', discord_user_id: int = None) -> bool:
        """Store a message embedding in ChromaDB"""
        if not self.initialized:
            await self.initialize()
            if not self.initialized:
                return False
        
        try:
            # Convert message_id to string for ChromaDB
            doc_id = str(message_id)
            
            # Prepare metadata
            metadata = {
                "discord_message_id": message_id,
                "discord_user_id": discord_user_id,
                "display_name": display_name,
                # Store numeric epoch seconds for timestamp so ChromaDB numeric comparisons work
                "timestamp": timestamp.timestamp(),
                "message_type": message_type,
                "content": content[:1000]  # Truncate content for metadata
            }
            
            # Store in ChromaDB
            self.collection.add(
                ids=[doc_id],
                embeddings=[embedding],
                metadatas=[metadata],
                documents=[content]
            )
            
            self.logger.debug(f"Stored embedding for message {message_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error storing embedding for message {message_id}: {e}")
            return False
    
    async def search_similar(self, query_embedding: List[float], limit: int = 10,
                           user_id: Optional[int] = None,
                           start_date: Optional[datetime.datetime] = None,
                           end_date: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
        """Search for similar messages using ChromaDB"""
        if not self.initialized:
            await self.initialize()
            if not self.initialized:
                return []
        
        try:
            # Defensive type casting for parameters (handles potential str from LLM args)
            limit = int(limit) if limit is not None else 10
            user_id = int(user_id) if user_id is not None else None
            
            # Ensure dates are datetime objects (they should already be from the database)
            if start_date and not isinstance(start_date, datetime.datetime):
                raise TypeError(f"start_date must be a datetime object, got {type(start_date)}")
            if end_date and not isinstance(end_date, datetime.datetime):
                raise TypeError(f"end_date must be a datetime object, got {type(end_date)}")

            # Build where clause for filtering
            where_clause = {}
            conditions = []
            
            if user_id:
                conditions.append({"discord_user_id": user_id})
            
            if start_date:
                # Use numeric epoch seconds for comparisons
                conditions.append({"timestamp": {"$gte": start_date.timestamp()}})
            
            if end_date:
                # Use numeric epoch seconds for comparisons
                conditions.append({"timestamp": {"$lte": end_date.timestamp()}})
            
            # Combine conditions with $and if multiple conditions exist
            if len(conditions) == 1:
                where_clause = conditions[0]
            elif len(conditions) > 1:
                where_clause = {"$and": conditions}
            
            # Perform similarity search
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_clause if where_clause else None
            )
            
            # Convert results to expected format
            similar_messages = []
            if results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    metadata = results['metadatas'][0][i]
                    distance = results['distances'][0][i]
                    
                    # Use Euclidean distance directly
                    # Lower distance = more similar
                    # We'll use distance as the similarity score (inverted: lower is better)
                    # This provides much better separation between relevant and irrelevant results
                    similarity = distance
                    
                    # Convert numeric epoch timestamp to datetime
                    timestamp_value = metadata['timestamp']
                    timestamp = datetime.datetime.fromtimestamp(timestamp_value)
                    
                    similar_messages.append({
                        'discord_message_id': metadata['discord_message_id'],
                        'content': results['documents'][0][i],
                        'display_name': metadata['display_name'],
                        'timestamp': timestamp,
                        'message_type': metadata['message_type'],
                        'similarity': similarity
                    })
            
            return similar_messages
            
        except Exception as e:
            self.logger.error(f"Error searching similar messages: {e}")
            return []
    
    async def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the ChromaDB collection"""
        if not self.initialized:
            await self.initialize()
            if not self.initialized:
                return {}
        
        try:
            count = self.collection.count()
            return {
                "total_embeddings": count,
                "collection_name": self.collection.name,
                "persist_directory": self.persist_directory
            }
        except Exception as e:
            self.logger.error(f"Error getting collection stats: {e}")
            return {}
    
    async def delete_embedding(self, message_id: int) -> bool:
        """Delete an embedding from ChromaDB"""
        if not self.initialized:
            await self.initialize()
            if not self.initialized:
                return False
        
        try:
            doc_id = str(message_id)
            self.collection.delete(ids=[doc_id])
            self.logger.debug(f"Deleted embedding for message {message_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting embedding for message {message_id}: {e}")
            return False
    
    async def migrate_from_sqlite(self, message_db) -> int:
        """Migrate existing embeddings from SQLite to ChromaDB"""
        if not self.initialized:
            await self.initialize()
            if not self.initialized:
                return 0
        
        try:
            # Get all existing embeddings from SQLite
            import aiosqlite
            async with aiosqlite.connect(message_db.db_path) as db:
                cursor = await db.execute("""
                    SELECT me.discord_message_id, me.embedding, m.content, u.display_name, 
                           m.timestamp, m.message_type, m.discord_user_id
                    FROM message_embeddings me
                    JOIN messages m ON me.discord_message_id = m.discord_message_id
                    JOIN users u ON m.discord_user_id = u.discord_user_id
                    WHERE m.has_embedding = TRUE
                """)
                
                rows = await cursor.fetchall()
                migrated_count = 0
                
                for message_id, embedding_blob, content, display_name, timestamp, message_type, discord_user_id in rows:
                    try:
                        import pickle
                        embedding = pickle.loads(embedding_blob)
                        
                        # Store in ChromaDB (timestamp is already datetime object from database)
                        success = await self.store_embedding(
                            message_id, embedding, content, display_name, timestamp, message_type, discord_user_id
                        )
                        
                        if success:
                            migrated_count += 1
                        
                        if migrated_count % 100 == 0:
                            self.logger.info(f"Migrated {migrated_count} embeddings...")
                            
                    except Exception as e:
                        self.logger.error(f"Error migrating message {message_id}: {e}")
                        continue
                
                self.logger.info(f"Migration complete. Migrated {migrated_count} embeddings to ChromaDB.")
                return migrated_count
                
        except Exception as e:
            self.logger.error(f"Error during migration: {e}")
            return 0
