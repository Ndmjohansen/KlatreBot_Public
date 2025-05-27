import openai
import re
import datetime
from openai import AsyncOpenAI
from ChadLogger import ChadLogger


class KlatreGPT:
    timestamps = []
    client = None

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

    async def prompt_gpt(self, prompt_context, prompt_question):
        if self.is_rate_limited():
            return 'Nu slapper du fandme lige lidt af med de spørgsmål'
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a danish-speaking chat bot, with an edgy attitude. "
                                 "You answer as if you are a teenage zoomer. "
                                 "You are provided some context from the chat. "
                                 "Limit your answers to 60 words or less. "
                                 "Do not answer with \"Google it yourself\""
                    },
                    {
                        "role": "user",
                        "content": f"CONTEXT:\n{prompt_context}QUESTION: {prompt_question}"
                    }
                ]
            )
            return_value = response.choices[0].message.content
        except Exception as e:
            return_value = f"Det kan jeg desværre ikke svare på. ({e})"

        return return_value

    @staticmethod
    async def get_recent_messages(channel_id, client):
        id_pattern = r"<@\d*>"
        messages = ''
        channel = client.get_channel(channel_id)
        async for message in channel.history(limit=5):
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
