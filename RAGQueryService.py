"""
RAG Query Service

This service handles semantic search and context retrieval for the RAG system.
It finds relevant messages and user context to enhance GPT responses.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from MessageDatabase import MessageDatabase
from RAGEmbeddingService import RAGEmbeddingService
from ChadLogger import ChadLogger
import datetime

class RAGQueryService:
    def __init__(self, message_db: MessageDatabase, embedding_service: RAGEmbeddingService):
        self.db = message_db
        self.embedding_service = embedding_service
        self.logger = logging.getLogger(__name__)
        self.similarity_threshold = 0.7  # Minimum similarity score
        self.max_context_messages = 10   # Maximum messages to include in context
        
    async def find_relevant_context(self, query: str, user_id: Optional[int] = None,
                                  limit: int = 10) -> List[Dict[str, Any]]:
        """Find relevant messages for a query using semantic search"""
        try:
            # Generate embedding for the query
            query_embedding = await self.embedding_service.generate_embedding(query)
            if not query_embedding:
                self.logger.error("Failed to generate query embedding")
                return []
            
            # Find similar messages
            similar_messages = await self.db.get_similar_messages(
                query_embedding, 
                limit=limit,
                user_id=user_id
            )
            
            # Filter by similarity threshold
            relevant_messages = [
                msg for msg in similar_messages 
                if msg['similarity'] >= self.similarity_threshold
            ]
            
            self.logger.debug(f"Found {len(relevant_messages)} relevant messages for query")
            return relevant_messages
            
        except Exception as e:
            self.logger.error(f"Error finding relevant context: {e}")
            return []
    
    async def get_user_context(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user personality context"""
        try:
            return await self.db.get_user_personality_context(user_id)
        except Exception as e:
            self.logger.error(f"Error getting user context: {e}")
            return None
    
    async def format_context_for_gpt(self, query: str, user_id: Optional[int] = None,
                                   include_personality: bool = True) -> str:
        """Format context for GPT prompt"""
        try:
            context_parts = []
            
            # Get relevant messages
            relevant_messages = await self.find_relevant_context(query, user_id)
            
            if relevant_messages:
                context_parts.append("RELEVANT CHAT HISTORY:")
                for msg in relevant_messages[:self.max_context_messages]:
                    timestamp = msg['timestamp']
                    if isinstance(timestamp, str):
                        timestamp = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    
                    context_parts.append(
                        f"{msg['display_name']} ({timestamp.strftime('%Y-%m-%d %H:%M')}): {msg['content']}"
                    )
            
            # Get user personality context if requested
            if include_personality and user_id:
                user_context = await self.get_user_context(user_id)
                if user_context:
                    context_parts.append(f"\nUSER PERSONALITY CONTEXT:\n{user_context['personality_text']}")
            
            return "\n".join(context_parts) if context_parts else ""
            
        except Exception as e:
            self.logger.error(f"Error formatting context for GPT: {e}")
            return ""
    
    async def get_enhanced_context(self, query: str, user_id: Optional[int] = None,
                                 recent_messages: Optional[List[str]] = None) -> str:
        """Get enhanced context combining RAG and recent messages"""
        try:
            context_parts = []
            
            # Add recent messages if provided
            if recent_messages:
                context_parts.append("RECENT MESSAGES:")
                context_parts.extend(recent_messages)
            
            # Add RAG context
            rag_context = await self.format_context_for_gpt(query, user_id)
            if rag_context:
                context_parts.append(rag_context)
            
            return "\n\n".join(context_parts) if context_parts else ""
            
        except Exception as e:
            self.logger.error(f"Error getting enhanced context: {e}")
            return ""
    
    async def find_user_specific_context(self, query: str, user_id: int) -> List[Dict[str, Any]]:
        """Find context specifically related to a user"""
        try:
            # Find messages about the user or by the user
            query_embedding = await self.embedding_service.generate_embedding(query)
            if not query_embedding:
                return []
            
            # Search for messages by the user
            user_messages = await self.db.get_similar_messages(
                query_embedding,
                limit=5,
                user_id=user_id
            )
            
            # Search for messages mentioning the user (this would require additional logic)
            # For now, we'll focus on messages by the user
            
            return user_messages
            
        except Exception as e:
            self.logger.error(f"Error finding user-specific context: {e}")
            return []
    
    async def get_conversation_summary(self, user_id: int, days: int = 7) -> str:
        """Get a summary of recent conversation for a user"""
        try:
            start_date = datetime.datetime.now() - datetime.timedelta(days=days)
            
            # Get recent messages
            messages = await self.db.get_messages_for_rag(
                limit=50,
                start_date=start_date
            )
            
            # Filter for user's messages
            user_messages = [msg for msg in messages if msg.get('discord_user_id') == user_id]
            
            if not user_messages:
                return "No recent activity found."
            
            # Create summary
            summary_parts = [f"Recent activity for {user_messages[0].get('display_name', 'User')}:"]
            
            for msg in user_messages[:10]:  # Limit to 10 most recent
                timestamp = msg['timestamp']
                if isinstance(timestamp, str):
                    timestamp = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                
                summary_parts.append(
                    f"- {timestamp.strftime('%m/%d %H:%M')}: {msg['content'][:100]}..."
                )
            
            return "\n".join(summary_parts)
            
        except Exception as e:
            self.logger.error(f"Error getting conversation summary: {e}")
            return "Error retrieving conversation summary."
    
    async def search_by_topic(self, topic: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search for messages by topic using semantic similarity"""
        try:
            query_embedding = await self.embedding_service.generate_embedding(topic)
            if not query_embedding:
                return []
            
            similar_messages = await self.db.get_similar_messages(
                query_embedding,
                limit=limit
            )
            
            return similar_messages
            
        except Exception as e:
            self.logger.error(f"Error searching by topic: {e}")
            return []
    
    async def parse_user_query(self, query: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
        """Parse query to extract target user and time reference using AI"""
        try:
            # First, try to extract @mentions directly from the query
            mention_pattern = r'<@!?(\d+)>'
            mentions = re.findall(mention_pattern, query)
            
            # If we found mentions, try to resolve them directly
            if mentions:
                for mention_id in mentions:
                    # Try to find user by ID
                    user_info = await self.db.get_user_by_id(int(mention_id))
                    if user_info:
                        # Replace mention with the DATABASE display name (not Discord display name)
                        query = query.replace(f'<@{mention_id}>', user_info['display_name'])
                        query = query.replace(f'<@!{mention_id}>', user_info['display_name'])
                    else:
                        # If user not found in database, keep the mention as-is for AI to handle
                        self.logger.warning(f"User ID {mention_id} not found in database, keeping mention as-is")
            
            # Get all users for context with both display names and user IDs
            all_users = await self.db.get_user_stats()
            
            # Create comprehensive user context for AI
            user_mappings = []
            for user in all_users:
                if user['display_name']:
                    user_mappings.append(f"{user['display_name']} (ID: {user['discord_user_id']})")
            
            user_context = f"Available users: {', '.join(user_mappings[:30])}"  # Include more users with IDs
            
            # Use OpenAI to extract user and time information
            extraction_prompt = f"""
            Analyze this query and extract:
            1. The target user name (if any) - must match one of the available users
            2. Time reference in days (if any)
            3. Handle @mentions by converting them to display names
            
            Query: "{query}"
            {user_context}
            
            IMPORTANT: 
            - @mentions have already been converted to database display names if the user exists
            - Use the exact display name from the available users list
            - The display names in the list are from the database, not Discord display names
            - User IDs are provided for reference but use display names in response
            
            Respond in JSON format:
            {{
                "target_user": "exact_display_name_from_available_users_or_null",
                "time_days_ago": number_or_null,
                "is_user_query": true_or_false
            }}
            
            Examples:
            - "What did Troels talk about 5 days ago?" → {{"target_user": "Troels", "time_days_ago": 5, "is_user_query": true}}
            - "What did TroelsTheClimber say yesterday?" → {{"target_user": "TroelsTheClimber", "time_days_ago": 1, "is_user_query": true}}
            - "What did @123456789 discuss last week?" → {{"target_user": "DatabaseDisplayName", "time_days_ago": 7, "is_user_query": true}}
            - "How are you?" → {{"target_user": null, "time_days_ago": null, "is_user_query": false}}
            """
            
            response = await self.embedding_service.client.chat.completions.create(
                model="gpt-5-mini",  # Use cheaper model for parsing
                messages=[
                    {
                        "role": "system",
                        "content": "You are a query parser. Extract user names and time references from queries. Always respond with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": extraction_prompt
                    }
                ],
                temperature=1.0  # Default temperature for gpt-5-mini
            )
            
            # Parse AI response
            import json
            try:
                result = json.loads(response.choices[0].message.content)
                target_user = result.get('target_user')
                time_reference = result.get('time_days_ago')
                is_user_query = result.get('is_user_query', False)
            except json.JSONDecodeError:
                self.logger.error("Failed to parse AI response as JSON")
                return None, None, None
            
            # Look up user by name if found
            target_user_id = None
            if target_user:
                user_info = await self.db.get_user_by_display_name(target_user)
                if user_info:
                    target_user_id = user_info['discord_user_id']
                else:
                    # Try fuzzy search
                    similar_users = await self.db.search_users_by_name(target_user)
                    if similar_users:
                        target_user_id = similar_users[0]['discord_user_id']
                        target_user = similar_users[0]['display_name']
                    else:
                        self.logger.warning(f"User '{target_user}' not found in database")
                        target_user = None
            
            return target_user, target_user_id, time_reference
            
        except Exception as e:
            self.logger.error(f"Error parsing user query with AI: {e}")
            # Fallback to simple regex parsing
            return await self._fallback_parse_user_query(query)
    
    async def _fallback_parse_user_query(self, query: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
        """Fallback regex-based parsing if AI fails"""
        # Common patterns for user-specific queries
        user_patterns = [
            r"what did (\w+) (?:talk about|say|mention)",
            r"(\w+) (?:talked about|said|mentioned)",
            r"(\w+) (?:was talking about|was saying)",
            r"(\w+) (?:discussed|discussing)",
            r"(\w+) (?:mentioned|mentions)",
        ]
        
        # Time patterns
        time_patterns = [
            r"(\d+) days? ago",
            r"(\d+) hours? ago", 
            r"yesterday",
            r"last week",
            r"(\d+) weeks? ago"
        ]
        
        target_user = None
        target_user_id = None
        time_reference = None
        
        # Extract user name
        for pattern in user_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                target_user = match.group(1)
                break
        
        # Extract time reference
        for pattern in time_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                if "yesterday" in match.group(0).lower():
                    time_reference = 1
                elif "last week" in match.group(0).lower():
                    time_reference = 7
                elif "days ago" in match.group(0).lower():
                    time_reference = int(match.group(1))
                elif "hours ago" in match.group(0).lower():
                    time_reference = int(match.group(1)) / 24  # Convert to days
                elif "weeks ago" in match.group(0).lower():
                    time_reference = int(match.group(1)) * 7
                break
        
        # Look up user by name if found
        if target_user:
            user_info = await self.db.get_user_by_display_name(target_user)
            if user_info:
                target_user_id = user_info['discord_user_id']
            else:
                # Try fuzzy search
                similar_users = await self.db.search_users_by_name(target_user)
                if similar_users:
                    target_user_id = similar_users[0]['discord_user_id']
                    target_user = similar_users[0]['display_name']
        
        return target_user, target_user_id, time_reference
    
    async def find_user_specific_messages(self, query: str, target_user_id: int, 
                                        days_back: Optional[int] = None) -> List[Dict[str, Any]]:
        """Find messages by a specific user with optional time filtering"""
        try:
            # Generate embedding for the query
            query_embedding = await self.embedding_service.generate_embedding(query)
            if not query_embedding:
                return []
            
            # Calculate date range if specified
            start_date = None
            if days_back:
                start_date = datetime.datetime.now() - datetime.timedelta(days=days_back)
            
            # Find similar messages by the target user
            similar_messages = await self.db.get_similar_messages(
                query_embedding,
                limit=20,
                user_id=target_user_id,
                start_date=start_date
            )
            
            # Filter by similarity threshold
            relevant_messages = [
                msg for msg in similar_messages 
                if msg['similarity'] >= self.similarity_threshold
            ]
            
            return relevant_messages
            
        except Exception as e:
            self.logger.error(f"Error finding user-specific messages: {e}")
            return []
    
    async def get_enhanced_context_for_user_query(self, query: str, asking_user_id: Optional[int] = None) -> Tuple[str, bool]:
        """Get enhanced context for user-specific queries with neutral response mode"""
        try:
            # Parse the query to extract target user and time info
            target_user, target_user_id, time_reference = await self.parse_user_query(query)
            
            context_parts = []
            is_factual_query = False
            
            if target_user_id:
                is_factual_query = True
                # Find messages by the target user
                messages = await self.find_user_specific_messages(
                    query, 
                    target_user_id, 
                    time_reference
                )
                
                if messages:
                    context_parts.append(f"MESSAGES FROM {target_user.upper()}:")
                    for msg in messages[:self.max_context_messages]:
                        timestamp = msg['timestamp']
                        if isinstance(timestamp, str):
                            timestamp = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        
                        context_parts.append(
                            f"{timestamp.strftime('%Y-%m-%d %H:%M')}: {msg['content']}"
                        )
                else:
                    context_parts.append(f"No relevant messages found from {target_user}")
            else:
                # Fall back to general search
                relevant_messages = await self.find_relevant_context(query, asking_user_id)
                if relevant_messages:
                    context_parts.append("RELEVANT MESSAGES:")
                    for msg in relevant_messages[:self.max_context_messages]:
                        timestamp = msg['timestamp']
                        if isinstance(timestamp, str):
                            timestamp = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        
                        context_parts.append(
                            f"{msg['display_name']} ({timestamp.strftime('%Y-%m-%d %H:%M')}): {msg['content']}"
                        )
            
            return "\n".join(context_parts) if context_parts else "", is_factual_query
            
        except Exception as e:
            self.logger.error(f"Error getting enhanced context for user query: {e}")
            return "", False
    
    async def get_rag_insights(self) -> Dict[str, Any]:
        """Get insights about the RAG system"""
        try:
            stats = await self.db.get_rag_stats()
            
            # Add additional insights
            insights = {
                **stats,
                'similarity_threshold': self.similarity_threshold,
                'max_context_messages': self.max_context_messages,
                'embedding_model': self.embedding_service.embedding_model
            }
            
            return insights
            
        except Exception as e:
            self.logger.error(f"Error getting RAG insights: {e}")
            return {}
