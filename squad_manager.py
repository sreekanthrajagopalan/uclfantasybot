"""
squad_manager.py

Module that implements squad selection algorithm.
"""


import sys
from io import TextIOWrapper
import json
from typing import Match
import requests
from requests.models import Response
import pandas as pd
import pyomo.environ as pyo
from requests.sessions import session


# API base URL
API_URL = r'https://gaming.uefa.com/en/uclfantasy'


# function to log into a session
def session_login(sn, payload_file: TextIOWrapper) -> Response:
    """POST request to login into a session"""

    url = r'/services/api/Session/login'
    req = sn.post(API_URL + url,
        headers={'accept': 'application/json', 'Content-Type': 'application/json'},
        data=json.dumps(json.load(payload_file)))
    print(f'Sent POST request to login: {req.url}')
    return req


# function to log out of a session
def session_logout(sn) -> Response:
    """POST request to logout of the session"""

    url = r'/services/api/Session/logout'
    req = sn.post(API_URL + url,
        headers={'Host': 'gaming.uefa.com',
            'Referer': 'https://gaming.uefa.com/en/uclfantasy/services/index.html'})
    print(f'Sent POST request to logout: {req.url}')
    return req


# function to get players data/information
def get_players_info(sn, gameday_id: int) -> Response:
    """GET request to UCL Fantasy API to get players information"""

    url = r'/services/api/Feed/players'
    req = sn.get(API_URL + url,
        params={'gamedayId': gameday_id, 'language': 'en'},
        headers={'Host': 'gaming.uefa.com',
            'Referer': 'https://gaming.uefa.com/en/uclfantasy/services/index.html'})
    print(f'Sent GET request for players data: {req.url}')
    return req


# get current squad
def get_current_squad(sn, guid: str, matchdayId: int):
    """Get current squad"""

    # return if guid is empty
    if guid == "":
        return []

    # try getting current squad
    url = f'/services/api/Gameplay/user/{guid}/team'
    try:
        req = sn.get(API_URL + url,
            params={'matchdayId': matchdayId, 'phaseId': 1},
            headers={'Host': 'gaming.uefa.com',
                'Referer': 'https://gaming.uefa.com/en/uclfantasy/services/index.html'})
        print(f'Sent GET request to get current team: {req.url}')

        # process response
        if req.status_code == 200:
            print('Retrieved team details!')
            print(req.json())
            return req.json()['data']['value']['playerid']
        
        print('Error retrieving team!')
        return []
    
    except:
        print('Some error occurred!')
        return []     


# define basic sets of constraints
def define_basic_constraints(model, matchday: int, stage: str) -> None:
    """Define basic sets of constraints in the MIP"""

    # required number of players by skills
    def rule_ReqdPlayersBySkills(m, skill):
        return sum(m.ySelectPlayer[p] for p in model.sPlayersWithSkills[skill]) \
            <= m.pReqdPlayersBySkills[skill]
    model.cReqdPlayersBySkills = pyo.Constraint(model.sSkills,
        rule=rule_ReqdPlayersBySkills)

    # player limit per club
    def rule_LimPlayersPerClub(m, club):
        return sum(m.ySelectPlayer[p] for p in model.sPlayersInClubs[club]) \
            <= m.pLimPlayersPerClub[stage]
    model.cLimitPlayersPerClub = pyo.Constraint(model.sClubs,
        rule=rule_LimPlayersPerClub)

    # cannot exceed budget
    def rule_Budget(m):
        return sum(m.pPlayerPrices[p] * m.ySelectPlayer[p] \
            for p in model.sPlayers) \
            <= m.pBudget[matchday]
    model.cBudget = pyo.Constraint(rule=rule_Budget)


# function to select the best squad for a given matchday
def select_matchday_squad(df_player_info: pd.DataFrame, matchday: int,
    current_squad: list = None) -> list:
    """MIP to select the best squad for a given matchday"""

    # declare Pyomo model
    model = pyo.ConcreteModel()

    # set of players
    model.sPlayers = pyo.Set(initialize=list(df_player_info['id']),
        doc='Set of players')

    # subset of active players
    model.sActivePlayers = pyo.Set(
        initialize=list(df_player_info[df_player_info['isActive'] == 1]['id']),
        doc='Set of active players')
    model.sInactivePlayers = model.sPlayers - model.sActivePlayers

    # subset of players unavailable for selection
    model.sAvailablePlayers = pyo.Set(
        initialize=list(df_player_info[df_player_info['trained'].str.match(
            'In contention to start next game')]['id']),
        doc='Set of players available for selection')
    model.sUnavailablePlayers = model.sPlayers - model.sAvailablePlayers

    # set of player skills
    model.sSkills = pyo.Set(initialize=[1, 2, 3, 4], doc='Set of player skills')

    # set of players by skills
    def sPlayersWithSkills_init(m, skill):
        for player in list(df_player_info[df_player_info['skill'] == skill]['id']):
            yield player
    model.sPlayersWithSkills = pyo.Set(model.sSkills, initialize=sPlayersWithSkills_init,
        doc='Set of players with a given skill')

    # set of clubs
    model.sClubs = pyo.Set(initialize=list(df_player_info['cCode'].unique()),
        doc='Set of clubs')

    # set of players in clubs
    def sPlayersInClubs_init(m, club):
        for player in list(df_player_info[df_player_info['cCode'] == club]['id']):
            yield player
    model.sPlayersInClubs = pyo.Set(model.sClubs, initialize=sPlayersInClubs_init,
        doc='Set of players in a given club')

    # set of matchdays
    num_matchdays = 13
    model.sMatchdays = pyo.Set(initialize=[i+1 for i in range(0, num_matchdays)],
        doc='Set of matchdays')

    # set of stages
    model.sStages = pyo.Set(initialize=['Group stage', 'Round of 16', 'Quarter-finals',
        'Semi-finals', 'Final'], doc='Set of stages')

    # set of matchdays in stages
    matchdays_in_stages = {'Group stage': [i+1 for i in range(0, 6)],
        'Round of 16': [7, 8], 'Quarter-finals': [9, 10], 'Semi-finals': [11, 12],
        'Final': [13]}
    def sMatchdaysInStages_init(m, stage):
        for matchday in matchdays_in_stages[stage]:
            yield matchday
    model.sMatchdaysInStages = pyo.Set(model.sStages, initialize=sMatchdaysInStages_init,
        doc='Set of matchdays in a given stage')

    # param: required number of players by skills in a squad
    model.pReqdPlayersBySkills = pyo.Param(model.sSkills, initialize={1:2, 2:5, 3:5, 4:3},
        doc="Required number of players by skills")

    # param: limit players per club by stages in a squad
    model.pLimPlayersPerClub = pyo.Param(model.sStages, initialize={'Group stage': 3,
        'Round of 16': 4, 'Quarter-finals': 5, 'Semi-finals': 6, 'Final': 8},
        doc='Limit on max number of players per club by stages')

    # param: free transfer limit for matchdays
    model.pLimFreeTransfers = pyo.Param(model.sMatchdays, initialize={1:15, 2:2, 3:2, 4:2,
        5:2, 6:2, 7:15, 8:3, 9:5, 10:3, 11:5, 12:3, 13:5},
        doc="Free transfers before matchdays")

    # param: budget
    def pBudget_init(m, matchday):
        if matchday > 6:
            return 105
        return 100
    model.pBudget = pyo.Param(model.sMatchdays, initialize=pBudget_init,
        doc='Budget for the matchday')

    # param: player prices
    def pPlayerPrices_init(m, player):
        return df_player_info[df_player_info['id'] == player]['value'].iloc[0]
    model.pPlayerPrices = pyo.Param(model.sPlayers, initialize=pPlayerPrices_init,
        doc='Player prices')

    # param: player average points
    def pPlayerAvgPoints_init(m, player):
        return df_player_info[df_player_info['id'] == player]['avgPlayerPts'].iloc[0]
    model.pPlayerAvgPoints = pyo.Param(model.sPlayers, initialize=pPlayerAvgPoints_init,
        doc='Player average points')

    # param: player last game day points
    def pPlayerLastGdPoints_init(m, player):
        return df_player_info[df_player_info['id'] == player]['lastGdPoints'].iloc[0]
    model.pPlayerLastGdPoints = pyo.Param(model.sPlayers, initialize=pPlayerLastGdPoints_init,
        doc='Player last game day points')

    # var: binary indicating if a player is selected for matchday squad
    model.ySelectPlayer = pyo.Var(model.sPlayers, domain=pyo.Binary)

    # utils
    def find_key(d, v):
        for k, vs in d.items():
            if v in vs:
                return k
    stage = find_key(matchdays_in_stages, matchday)

    # define basic sets of constraints
    define_basic_constraints(model, matchday, stage)

    # constraint: exclude inactive players
    for p in model.sInactivePlayers:
        model.ySelectPlayer[p].fix(0)

    # constraint: exclude players not available for selection
    #BUG: Why is 'trained' field '' between matchdays?
    #for p in model.sUnavailablePlayers:
    #    model.ySelectPlayer[p].fix(0)

    #TODO: constraint: transfer limit

    # define objective
    form_weight = 0.5
    def objMaxAvgPointsFormWeighted(m):
        return sum(((1-form_weight) * m.pPlayerAvgPoints[p] + form_weight * m.pPlayerLastGdPoints[p])\
            * m.ySelectPlayer[p] for p in model.sPlayers)
    model.objMaxAvgPointsFormWeighted = pyo.Objective(rule=objMaxAvgPointsFormWeighted,
        sense=pyo.maximize)

    # solve MIP to get best squad
    opt = pyo.SolverFactory('cbc')
    opt.solve(model, tee=True)

    # return best squad
    opt_squad = []
    for p in model.sPlayers:
        if pyo.value(model.ySelectPlayer[p]) >= 0.9999:
            opt_squad.append(df_player_info[df_player_info['id'] == p]['pDName'].iloc[0])

    return opt_squad


# main function
def main():
    """Main function"""

    # match day
    matchday = 6

    # session
    sn = requests.session()

    # user GUID
    guid = ""

    with open('login_payload.json', encoding='UTF8') as f_login_payload:

        # login to a session
        res = session_login(sn, f_login_payload)
        if res.status_code == 200:
            print('Logged in!')
            print(res.json())
            guid = res.json()['data']['value']['UCL_CLASSIC_RAW']['guid']
        else:
            print('Error logging in!')
            sys.exit()

        # query players data
        print('Querying player info...')
        res = get_players_info(sn, matchday-1)
        if res.status_code == 200:
            print(f"Number of players: {len(res.json()['data']['value']['playerList'])}")
        else:
            print(f'Status code: {res.status_code}')

        # create a data frame
        df_player_info = pd.json_normalize(res.json()['data']['value']['playerList'])
        print(df_player_info.head(10))

        # get current squad
        if matchday > 1:
            current_squad = get_current_squad(sn, guid, matchday-1)
        else:
            current_squad = []
        print(current_squad)

        #TODO: select best squad
        opt_squad = select_matchday_squad(df_player_info, matchday, current_squad)
        print(opt_squad)

        # logout of the session
        res = session_logout(sn)
        if res.status_code == 200:
            print('Logged out!')
        else:
            print('Error logging out!')
            sys.exit()


if __name__ == "__main__":
    main()
