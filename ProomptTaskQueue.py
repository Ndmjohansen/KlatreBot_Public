import asyncio
from KlatreGPT import KlatreGPT
from ChadLogger import ChadLogger


class GPTTask:
    def __init__(self, discord_context, message_history):
        self.context = discord_context
        self.message_history = message_history
        self.question = self.context.message.content[5:]
        self.result_text = ''


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
        if return_value[1:] == '"' and return_value[:1] == '"':
            return_value = return_value[1:-1]
        if return_value.startswith('KlatreBot:'):
            return_value = return_value[11:0]
        task.return_text = return_value
        return task

    async def worker(self):
        while True:
            task = await self.task_queue.get()
            try:
                result = await asyncio.wait_for(self.do_work(task), 10)
            except asyncio.TimeoutError:
                ChadLogger.log(
                    f"OpenAI timed out on question: {task.question}")
                task.return_text = f"Det kan jeg desværre ikke hjælpe med [redacted] har sagt det ikke er cool!"
                result = task
            ChadLogger.log("Putting response in result queue")
            await self.result_queue.put(result)
