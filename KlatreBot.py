import datetime
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
import discord
from discord.ext import commands
import asyncio
import requests
import io
from KlatringAttendance import KlatringAttendance
from PIL import Image
from pelleService import whereTheFuckIsPelle
from KlatreGPT import KlatreGPT
import subprocess
import argparse
from ChadLogger import ChadLogger


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
KGPT = KlatreGPT(openaikey)
executor = ThreadPoolExecutor(max_workers=5)


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


@bot.event
async def on_ready():
    # Things to do when connecting
    ChadLogger.log("(Re)connected to discord!")


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
    loop = asyncio.get_event_loop()
    context_msgs = await KGPT.get_recent_messages(ctx.channel.id, bot)
    response_msg = await loop.run_in_executor(executor, KGPT.prompt_gpt, context_msgs, ctx.message.content[5:])
    if response_msg[1:] == '"' and response_msg[:1] == '"':
        response_msg = response_msg[1:-1]
    if response_msg.startswith('KlatreBot:'):
        response_msg = response_msg[11:0]
    await ctx.reply(response_msg)


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
    await ctx.send(whereTheFuckIsPelle())


@bot.command()
async def uptime(ctx):
    totalUptimeSeconds = (datetime.datetime.now() -
                          startTime).total_seconds()
    prettyUptime = "{:0>8}".format(
        str(datetime.timedelta(seconds=totalUptimeSeconds)))
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
async def logs(ctx):
    if isinstance(ctx.channel, discord.DMChannel):
        await ctx.channel.send(ChadLogger().query_logs())


@bot.command()
async def clear(ctx):
    if isinstance(ctx.channel, discord.DMChannel):
        ChadLogger().clear_logs()
        await ctx.channel.send("Logs cleared!")


@bot.event
async def on_message(message):  # used for searching for substrings
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
    if message.content.startswith('!downus') or 'fail' in message.content:
        await message.channel.send(f"https://cdn.discordapp.com/attachments"
                                   f"/1003718776430268588/1153668006728192101/downus_on_wall.gif")

    # KlatreBot?
    if message.content.lower()[0:9] == 'klatrebot' and message.content[-1] == '?':
        await message.channel.send(get_random_svar())

    # Glar?
    if '!glar' in message.content and not message.content.startswith('!glar'):
        await message.channel.send('https://imgur.com/CnRFnel')

    # Det kan man jo ikke det der
    pattern = r".*(det\skan\sman\s(\w+\s)?ik).*"
    if re.search(pattern, message.content.lower()):
        await message.channel.send('https://cdn.discordapp.com/attachments/'
                                   '1049312345068933134/1049363489354952764/pellememetekst.gif')

    # Krævet for ikke at blocke @bot.command listeners
    await bot.process_commands(message)


@bot.event
async def setup_hook():
    bot.loop.create_task(send_message_at_time())


async def on_command_error(ctx: commands.Context, error):
    print(f'Ignoring exception in command {ctx.command}:', file=sys.stderr)
    ChadLogger().log_exception(
        type(error), error, error.__traceback__)

if __name__ == "__main__":
    bot.on_command_error = on_command_error
    bot.run(discordkey)
