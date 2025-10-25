"""
RAG Embedding Service

This service handles embedding generation and management for the RAG system.
It uses OpenAI's embedding API to generate vector representations of messages and user personalities.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from MessageDatabase import MessageDatabase
from ChadLogger import ChadLogger
import datetime

class RAGEmbeddingService:
    def __init__(self, openai_client: AsyncOpenAI, message_db: MessageDatabase):
        self.client = openai_client
        self.db = message_db
        self.logger = logging.getLogger(__name__)
        self.embedding_model = "text-embedding-3-small"
        self.batch_size = 100
        self.rate_limit_delay = 0.1  # 10 requests per second
        
    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for a single text"""
        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding
        except Exception as e:
            import sys
            error_msg = f"ERROR: OpenAI embedding generation failed: {e}"
            self.logger.error(error_msg)
            # Print to stderr so it doesn't fail silently
            print(error_msg, file=sys.stderr)
            return None
    
    async def generate_message_embeddings(self, limit: int = 100) -> int:
        """Generate embeddings for messages that don't have them yet"""
        messages = await self.db.get_messages_without_embeddings(limit)
        if not messages:
            self.logger.info("No messages need embeddings")
            return 0
        
        success_count = 0
        self.logger.info(f"Generating embeddings for {len(messages)} messages")
        
        for i, message in enumerate(messages):
            try:
                # Skip command messages (starting with !)
                if message['content'].startswith('!'):
                    self.logger.debug(f"Skipping command message {message['discord_message_id']}")
                    continue
                
                # Generate embedding
                embedding = await self.generate_embedding(message['content'])
                if embedding:
                    # Store in database
                    success = await self.db.store_message_embedding(
                        message['discord_message_id'], 
                        embedding, 
                        self.embedding_model
                    )
                    if success:
                        success_count += 1
                        self.logger.debug(f"Generated embedding for message {message['discord_message_id']}")
                    else:
                        self.logger.error(f"Failed to store embedding for message {message['discord_message_id']}")
                else:
                    self.logger.error(f"Failed to generate embedding for message {message['discord_message_id']}")
                
                # Rate limiting
                if (i + 1) % 10 == 0:
                    await asyncio.sleep(self.rate_limit_delay)
                    self.logger.info(f"Processed {i + 1}/{len(messages)} messages")
                    
            except Exception as e:
                self.logger.error(f"Error processing message {message['discord_message_id']}: {e}")
                continue
        
        self.logger.info(f"Generated {success_count}/{len(messages)} embeddings")
        return success_count
    
    
    
    
    
    async def get_embedding_stats(self) -> Dict[str, Any]:
        """Get embedding generation statistics"""
        return await self.db.get_rag_stats()
    
    async def cleanup_old_embeddings(self, days_old: int = 30) -> int:
        """Remove embeddings for messages older than specified days"""
        try:
            cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days_old)
            
            async with self.db.db_path as db:
                # Get old message IDs
                cursor = await db.execute("""
                    SELECT discord_message_id FROM messages 
                    WHERE timestamp < ? AND has_embedding = TRUE
                """, (cutoff_date,))
                
                old_message_ids = [row[0] for row in await cursor.fetchall()]
                
                if not old_message_ids:
                    return 0
                
                # Remove embeddings
                await db.execute("""
                    DELETE FROM message_embeddings 
                    WHERE discord_message_id IN ({})
                """.format(','.join('?' * len(old_message_ids))), old_message_ids)
                
                # Mark messages as not having embeddings
                await db.execute("""
                    UPDATE messages 
                    SET has_embedding = FALSE 
                    WHERE discord_message_id IN ({})
                """.format(','.join('?' * len(old_message_ids))), old_message_ids)
                
                await db.commit()
                
                self.logger.info(f"Cleaned up {len(old_message_ids)} old embeddings")
                return len(old_message_ids)
                
        except Exception as e:
            self.logger.error(f"Error cleaning up old embeddings: {e}")
            return 0
