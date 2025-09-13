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
            self.logger.error(f"Error generating embedding: {e}")
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
    
    async def generate_user_personality_embedding(self, discord_user_id: int, 
                                                personality_text: str) -> bool:
        """Generate and store personality embedding for a user"""
        try:
            # Generate embedding
            embedding = await self.generate_embedding(personality_text)
            if not embedding:
                self.logger.error(f"Failed to generate personality embedding for user {discord_user_id}")
                return False
            
            # Store in database
            success = await self.db.store_user_personality_embedding(
                discord_user_id, 
                personality_text, 
                embedding, 
                self.embedding_model
            )
            
            if success:
                self.logger.info(f"Generated personality embedding for user {discord_user_id}")
            else:
                self.logger.error(f"Failed to store personality embedding for user {discord_user_id}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error generating personality embedding for user {discord_user_id}: {e}")
            return False
    
    async def generate_user_personality_from_messages(self, discord_user_id: int, 
                                                    message_limit: int = 50) -> bool:
        """Generate personality embedding from user's recent messages"""
        try:
            # Get user's recent messages
            messages = await self.db.get_messages_for_rag(
                limit=message_limit,
                start_date=datetime.datetime.now() - datetime.timedelta(days=30)
            )
            
            # Filter messages by user
            user_messages = [msg for msg in messages if msg.get('discord_user_id') == discord_user_id]
            
            if not user_messages:
                self.logger.warning(f"No messages found for user {discord_user_id}")
                return False
            
            # Create personality text from messages
            personality_text = self._create_personality_text(user_messages)
            
            # Generate and store embedding
            return await self.generate_user_personality_embedding(discord_user_id, personality_text)
            
        except Exception as e:
            self.logger.error(f"Error generating personality from messages for user {discord_user_id}: {e}")
            return False
    
    def _create_personality_text(self, messages: List[Dict[str, Any]]) -> str:
        """Create personality text from user messages"""
        # Extract content and create a personality summary
        contents = [msg['content'] for msg in messages if msg.get('content')]
        
        # Create a personality prompt
        personality_prompt = f"""
        Based on these messages from a Discord user, create a personality profile:
        
        Messages:
        {chr(10).join(contents[:20])}  # Limit to first 20 messages
        
        Create a concise personality description focusing on:
        - Communication style
        - Interests and topics they discuss
        - Tone and attitude
        - Common phrases or expressions
        - Personality traits
        """
        
        return personality_prompt.strip()
    
    async def batch_generate_personalities(self, user_ids: List[int]) -> int:
        """Generate personality embeddings for multiple users"""
        success_count = 0
        
        for user_id in user_ids:
            try:
                success = await self.generate_user_personality_from_messages(user_id)
                if success:
                    success_count += 1
                
                # Rate limiting
                await asyncio.sleep(self.rate_limit_delay)
                
            except Exception as e:
                self.logger.error(f"Error generating personality for user {user_id}: {e}")
                continue
        
        self.logger.info(f"Generated {success_count}/{len(user_ids)} personality embeddings")
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
