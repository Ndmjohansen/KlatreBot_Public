import asyncio
from KlatreGPT import KlatreGPT
from ChadLogger import ChadLogger


class GPTTask:
    def __init__(self, discord_context, message_history):
        self.context = discord_context
        self.message_history = message_history
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
        return_value = await KlatreGPT().prompt_gpt(
            task.message_history, task.question)
        if return_value[-1:] == '"' and return_value[:1] == '"':
            return_value = return_value[1:-1]
        if return_value.startswith('KlatreBot:'):
            return_value = return_value[11:]
        task.return_text = return_value

    async def worker(self):
        while True:
            task = await self.task_queue.get()
            is_retrying = False
            try:
                await asyncio.wait_for(self.do_work(task), 30)
            except asyncio.TimeoutError:
                if task.retry_count > 10:
                    task.return_text = f"Det kan jeg desværre ikke hjælpe med [redacted] har sagt det ikke er cool! Jeg har spurgt {task.retry_count} gange!"
                else:
                    is_retrying = True
                    task.retry_count += 1
                    ChadLogger.log(
                        f"Retrying question! Count: {task.retry_count}")
                    await self.task_queue.put(task)
            if not is_retrying:
                await self.result_queue.put(task)
