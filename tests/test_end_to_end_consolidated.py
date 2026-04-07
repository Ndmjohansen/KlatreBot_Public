import pytest
import os
import tempfile
import shutil
import datetime
from KlatreGPT import KlatreGPT
from MessageDatabase import MessageDatabase
from ChromaVectorService import ChromaVectorService

@pytest.mark.asyncio
async def test_end_to_end_consolidated_flow():
    """
    Consolidated end-to-end test (more verbose):
    - Prepares a small MessageDatabase + Chroma collection
    - Inserts messages and deterministic embeddings
    - Initializes KlatreGPT (with OpenAI key from .env if present)
    - Wraps the LLM client to capture calls and assert the planner was invoked
    - Runs prompt_gpt (the full !gpt flow) and verifies a composed response is returned
    """
    # Load openai key from .env in repo root (optional; test is skipped if not present)
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.abspath(env_path)
    openai_key = None
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("openaikey="):
                    openai_key = line.strip().split("=", 1)[1]
                    break

    if not openai_key:
        pytest.skip("No OpenAI key found in .env; skipping consolidated end-to-end test.")

    tmpdir = tempfile.mkdtemp(prefix="e2e_consolidated_")
    tmpdb = os.path.join(tmpdir, "test_klatrebot.db")
    chroma_dir = os.path.join(tmpdir, "chroma_db")
    print(f"[TEST] Using temporary directory: {tmpdir}")
    try:
        md = MessageDatabase(db_path=tmpdb)
        md.chroma_service = ChromaVectorService(persist_directory=chroma_dir)
        await md.initialize()

        # Insert a user and messages covering different topics (climbing + other)
        await md.upsert_user(1001, "TestUser")
        now = datetime.datetime.now(datetime.timezone.utc)
        msgs = [
            ("Just went bouldering at the gym today, so pumped!", now),
            ("Random unrelated message", now - datetime.timedelta(minutes=5)),
            ("Anyone wants beta for that V3? I tried some crimps and a heel hook.", now - datetime.timedelta(minutes=10)),
        ]
        for i, (text, ts) in enumerate(msgs, start=1):
            await md.log_message(i, 1, 1001, text, timestamp=ts)
            print(f"[TEST] Inserted message {i}: {text!r} (timestamp={ts.isoformat()})")

        # Deterministic embeddings (populates Chroma)
        emb1 = [0.1] * 8
        emb2 = [0.5] * 8
        emb3 = [0.11] * 8
        await md.store_message_embedding(1, emb1)
        await md.store_message_embedding(2, emb2)
        await md.store_message_embedding(3, emb3)
        print("[TEST] Stored deterministic embeddings and populated Chroma")

        kg = KlatreGPT()
        kg.set_openai_key(openai_key)
        kg.initialize_rag(md)

        # Avoid remote embedding calls during tool execution
        async def fake_generate_embedding(text: str):
            txt = text.lower()
            if any(k in txt for k in ("boulder", "bouldering", "v3", "beta", "climb")):
                return [0.1] * 8
            return [0.5] * 8
        kg.embedding_service.generate_embedding = fake_generate_embedding

        # Wrap LLM call to capture invocations and detect planner
        original_create = kg.client.chat.completions.create
        calls = []

        async def create_wrapper(*args, **kwargs):
            model = kwargs.get("model") if "model" in kwargs else (args[0] if len(args) > 0 else None)
            messages = kwargs.get("messages")
            snapshot = {
                "model": model,
                "messages": [{"role": m.get("role"), "content": (m.get("content")[:400] + "...") if isinstance(m.get("content"), str) and len(m.get("content"))>400 else m.get("content")} for m in (messages or [])]
            }
            calls.append(snapshot)
            print(f"[LLM CALL] model={model}; messages_count={len(snapshot['messages'])}")
            # print first 2 messages for context
            for idx, m in enumerate(snapshot["messages"][:2], start=1):
                print(f"  msg{idx} ({m.get('role')}): {repr(m.get('content'))[:200]}")
            return await original_create(*args, **kwargs)

        kg.client.chat.completions.create = create_wrapper

        # Run the orchestrated prompt flow
        question = "Who talked about bouldering recently?"
        print(f"[TEST] Running prompt_gpt with question: {question!r}")
        response = await kg.prompt_gpt("", question, user_id=1001, use_rag=True)

        # Ensure we captured LLM calls and planner was invoked
        print(f"[TEST] Captured {len(calls)} LLM calls")
        models_used = list({c.get("model") for c in calls})
        print(f"[TEST] Models used in calls: {models_used}")
        planner_called = False
        for c in calls:
            for m in c["messages"]:
                if isinstance(m.get("content"), str) and ("You are a planner LLM" in m.get("content") or "planner LLM" in m.get("content")):
                    planner_called = True
                    break
            if planner_called:
                break
        assert planner_called, f"Planner LLM was not called. Captured calls: {calls}"

        # Basic assertions on the final composed response
        print(f"[TEST] Final composed response (truncated): {repr(response)[:500]}")
        assert isinstance(response, str) and len(response.strip()) > 0, "Final response should be a non-empty string"
        assert any(keyword in response.lower() for keyword in ("bouldering", "boulder", "beta", "v3")), f"Response did not reference expected topics: {response}"

    finally:
        try:
            shutil.rmtree(tmpdir)
            print(f"[TEST] Cleaned up temporary directory: {tmpdir}")
        except Exception:
            pass
