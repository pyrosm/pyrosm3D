// Walking in pyrosm3d's views: where the camera of a walker stands and how it moves
// along the ground, the walkways of the network, stairs and ramps.
(function (view) {
  "use strict";

  // Walking: the camera stands on the ground or on a walkway and looks around from
  // there
  const WALK = {
    fovy: 75, // degrees of the field of view from top to bottom
    eye: 1.7, // metres from the walker's feet to the eye
    reach: 2, // metres from the eye to the point that the view turns around
    tilt: 60, // degrees that the look turns up and down at most
    down: 4, // degrees that the look is turned down at the start
    pinch: 30, // metres ahead for a pinch to twice the size
    step: 5, // metres of an arrow key
    turn: 10, // degrees of an arrow key
    slow: 8, // metres a second when a walk button is pressed
    gain: 12, // metres a second that each second of holding adds
    fast: 50, // metres a second at most
    near: 4, // metres to the side within which a walkway carries the walker
    window: 2.5, // metres up or down within which a walkway or the terrain is at the walker's feet
    start: [1, 2.5], // metres from the terrain within which a walk looks for a walkway to start on, nearest first
    slope: 1, // metres that the walker rises or falls at most in a metre walked
    pace: 1, // metres of the paces that a longer move is walked in
    cell: 8, // metres of the squares that the walkways are looked up by
  };
  const radians = (degrees) => (degrees * Math.PI) / 180;

  // From the point that the camera turns around to the camera, in metres: along the
  // view's angles (rotationX above the horizon; rotationOrbit the compass direction of
  // the look) as far as its zoom and field of view put it on a screen height pixels
  // high
  function cameraOffset(state, height) {
    const fovy = state.fovy || view.FLY_FOVY;
    const distance = height / (2 * Math.tan(radians(fovy) / 2) * Math.pow(2, state.zoom));
    const up = radians(state.rotationX);
    const around = radians(state.rotationOrbit);
    return [
      -distance * Math.cos(up) * Math.sin(around),
      -distance * Math.cos(up) * Math.cos(around),
      distance * Math.sin(up),
    ];
  }

  // Where the camera of a view state is
  function eyeOf(state, height) {
    const offset = cameraOffset(state, height);
    return state.target.map((value, axis) => value + offset[axis]);
  }

  // The view state with its camera at eye
  function seenFrom(state, eye, height) {
    const offset = cameraOffset(state, height);
    return Object.assign({}, state, { target: eye.map((value, axis) => value - offset[axis]) });
  }

  // A walking view state turned to angles, its camera staying where it is
  function turnedView(state, angles, height) {
    const next = Object.assign({}, state, angles);
    next.rotationX = Math.max(-WALK.tilt, Math.min(WALK.tilt, next.rotationX));
    return seenFrom(next, eyeOf(state, height), height);
  }

  // A walking view state moved metres in the direction of its look, from eye (by
  // default from where its camera is), pace by pace. climb(from, x, y) gives the
  // height of the eye at a place for a walker who comes from the eye place from (see
  // climbOver)
  function walkedView(state, metres, height, climb, eye) {
    let at = eye || eyeOf(state, height);
    const around = radians(state.rotationOrbit);
    const pace = Math.sign(metres) * Math.max(WALK.pace, Math.abs(metres) / 400);
    let left = Math.abs(metres);
    while (left > 1e-9) {
      const go = Math.abs(pace) < left ? pace : Math.sign(metres) * left;
      const x = at[0] + Math.sin(around) * go;
      const y = at[1] + Math.cos(around) * go;
      at = [x, y, climb(at, x, y)];
      left -= Math.abs(go);
    }
    return seenFrom(state, at, height);
  }

  // The walkways of the data, for walking: the stretches between the points of every
  // line of the network (not of a line drawn always, such as the route, which runs
  // along them, and nothing that goes straight up, such as a lift) as x, y, z of both
  // ends, and for each square of WALK.cell metres the stretches that pass it
  function walkwaysOf(groups) {
    const ends = [];
    const cells = new Map();
    const key = (column, row) => (column + 32768) * 65536 + (row + 32768);
    groups.forEach((group) => {
      if (group.kind !== "lines" || group.always) return;
      group.items.forEach((item) => {
        for (let at = 1; at < item.p.length; at += 1) {
          const one = item.p[at - 1];
          const other = item.p[at];
          const length = Math.hypot(other[0] - one[0], other[1] - one[1]);
          if (length < 0.05) continue;
          const stretch = ends.length / 6;
          ends.push(one[0], one[1], one[2], other[0], other[1], other[2]);
          const pieces = Math.ceil(length / (WALK.cell / 2));
          let last = null;
          for (let piece = 0; piece <= pieces; piece += 1) {
            const share = piece / pieces;
            const cell = key(
              Math.floor((one[0] + (other[0] - one[0]) * share) / WALK.cell),
              Math.floor((one[1] + (other[1] - one[1]) * share) / WALK.cell)
            );
            if (cell === last) continue;
            last = cell;
            if (!cells.has(cell)) cells.set(cell, []);
            cells.get(cell).push(stretch);
          }
        }
      });
    });
    return { ends: new Float32Array(ends), cells, key };
  }

  // The height of the walkway nearest to a place, among those within WALK.near metres
  // to the side whose height there is within window (WALK.window by default) of feet;
  // null when there is none
  function walkwayAt(walkways, x, y, feet, window) {
    const within = window === undefined ? WALK.window : window;
    const column = Math.floor(x / WALK.cell);
    const row = Math.floor(y / WALK.cell);
    const ends = walkways.ends;
    let best = null;
    let least = WALK.near;
    for (let across = -1; across <= 1; across += 1) {
      for (let up = -1; up <= 1; up += 1) {
        const passing = walkways.cells.get(walkways.key(column + across, row + up)) || [];
        for (let at = 0; at < passing.length; at += 1) {
          const from = passing[at] * 6;
          const east = ends[from + 3] - ends[from];
          const north = ends[from + 4] - ends[from + 1];
          const along = ((x - ends[from]) * east + (y - ends[from + 1]) * north) / (east * east + north * north);
          const share = Math.max(0, Math.min(1, along));
          const away = Math.hypot(x - ends[from] - east * share, y - ends[from + 1] - north * share);
          const height = ends[from + 2] + (ends[from + 5] - ends[from + 2]) * share;
          if (away <= least && Math.abs(height - feet) <= within) {
            least = away;
            best = height;
          }
        }
      }
    }
    return best;
  }

  // The height of the ground of a grid (see view.squaresOf) at a place, between the
  // four corners around it; null outside the grid and where a corner has no height.
  // The heights are those of the drawn surface, or others for the same corners, such as
  // the terrain (t of a grid), which the drawn surface lies under
  function groundAt(grid, x, y, heights) {
    const of = heights || grid.z;
    const across = (x - grid.x) / grid.step;
    const up = (y - grid.y) / grid.step;
    if (!(across >= 0 && up >= 0 && across <= grid.columns - 1 && up <= grid.rows - 1)) return null;
    const column = Math.min(Math.floor(across), grid.columns - 2);
    const row = Math.min(Math.floor(up), grid.rows - 2);
    const corner = (line, place) => of[line * grid.columns + place];
    const corners = [
      corner(row, column), corner(row, column + 1), corner(row + 1, column),
      corner(row + 1, column + 1),
    ];
    if (corners.some((height) => height === null)) return null;
    const east = across - column;
    const north = up - row;
    return (
      (corners[0] * (1 - east) + corners[1] * east) * (1 - north) +
      (corners[2] * (1 - east) + corners[3] * east) * north
    );
  }

  // Where a walk starts at a place: on the nearest walkway there within the first band
  // of WALK.start of the terrain's height, else within the next band, else on the
  // terrain, else at the height given; the height of the walker's feet
  function startingAt(walkways, grid, x, y, otherwise) {
    const land = grid ? groundAt(grid, x, y, grid.t) : null;
    const base = land === null ? otherwise : land;
    for (let band = 0; band < WALK.start.length; band += 1) {
      const way = walkwayAt(walkways, x, y, base, WALK.start[band]);
      if (way !== null) return way;
    }
    return base;
  }

  // How a walker rises and falls: the function climb(from, x, y), the height of the
  // eye at a place for a walker whose eye comes from the place from. The feet follow
  // the nearest walkway at their own height, so stairs, escalators and ramps take the
  // walker down and up; away from the walkways they follow the terrain when the
  // walker came along it, and otherwise keep their height. The height changes by
  // WALK.slope metres at most in a metre walked. walkways() gives the walkways (see
  // walkwaysOf), grid the ground with its terrain (see groundAt), either may be
  // missing
  function climbOver(walkways, grid) {
    return (from, x, y) => {
      const feet = from[2] - WALK.eye;
      let goal = walkways ? walkwayAt(walkways(), x, y, feet) : null;
      if (goal === null && grid) {
        const before = groundAt(grid, from[0], from[1], grid.t);
        const here = groundAt(grid, x, y, grid.t);
        const onTerrain = before !== null && Math.abs(before - feet) <= WALK.window;
        if (onTerrain && here !== null) goal = here;
      }
      if (goal === null) return from[2];
      const most = WALK.slope * Math.hypot(x - from[0], y - from[1]);
      return from[2] + Math.max(-most, Math.min(most, goal - feet));
    };
  }

  Object.assign(view, {
    WALK, eyeOf, seenFrom, turnedView, walkedView, walkwaysOf, walkwayAt, groundAt, startingAt,
    climbOver,
  });
})((window.pyrosm3d = window.pyrosm3d || {}));
