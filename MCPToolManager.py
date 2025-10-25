"""
MCPToolManager

Simple local tool registry and executor to allow the LLM planner to pick and run tools.
Designed to be extensible: tools are registered with a name, description, input schema and an async callable.

Later this manager can be extended to call remote MCP servers (use_mcp_tool).
"""
import asyncio
import time
import json
import logging
from typing import Callable, Any, Dict, Optional, List

logger = logging.getLogger(__name__)

class MCPToolManager:
    def __init__(self, rag_query_service=None):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.rag = rag_query_service
        # Register default RAG tools if a rag_query_service is provided
        if self.rag:
            self._register_default_rag_tools()

    def register_tool(self, name: str, func: Callable, description: str = "", schema: Optional[Dict[str, Any]] = None):
        """Register a tool callable. func may be async or sync. Schema is a simple hint dict."""
        self.tools[name] = {
            "func": func,
            "description": description,
            "schema": schema or {}
        }
        logger.debug(f"Registered tool: {name}")

    def get_tool_catalog(self) -> List[Dict[str, Any]]:
        """Return a machine readable catalog for planner prompts."""
        catalog = []
        for name, meta in self.tools.items():
            catalog.append({
                "name": name,
                "description": meta.get("description", ""),
                "schema": meta.get("schema", {})
            })
        return catalog

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a registered tool and return a standardized result dict."""
        if name not in self.tools:
            return {"success": False, "error": f"Tool '{name}' not found."}
        func = self.tools[name]["func"]
        start = time.time()
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(**(args or {}))
            else:
                # run sync function in threadpool
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: func(**(args or {})))
            duration = time.time() - start
            logger.info(f"Tool '{name}' executed in {duration:.2f}s")
            return {"success": True, "tool": name, "duration": duration, "output": result}
        except Exception as e:
            duration = time.time() - start
            logger.exception(f"Tool '{name}' failed after {duration:.2f}s: {e}")
            return {"success": False, "tool": name, "duration": duration, "error": str(e)}

    def _register_default_rag_tools(self):
        """Register a small set of local RAG-related tools based on the provided rag_query_service.
        This implementation consolidates similar retrieval functionality into a single, flexible
        `search_messages` tool while keeping backward-compatible aliases for ease of use.
        """

        async def search_messages(query: str = None,
                                  topic: str = None,
                                  user_id: Optional[int] = None,
                                  target_user_id: Optional[int] = None,
                                  limit: int = 10,
                                  days_back: Optional[int] = None):
            """Unified search tool supporting multiple common use cases.

            Behavior:
            - If `topic` is provided, perform a topic-based semantic search.
            - If `target_user_id` is provided, perform a user-specific search (optionally filtered by `query` or `days_back`).
            - Otherwise, if `query` is provided, perform a general relevance-based context search.
            - Returns a consistent dict with `query` and `results`.
            - Maximum limit enforced at 10 to prevent context overload.
            """
            # Safe type casting for int params (handles LLM str outputs like "20")
            # Enforce maximum limit of 10 to prevent context overload
            limit = min(int(limit) if limit is not None else 10, 10)
            user_id = int(user_id) if user_id is not None else None
            target_user_id = int(target_user_id) if target_user_id is not None else None
            days_back = int(days_back) if days_back is not None else None

            # Topic search wins if provided
            if topic is not None:
                results = await self.rag.search_by_topic(topic, limit=limit)
                return {"query": topic, "results": results}

            # User-specific search
            if target_user_id is not None:
                results = await self.rag.find_user_specific_messages(query or "", target_user_id, days_back=days_back)
                return {"query": query or "", "target_user_id": target_user_id, "results": results}

            # General relevance search
            if query is not None:
                results = await self.rag.find_relevant_context(query, user_id=user_id, limit=limit)
                return {"query": query, "results": results}

            # Fallback: return empty results
            return {"query": query or topic or "", "results": []}

        # Backwards-compatible wrappers that call the unified search_messages tool
        async def rag_search(topic: str, limit: int = 10):
            """Alias for topic-based semantic search. Preserve legacy output field 'topic'. Max 10 results."""
            # Safe casting and enforce max limit
            limit = min(int(limit) if limit is not None else 10, 10)
            res = await search_messages(topic=topic, limit=limit)
            # search_messages returns {"query": topic, "results": [...]}; keep legacy key "topic"
            return {"topic": res.get("query"), "results": res.get("results")}

        async def find_relevant_context(query: str, user_id: Optional[int] = None, limit: int = 10):
            """Alias for a general relevance-based search. Max 10 results."""
            # Safe casting and enforce max limit
            limit = min(int(limit) if limit is not None else 10, 10)
            user_id = int(user_id) if user_id is not None else None
            return await search_messages(query=query, user_id=user_id, limit=limit)

        async def user_messages(query: str, target_user_id: int, days_back: Optional[int] = None):
            """Alias for a user-specific search."""
            # Safe casting
            target_user_id = int(target_user_id)
            days_back = int(days_back) if days_back is not None else None
            return await search_messages(query=query, target_user_id=target_user_id, days_back=days_back)

        async def conversation_summary(user_id: int, days: int = 7):
            """Get a textual conversation summary for a user."""
            # Safe casting
            user_id = int(user_id)
            days = int(days)
            summary = await self.rag.get_conversation_summary(user_id, days=days)
            return {"user_id": user_id, "days": days, "summary": summary}

        # Register the unified tool first (recommended for planners that understand it)
        self.register_tool(
            "search_messages",
            search_messages,
            description="Unified message search. Supports {query?, topic?, user_id?, target_user_id?, limit?, days_back?}",
            schema={"query": "str|null", "topic": "str|null", "user_id": "int|null", "target_user_id": "int|null", "limit": "int", "days_back": "int|null"}
        )

        # Register compatibility aliases so existing planners/tests keep working
        self.register_tool(
            "rag_search",
            rag_search,
            description="(alias) Semantic search for a topic. Args: {topic: str, limit: int}",
            schema={"topic": "str", "limit": "int"}
        )
        self.register_tool(
            "find_relevant_context",
            find_relevant_context,
            description="(alias) Find relevant messages for a query. Args: {query: str, user_id: int|null, limit: int}",
            schema={"query": "str", "user_id": "int|null", "limit": "int"}
        )
        self.register_tool(
            "user_messages",
            user_messages,
            description="(alias) Find messages by a specific user. Args: {query: str, target_user_id: int, days_back: int|null}",
            schema={"query": "str", "target_user_id": "int", "days_back": "int|null"}
        )
        self.register_tool(
            "conversation_summary",
            conversation_summary,
            description="Get a summary of recent conversation for a user. Args: {user_id: int, days: int}",
            schema={"user_id": "int", "days": "int"}
        )
