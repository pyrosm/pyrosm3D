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

# (name in the legend, colour of the floor, name in the hover text) of each kind of
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
# Walls are see-through panels, lit from one side so that their faces differ
WALL_NAME = "Walls (rooms and indoor=wall)"
OUTER_WALL_NAME = "Outer walls (level or building outlines)"
WALL_STYLE = dict(
    color="#8cc4ec",
    opacity=0.32,
    flatshading=True,
    lighting=dict(ambient=0.55, diffuse=0.7, specular=0.05, roughness=0.9, fresnel=0),
    lightposition=dict(x=1000, y=-2000, z=3000),
)
# (name in the legend, colour, name in the hover text) of the columns of each kind of
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
# Where the view starts: seen from the south-east and above, so that north lies away
# from the viewer, with the middle of the scene a little below the middle of the view
CAMERA = dict(eye=dict(x=1.25, y=-1.35, z=0.95), center=dict(x=0, y=0, z=-0.08))
# The axes of the scene: no panes behind the drawing, and quiet lines and text
AXIS_STYLE = dict(
    showbackground=False,
    gridcolor="#d6dbe1",
    zerolinecolor="#d6dbe1",
    color="#5c6672",
    title_font_size=11,
    tickfont_size=10,
)
BACKGROUND_COLOUR = "#ffffff"
# The label of the element under the pointer
HOVER_LABEL = dict(bgcolor="#ffffff", bordercolor="#d6dbe1", font_color="#1c2229")
# (name in the legend, colour, marker symbol, name in the hover text) of the markers
DOOR_STYLE = ("Doors and entrances", "#31363b", "square", "door or entrance")
POI_STYLE = ("Shops and amenities", "#a07a00", "circle", "shop or amenity")


def metres_of_levels(levels):
    """How many metres ``levels`` (a number or an array) lie above the ground floor,
    level 0: :data:`FLOOR_HEIGHT` metres for each level above it and
    :data:`UNDERGROUND_FLOOR_HEIGHT` metres for each level below it."""
    levels = np.asarray(levels, dtype=float)
    return np.where(levels < 0, UNDERGROUND_FLOOR_HEIGHT, FLOOR_HEIGHT) * levels


def levels_of_metres(metres):
    """The levels (a number or an array) that lie ``metres`` above the ground floor:
    the inverse of :func:`metres_of_levels`."""
    metres = np.asarray(metres, dtype=float)
    return metres / np.where(metres < 0, UNDERGROUND_FLOOR_HEIGHT, FLOOR_HEIGHT)
