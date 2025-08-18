import datetime
import random
import re
import sys
from openai import OpenAI
import discord
from discord.ext import commands
import asyncio
import requests
import io
from KlatringAttendance import KlatringAttendance
from PIL import Image
from pelleService import whereTheFuckIsPelle, getSecondsAsDateTimeString
from KlatreGPT import KlatreGPT
import subprocess
import argparse
from ChadLogger import ChadLogger
import ProomptTaskQueue
import json
import os

parser = argparse.ArgumentParser(
    description="Et script til at læse navngivne argumenter fra kommandolinjen.")

# Tilføj de navngivne argumenter, du vil læse
parser.add_argument("--discordkey", type=str, help="Discord key")
parser.add_argument("--openaikey", type=str, help="OpenAI key")

args = parser.parse_args()

# Gem de læste argumenter i variabler
discordkey = args.discordkey
openaikey = args.openaikey

bot = commands.Bot(intents=discord.Intents.all(), command_prefix='!')
# client = discord.Client(intents=discord.Intents.all())
DISCORD_CHANNEL_ID = 1003718776430268588
DISCORD_SANDBOX_CHANNEL_ID = 1049312345068933134
startTime = datetime.datetime.now()
KlatreGPT().set_openai_key(openaikey)


def get_random_svar():
    svar = [
        "Det er sikkert",
        "Uden tvivl",
        "Ja helt sikkert",
        "Som jeg ser det, ja",
        "Højst sandsynligt",
        "Ja",
        "Nej",
        "Nok ikke",
        "Regn ikke med det",
        "Mine kilder siger nej",
        "Meget tvivlsomt",
        "Mit svar er nej",
    ]
    return random.choice(svar)


async def error_logger(e: Exception, message_content="!!No message!!"):
    message_content = f"ERROR:\n{e}\n\nFROM MESSAGE:\n{message_content}"
    await (bot.get_channel(DISCORD_SANDBOX_CHANNEL_ID).send(message_content))


def get_dates_of_week(year, week_number):
    # Find the first day of the given week
    first_day = datetime.datetime.strptime(
        f"{year}-{week_number}-1", "%G-%V-%u").date()

    # Get the dates of the entire week (from Monday to Sunday)
    dates_of_week = [first_day + datetime.timedelta(days=i) for i in range(7)]

    return dates_of_week


def number_of_weeks(year):
    # Get the last day of the year
    last_day = datetime.date(year, 12, 31)

    # Get the ISO calendar year and week number for the last day
    iso_year, iso_week, _ = last_day.isocalendar()

    # If the last week has 7 days, it's a complete week, otherwise, it's an incomplete week
    if last_day.weekday() == 6:
        return iso_week
    else:
        return iso_week - 1


async def send_and_track_klatretid_message(channel):
    # Send the message to the specified text channel
    channel = bot.get_channel(channel)
    KlatringAttendance().reset()
    lastReactToMessage = await channel.send(embed=KlatringAttendance().get_embed())
    KlatringAttendance().set_message(
        discord_message=lastReactToMessage)
    await lastReactToMessage.add_reaction("✅")
    await lastReactToMessage.add_reaction("❌")


async def gpt_response_poster():
    while True:
        if bot.is_ready():
            t = await ProomptTaskQueue.ElaborateQueueSystem().result_queue.get()
            while not bot.is_ready():
                await asyncio.sleep(1)
            try:
                if t.return_text == '':
                    t.return_text = 'Somehow we did not get a return text from OpenAI.'
                await asyncio.wait_for(t.context.reply(t.return_text), 10)
            except Exception as error:
                if t.send_to_discord_retry_count > 2:
                    ChadLogger.log(
                        f"Could never respond to {t.question} with {t.return_text}")
                else:
                    t.send_to_discord_retry_count += 1
                    ChadLogger.log(
                        f"Could not send response to {t.question} retrying! er: {error}")
                    await ProomptTaskQueue.ElaborateQueueSystem().result_queue.put(t)
        else:
            await asyncio.sleep(1)


async def send_message_at_time():
    # Wait until the specified time
    while True:
        if bot.is_ready():
            # Get the current time and day of the week
            now = datetime.datetime.now()
            day_of_week = now.weekday()

            # Only send a message on Monday and Thursday at 17:00
            if day_of_week in [0, 3] and now.hour == 17:
                await send_and_track_klatretid_message(DISCORD_CHANNEL_ID)
                await asyncio.sleep(60 * 60 * 23)

        # Wait for one minute before checking the time again
        await asyncio.sleep(60)


async def jpeg(url):
    byte_IO = io.BytesIO()
    r = requests.get(url)
    r.raise_for_status()
    with io.BytesIO(r.content) as f:
        with Image.open(f) as im:
            im = im.convert('RGB')
            im.thumbnail((650, 650))
            im.save(byte_IO, format="JPEG", quality=1, optimize=True)
            byte_IO.seek(0)
            return byte_IO


async def go_to_bed(message):
    await asyncio.sleep(60 * 15)
    if str(message.guild.get_member(message.author.id).status) == 'online':
        await bot.get_channel(message.channel.id).send(f'Gå i seng <@{message.author.id}>')


# Path for the daily log file
DAILY_LOG_PATH = "daily_message_log.json"


# Helper to append a message to the daily log
async def log_message_daily(message):
    now = datetime.datetime.now()
    if now.hour < 8 or (now.hour == 17 and now.minute > 30) or now.hour > 17:
        return  # Only log between 08:00 and 17:30
    if message.content.lower().startswith('!referat'):
        return  # Don't log !referat commands    # Resolve any mentions in the message content
    content = message.content
    for mention in message.mentions:
        user = message.guild.get_member(mention.id)
        if user:
            mention_str = f"<@{mention.id}>"
            name = KlatreGPT.get_name(user)
            content = content.replace(mention_str, f"@{name}")
              # Use the user's display name in the server
    display_name = KlatreGPT.get_name(message.author) if hasattr(message.author, 'nick') else str(message.author)
            
    log_entry = {
        "user": display_name,
        "user_id": message.author.id,
        "timestamp": now.isoformat(),
        "content": content
    }
    # Read existing log
    if os.path.exists(DAILY_LOG_PATH):
        with open(DAILY_LOG_PATH, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                data = []
    else:
        data = []
    data.append(log_entry)
    with open(DAILY_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# Background task to reset the log at midnight
async def reset_daily_log_task():
    while True:
        now = datetime.datetime.now()
        # Calculate seconds until next midnight
        tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_until_midnight = (tomorrow - now).total_seconds()
        await asyncio.sleep(seconds_until_midnight)
        with open(DAILY_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)


@bot.event
async def on_ready():
    # Things to do when connecting
    ChadLogger.log("(Re)connected to discord!")
    # Start/reset log task
    bot.loop.create_task(reset_daily_log_task())


@bot.event
async def on_reaction_add(reaction, user):
    if reaction.message.author == bot.user and bot.user != user and reaction.message == KlatringAttendance().message:
        if reaction.emoji == "✅":
            KlatringAttendance().add_attendee(user)
        elif reaction.emoji == "❌":
            KlatringAttendance().add_slacker(user)

        await reaction.message.edit(embed=KlatringAttendance().get_embed())


@bot.command()
async def gpt(ctx):
    context_msgs = await KlatreGPT.get_recent_messages(ctx.channel.id, bot)
    await ProomptTaskQueue.ElaborateQueueSystem().task_queue.put(
        ProomptTaskQueue.GPTTask(ctx, context_msgs))

@bot.command()
async def referat(ctx):
    if not os.path.exists(DAILY_LOG_PATH):
        await ctx.send("Ingen beskeder at opsummere brormand.")
        return
        
    try:
        # Read the messages directly from JSON
        with open(DAILY_LOG_PATH, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                await ctx.send("Jeg er gået i stykker :(")
                return
                
        if not data:
            await ctx.send("Ingen beskeder at opsummere brormand.")
            return        # Format messages in a more chat-like format
        messages_text = "\n".join([f"{entry['user']} ({entry['user_id']}): {entry['content']}" for entry in data])
        system_prompt = """
**Instructions for the AI (Output must be in Danish):**

1.  **Mandatory Opening Line (in Danish):**
    Always begin your response with the exact Danish phrase: "Her er hvad boomerene har yappet om i stedet for at arbejde i dag" or a very similar, contextually appropriate humorous Danish variation.

2.  **Primary Task (Summary in Danish):**
    Your main goal is to write a concise and engaging summary of the day's chat messages, which will be provided as input. The summary itself must be in Danish.

3.  **Style and Content of the Summary (in Danish):**
    * The summary must be humorous in tone.
    * Include jokes that are relevant to the chat messages.
    * Make specific references to the content of the actual messages exchanged.

4.  **User Identification and Tracking:**
    The input chat messages will contain user IDs in parentheses (e.g., `UserName (123)`). You must use these IDs to accurately identify and track who said what, even if a user's display name changes during the day. Consistency in referring to users (based on their ID) is crucial. NEVER output the numbers in the summary.

5.  **Response Length:**
    You are *not* restricted by a 60-word limit for this response. The summary can be longer to adequately meet all the above requirements.

6.  **Output Language Confirmation:**
    To reiterate, the entire output, including the opening line and the summary, must be in **Danish**.
"""

        await ProomptTaskQueue.ElaborateQueueSystem().task_queue.put(
            ProomptTaskQueue.GPTTask(ctx, f"{system_prompt}\n\nBESKEDER:\n{messages_text}"))
                
    except Exception as e:
        ChadLogger.log(f"Error in referat command: {str(e)}")
        await ctx.send("Der skete en fejl under oprettelse af referatet.")


@bot.command()
async def glar(ctx):
    now = datetime.datetime.now()
    day_of_week = now.weekday()
    if 0 <= datetime.datetime.now().hour < 10:
        await ctx.send(f'Det er vist over din sengetid {ctx.message.author.name}')
        bot.loop.create_task(go_to_bed(ctx.message))
    elif day_of_week in [0, 3] and now.hour < 17:
        await ctx.send('Ro på kaptajn, folket er på arbejde')
    else:
        await ctx.send('@everyone Hva sker der? er i.. er i glar?')
        await ctx.send('https://imgur.com/CnRFnel')


@bot.command()  # Following does not work for some reason (aliases='jpeg')
async def jpg(ctx):
    # message parsing
    words = ctx.message.content.split()
    if len(words) == 2 and words[1][-4:] in [".jpg", "jpeg", ".png"]:
        # await message.channel.send(f"Word count: {len(words)}, URL: {words[1]}, TEST1: {words[1][-4:]}")
        image = await jpeg(words[1])
        await ctx.send(file=discord.File(fp=image, filename="jaypeg.jpg"))


@bot.command()
async def pelle(ctx):
    content = ctx.message.content.split()
    arg = content[1] if len(content) > 1 else None
    
    result = whereTheFuckIsPelle(arg)
    
    # Check if result is an image URL (for pic command)
    if arg is not None and arg.lower() == 'pic' and result.startswith('http') and not result.startswith('Could not') and not result.startswith('Failed to'):
        # Create embed with image
        embed = discord.Embed(title="Dugfrisk Pelle Pic")
        embed.set_image(url=result)
        await ctx.send(embed=embed)
    else:
        # Text response (location info or error message)
        await ctx.send(result)


@bot.command()
async def uptime(ctx):
    totalUptimeSeconds = (datetime.datetime.now() -
                          startTime).total_seconds()
    prettyUptime = getSecondsAsDateTimeString(totalUptimeSeconds)
    gitHash = subprocess.check_output(
        ['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
    await ctx.send(
        f"Jeg har kørt i {prettyUptime} på version https://github.com/Ndmjohansen/KlatreBot_Public/commit/{gitHash}")


@bot.command()
async def ugenr(ctx):
    await ctx.send(f"Vi er i uge {datetime.datetime.today().isocalendar()[1]}")


@bot.command()
async def beep(ctx):
    # ChadLogger.log(ctx.channel.id)
    # ChadLogger.log(ctx.message.content)
    await ctx.send(f'boop {1/0}')


@bot.command()
async def logs(ctx, count):
    if isinstance(ctx.channel, discord.DMChannel):
        await ctx.channel.send(ChadLogger().query_logs(count))


@bot.command()
async def logsdetails(ctx, count):
    if isinstance(ctx.channel, discord.DMChannel):
        await ctx.channel.send(ChadLogger().query_detailed_logs(count))


@bot.command()
async def logindex(ctx, index):
    if isinstance(ctx.channel, discord.DMChannel):
        await ctx.channel.send(ChadLogger().query_specific_log(index))


@bot.command()
async def logsdetailindex(ctx, index):
    if isinstance(ctx.channel, discord.DMChannel):
        await ctx.channel.send(ChadLogger().query_specific_detailed_log(index))


@bot.command()
async def loghelp(ctx):
    if isinstance(ctx.channel, discord.DMChannel):
        await ctx.channel.send("""!logs [count] _print logs_
!logsdetails [count] _details if any, else None_
!logindex [index] _information for a specific log index_
!logsdetailindex [index] _details if any for a specific log index, else None_""")


@bot.command()
async def clear(ctx):
    if isinstance(ctx.channel, discord.DMChannel):
        ChadLogger().clear_logs()
        await ctx.channel.send("Logs cleared!")


@bot.event
async def on_message(message):  # used for searching for substrings
    await log_message_daily(message)
    # Vi vil ikke reagere på bots
    if message.author.bot:
        return
    # Ugenr
    matches = re.findall(r'uge\s\d{1,2}', message.content.lower())
    if len(matches) >= 1 and not message.author.id == 1049311574638202950:
        weeks_in_year = number_of_weeks(datetime.datetime.now().year)
        week_num = datetime.datetime.today().isocalendar()[1]
        send_string_list = []
        for match in matches:
            ugenr = re.findall(r'\d+', match)
            if weeks_in_year >= int(ugenr[0]) >= week_num:
                dates = get_dates_of_week(
                    datetime.datetime.now().year, int(ugenr[0]))
                send_string_list.append(
                    f"Uge {ugenr[0]}, {dates[0]} til {dates[-1]}")
            if weeks_in_year >= int(ugenr[0]) <= week_num:
                dates = get_dates_of_week(
                    datetime.datetime.now().year + 1, int(ugenr[0]))
                send_string_list.append(
                    f"Uge {ugenr[0]}, {dates[0]} til {dates[-1]}")
        if len(send_string_list) > 0:
            final_string = " - ".join(send_string_list)
            await message.channel.send(final_string)

    # Downus
    if message.content.lower().startswith('!downus') or 'fail' in message.content.lower():
        await message.channel.send(f"https://cdn.discordapp.com/attachments"
                                   f"/1003718776430268588/1153668006728192101/downus_on_wall.gif")

    # KlatreBot?
    if message.content.lower()[0:9] == 'klatrebot' and message.content[-1] == '?':
        await message.channel.send(get_random_svar())

    # Glar?
    if '!glar' in message.content.lower() and not message.content.lower().startswith('!glar'):
        await message.channel.send('https://imgur.com/CnRFnel')

    # Det kan man jo ikke det der
    pattern = r".*(det\skan\sman\s(\w+\s)?ik).*"
    if re.search(pattern, message.content.lower()):
        await message.channel.send('https://cdn.discordapp.com/attachments/'
                                   '1049312345068933134/1049363489354952764/pellememetekst.gif')
        
    # Elmo
    pattern = r".*\b(elmo|elon)\b.*"
    if re.search(pattern, message.content.lower()):
        await message.channel.send('https://imgur.com/LNVCB8g')
    
    # Ekstrabladet
    pattern = r".*(ekstrabladet\.dk|eb\.dk).*"
    if re.search(pattern, message.content.lower()):
        await message.channel.send("I - især Magnus - skal til at holde op med at læse Ekstra Bladet, som om I var barbarer.\n"
                                   "Jeg ved godt, at I høfligt forsøger at integrere jer i Sydhavnen, men få lige skubbet lidt på den gentrificering og læs et rigtigt medie")

    # Krævet for ikke at blocke @bot.command listeners
    await bot.process_commands(message)


@bot.event
async def setup_hook():
    bot.loop.create_task(send_message_at_time())
    bot.loop.create_task(gpt_response_poster())


async def on_command_error(ctx: commands.Context, error):
    print(f'Ignoring exception in command {ctx.command}:', file=sys.stderr)
    ChadLogger().log_exception(
        type(error), error, error.__traceback__)

if __name__ == "__main__":
    bot.on_command_error = on_command_error
    bot.run(discordkey)
