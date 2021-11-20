# UCL Fantasy Bot
UEFA Champions League Fantasy Football bot based on mathematical optimization

# Introduction
The bot at this time is a simple Python script that logs into a Fantasy Football session for squad management:
- Get the current team,
- Get the feed of players data,
- Find the best team for the next matchday.

The optimal team selection is based on a integer programming (IP) model that selects players based on basic fantasy rules.

## Notes
- The bot does not automatically make the transfers between matchdays at this time.
- The bot assumes a team already exists.
- The optimization model does not consider playing wildcard and limitless chips at this time.
- The optimization model does not consider substitutions within matchdays at this time.

# Requirements
The bot is developed natively in Python. The mathematical optimization model is based on [Pyomo](https://pyomo.readthedocs.io/en/stable/) open-source modeling system. The bot currently uses [COIN-OR CBC](https://projects.coin-or.org/Cbc) mixed-integer linear programming solver installed via the Ubuntu package `coinor-cbc`.

# Usage
Install Python modules and optimization solver requirements.
- Python modules in `.devcontainer/requirements.txt`
- COIN-OR CBC solver

Create a `login_payload.json` file from the template with appropriate user credentials. See [this Reddit](https://www.reddit.com/r/FantasyCL/comments/mmq80a/uefa_fantasy_cl_data_api/) for details to get the login payload.

Run `python squad_manager.py -md 5` to get the squad for the 5th matchday.

# Develop
You may use the `.devcontainer` in the repository to get started with the development.

## TODOs
### Known issues
- Handle the scenario when a team does not exist

# Disclaimer
The project is intended to be academic in nature. The author(s) have neither monetarily benefited from third-parties nor have won any official fantasy football prize. The author(s) will duly disclose any such benefits upon receipt and forfeit them if required. The author(s) shall not be held liable for any misuse of the software or for any violation of the spirit of the fantasy football by others.