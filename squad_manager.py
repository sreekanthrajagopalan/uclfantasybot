"""
squad_manager.py

Module that implements squad selection algorithm.
"""


import sys, argparse
from io import TextIOWrapper
import json
import requests
from requests.models import Response
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition


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
        return {}

    # try getting current squad
    url = f'/services/api/Gameplay/user/{guid}/team'
    try:
        req = sn.get(API_URL + url,
            params={'matchdayId': matchdayId},
            headers={'Host': 'gaming.uefa.com',
                'Referer': 'https://gaming.uefa.com/en/uclfantasy/services/index.html'})
        print(f'Sent GET request to get current team: {req.url}')

        # process response
        if req.status_code == 200:
            print('Retrieved team details!')
            return req.json()['data']['value']
        
        print('Error retrieving team!')
        return {}
    
    except requests.exceptions:
        print('Some error occurred!')
        return {}


# define basic sets of constraints
def define_basic_constraints(model, matchday: int, stage: str,
    current_squad: dict = None) -> None:
    """Define basic sets of constraints in the MIP"""

    # required number of players by skills
    def rule_ReqdPlayersBySkills(m, skill):
        return sum(m.ySelectPlayer[p] for p in model.sPlayersWithSkills[skill]) \
            == m.pReqdPlayersBySkills[skill]
    model.cReqdPlayersBySkills = pyo.Constraint(model.sSkills,
        rule=rule_ReqdPlayersBySkills)

    # player limit per club
    def rule_LimPlayersPerClub(m, club):
        return sum(m.ySelectPlayer[p] for p in model.sPlayersInClubs[club]) \
            <= m.pLimPlayersPerClub[stage]
    model.cLimitPlayersPerClub = pyo.Constraint(model.sClubs,
        rule=rule_LimPlayersPerClub)

    if current_squad == {}:
        # cannot exceed budget
        #NOTE: can be removed once tested as balance constraint is equivalent when
        # model.sCurrentPlayers = {}
        def rule_Budget(m):
            return sum(m.pPlayerValues[p] * m.ySelectPlayer[p] \
                for p in model.sPlayers) \
                <= m.pBudget[matchday]
        model.cBudget = pyo.Constraint(rule=rule_Budget)

    else:
        # balance should be non-negative
        def rule_Balance(m):
            return sum(m.pPlayerValues[p] for p in model.sCurrentPlayers) \
                - sum(m.pPlayerValues[p] * m.ySelectPlayer[p] for p in model.sPlayers) \
                + current_squad['teamBalance'] >= 0
        model.cBalance = pyo.Constraint(rule=rule_Balance)

    # number of extra transfers
    def rule_NumExtraTransfers(m):
        return sum(1 - m.ySelectPlayer[p] for p in model.sCurrentPlayers) \
            - m.pLimFreeTransfers[matchday] <= m.zNumExtraTransfers
    model.cNumExtraTransfers = pyo.Constraint(rule=rule_NumExtraTransfers)

    # transfer limit
    def rule_LimFreeTransfers(m):
        return m.zNumExtraTransfers <= 0
    model.cLimFreeTransfers = pyo.Constraint(rule=rule_LimFreeTransfers)


# function to select the best squad for a given matchday
def select_matchday_squad(df_player_info: pd.DataFrame, matchday: int,
    current_squad: dict = None, user_opt: dict = None) -> list:
    """MIP to select the best squad for a given matchday"""

    # declare Pyomo model
    model = pyo.ConcreteModel()

    # set of players
    model.sPlayers = pyo.Set(initialize=list(df_player_info['id']),
        ordered=False, doc='Set of players')

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

    # current players in the squad
    def sCurrentPlayers_init(m):
        for player in current_squad['playerid']:
            yield str(player['id'])
    model.sCurrentPlayers = pyo.Set(initialize=sCurrentPlayers_init,
        doc='Set of players currently in the squad')

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

    # param: player value
    def pPlayerValues_init(m, player):
        return df_player_info[df_player_info['id'] == player]['value'].iloc[0]
    model.pPlayerValues = pyo.Param(model.sPlayers, initialize=pPlayerValues_init,
        doc='Player values')

    # param: player total points
    def pPlayerTotPoints_init(m, player):
        return df_player_info[df_player_info['id'] == player]['totPts'].iloc[0]
    model.pPlayerTotPoints = pyo.Param(model.sPlayers, initialize=pPlayerTotPoints_init,
        doc='Player total points')

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

    # var: number of extra transfers made for the matchday
    model.zNumExtraTransfers = pyo.Var(domain=pyo.Integers, bounds=(0, 15),
        initialize=0)

    # utils
    def find_key(d, v):
        for k, vs in d.items():
            if v in vs:
                return k
    stage = find_key(matchdays_in_stages, matchday)

    # define basic sets of constraints
    define_basic_constraints(model, matchday, stage, current_squad)

    # constraint: exclude inactive players
    for p in model.sInactivePlayers:
        model.ySelectPlayer[p].fix(0)

    # constraint: exclude players not available for selection
    #BUG: Why is 'trained' field '' between matchdays?
    for p in model.sUnavailablePlayers:
        model.ySelectPlayer[p].fix(0)

    # constraint: average % selected should be exceed a given value
    avg_percent_sel = 10
    def rule_AvgPercentSelected(m):
        return sum(df_player_info[df_player_info['id'] == p]['selPer'].iloc[0] \
            * model.ySelectPlayer[p] for p in m.sActivePlayers) >= avg_percent_sel \
            * sum(m.pReqdPlayersBySkills[s] for s in m.sSkills) 
    model.cAvgPercentSelected = pyo.Constraint(rule=rule_AvgPercentSelected)

    # constraint: minimum % selected should be exceed a given value
    min_percent_sel = 1
    def rule_MinPercentSelected(m, player):
        return df_player_info[df_player_info['id'] == player]['selPer'].iloc[0] \
            * m.ySelectPlayer[player] >= min_percent_sel * m.ySelectPlayer[player]
    model.cMinPercentSelected = pyo.Constraint(model.sActivePlayers,
        rule=rule_MinPercentSelected)

    # fix specific players
    if user_opt is not None:
        for p in user_opt['includePlayers']:
            if str(p) in model.sPlayers:
                model.ySelectPlayer[str(p)].fix(1)
        for p in user_opt['excludePlayers']:
            if str(p) in model.sPlayers:
                model.ySelectPlayer[str(p)].fix(0)

    # define objectives
    ## 1. squad value
    def objMaxSquadValue(m):
        return sum(m.pPlayerValues[p] * m.ySelectPlayer[p] \
            for p in (model.sActivePlayers - model.sUnavailablePlayers))

    ## 2. total points
    def objMaxTotalPoints(m):
        return sum(m.pPlayerTotPoints[p] * m.ySelectPlayer[p] 
            for p in (model.sActivePlayers - model.sUnavailablePlayers))

    ## 3. weighted average points and last matchday points (form)
    form_weight = 0.3
    def objMaxAvgPointsFormWeighted(m):
        return sum(((1-form_weight) * m.pPlayerAvgPoints[p] + form_weight * m.pPlayerLastGdPoints[p])\
            * m.ySelectPlayer[p] for p in (model.sActivePlayers - model.sUnavailablePlayers))
    
    ## 4. overall objective
    extra_trans_pen = 20
    def objOverall(m):
        if matchday == 1:
            return objMaxAvgPointsFormWeighted(m) + objMaxSquadValue(m)
        return objMaxTotalPoints(m)/(matchday-1) + objMaxAvgPointsFormWeighted(m) + objMaxSquadValue(m) \
            - extra_trans_pen * m.zNumExtraTransfers

    # set objective 
    model.obj = pyo.Objective(rule=objOverall, sense=pyo.maximize)

    # solve MIP to get best squad
    opt = pyo.SolverFactory('cbc')
    results = opt.solve(model, tee=True)

    # if MIP is infeasible, drop unavailability constraint and free transfer limit
    #TODO: consider playing the wildcard if available?
    if results.solver.termination_condition == TerminationCondition.infeasible:
        for p in model.sUnavailablePlayers:
            if p in model.sCurrentPlayers:
                model.ySelectPlayer[p].unfix()
        model.cLimFreeTransfers.deactivate()

        # solve MIP to get best squad
        opt = pyo.SolverFactory('cbc')
        opt.solve(model, tee=True)

    # stats
    print(f'Number of extra transfers: {pyo.value(model.zNumExtraTransfers)}')
    numInactivePlayersInSquad = 0
    for p in model.sUnavailablePlayers:
        if pyo.value(model.ySelectPlayer[p]) >= 0.9999:
            numInactivePlayersInSquad += 1
    print(f'Number of inactive players: {numInactivePlayersInSquad}')

    # return best squad
    opt_squad = []
    for p in model.sPlayers:
        if pyo.value(model.ySelectPlayer[p]) >= 0.9999:
            opt_squad.append(df_player_info[df_player_info['id'] == p]['pDName'].iloc[0])

    return opt_squad


# main function
def main():
    """Main function"""

    # parse arguments
    parser = argparse.ArgumentParser(description='UEFA Champions League Fantasy Football bot.')
    parser.add_argument('-md', metavar='Matchday', type=int, required=True, dest='matchday',
                    help='matchday to find the best squad transfers')
    parser.add_argument('-inc', metavar='Include Player(s)', nargs="*", type=int, default=[], dest='include_players',
                    help='must-include players')
    parser.add_argument('-exc', metavar='Exclude Player(s)', nargs='*', type=int, default=[], dest='exclude_players',
                    help='must-exclude players')
    args = parser.parse_args()

    # match day
    matchday = args.matchday

    # must select or avoid players
    include_players = args.include_players
    exclude_players = args.exclude_players

    # make user options dict
    user_opt = {'includePlayers': include_players, 'excludePlayers': exclude_players}

    # session
    sn = requests.session()

    # user GUID
    guid = ""

    with open('login_payload.json', encoding='UTF8') as f_login_payload:

        # login to a session
        res = session_login(sn, f_login_payload)
        if res.status_code == 200:
            print('Logged in!')
            guid = res.json()['data']['value']['UCL_CLASSIC_RAW']['guid']
        else:
            print('Error logging in!')
            sys.exit()

        # query players data
        print('Querying player info...')
        res = get_players_info(sn, matchday)
        if res.status_code == 200:
            print(f"Number of players: {len(res.json()['data']['value']['playerList'])}")
        else:
            print(f'Status code: {res.status_code}')

        # create a data frame
        df_player_info = pd.json_normalize(res.json()['data']['value']['playerList'])
        print(df_player_info.head(10))

        # get current squad
        #TODO: What if a team is not created yet?
        current_squad = get_current_squad(sn, guid, matchday)
        filter_list = [str(player['id']) for player in current_squad['playerid']]
        curr_squad_players = list(df_player_info.query('id == @filter_list')['pDName'])

        # select best squad
        next_squad_players = select_matchday_squad(df_player_info, matchday, current_squad, user_opt)

        # compare squads
        print('\n\n')
        print(f'Current squad: {curr_squad_players}')
        print(f"Current Squad value: \
            {df_player_info.query('pDName == @curr_squad_players')['value'].sum()}")
        print('\n')
        print(f'Transfer out: {set(curr_squad_players).difference(set(next_squad_players))}')
        print(f'Transfer in : {set(next_squad_players).difference(set(curr_squad_players))}')
        print('\n')
        print(f'Next Squad: {next_squad_players}')
        print(f"Next squad value: \
            {df_player_info.query('pDName == @next_squad_players')['value'].sum()}")
        print('\n\n')

        # logout of the session
        res = session_logout(sn)
        if res.status_code == 200:
            print('Logged out!')
        else:
            print('Error logging out!')
            sys.exit()


if __name__ == "__main__":
    main()
