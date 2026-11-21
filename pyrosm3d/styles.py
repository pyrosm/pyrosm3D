"""The heights, colours and names used in the drawings of indoor elements."""

import numpy as np

# Metres of drawing height for one level
FLOOR_HEIGHT = 4.0
# Metres for one level below the ground floor, where levels are placed in metres
UNDERGROUND_FLOOR_HEIGHT = 6.0
# Walls are cut away at this height, so that the rooms stay visible from above
WALL_HEIGHT = 0.4 * FLOOR_HEIGHT
# Metres drawn around the indoor areas
VIEW_MARGIN = 10.0
# How much taller than to scale the views draw heights when they are not drawn to scale,
# so that what lies above and below each other stands apart
HEIGHT_STRETCH = 2.2
# Metres of floor left open across the stairs, escalators and moving walkways that
# rise through it. OSM has no widths for them: 1.6 m is about the overall width of an
# escalator with a 1 m step, and the width of stairs is assumed.
OPENING_WIDTHS = {"escalator": 1.6, "moving_walkway": 1.6, "stairs": 2.0}
# Metres of floor kept as a landing where a climb ends
LANDING = 1.0
# Metres of wall left open at a door, and how far from a wall a door may lie to open it
DOOR_GAP = 0.9
DOOR_REACH = 0.25

# (name in the list of layers, colour of the floor, name in the text) of each kind of
# area that has a floor, in drawing order
AREA_STYLES = {
    "room": ("Rooms", "#e3dccd", "room"),
    "shop": ("Shops and food in rooms", "#f6e3a1", "shop or food room"),
    "toilets": ("Toilets", "#bfdff8", "toilets"),
    "corridor": ("Corridors and indoor areas", "#f4f2ee", "corridor or indoor area"),
    "indoor": ("Other indoor areas", "#e7eaee", "indoor area"),
    "shaft": ("Stairwells, lifts, storage", "#c9cbce", "stairwell, lift or storage"),
    "platform": ("Platform areas", "#bfe6d3", "platform area"),
    "walking_area": ("Walking areas", "#dad6ea", "walking area"),
}
OUTLINE_COLOUR = "#8a8f98"
LEVEL_OUTLINE_COLOUR = "#b9a99c"
# Walls are see-through: their colour, and how much a wall hides of what is behind it
WALL_NAME = "Walls (rooms and indoor=wall)"
OUTER_WALL_NAME = "Outer walls (level or building outlines)"
WALL_COLOUR = "#8cc4ec"
WALL_OPACITY = 0.32
# (name in the list of layers, colour, name in the text) of the columns of each kind of
# shaft
COLUMN_STYLES = {
    "stairs": ("Stairwells (room=stairs)", "#e07b5f", "stairwell"),
    "elevator": (
        "Lift shafts (room=elevator or highway=elevator)",
        "#9b59c6",
        "lift shaft",
    ),
}
# The floor of a level or building outline, drawn under its outer walls
LEVEL_FLOOR_COLOUR = "#ebe9e4"
# The background of the indoor view
BACKGROUND_COLOUR = "#ffffff"
# (name in the list of layers, colour, name in the text) of the doors and the shops
DOOR_STYLE = ("Doors and entrances", "#31363b", "door or entrance")
POI_STYLE = ("Shops and amenities", "#a07a00", "shop or amenity")


def metres_of_levels(levels):
    """How many metres ``levels`` (a number or an array) lie above the ground floor,
    level 0: :data:`FLOOR_HEIGHT` metres for each level above it and
    :data:`UNDERGROUND_FLOOR_HEIGHT` metres for each level below it."""
    levels = np.asarray(levels, dtype=float)
    return np.where(levels < 0, UNDERGROUND_FLOOR_HEIGHT, FLOOR_HEIGHT) * levels
