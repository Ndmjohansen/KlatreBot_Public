# import requests module
import requests
import re
import datetime
from dateutil.parser import parse
import pytz
# import pdb  # for debugging

KINDS = {'ACCOMMODATION': ':love_hotel:', 'DRIVING': ':blue_car:', 'FLYING': ':airplane:', 'HIKING': ':man_running:', 'POINTOFINTEREST': ':mount_fuji:', 'SIGHTSEEING': ':statue_of_liberty:',
         'WINE': ':wine:', 'TAKEOFF': ':airplane:', 'LANDING': ':airplane:', 'BREAKFAST': ':pancakes:', 'DINNER': ':sushi:', 'SLEEPING': ':sleeping:', 'TRANSFER': ':airplane:', 'CHILL': ':pepedance:',
         'BUS': ':minibus:'}
copenhagen = pytz.timezone('Europe/Copenhagen')


def getSecondsAsDateTimeString(totalSeconds):
    days, seconds = divmod(totalSeconds, 86400)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    days_text = 'dag' if days == 1 else 'dage'
    hours_text = 'time' if hours == 1 else 'timer'
    minutes_text = 'minut' if minutes == 1 else 'minutter'
    seconds_text = 'sekund' if seconds == 1 else 'sekunder'

    final_text = '' if days == 0 else f"{days:.0f} {days_text} "
    final_text += '' if hours == 0 else f"{hours:.0f} {hours_text} "
    final_text += '' if hours == 0 and minutes == 0 else f"{minutes:.0f} {minutes_text} "
    final_text += '' if seconds == 0 else f"{seconds:.0f} {seconds_text}"

    return final_text


def whereTheFuckIsPelle(arg=None, debug_ts=""):
    PELLE_CTX = "namibia-2025"

    if (arg is not None and arg.lower() == 'pic'):
        try:
            html_url = f"https://pellelauritsen.net/api/html/{PELLE_CTX}/newest"
            response = requests.get(html_url)
            response.raise_for_status()
            
            # Extract image URL using regex
            img_match = re.search(r'<img src="([^"]+)"', response.text)
            if img_match:
                return img_match.group(1)
            else:
                return "Could not find latest Pelle picture"
        except Exception as e:
            return f"Failed to fetch Pelle pic: {str(e)}"

    MAX_DISTANCE = 1000_000_000  # A large number to represent no activity
    fulljs = []

    response = requests.get(f'https://pellelauritsen.net/{PELLE_CTX}.json')
    if (not response.ok):
        return 'Ingen aner hvor Pelle er, men måske er han på vej til klatring.'
    fulljs = response.json()

    currentAccommodation = {}
    currentActivity = {}
    lastDistance = MAX_DISTANCE
    nextActivity = {}

    if len(debug_ts) > 0:
        now = copenhagen.localize(parse(debug_ts))
    else:
        now = copenhagen.localize(datetime.datetime.now())

    for activity in fulljs.get('activities', []):
        if not 'begin' in activity:
            continue
        start = pytz.timezone(activity['begin']['timezone']).localize(
            parse(activity['begin']['dateTime']))
        end = pytz.timezone(activity['end']['timezone']).localize(
            parse(activity['end']['dateTime']))
        
        if (now > start and now < end):
            if ( 'kind' in activity and activity['kind'] == 'ACCOMMODATION'):
                currentAccommodation = activity
            else:
                currentActivity = activity

            continue
        
        secondsUntilNext = (start - now).total_seconds()
        if (lastDistance > secondsUntilNext and secondsUntilNext > 0):
            lastDistance = secondsUntilNext
            nextActivity = activity

    outputString = ""
    if (len(currentActivity) == 0):
        if (lastDistance < 0 or lastDistance == MAX_DISTANCE):
            return "Pelle er på vej til klatring..."

        prettySeconds = getSecondsAsDateTimeString(lastDistance)

        currentActivity = nextActivity
        outputString += f"Om {prettySeconds}: {pytz.timezone(currentActivity['begin']['timezone']).localize(parse(currentActivity['begin']['dateTime']))} - "

    outputString += f"{KINDS[currentActivity['kind']]} {currentActivity['title']}"
    if ('description' in currentActivity and len(currentActivity['description']) > 0):
        outputString += f" ({currentActivity['description']})"
    
    if (currentActivity['kind'] == 'FLYING' and 'description' in currentActivity):
        flightNumber = currentActivity['description'].replace(" ", "")
        outputString += f"\nhttps://www.flightradar24.com/data/flights/{flightNumber}"

    beginLocation = f"{currentActivity['begin']['location']}"
    endLocation = f"{currentActivity['end']['location']}"
    if (beginLocation != endLocation):
        outputString += f"\n({currentActivity['begin']['location']} -> {currentActivity['end']['location'] })"

    end = pytz.timezone(currentActivity['end']['timezone']).localize(
        parse(currentActivity['end']['dateTime']))

    sekunderTilEnd = getSecondsAsDateTimeString((end - now).total_seconds())
    outputString += f" færdig om {sekunderTilEnd}"

    if (len(currentAccommodation) != 0):
        outputString += f"\nI mellemtiden chiller Pelle @ {KINDS[currentAccommodation['kind']]} {currentAccommodation['title']}"

    if ('url' in currentActivity):
        outputString += f" {currentActivity['url']}"
    elif ('url' in currentAccommodation):
        outputString += f" {currentAccommodation['url']}"
    
    coordinate = []
    if (len(nextActivity) == 0 and 'coordinate' in currentActivity):
        coordinate = currentActivity['coordinate']
    elif ('coordinate' in currentAccommodation):
        coordinate = currentAccommodation['coordinate']
    elif ('coordinate' in nextActivity):
        coordinate = nextActivity['coordinate']

    if (len(coordinate) == 2):
        outputString += f" https://www.openstreetmap.org/search?query={coordinate[0]}%2C%20{coordinate[1]}"

    return outputString
