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

    @staticmethod
    def get_name(member):
        if not member.nick is None:
            return member.nick
        if not member.global_name is None:
            return member.global_name
        return member.name

    async def resolve_user_id(self, user_id, client, message):
        user = await message.guild.get_member(user_id)
        if user is None:  # This happens if you are talking about a discord user that is not on the current server.
            user = await client.get_user(user_id)
            return user.display_name
        return self.get_name(user)
