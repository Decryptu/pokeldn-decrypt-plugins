"""Type effectiveness, from Pokemon Showdown's public type chart (MIT licence): data/typechart.json maps
a defending type to {attacking type: multiplier}."""
import json
import os

CHART = json.load(open(os.path.join(os.path.dirname(__file__), "data", "typechart.json")))


def multiplier(attacking, defending):
    return CHART[defending][attacking]
