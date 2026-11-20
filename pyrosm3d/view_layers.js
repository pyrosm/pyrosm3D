// The deck.gl layers of a page of pyrosm3d: each group of the page's data (the ground,
// floors, outlines, see-through walls, lines and points; all in metres from the middle
// of the data, x east, y north, z up) as the layers that draw it in one of the page's
// views: the solid model, the see-through map, or the indoor view.
(function (view) {
  "use strict";

  // A colour of the data ("#rrggbb") as deck.gl takes it, with its opacity (0 to 255)
  function colour(hex, alpha) {
    const part = (at) => parseInt(hex.slice(at, at + 2), 16);
    return [part(1), part(3), part(5), alpha === undefined ? 255 : alpha];
  }

  // The rings of items as lines, each where it is: the outlines of floors. Kept for
  // each list of items
  const outlines = new WeakMap();
  function outlinesOf(items) {
    if (!outlines.has(items)) outlines.set(items, items.flatMap((item) => item.r));
    return outlines.get(items);
  }

  // The views of a page: the solid model, the see-through map, and on a page with
  // indoor elements the indoor view
  const SOLID = "solid";
  const THROUGH = "through";
  const INDOOR = "indoor";

  // Whether a view draws a group: the indoor view leaves out the ground, and a group
  // can be for one view only
  function drawnIn(group, mode) {
    if (mode === INDOOR && group.kind === "ground") return false;
    return !group.only || group.only === mode;
  }

  // Whether an item of a group is shown when one level is picked: a line on the levels
  // that the data lists for it (ls), else on its first level (a; a line without one is
  // at street level, 0); anything else on its own level (a column through several
  // floors has none, and is shown only with all levels)
  function onLevel(group, item, level) {
    if (group.kind === "lines") {
      return (item.ls || [item.a === undefined ? 0 : item.a]).indexOf(level) >= 0;
    }
    return item.l === level;
  }

  // The items of a group that a view draws: all of them, or in the indoor view those
  // that it does not leave out (o), on the picked level when there is one
  function itemsIn(group, mode, level) {
    if (mode !== INDOOR) return group.items;
    const key = level === null || level === undefined ? "all" : String(level);
    group.indoors = group.indoors || {};
    if (!group.indoors[key]) {
      group.indoors[key] = group.items.filter(
        (item) => !item.o && (key === "all" || onLevel(group, item, level))
      );
    }
    return group.indoors[key];
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

  // The dashes of the kinds of line that the indoor view dashes, each as the lengths
  // of a dash and of a gap in widths of the line; the library's extension that draws
  // them is made once
  const DASHES = { dash: [3, 2], dot: [1, 1.5] };
  let dashExtension = null;
  function dashing() {
    dashExtension = dashExtension || new deck.PathStyleExtension({ dash: true });
    return dashExtension;
  }

  // The layer of a group of lines: in the indoor view with the colour, the width in
  // pixels and the dash of its look there (plot); else as wide as a path on the
  // ground, within limits on the screen, and in the see-through view paler below
  // ground (b). A group drawn always (the route) is never hidden by what is in front
  function linesOf(group, items, mode, placed) {
    const plotted = mode === INDOOR && group.plot;
    const dashes = plotted ? DASHES[group.plot[2]] : null;
    const dashed = dashes ? { extensions: [dashing()], getDashArray: dashes } : {};
    const above = plotted ? colour(group.plot[0]) : colour(group.colour, group.alpha);
    const below = colour(group.colour, Math.round(group.alpha * group.belowShare));
    return new deck.PathLayer(
      Object.assign({}, placed, dashed, {
        id: "lines-" + group.name,
        data: items,
        getPath: (item) => item.p,
        getColor: mode === THROUGH ? (item) => (item.b ? below : above) : above,
        getWidth: plotted ? group.plot[1] : group.metres,
        widthUnits: plotted ? "pixels" : "meters",
        widthMinPixels: plotted ? 0 : group.minPixels,
        widthMaxPixels: plotted ? 1000 : group.maxPixels,
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
  // over and under it; the ground, the floors and the outlines hide nothing. Indoor:
  // no ground; the floors are opaque plates, only the items on the picked level are
  // drawn when there is one. Heights are drawn stretch times taller than to scale. A
  // group of glass (the walls of rooms, stairwells, lift shafts) is see-through blocks
  // in all three, which hide nothing themselves.
  function layersOfGroup(group, shown, mode, level, stretch) {
    if (!shown.get(group) || !drawnIn(group, mode)) return [];
    const indoor = mode === INDOOR;
    const items = itemsIn(group, mode, level);
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
    if (group.kind === "floors") {
      const alpha = indoor ? 255 : mode === THROUGH ? group.throughAlpha : group.alpha;
      const fills = {};
      Object.keys(group.colours).forEach((kind) => {
        fills[kind] = colour(group.colours[kind], alpha);
      });
      return [
        new deck.PolygonLayer(
          Object.assign({}, placed, {
            id: "floors-" + group.name,
            data: items,
            getPolygon: (item) => item.r,
            getFillColor: (item) => fills[item.k],
            stroked: false,
            pickable: true,
            parameters: hidesNothing,
            updateTriggers: { getFillColor: mode },
          })
        ),
        new deck.PathLayer(
          Object.assign({}, placed, {
            id: "outlines-" + group.name,
            data: outlinesOf(items),
            getPath: (ring) => ring,
            getColor: colour(group.edge, indoor ? 255 : group.edgeAlpha),
            getWidth: indoor && group.plotEdge !== undefined ? group.plotEdge : group.edgeWidth,
            widthUnits: "pixels",
            billboard: true,
            parameters: hidesNothing,
          })
        ),
      ];
    }
    if (group.kind === "outlines") {
      return [
        new deck.PathLayer(
          Object.assign({}, placed, {
            id: "frames-" + group.name,
            data: items,
            getPath: (item) => item.p,
            getColor: colour(group.colour),
            getWidth: group.width,
            widthUnits: "pixels",
            billboard: true,
            parameters: hidesNothing,
          })
        ),
      ];
    }
    if (group.kind === "glass") {
      return [
        new deck.PolygonLayer(
          Object.assign({}, placed, {
            id: "glass-" + group.name,
            data: items,
            getPolygon: (item) => item.r,
            extruded: true,
            getElevation: (item) => item.h,
            getFillColor: colour(group.colour, group.alpha),
            pickable: Boolean(group.pickable),
            material: { ambient: 0.55, diffuse: 0.7, shininess: 2, specularColor: [20, 20, 20] },
            parameters: { depthMask: false },
          })
        ),
      ];
    }
    if (group.kind === "lines") return [linesOf(group, items, mode, placed)];
    // points mark places (the ends of a route, doors, entrances) and are drawn over
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
  // front still hides what is behind. In the other views the groups keep their order,
  // but the points come last, so that nothing is drawn over them
  const DRAWN = { ground: 0, floors: 2, outlines: 2, glass: 3, lines: 4, points: 5 };
  const POINTS_LAST = { points: 1 };

  // The layers of the data in a view ("solid", "through" or "indoor") of the groups
  // that shown (a Map) has switched on, in the indoor view on the picked level (null:
  // all), with the heights drawn stretch times taller
  function layersOf(data, shown, mode, level, stretch) {
    const order = mode === THROUGH ? DRAWN : POINTS_LAST;
    const rank = (group) => order[group.kind] || 0;
    const groups = data.groups.slice().sort((one, other) => rank(one) - rank(other));
    return groups.reduce(
      (all, group) => all.concat(layersOfGroup(group, shown, mode, level, stretch)),
      []
    );
  }

  Object.assign(view, {
    SOLID, THROUGH, INDOOR, colour, drawnIn, itemsIn, squaresOf, textOf, layersOf,
  });
})((window.pyrosm3d = window.pyrosm3d || {}));
