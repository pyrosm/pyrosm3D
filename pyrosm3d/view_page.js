// The page script of pyrosm3d's views: starts deck.gl on the data in the page (see
// pyrosm3d.view.View) with a camera that turns around a point, and wires the page's
// controls: the views, the level of the indoor view, "True heights", the sliders and
// buttons of the camera, the list of layers, and what a tapped item is. Errors show
// in a box on the page.
(function (view) {
  "use strict";

  const byId = (id) => document.getElementById(id);

  function report(message) {
    const box = byId("error");
    box.hidden = false;
    box.textContent = "This page hit an error: " + message;
  }
  window.addEventListener("error", (event) => report(event.message));

  // Where the indoor view starts: seen from the south-east and above, from so far that
  // the box of the view fits the screen
  const INDOOR_START = {
    tilt: 27, // degrees above the horizon
    turn: -43, // the compass direction of the look
    across: 1.45, // how many of the box's longest sides the width of the screen holds
    down: 0.9, // and its height
  };
  const radians = (degrees) => (degrees * Math.PI) / 180;

  function begin(data) {
    // the view that the page opens in and, in the indoor view, the picked level
    // (null: all levels)
    let mode = data.mode || view.SOLID;
    if (mode === view.INDOOR && !data.indoor) mode = view.SOLID;
    let level = null;
    // what is switched on: in the views of the city, and in the indoor view, where
    // every kind of line of the network is on at the start
    const shownBy = { solid: new Map(), indoor: new Map() };
    data.groups.forEach((group) => {
      if (group.grid) group.items = view.squaresOf(group.grid);
      shownBy.solid.set(group, Boolean(group.visible));
      shownBy.indoor.set(group, Boolean(group.plot) || Boolean(group.visible));
    });
    const shown = () => (mode === view.INDOOR ? shownBy.indoor : shownBy.solid);
    const tilt = byId("tilt");
    const turn = byId("turn");
    const info = byId("info");
    const canvas = byId("canvas");
    const stage = byId("stage");
    let state = Object.assign({ fovy: view.FLY_FOVY, walk: false }, data.view);
    // the height of the screen in pixels
    const tall = () => canvas.clientHeight || state.height || 800;
    // "True heights" in the views of the city (solid and see-through) and in the indoor
    // view: the city is to scale at the start, the indoor view draws its heights taller
    const toScale = { city: true, indoor: false };
    const scaleOf = () => (mode === view.INDOOR ? "indoor" : "city");
    // how much taller than to scale the view draws heights when "True heights" is off
    const taller = () => (mode === view.INDOOR ? data.indoor.stretch : data.stretch) || 1;
    // how much taller than to scale the heights are drawn now; a walker sees them to
    // scale
    const stretched = () => (state.walk || toScale[scaleOf()] ? 1 : taller());
    // the zoom at which the screen holds `across` metres in its width and `down` in its
    // height, within the limits of the view
    const zoomThatFits = (across, down) => {
      const wide = canvas.clientWidth || window.innerWidth || 800;
      const fits = Math.log2(Math.min(wide / across, tall() / down));
      const lowest = data.view.minZoom === undefined ? -Infinity : data.view.minZoom;
      const highest = data.view.maxZoom === undefined ? Infinity : data.view.maxZoom;
      return Math.max(lowest, Math.min(highest, fits));
    };
    const indoorStart = () => {
      const box = data.indoor.box;
      const longest = Math.max(box[2] - box[0], box[3] - box[1]);
      return {
        target: [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2, data.indoor.ground * stretched()],
        rotationX: INDOOR_START.tilt,
        rotationOrbit: INDOOR_START.turn,
        zoom: zoomThatFits(INDOOR_START.across * longest, INDOOR_START.down * longest),
      };
    };
    // the view of the data; with data.fit (metres from west to east and from south to
    // north) from so far that so much of the ground fits the screen at the view's tilt
    // and turn: across the screen and, foreshortened by the tilt, up it
    const cityStart = () => {
      const target = [data.view.target[0], data.view.target[1], data.view.target[2] * stretched()];
      if (!data.fit) return Object.assign({}, data.view, { target });
      const lean = Math.sin(radians(Math.abs(data.view.rotationX)));
      const turn = radians(data.view.rotationOrbit || 0);
      const [east, north] = data.fit;
      const across = Math.abs(east * Math.cos(turn)) + Math.abs(north * Math.sin(turn));
      const up = Math.abs(east * Math.sin(turn)) + Math.abs(north * Math.cos(turn));
      return Object.assign({}, data.view, { target, zoom: zoomThatFits(across, up * lean) });
    };
    const startView = () => (mode === view.INDOOR ? indoorStart() : cityStart());
    state = Object.assign(state, startView());
    // the sliders show the view: its tilt, and the compass direction of its look
    // (-180 to 180 degrees, north at 0)
    const showTilt = () => {
      tilt.value = String(Math.round(state.rotationX));
      turn.value = String(Math.round(((((state.rotationOrbit + 180) % 360) + 360) % 360) - 180));
    };

    // the ground and the walkways that a walker follows (the walkways are sorted out at
    // the first walk)
    const ground = data.groups.find((group) => group.kind === "ground" && group.grid);
    let walkways = null;
    const network = () => {
      walkways = walkways || view.walkwaysOf(data.groups);
      return walkways;
    };
    const climb = view.climbOver(network, ground && ground.grid);

    const instance = new deck.Deck({
      canvas,
      width: "100%",
      height: "100%",
      views: new deck.OrbitView({ id: "main", orbitAxis: "Z" }),
      // one finger moves, a pinch zooms and turns, three fingers tilt; no zoom on a
      // double tap
      controller: {
        type: view.freeController(climb),
        dragMode: "pan",
        touchRotate: true,
        dragRotate: true,
        inertia: 300,
        doubleClickZoom: false,
      },
      viewState: state,
      pickingRadius: 8,
      layers: view.layersOf(data, shown(), mode, level, stretched()),
      onViewStateChange: (change) => {
        state = change.viewState;
        instance.setProps({ viewState: state });
        showTilt();
      },
      getTooltip: (picked) => {
        const text = view.textOf(picked.object, data.tables);
        return text ? { text } : null;
      },
      onClick: (picked) => {
        const text = view.textOf(picked.object, data.tables);
        info.hidden = !text;
        info.textContent = text;
      },
      onError: (error) => report(error && error.message ? error.message : String(error)),
      onResize: (size) => resized(size.height),
    });

    // a drag with the right mouse button turns the view: no menu of the browser then
    canvas.addEventListener("contextmenu", (event) => event.preventDefault());

    function show() {
      instance.setProps({ viewState: state });
      showTilt();
    }
    // flying, the view changes as told; walking, it turns where the walker stands
    function look(change) {
      state = state.walk ? view.turnedView(state, change, tall()) : Object.assign({}, state, change);
      show();
    }
    function draw() {
      instance.setProps({ layers: view.layersOf(data, shown(), mode, level, stretched()) });
    }
    // The view keeps its place when the heights are drawn taller or back to scale: the
    // point that it turns around moves with them. before is how much taller they were
    // drawn
    function withHeights(before) {
      const now = stretched();
      if (now === before) return;
      const target = [state.target[0], state.target[1], (state.target[2] * now) / before];
      state = Object.assign({}, state, { target });
    }

    // The choice of the view, and what goes with it: the level picker and the white
    // ground of the indoor view, and the layers that the view draws in the list
    const viewButtons = { solid: byId("viewSolid"), through: byId("viewThrough"), indoor: byId("viewIndoor") };
    const levelRow = byId("levels");
    const levelPick = byId("level");
    const trueHeights = byId("trueHeights");
    const heightsSwitch = byId("heights");
    const entries = [];
    function showMode() {
      Object.keys(viewButtons).forEach((name) => {
        viewButtons[name].className = name === mode ? "on" : "";
        viewButtons[name].setAttribute("aria-pressed", String(name === mode));
      });
      viewButtons.indoor.hidden = !data.indoor;
      levelRow.hidden = mode !== view.INDOOR;
      heightsSwitch.hidden = taller() === 1;
      trueHeights.checked = toScale[scaleOf()];
      stage.style.background = mode === view.INDOOR ? data.indoor.background : "";
      entries.forEach((entry) => {
        entry.label.hidden = !view.drawnIn(entry.group, mode);
        entry.box.checked = Boolean(shown().get(entry.group));
      });
    }
    function setMode(next) {
      if (next === mode || (next === view.INDOOR && !data.indoor)) return;
      const before = stretched();
      mode = next;
      withHeights(before);
      showMode();
      draw();
      show();
    }
    // The heights of the view that is on to scale (on) or drawn taller; the view keeps
    // its place. The city views and the indoor view each remember their own choice
    function setToScale(on) {
      const before = stretched();
      toScale[scaleOf()] = Boolean(on);
      trueHeights.checked = toScale[scaleOf()];
      withHeights(before);
      draw();
      show();
    }
    // One level of the indoor view, or all of them (null): the view moves to the
    // height of the picked level
    function setLevel(next) {
      level = next === null || next === undefined || next === "" ? null : Number(next);
      levelPick.value = level === null ? "" : String(level);
      const picked = level === null ? null : data.indoor.levels.find((entry) => entry[0] === level);
      if (picked && !state.walk) {
        state = Object.assign({}, state, {
          target: [state.target[0], state.target[1], picked[1] * stretched()],
        });
      }
      draw();
      show();
    }

    // Walking starts at the point that the flying view turns around, on the walkway or
    // the terrain there, looking the way the view looks; it ends in a flying view that
    // turns around the walker's feet
    const stroll = byId("walk");
    const moves = byId("moves");
    const flyOnly = [byId("above"), byId("side")];
    let flying = null;
    // the zoom at which the point that a walker's view turns around is WALK.reach ahead
    // of the eye on a screen high pixels high
    const walkingZoom = (high) =>
      Math.log2(high / (2 * Math.tan(radians(view.WALK.fovy) / 2) * view.WALK.reach));
    // a screen of another height (a phone turned): the walker stays where it stands
    let shownHeight = tall();
    function resized(high) {
      if (state.walk && high !== shownHeight) {
        const eye = view.eyeOf(state, shownHeight);
        const zoom = walkingZoom(high);
        state = view.seenFrom(Object.assign({}, state, { zoom, minZoom: zoom, maxZoom: zoom }), eye, high);
        instance.setProps({ viewState: state });
      }
      shownHeight = high;
    }
    function walk(on) {
      if (on === Boolean(state.walk)) return;
      const high = tall();
      shownHeight = high;
      const before = stretched();
      const WALK = view.WALK;
      if (on) {
        flying = {};
        ["zoom", "rotationX", "minZoom", "maxZoom", "minRotationX", "maxRotationX"].forEach((key) => {
          flying[key] = state[key];
        });
        const feet = view.startingAt(
          network(), ground && ground.grid, state.target[0], state.target[1], state.target[2] / before
        );
        const eye = [state.target[0], state.target[1], feet + WALK.eye];
        const zoom = walkingZoom(high);
        const walking = Object.assign({}, state, {
          walk: true, fovy: WALK.fovy, rotationX: WALK.down, zoom, minZoom: zoom, maxZoom: zoom,
          minRotationX: -WALK.tilt, maxRotationX: WALK.tilt,
        });
        state = view.seenFrom(walking, eye, high);
      } else {
        const eye = view.eyeOf(state, high);
        state = Object.assign({}, state, flying, {
          walk: false, fovy: view.FLY_FOVY, target: [eye[0], eye[1], eye[2] - WALK.eye],
        });
        withHeights(1);
      }
      if (stretched() !== before) draw();
      stroll.checked = on;
      trueHeights.disabled = on;
      moves.hidden = !on;
      flyOnly.forEach((button) => {
        button.hidden = on;
      });
      tilt.min = String(on ? -WALK.tilt : (state.minRotationX === undefined ? -90 : state.minRotationX));
      tilt.max = String(on ? WALK.tilt : (state.maxRotationX === undefined ? 90 : state.maxRotationX));
      show();
    }
    // the walker goes metres ahead (back when negative)
    function step(metres) {
      if (!state.walk) return;
      state = view.walkedView(state, metres, tall(), climb);
      show();
    }
    // a button that walks for as long as it is held, faster the longer
    function walksWhileHeld(button, direction) {
      let since = null;
      let last = null;
      let frame = null;
      const move = (now) => {
        const seconds = Math.min(0.1, (now - last) / 1000);
        const speed = Math.min(view.WALK.fast, view.WALK.slow + (view.WALK.gain * (now - since)) / 1000);
        last = now;
        step(direction * speed * seconds);
        frame = requestAnimationFrame(move);
      };
      button.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        if (frame !== null) return;
        since = performance.now();
        last = since;
        frame = requestAnimationFrame(move);
      });
      ["pointerup", "pointercancel", "pointerleave"].forEach((type) => {
        button.addEventListener(type, () => {
          if (frame !== null) cancelAnimationFrame(frame);
          frame = null;
        });
      });
    }
    walksWhileHeld(byId("ahead"), 1);
    walksWhileHeld(byId("back"), -1);
    stroll.addEventListener("change", () => walk(stroll.checked));
    trueHeights.addEventListener("change", () => setToScale(trueHeights.checked));
    showTilt();
    // the tilt counts degrees above the horizon: 90 from above, 0 from the side,
    // negative from below; walking, it is how far the look is turned down
    tilt.addEventListener("input", () => look({ rotationX: Number(tilt.value) }));
    turn.addEventListener("input", () => look({ rotationOrbit: Number(turn.value) }));
    byId("north").addEventListener("click", () => look({ rotationOrbit: 0 }));
    byId("above").addEventListener("click", () => look({ rotationX: 90, rotationOrbit: 0 }));
    byId("side").addEventListener("click", () => look({ rotationX: 0 }));
    byId("home").addEventListener("click", () => {
      walk(false);
      look(startView());
    });
    Object.keys(viewButtons).forEach((name) => {
      viewButtons[name].addEventListener("click", () => setMode(name));
    });
    if (data.indoor) {
      [["", "All levels"]]
        .concat(data.indoor.levels.map((entry) => [String(entry[0]), "Level " + entry[0]]))
        .forEach((choice) => {
          const option = document.createElement("option");
          option.value = choice[0];
          option.textContent = choice[1];
          levelPick.appendChild(option);
        });
      levelPick.addEventListener("change", () => setLevel(levelPick.value));
    }

    const list = byId("layers");
    data.groups.forEach((group) => {
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.addEventListener("change", () => {
        shown().set(group, box.checked);
        draw();
      });
      entries.push({ group, label, box });
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = group.colour;
      const name = document.createElement("span");
      name.textContent = group.name + " (" + group.items.length + ")";
      label.appendChild(box);
      label.appendChild(swatch);
      label.appendChild(name);
      list.appendChild(label);
    });
    showMode();
    return {
      instance, data, look, walk, step, resized, mode: setMode, level: setLevel,
      toScale: setToScale, state: () => ({ mode, level, stretch: stretched() }),
      view: () => state,
    };
  }

  function start() {
    const data = JSON.parse(byId("data").textContent);
    if (typeof deck === "undefined" || !deck.Deck) {
      report("the deck.gl library did not load.");
      return null;
    }
    return begin(data);
  }

  try {
    view.started = start();
  } catch (error) {
    report(error && error.message ? error.message : String(error));
  }
})((window.pyrosm3d = window.pyrosm3d || {}));
