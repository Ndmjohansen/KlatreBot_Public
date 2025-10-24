import openai
import re
import datetime
import os
import logging
import time
from openai import AsyncOpenAI
from ChadLogger import ChadLogger
from RAGQueryService import RAGQueryService
from RAGEmbeddingService import RAGEmbeddingService
from MessageDatabase import MessageDatabase
from MCPToolManager import MCPToolManager
import json
import sys


class KlatreGPT:
    timestamps = []
    client = None
    rag_query_service = None
    embedding_service = None
    message_db = None
    logger = logging.getLogger(__name__)

    def __new__(self):
        if not hasattr(self, 'instance'):
            self.instance = super(KlatreGPT, self).__new__(self)
            self.instance.__initialized = False
        return self.instance

    def __init__(self):
        if (self.__initialized):
            return
        self.__initialized = True

    def set_openai_key(self, key):
        self.client = AsyncOpenAI(api_key=key)
    
    def initialize_rag(self, message_db: MessageDatabase):
        """Initialize RAG services and tool manager"""
        self.message_db = message_db
        self.embedding_service = RAGEmbeddingService(self.client, message_db)
        self.rag_query_service = RAGQueryService(message_db, self.embedding_service)
        # Initialize MCP tool manager with local RAG tools. This can be extended later to call remote MCP tools.
        self.tool_manager = MCPToolManager(self.rag_query_service)

    def load_system_prompt(self):
        """Load system prompt from external file"""
        try:
            prompt_file_path = os.path.join(os.path.dirname(__file__), 'klatrebot_prompt.txt')
            with open(prompt_file_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except FileNotFoundError:
            ChadLogger.log("Warning: klatrebot_prompt.txt not found, using default prompt")
            return """You are a danish-speaking chat bot, with an edgy attitude. 
You answer as if you are a teenage zoomer. 
You are provided some context from the chat and potentially relevant historical messages.
Use the context to give more personalized and relevant answers.
Limit your answers to 250 words or less. 
Do not answer with "Google it yourself"
If you have relevant context about the user, use it to make your response more personal and accurate."""

    def is_rate_limited(self):
        new_stamp = datetime.datetime.now()
        self.timestamps.append(new_stamp)
        for timestamp in self.timestamps:
            timediff = round((new_stamp - timestamp).total_seconds())
            # ChadLogger.log(f"time diff {round((new_stamp - timestamp).total_seconds())}")
            if timediff >= 1800:
                self.timestamps.remove(timestamp)
        if len(self.timestamps) < 30:
            return False
        else:
            return True

    async def prompt_gpt(self, prompt_context, prompt_question, user_id=None, use_rag=True):
        """Orchestrated prompt flow:
        1) Optionally retrieve enhanced context via RAG
        2) Ask planner LLM which tools to call
        3) Execute tools via MCPToolManager
        4) Compose final answer using tool outputs + context
        Falls back to legacy behavior on planner/tool failure.
        """
        if self.is_rate_limited():
            self.logger.warning("Rate limit exceeded - rejecting request")
            return 'Nu slapper du fandme lige lidt af med de spørgsmål'
        
        start_time = time.time()
        self.logger.info(f"Starting orchestrated LLM request for user {user_id}: {prompt_question[:100]}...")
        
        # Step 0: prepare recent context only — let the planner decide RAG calls
        try:
            # Do NOT call RAG here. Provide only the recent chat context (if any)
            # and let the planner LLM choose which RAG tools to invoke (and how liberally).
            enhanced_context = prompt_context or ""
            is_factual_query = False
        except Exception as e:
            self.logger.exception(f"Failed preparing context: {e}")
            enhanced_context = prompt_context or ""
            is_factual_query = False

        # Load system prompt
        system_prompt = self.load_system_prompt()

        # Prepare planner input (tool catalog)
        tool_catalog = []
        if getattr(self, "tool_manager", None):
            try:
                tool_catalog = self.tool_manager.get_tool_catalog()
            except Exception as e:
                self.logger.exception(f"Failed to get tool catalog: {e}")
                tool_catalog = []

        planner_prompt_system = "You are a planner LLM. Given a user question and available tools, return a JSON object describing which tools to call and with which arguments. Respond with valid JSON only."
        planner_user_content = (
            f"Available tools:\n{json.dumps(tool_catalog, indent=2)}\n\n"
            f"Context:\n{enhanced_context}\n\n"
            f"Question:\n{prompt_question}\n\n"
            "Return JSON with the following structure:\n"
            "{\n"
            "  \"tool_plan\": [ {\"name\": \"tool_name\", \"args\": { ... } }, ... ],\n"
            "  \"final_instructions\": \"instructions for final answer (tone / constraints)\",\n"
            "  \"refine\": false\n"
            "}\n"
            "RAG tools (rag_search, find_relevant_context, user_messages, conversation_summary) should be used liberally. For factual/context-heavy queries, prefer exhaustive searches: use broader queries and larger 'limit' values to return many messages so the final answer can be well grounded. Prefer at most 2 tool calls. Only request more than 2 when necessary; if you request >2 include the field \"allow_extra_calls\": true and provide a short \"extra_call_justification\" explaining why additional calls are needed. Planner may request up to 4 calls. Each tool call may request many results (set 'limit' high) to allow comprehensive context retrieval."
        )

        # Call planner
        planner_response_text = None
        planner_json = None
        try:
            # Primary planner call
            planner_resp = await self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": planner_prompt_system},
                    {"role": "user", "content": planner_user_content}
                ],
                temperature=1
            )
            planner_response_text = planner_resp.choices[0].message.content
            self.logger.debug(f"Planner response: {planner_response_text}")
            # Parse JSON from planner (be forgiving)
            try:
                planner_json = json.loads(planner_response_text)
            except Exception:
                # If parsing fails, try one repair/re-prompt to force valid JSON
                try:
                    self.logger.info("Planner returned non-JSON; attempting one re-prompt to repair format")
                    repair_prompt = (
                        "The planner previously returned the following output:\n\n"
                        f"{planner_response_text}\n\n"
                        "It must return valid JSON only, matching the structure described earlier. "
                        "Please output the corrected JSON (no additional text)."
                    )
                    repair_resp = await self.client.chat.completions.create(
                        model="gpt-5-mini",
                        messages=[
                            {"role": "system", "content": planner_prompt_system},
                            {"role": "user", "content": repair_prompt}
                        ],
                        temperature=1
                    )
                    repair_text = repair_resp.choices[0].message.content
                    self.logger.debug(f"Planner repair response: {repair_text}")
                    planner_json = json.loads(repair_text)
                except Exception as e:
                    self.logger.exception(f"Planner repair attempt failed: {e}")
                    planner_json = None
        except Exception as e:
            self.logger.exception(f"Planner LLM failed or returned invalid JSON: {e}")
            planner_json = None

        tool_results = {}
        planner_failed = False

        # If planner produced a plan, validate and execute
        if planner_json and isinstance(planner_json, dict):
            tool_plan = planner_json.get("tool_plan", [])
            final_instructions = planner_json.get("final_instructions", "")
            # Enforce depth / call limit: prefer 2, allow up to 4 when planner justifies
            default_max_calls = 2
            absolute_max_calls = 4
            try:
                requested_calls = len(tool_plan)
                allowed_calls = min(requested_calls, absolute_max_calls)
                # If planner requests more than the default, require explicit allowance and justification
                if requested_calls > default_max_calls:
                    allow_extra = planner_json.get("allow_extra_calls", False)
                    justification = planner_json.get("extra_call_justification", "") or planner_json.get("extra_call_justifications", "")
                    if not allow_extra or not justification:
                        self.logger.warning("Planner requested >2 calls but did not provide allow_extra_calls=true and justification; limiting to 2")
                        allowed_calls = default_max_calls
                    else:
                        self.logger.info(f"Planner requested {requested_calls} calls with justification: {justification}. Allowing up to {allowed_calls} calls.")
                for idx, step in enumerate(tool_plan[:allowed_calls]):
                    tool_name = step.get("name")
                    args = step.get("args", {}) or {}
                    if not tool_name or tool_name not in getattr(self, "tool_manager").tools:
                        self.logger.warning(f"Planner requested unknown tool: {tool_name}")
                        tool_results[tool_name or f"unknown_{idx}"] = {"success": False, "error": "unknown tool"}
                        continue
                    # Execute tool
                    res = await self.tool_manager.call_tool(tool_name, args)
                    tool_results[tool_name] = res
            except Exception as e:
                self.logger.exception(f"Tool execution failed: {e}")
                planner_failed = True
        else:
            planner_failed = True
            final_instructions = ""

        # If planner failed, fallback to legacy single-call flow
        if planner_failed:
            self.logger.info("Planner failed - falling back to legacy single-call LLM behavior")
            try:
                full_prompt = f"CONTEXT:\n{enhanced_context}\n\nQUESTION: {prompt_question}"
                llm_start = time.time()
                response = await self.client.chat.completions.create(
                    model="gpt-5-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": full_prompt}
                    ]
                )
                llm_time = time.time() - llm_start
                total_time = time.time() - start_time
                return_value = response.choices[0].message.content
                self.logger.info(f"Legacy LLM response time: {llm_time:.2f}s, total {total_time:.2f}s")
                return return_value
            except Exception as e:
                total_time = time.time() - start_time
                self.logger.error(f"Legacy LLM request failed after {total_time:.2f}s: {e}")
                return f"Det kan jeg desværre ikke svare på. ({e})"

        # Build final prompt including tool outputs
        tool_outputs_block = json.dumps(tool_results, default=str, indent=2)
        # Emit RAG tool outputs to real stdout for test debugging (bypass pytest capture)
        try:
            sys.__stdout__.write("[RAG TOOL OUTPUTS]\n")
            sys.__stdout__.write(tool_outputs_block + "\n")
        except Exception:
            print("[RAG TOOL OUTPUTS]")
            print(tool_outputs_block)
        final_instructions_block = final_instructions or ""
        # Instruct the final composer to integrate retrieved information naturally (do not expose tool provenance).
        final_prompt = (
            f"CONTEXT:\n{enhanced_context}\n\n"
            f"RETRIEVED_INFO:\n{tool_outputs_block}\n\n"
            f"FINAL INSTRUCTIONS:\n{final_instructions_block}\n\n"
            f"QUESTION: {prompt_question}\n\n"
            "Compose a concise answer (max 250 words). Use the retrieved information as if it were your own memory — do NOT state that the information came from a tool, database, or 'RAG'. "
            "Do not include phrases like '(fra RAG)', 'from RAG', or 'tool outputs'. Integrate facts naturally and avoid exposing retrieval metadata. Keep the bot voice as specified by the system prompt."
        )

        # Call final LLM to compose the answer
        try:
            llm_start = time.time()
            response = await self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": final_prompt}
                ]
            )
            llm_time = time.time() - llm_start
            total_time = time.time() - start_time
            return_value = response.choices[0].message.content
            self.logger.info(f"Final LLM compose time: {llm_time:.2f}s, total {total_time:.2f}s")
            self.logger.debug(f"Final composed response: {return_value}")
            return return_value
        except Exception as e:
            total_time = time.time() - start_time
            self.logger.exception(f"Final LLM compose failed after {total_time:.2f}s: {e}")
            return f"Det kan jeg desværre ikke svare på. ({e})"

    @staticmethod
    async def get_recent_messages(channel_id, message_db=None, client=None):
        """Get recent messages from database if available, otherwise fallback to Discord API"""
        if message_db:
            try:
                # Try to get recent messages from database first
                recent_messages = await message_db.get_recent_messages_from_db(channel_id, limit=10)
                if recent_messages:
                    return recent_messages
            except Exception as e:
                ChadLogger.log(f"Failed to get recent messages from database: {e}")
        
        # Fallback to Discord API (original implementation). Accept an optional client.
        return await KlatreGPT._get_recent_messages_from_discord(channel_id, client)
    
    @staticmethod
    async def _get_recent_messages_from_discord(channel_id, client):
        """Original Discord API implementation as fallback"""
        if client is None:
            ChadLogger.log("Discord client is None - cannot fetch history; returning empty context")
            return ''
        id_pattern = r"<@\d*>"
        messages = ''
        channel = client.get_channel(channel_id)
        async for message in channel.history(limit=10):
            # ChadLogger.log(f"MESSAGE: {message.content}")
            inner_message = ''
            for match in re.findall(id_pattern, message.content):
                # ChadLogger.log(f"Match: {match}")
                username = KlatreGPT.resolve_user_id(
                    match[2:-1], client, channel)
                message.content = re.sub(match, username, message.content)
                # ChadLogger.log(message.content)
            messages = f"\"{message.author.display_name}: {message.content}\"\n" + messages
        # ChadLogger.log('Retrieved history')
        # ChadLogger.log(messages)
        return messages

    @staticmethod
    def get_name(member):
        if not member.nick is None:
            return member.nick
        if not member.global_name is None:
            return member.global_name
        return member.name

    @staticmethod
    def resolve_user_id(user_id, client, channel):
        user = channel.guild.get_member(int(user_id))
        if user is None:  # This happens if you are talking about a discord user that is not on the current server.
            discord_user = client.get_user(int(user_id))
            if discord_user is None:
                # f"Cannot resolve {user_id}"
                return 'Ukendt'
            else:
                return discord_user.display_name
        return KlatreGPT.get_name(user)
