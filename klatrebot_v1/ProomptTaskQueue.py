import asyncio
from KlatreGPT import KlatreGPT
from ChadLogger import ChadLogger


class GPTTask:
    def __init__(self, discord_context, message_history, user_id=None):
        self.context = discord_context
        self.message_history = message_history
        self.user_id = user_id
        self.question = self.context.message.content[5:]
        self.result_text = ''
        self.retry_count = 0
        self.send_to_discord_retry_count = 0


class ElaborateQueueSystem:
    def __new__(self):
        if not hasattr(self, 'instance'):
            self.instance = super(ElaborateQueueSystem, self).__new__(self)
            self.instance.__initialized = False
        return self.instance

    def __init__(self):
        if (self.__initialized):
            return
        self.__initialized = True
        self.task_queue = asyncio.Queue()
        self.result_queue = asyncio.Queue()
        self.worker_task = asyncio.create_task(self.worker())

    async def do_work(self, task):
        try:
            return_value = await KlatreGPT().prompt_gpt(
                task.message_history, task.question, task.user_id)
        except Exception as e:
            # Capture unexpected errors from the LLM flow and return a helpful message
            ChadLogger.log(f"Error while running GPT task: {e}")
            task.return_text = f"Det kan jeg desværre ikke svare på. ({e})"
            return

        # Strip surrounding quotes if present
        if return_value[-1:] == '"' and return_value[:1] == '"':
            return_value = return_value[1:-1]
        # Remove legacy prefix
        if return_value.startswith('KlatreBot:'):
            return_value = return_value[11:]
        task.return_text = return_value

    async def worker(self):
        while True:
            task = await self.task_queue.get()
            is_retrying = False
            try:
                # Increase timeout to 60s to accommodate web_search and planner latency
                await asyncio.wait_for(self.do_work(task), 60)
            except asyncio.TimeoutError:
                if task.retry_count > 0:  # Allow only 1 retry (0 -> 1, then fail)
                    task.return_text = f"Det kan jeg desværre ikke hjælpe med [redacted] har sagt det ikke er cool! Jeg har spurgt {task.retry_count + 1} gange!"
                else:
                    is_retrying = True
                    task.retry_count += 1
                    ChadLogger.log(
                        f"Retrying question! Count: {task.retry_count}")
                    await self.task_queue.put(task)
            if not is_retrying:
                await self.result_queue.put(task)
