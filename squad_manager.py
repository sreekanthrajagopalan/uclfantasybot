"""
squad_manager.py

Module that implements squad selection algorithm.
"""


import sys
from io import TextIOWrapper
import json
import requests
from requests.models import Response


# API base URL
API_URL = r'https://gaming.uefa.com/en/uclfantasy'


def session_login(payload_file: TextIOWrapper) -> Response:
    """POST request to login into a session"""

    url = r'/services/api/Session/login'
    req = requests.post(API_URL + url,
        headers={'accept': 'application/json', 'Content-Type': 'application/json'},
        data=json.dumps(json.load(payload_file)))
    print(f'Sent POST request to login: {req.url}')
    return req


def session_logout() -> Response:
    """POST request to logout of the session"""

    url = r'/services/api/Session/logout'
    req = requests.post(API_URL + url,
        headers={'Host': 'gaming.uefa.com',
            'Referer': 'https://gaming.uefa.com/en/uclfantasy/services/index.html'})
    print(f'Sent POST request to logout: {req.url}')
    return req


def get_players_info(gameday_id: int) -> Response:
    """GET request to UCL Fantasy API to get players information"""

    url = r'/services/api/Feed/players'
    req = requests.get(API_URL + url,
        params={'gamedayId': gameday_id, 'language': 'en'},
        headers={'Host': 'gaming.uefa.com',
            'Referer': 'https://gaming.uefa.com/en/uclfantasy/services/index.html'})
    print(f'Sent GET request for players data: {req.url}')
    return req


with open('login_payload.json', encoding='UTF8') as f:

    # login to a session
    res = session_login(f)
    if res.status_code == 200:
        print('Logged in!')
        print(res.json())
    else:
        print('Error logging in!')
        sys.exit()

    # query players data
    print('Querying player info...')
    res = get_players_info(4)
    if res.status_code == 200:
        print(f"Number of players: {len(res.json()['data']['value']['playerList'])}")
    else:
        print(f'Status code: {res.status_code}')

    # logout of the session
    res = session_logout()
    if res.status_code == 200:
        print('Logged out!')
    else:
        print('Error logging out!')
        sys.exit()
