# import requests module
import requests
import datetime
from dateutil.parser import parse
import pytz
#import pdb # for debugging

KINDS = {'ACCOMMODATION': ':love_hotel:', 'DRIVING':':blue_car:', 'FLYING':':airplane:', 'HIKING':':man_running:', 'POINTOFINTEREST':':mount_fuji:', 'SIGHTSEEING':':statue_of_liberty:', 'WINE': ':wine:', 'TAKEOFF':':airplane:', 'LANDING':':airplane:', 'BREAKFAST':':pancakes:', 'DINNER':':sushi:','SLEEPING':':sleeping:','TRANSFER':':airplane:', 'CHILL':':pepedance:'}
copenhagen = pytz.timezone('Europe/Copenhagen')

def whereTheFuckIsPelle(debug=0):
    response = requests.get('https://pellelauritsen.net/australia.json')
    fulljs = response.json()
    js = {} # fulljs[1]

    for event in fulljs:
        if not 'begin' in event:
            continue
        start = pytz.timezone(event['begin']['timezone']).localize(parse(event['begin']['dateTime']))
        end = pytz.timezone(event['end']['timezone']).localize(parse(event['end']['dateTime']))
        now = copenhagen.localize(datetime.datetime.now())
        if debug:
            now = copenhagen.localize(parse("2023-11-07T09:00:00"))
        if(now > start and now < end):
            js = event
            break

    if(len(js) ==0):
        return "Pelle is idling..."

    outputString = f"{KINDS[js['kind']]} {js['title']} ({js['description']})"
    beginLocation = f"{js['begin']['location']}"
    endLocation = f"{js['end']['location']}"
    if(beginLocation != endLocation):
        outputString += f" ({js['begin']['location']} -> {js['end']['location'] })"

    if('url' in js):
        outputString += f" {js['url']}"
    if('coordinate' in js):
        outputString +=  f" https://www.openstreetmap.org/search?query={js['coordinate'][0]}%2C%20{js['coordinate'][1]}"

    return outputString
