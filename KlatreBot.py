import datetime
import random
import re
import discord
import asyncio
import requests
import io
import sys
from KlatringAttendance import KlatringAttendance
from PIL import Image
from pelleService import whereTheFuckIsPelle
import subprocess

client = discord.Client(intents=discord.Intents.all())
DISCORD_CHANNEL_ID = 1003718776430268588
pattern = r".*(det\skan\sman\s(\w+\s)?ik).*"
timeout = []
Magnus = 229599553953726474
startTime = datetime.datetime.now()


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
    channel = client.get_channel(channel)
    global latestKlatreAttendances
    latestKlatreAttendances = KlatringAttendance()
    lastReactToMessage = await channel.send(embed=latestKlatreAttendances.get_embed())
    latestKlatreAttendances.set_message(
        discord_message=lastReactToMessage)
    await lastReactToMessage.add_reaction("✅")
    await lastReactToMessage.add_reaction("❌")


async def send_message_at_time():
    # Wait until the specified time
    while True:
        # Get the current time and day of the week
        now = datetime.datetime.now()
        day_of_week = now.weekday()

        # Only send a message on Monday and Thursday at 17:00
        if day_of_week in [0, 3] and now.hour == 17:
            await send_and_track_klatretid_message(DISCORD_CHANNEL_ID)
            await asyncio.sleep(60 * 60 * 23)

        # Wait for one minute before checking the time again
        await asyncio.sleep(60)


async def timeout_user_by_id(id, time_in_sec):
    timeout.append(id)
    timestamp_start = datetime.datetime.now()
    print(f"timeout {id} for {time_in_sec}")
    while id in timeout:
        time_passed_sec = (datetime.datetime.now()-timestamp_start).seconds
        # print(f"{id} is on timeout for {time_passed_sec}")
        if time_passed_sec > time_in_sec:
            timeout.remove(id)
        await asyncio.sleep(1)
    print(f"{id} unbanned, timeout table = {timeout}")


async def jpeg(url):
    byte_IO = io.BytesIO()
    r = requests.get(url)
    r.raise_for_status()
    with io.BytesIO(r.content) as f:
        with Image.open(f) as im:
            im = im.convert('RGB')
            im.thumbnail((650, 650))
            im.save(byte_IO, format="JPEG", quality=1, optimize=True)
            # byteimg = Image.open(byte_IO)
            byte_IO.seek(0)
            return byte_IO


async def go_to_bed(message):
    await asyncio.sleep(60 * 15)
    if str(message.guild.get_member(message.author.id).status) == 'online':
        await client.get_channel(message.channel.id).send(f'Gå i seng <@{message.author.id}>')


@client.event
async def on_ready():
    # Start the send_message_at_time function when the bot connects to Discord
    tasks = asyncio.all_tasks()
    coro_names = []
    for task in tasks:
        coro_names.append(task.get_coro().__name__)
    if 'send_message_at_time' not in coro_names:
        print('Task not running, starting task')
        client.loop.create_task(send_message_at_time())


@client.event
async def on_reaction_add(reaction, user):
    if (reaction.message.author != client.user and client.user != user):
        await reaction.message.add_reaction(reaction.emoji)

    if (reaction.message.author == client.user and client.user != user and reaction.message == latestKlatreAttendances.message):
        if (reaction.emoji == "✅"):
            latestKlatreAttendances.add_attendee(user)
        elif (reaction.emoji == "❌"):
            latestKlatreAttendances.add_slacker(user)

        await latestKlatreAttendances.message.edit(embed=latestKlatreAttendances.get_embed())


@client.event
async def on_message(message):
    if message.content.startswith('!debug') \
            and message.channel.id == 1049312345068933134 \
            and message.author.id != 1049311574638202950:
        await message.channel.send(message.content)
        await send_and_track_klatretid_message(1049312345068933134)

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

    if message.content.startswith('!ugenr'):
        await message.channel.send(f"Vi er i uge {datetime.datetime.today().isocalendar()[1]}")

    if message.content.startswith('!downus') or 'fail' in message.content:
        await message.channel.send(f"https://cdn.discordapp.com/attachments"
                                   f"/1003718776430268588/1153668006728192101/downus_on_wall.gif")

    if message.content.startswith('!timeout') and not message.author.id == Magnus:
        words = message.content.split()
        if len(words) == 2 and words[1] == 'clear' and message.author.id not in timeout:
            await message.channel.send(f"Alle kriminelle er løsladte")
            timeout.clear()
        elif len(words) == 3 and int(words[2]) < 600:
            await message.channel.send(f"{words[1]} på timeout i {words[2]} sekunder, ingen glar til dig")
            await timeout_user_by_id(int(words[1]), int(words[2]))
        elif len(words) == 3 and int(words[2]) > 600:
            await message.channel.send(f"Måske {words[2]} sekunder er lige i overkanten, kaptajn")

    if message.content.startswith('!jpg') or message.content.startswith('!jpeg'):
        # message parsing
        words = message.content.split()
        if len(words) == 2 and words[1][-4:] in [".jpg", "jpeg", ".png"]:
            # await message.channel.send(f"Word count: {len(words)}, URL: {words[1]}, TEST1: {words[1][-4:]}")
            image = await jpeg(words[1])
            await message.channel.send(file=discord.File(fp=image, filename="jaypeg.jpg"))

    if message.content.startswith('!pelle'):
        await message.channel.send(whereTheFuckIsPelle())

    if message.content.startswith('!uptime'):
        totalUptimeSeconds = (datetime.datetime.now() -
                              startTime).total_seconds()
        prettyUptime = "{:0>8}".format(
            str(datetime.timedelta(seconds=totalUptimeSeconds)))
        gitHash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
        await message.channel.send(f"Jeg har kørt i {prettyUptime} på version https://github.com/Ndmjohansen/KlatreBot_Public/commit/{gitHash}")

    if message.content.startswith('!pelle_debug'):
        await message.channel.send(whereTheFuckIsPelle(1))

    if message.content.startswith('!say') and message.channel.id == 1049312345068933134:
        channel = client.get_channel(DISCORD_CHANNEL_ID)
        message_to_send = message.content[4:].strip()
        if not len(message_to_send) == 0:
            print(f"message is: {len(message_to_send)} and being sent")
            await channel.send(message_to_send)

    if message.content.lower()[0:9] == 'klatrebot' and message.content[-1] == '?':
        await message.channel.send(get_random_svar())

    if '!glar' in message.content and not message.content.startswith('!glar') and message.author.id not in timeout:
        await message.channel.send('https://imgur.com/CnRFnel')

    if message.content.startswith('!glar') and message.author.id not in timeout:
        now = datetime.datetime.now()
        day_of_week = now.weekday()
        if 0 <= datetime.datetime.now().hour < 10:
            await message.channel.send(f'Det er vist over din sengetid {message.author.name}')
            client.loop.create_task(go_to_bed(message))
        # elif day_of_week in [0, 3] and now.hour < 17:
            # await message.channel.send('Ro på kaptajn, folket er på arbejde')
        else:
            await message.channel.send('@everyone Hva sker der? er i.. er i glar?')
            await message.channel.send('https://imgur.com/CnRFnel')

    # Pelle
    msg = message.content.lower()
    if re.search(pattern, msg):
        await message.channel.send('https://cdn.discordapp.com/attachments/'
                                   '1049312345068933134/1049363489354952764/pellememetekst.gif')

client.run(sys.argv[1])
