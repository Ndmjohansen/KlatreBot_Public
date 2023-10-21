# import requests module
import requests
import datetime
from dateutil.parser import parse
import pytz
# import pdb  # for debugging

KINDS = {'ACCOMMODATION': ':love_hotel:', 'DRIVING': ':blue_car:', 'FLYING': ':airplane:', 'HIKING': ':man_running:', 'POINTOFINTEREST': ':mount_fuji:', 'SIGHTSEEING': ':statue_of_liberty:',
         'WINE': ':wine:', 'TAKEOFF': ':airplane:', 'LANDING': ':airplane:', 'BREAKFAST': ':pancakes:', 'DINNER': ':sushi:', 'SLEEPING': ':sleeping:', 'TRANSFER': ':airplane:', 'CHILL': ':pepedance:'}
copenhagen = pytz.timezone('Europe/Copenhagen')


def whereTheFuckIsPelle(debug=0):
    fulljs = []
    gitgud = 0
    response = requests.get('https://pellelauritsen.net/australia.json')
    fulljs = response.json()
    if ('sugandese' in fulljs[0]['title']):
        while (gitgud < 100):
            response = requests.get(
                f'https://pellelauritsen.net/australia-{gitgud}.json')
            gitgud += 1
            if (response.ok):
                fulljs = response.json()
                if ('sugandese' in fulljs[0]['title']):
                    continue
                else:
                    break
            else:
                continue
    if (gitgud == 100):
        return ''

    js = {}
    lastDistance = 1000000000
    shortestEntry = {}

    for event in fulljs:
        if not 'begin' in event:
            continue
        start = pytz.timezone(event['begin']['timezone']).localize(
            parse(event['begin']['dateTime']))
        end = pytz.timezone(event['end']['timezone']).localize(
            parse(event['end']['dateTime']))
        now = copenhagen.localize(datetime.datetime.now())
        if debug:
            now = copenhagen.localize(parse("2023-10-28T16:20:00"))
        currentDistance = (start - now).total_seconds()
        if (lastDistance > currentDistance and currentDistance > 0):
            lastDistance = currentDistance
            shortestEntry = event

        if (now > start and now < end):
            js = event
            break

    outputString = ""
    if (len(js) == 0):
        if (lastDistance < 0 or lastDistance == 1000000000):
            return "Pelle er på vej til klatring..."

        minutes, seconds = divmod(lastDistance, 60)
        hours, minutes = divmod(minutes, 60)
        prettySeconds = "%d timer %02d minuter %02d sekunder" % (
            hours, minutes, seconds)

        js = shortestEntry
        outputString += f"Om {prettySeconds}: {pytz.timezone(js['begin']['timezone']).localize(parse(js['begin']['dateTime']))} - "

    outputString += f"{KINDS[js['kind']]} {js['title']} ({js['description']})"
    beginLocation = f"{js['begin']['location']}"
    endLocation = f"{js['end']['location']}"
    if (beginLocation != endLocation):
        outputString += f" ({js['begin']['location']} -> {js['end']['location'] })"

    if ('url' in js):
        outputString += f" {js['url']}"
    if ('coordinate' in js):
        outputString += f" https://www.openstreetmap.org/search?query={js['coordinate'][0]}%2C%20{js['coordinate'][1]}"

    return outputString
