import json
from urllib.parse import quote
from urllib.request import Request, urlopen


class WeatherLookupError(RuntimeError):
    pass


def fetch_weather(location: str) -> dict:
    location = (location or '').strip()
    if not location:
        raise WeatherLookupError('Enter a city, airport code, or place name.')

    url = f"https://wttr.in/{quote(location)}?format=j1"
    request = Request(url, headers={
        'User-Agent': 'fedexsucks-weather/0.1',
    })

    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except Exception as exc:
        raise WeatherLookupError(f'wttr.in lookup failed: {exc}') from exc

    current = (payload.get('current_condition') or [{}])[0]
    weather_days = (payload.get('weather') or [])[:3]

    return {
        'location': location,
        'current': {
            'temp_f': current.get('temp_F'),
            'temp_c': current.get('temp_C'),
            'feels_like_f': current.get('FeelsLikeF'),
            'feels_like_c': current.get('FeelsLikeC'),
            'humidity': current.get('humidity'),
            'wind_mph': current.get('windspeedMiles'),
            'wind_kmph': current.get('windspeedKmph'),
            'description': ((current.get('weatherDesc') or [{}])[0]).get('value', 'Unknown'),
        },
        'days': [
            {
                'date': day.get('date'),
                'avg_temp_f': day.get('avgtempF'),
                'avg_temp_c': day.get('avgtempC'),
                'max_temp_f': day.get('maxtempF'),
                'min_temp_f': day.get('mintempF'),
                'max_temp_c': day.get('maxtempC'),
                'min_temp_c': day.get('mintempC'),
                'sun_hour': day.get('sunHour'),
                'uv_index': day.get('uvIndex'),
                'summary': ((next((slot for slot in (day.get('hourly') or []) if slot.get('time') == '1200'), (day.get('hourly') or [{}])[0]) or {}).get('weatherDesc') or [{}])[0].get('value', 'Unknown'),
                'chance_of_rain': (next((slot for slot in (day.get('hourly') or []) if slot.get('time') == '1200'), (day.get('hourly') or [{}])[0]) or {}).get('chanceofrain', '0'),
                'chance_of_sunshine': (next((slot for slot in (day.get('hourly') or []) if slot.get('time') == '1200'), (day.get('hourly') or [{}])[0]) or {}).get('chanceofsunshine', '0'),
            }
            for day in weather_days
        ],
    }
