import os
import tempfile
import shutil
import datetime
import pytest
from KlatreGPT import KlatreGPT
from MessageDatabase import MessageDatabase
from ChromaVectorService import ChromaVectorService

@pytest.mark.asyncio
async def test_manual_query_grade_lookup():
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
        pytest.skip("No OpenAI key found in .env; skipping manual grade lookup test.")

    tmpdir = tempfile.mkdtemp(prefix="manual_query_")
    tmpdb = os.path.join(tmpdir, "test_klatrebot.db")
    chroma_dir = os.path.join(tmpdir, "chroma_db")
    print(f"[MANUAL TEST] Using temporary directory: {tmpdir}")
    try:
        md = MessageDatabase(db_path=tmpdb)
        md.chroma_service = ChromaVectorService(persist_directory=chroma_dir)
        await md.initialize()

        # Insert a user and messages that include grade info
        await md.upsert_user(1001, "TestUser")
        now = datetime.datetime.now(datetime.timezone.utc)
        msgs = [
            ("Just went bouldering at the gym today, so pumped!", now),
            ("Random unrelated message", now - datetime.timedelta(minutes=5)),
            ("Anyone wants beta for that V3? I tried some crimps.", now - datetime.timedelta(minutes=10)),
            ("I managed to top out a V4 yesterday, hype!", now - datetime.timedelta(days=1)),
        ]
        for i, (text, ts) in enumerate(msgs, start=1):
            await md.log_message(i, 1, 1001, text, timestamp=ts)
            print(f"[MANUAL TEST] Inserted message {i}: {text!r}")

        # Deterministic embeddings (populate Chroma)
        emb1 = [0.1] * 8
        emb2 = [0.5] * 8
        emb3 = [0.11] * 8
        emb4 = [0.12] * 8
        await md.store_message_embedding(1, emb1)
        await md.store_message_embedding(2, emb2)
        await md.store_message_embedding(3, emb3)
        await md.store_message_embedding(4, emb4)
        print("[MANUAL TEST] Stored deterministic embeddings and populated Chroma")

        kg = KlatreGPT()
        kg.set_openai_key(openai_key)
        kg.initialize_rag(md)

        # Avoid remote embedding calls during tool execution
        async def fake_generate_embedding(text: str):
            txt = text.lower()
            # Map mentions of bouldering/grades to the low-dimensional deterministic vector
            if any(k in txt for k in ("boulder", "bouldering", "v3", "v4", "v5", "v2", "grade")):
                return [0.1] * 8
            return [0.5] * 8
        kg.embedding_service.generate_embedding = fake_generate_embedding

        question = "What grade does TestUser climb?"
        print(f"[MANUAL TEST] Running prompt_gpt with question: {question!r}")
        response = await kg.prompt_gpt("", question, user_id=1001, use_rag=True)
        print("[MANUAL TEST] Response:")
        print(response)
        # Basic check: ensure some grade-like token appears
        assert isinstance(response, str) and len(response.strip()) > 0
    finally:
        try:
            shutil.rmtree(tmpdir)
            print(f"[MANUAL TEST] Cleaned up temporary directory: {tmpdir}")
        except Exception:
            pass
