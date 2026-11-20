// The deck.gl layers of a page of pyrosm3d: each group of the page's data (the ground,
// lines and points; all in metres from the middle of the data, x east, y north, z up)
// as the layers that draw it in one of the page's views: the solid model or the
// see-through map.
(function (view) {
  "use strict";

  // A colour of the data ("#rrggbb") as deck.gl takes it, with its opacity (0 to 255)
  function colour(hex, alpha) {
    const part = (at) => parseInt(hex.slice(at, at + 2), 16);
    return [part(1), part(3), part(5), alpha === undefined ? 255 : alpha];
  }

  // The views of a page: the solid model and the see-through map
  const SOLID = "solid";
  const THROUGH = "through";

  // Whether a view draws a group: a group can be for one view only
  function drawnIn(group, mode) {
    return !group.only || group.only === mode;
  }

  // The squares of a ground given as a grid of heights (rows from south to north, each
  // from west to east; null where the height is not known): a ring of five corners for
  // each square that has all four heights
  function squaresOf(grid) {
    const squares = [];
    const corner = (row, column) => {
      const z = grid.z[row * grid.columns + column];
      return z === null ? null : [grid.x + column * grid.step, grid.y + row * grid.step, z];
    };
    for (let row = 0; row < grid.rows - 1; row += 1) {
      for (let column = 0; column < grid.columns - 1; column += 1) {
        const ring = [
          corner(row, column), corner(row, column + 1), corner(row + 1, column + 1),
          corner(row + 1, column),
        ];
        if (ring.every(Boolean)) squares.push({ r: ring.concat([ring[0]]) });
      }
    }
    return squares;
  }

  // What a tapped item is: its own text, or for a line of the network its name, its
  // element (e: 1 for a relation, 2 for a node, such as a lift) with its highway
  // value, and its levels (names and highway values are numbers into the tables of
  // the data)
  function textOf(item, tables) {
    if (!item) return "";
    if (item.t !== undefined) return item.t;
    if (item.w === undefined) return "";
    const lines = [];
    if (item.n !== undefined) lines.push(tables.names[item.n]);
    lines.push(["way ", "relation ", "node "][item.e || 0] + item.w + " · " + tables.highways[item.h]);
    if (item.a !== undefined) {
      lines.push(item.c === undefined ? "level " + item.a : "levels " + item.a + " → " + item.c);
    }
    return lines.join("\n");
  }

  // The layer of a group of lines: as wide as a path on the ground, within limits on
  // the screen, and in the see-through view paler below ground (b). A group drawn
  // always (the route) is never hidden by what is in front
  function linesOf(group, items, mode, placed) {
    const above = colour(group.colour, group.alpha);
    const below = colour(group.colour, Math.round(group.alpha * group.belowShare));
    return new deck.PathLayer(
      Object.assign({}, placed, {
        id: "lines-" + group.name,
        data: items,
        getPath: (item) => item.p,
        getColor: mode === THROUGH ? (item) => (item.b ? below : above) : above,
        getWidth: group.metres,
        widthUnits: "meters",
        widthMinPixels: group.minPixels,
        widthMaxPixels: group.maxPixels,
        billboard: true,
        jointRounded: true,
        capRounded: Boolean(group.rounded),
        pickable: true,
        parameters: group.always ? { depthTest: false } : {},
        updateTriggers: { getColor: mode },
      })
    );
  }

  // The deck.gl layers of a group of the data in a view; none when the group is
  // switched off in shown (a Map of groups) or the view does not draw it.
  // Solid: the ground hides what is below it. See-through: a map with the network
  // over and under it; the ground hides nothing. Heights are drawn stretch times
  // taller than to scale.
  function layersOfGroup(group, shown, mode, stretch) {
    if (!shown.get(group) || !drawnIn(group, mode)) return [];
    const items = group.items;
    const hidesNothing = mode === THROUGH ? { depthMask: false } : {};
    const placed =
      stretch && stretch !== 1
        ? { modelMatrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, stretch, 0, 0, 0, 0, 1] }
        : {};
    if (group.kind === "ground") {
      return [
        new deck.PolygonLayer(
          Object.assign({}, placed, {
            id: "ground-" + group.name,
            data: items,
            getPolygon: (item) => item.r,
            getFillColor: colour(group.colour),
            stroked: false,
            parameters: hidesNothing,
          })
        ),
      ];
    }
    if (group.kind === "lines") return [linesOf(group, items, mode, placed)];
    // points mark places (the ends of a route, entrances) and are drawn over
    // everything, so that nothing hides them
    if (group.kind === "points") {
      return [
        new deck.ScatterplotLayer(
          Object.assign({}, placed, {
            id: "points-" + group.name,
            data: items,
            getPosition: (item) => item.c,
            getFillColor: colour(group.colour),
            getRadius: group.width,
            radiusUnits: "pixels",
            billboard: true,
            pickable: true,
            parameters: { depthTest: false },
          })
        ),
      ];
    }
    return [];
  }

  // The order in which the kinds of groups are drawn in the see-through view: the map
  // first, as its ground hides nothing, then what is on and in it, where what is in
  // front still hides what is behind. In the solid view the groups keep their order,
  // but the points come last, so that nothing is drawn over them
  const DRAWN = { ground: 0, lines: 4, points: 5 };
  const POINTS_LAST = { points: 1 };

  // The layers of the data in a view ("solid" or "through") of the groups that shown
  // (a Map) has switched on, with the heights drawn stretch times taller
  function layersOf(data, shown, mode, stretch) {
    const order = mode === THROUGH ? DRAWN : POINTS_LAST;
    const rank = (group) => order[group.kind] || 0;
    const groups = data.groups.slice().sort((one, other) => rank(one) - rank(other));
    return groups.reduce(
      (all, group) => all.concat(layersOfGroup(group, shown, mode, stretch)),
      []
    );
  }

  Object.assign(view, { SOLID, THROUGH, colour, drawnIn, squaresOf, textOf, layersOf });
})((window.pyrosm3d = window.pyrosm3d || {}));
