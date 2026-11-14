"""The heights, colours and names used in the drawings of indoor elements."""

# Metres of drawing height for one level
FLOOR_HEIGHT = 4.0
# Walls are cut away at this height, so that the rooms stay visible from above
WALL_HEIGHT = 0.4 * FLOOR_HEIGHT
# Metres drawn around the indoor areas
VIEW_MARGIN = 10.0
# Metres of floor left open across the stairs, escalators and moving walkways that
# rise through it. OSM has no widths for them: 1.6 m is about the overall width of an
# escalator with a 1 m step, and the width of stairs is assumed.
OPENING_WIDTHS = {"escalator": 1.6, "moving_walkway": 1.6, "stairs": 2.0}
# Metres of floor kept as a landing where a climb ends
LANDING = 1.0

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
}
OUTLINE_COLOUR = "#8a8f98"
# (name in the legend, colour, marker symbol, name in the hover text) of the markers
DOOR_STYLE = ("Doors and entrances", "#31363b", "square", "door or entrance")
POI_STYLE = ("Shops and amenities", "#a07a00", "circle", "shop or amenity")
