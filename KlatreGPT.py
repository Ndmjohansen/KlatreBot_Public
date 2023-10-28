import openai
import re
import datetime


class KlatreGPT:
    timestamps = []

    def __init__(self, key):
        openai.api_key = key

    def is_rate_limited(self):
        new_stamp = datetime.datetime.now()
        self.timestamps.append(new_stamp)
        for timestamp in self.timestamps:
            timediff = round((new_stamp - timestamp).total_seconds())
            # print(f"time diff {round((new_stamp - timestamp).total_seconds())}")
            if timediff >= 1800:
                self.timestamps.remove(timestamp)
        if len(self.timestamps) < 30:
            return False
        else:
            return True

    def prompt_gpt(self, prompt_context, prompt_question):
        if self.is_rate_limited(): return 'Nu slapper du fandme lige lidt af med de spørgsmål'

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system",
                 "content": "You are a mean-spirited and rude danish-speaking chat bot, with a negative attitude."
                            "Your answers must always arrive at a confident conclusion, "
                            "even if you must make assumptions or guesses."
                            "Your answers boil down to yes 50% of the time, and no 50% of the time."
                            "You are provided some context from the chat."
                 },
                {"role": "user",
                 "content": f"CONTEXT:\n{prompt_context}QUESTION: {prompt_question}"
                 }
            ]
        )
        print(f"Prompt to OpenAI: CONTEXT: {prompt_context} \nQUESTION: {prompt_question}\n")
        returnval = response['choices'][0]['message']['content']
        print(f"Result from OpenAI: {returnval}")
        return returnval

    async def get_recent_messages(self, channel_id, client):
        id_pattern = r"<@\d*>"
        messages = ''
        async for message in client.get_channel(channel_id).history(limit=5):
            # print(f"MESSAGE: {message.content}")
            inner_message = ''
            for match in re.findall(id_pattern, message.content):
                # print(f"Match: {match}")
                message.content = re.sub(match, await self.resolve_user_id(match[2:-1], client), message.content)
                print(message.content)
            messages = f"\"{message.author.display_name}: {message.content}\"\n" + messages
        # print('Retrieved history')
        # print(messages)
        return messages

    async def resolve_user_id(self, user_id, client):
        user = await client.fetch_user(user_id)
        return user.display_name
