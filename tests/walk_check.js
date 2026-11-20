// Checks walking on a page of a pyrosm3d view with the real deck.gl library (no
// drawing; there is no WebGL here). The page's data is made by the test: a street at
// 10 m along y = 0, stairs from it at x = 50 down to 5 m at y = 20, a tunnel on from
// there, a bridge at 16 m across the tunnel at y = 30, a lift at x = 60 from 10 m to
// 30 m, a route, and terrain at 10 m with the drawn ground at 9.5 m. Exits with an
// error when a check fails.
//
// usage: node walk_check.js <page.html> <deck.gl bundle>
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const [file, bundle] = process.argv.slice(2);
const page = fs.readFileSync(file, "utf8");
global.window = global;
global.self = global;
global.document = {
  createElement: () => ({ style: {}, getContext: () => null }),
  readyState: "complete", addEventListener() {}, body: { appendChild() {} },
};
if (!global.navigator) global.navigator = { userAgent: "node" };
global.addEventListener = global.addEventListener || (() => {});
const real = require(path.resolve(bundle));

const W = 390;
const H = 844;
function element(id) {
  return {
    id, hidden: false, textContent: "", value: "", checked: false, disabled: false,
    className: "", min: "", max: "", style: {}, children: [], attributes: {}, listeners: {},
    appendChild(child) { this.children.push(child); },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(type, listener) { this.listeners[type] = listener; },
    fire(type) { this.listeners[type]({ preventDefault() {} }); },
  };
}
const elements = {};
const byId = (id) => {
  elements[id] = elements[id] || element(id);
  return elements[id];
};
const opening = '<script id="data" type="application/json">';
const from = page.indexOf(opening) + opening.length;
byId("data").textContent = page.slice(from, page.indexOf("</script>", from));
byId("error").hidden = true;
Object.assign(byId("canvas"), { clientWidth: W, clientHeight: H });
let made = null;
const library = Object.defineProperty(Object.create(real), "Deck", {
  value: class {
    constructor(props) { made = this; this.props = props; }
    setProps(props) { Object.assign(this.props, props); }
  },
});
const context = {
  document: { getElementById: byId, createElement: (tag) => element(tag) },
  deck: library, console, addEventListener() {}, WeakMap, Map, Float32Array,
};
context.window = context;
vm.createContext(context);
vm.runInContext(page.slice(page.lastIndexOf("<script>") + 8, page.lastIndexOf("</script>")), context);
const view = context.pyrosm3d;
const started = view.started;
assert.ok(started, "the page started: " + byId("error").textContent);
const WALK = view.WALK;
const close = (a, b, by, what) => assert.ok(Math.abs(a - b) <= by, what + ": " + a + " against " + b);
const apart = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
// values made by the page's script, as plain values of this script (they have the
// prototypes of the page's context)
const plain = (value) => JSON.parse(JSON.stringify(value));
const orbit = made.props.views;
const makeViewport = (props) => orbit.makeViewport({ width: W, height: H, viewState: props });
const Free = made.props.controller.type;
const controller = new Free({ eventManager: { on() {}, off() {} }, makeViewport, onViewStateChange() {}, onStateChange() {} });
const State = controller.ControllerState;
const stateOf = (state) => new State(Object.assign({ makeViewport, width: W, height: H }, state));

// Flying: the camera is where the page's own arithmetic puts it
const flyView = started.view();
assert.strictEqual(flyView.fovy, view.FLY_FOVY);
assert.strictEqual(flyView.walk, false);
let viewport = makeViewport(flyView);
assert.ok(apart(view.eyeOf(flyView, H), viewport.cameraPosition) < 1e-6 * apart(viewport.cameraPosition, flyView.target), "the eye of the flying view");

// Walking starts on the ground at the point the flying view turned around (on the
// terrain at 10 m beside the street, which is in reach), looking the way it looked,
// with a wide field of view
started.walk(true);
let state = started.view();
assert.strictEqual(state.walk, true);
assert.strictEqual(state.fovy, WALK.fovy);
assert.strictEqual(state.rotationOrbit, flyView.rotationOrbit);
assert.strictEqual(state.rotationX, WALK.down);
let eye = view.eyeOf(state, H);
close(eye[0], flyView.target[0], 1e-9, "the walker stands at the centre of the flying view, x");
close(eye[1], flyView.target[1], 1e-9, "the walker stands at the centre of the flying view, y");
close(eye[2], 10 + WALK.eye, 1e-9, "the eye is over the street");
viewport = makeViewport(state);
assert.ok(apart(eye, viewport.cameraPosition) < 1e-6, "the eye of the walking view is the library's camera");
close(apart(eye, state.target), WALK.reach, 1e-9, "metres from the eye to the point the view turns around");
assert.strictEqual(byId("moves").hidden, false);
assert.strictEqual(byId("above").hidden, true);
assert.strictEqual(byId("side").hidden, true);
assert.strictEqual(byId("walk").checked, true);
assert.strictEqual(byId("trueHeights").disabled, true);
assert.deepStrictEqual([byId("tilt").min, byId("tilt").max], [String(-WALK.tilt), String(WALK.tilt)]);

// A screen of another height (a phone turned): the walker stays where it stands, and
// the point the view turns around stays WALK.reach ahead
started.resized(600);
close(apart(view.eyeOf(started.view(), 600), eye), 0, 1e-6, "the walker stays on a lower screen");
close(apart(view.eyeOf(started.view(), 600), started.view().target), WALK.reach, 1e-9, "the reach on a lower screen");
started.resized(H);
close(apart(view.eyeOf(started.view(), H), eye), 0, 1e-6, "and back");
state = started.view();

// A drag looks around: the walker stays, and the look turns against the finger, up
// to its limits
const moved = stateOf(state).panStart({ pos: [200, 400] }).pan({ pos: [260, 450] }).getViewportProps();
assert.ok(apart(view.eyeOf(moved, H), eye) < 1e-9, "the walker stays while looking around");
assert.ok(moved.rotationOrbit < state.rotationOrbit && moved.rotationX < state.rotationX, "the look turns against the finger");
const up = stateOf(state).panStart({ pos: [200, 100] }).pan({ pos: [200, 5000] }).getViewportProps();
assert.strictEqual(up.rotationX, -WALK.tilt);

// A pinch walks 30 m ahead for twice the size, counted from where it began; the
// wheel walks back; the arrow keys walk and turn
const ahead = [Math.sin((state.rotationOrbit * Math.PI) / 180), Math.cos((state.rotationOrbit * Math.PI) / 180)];
const walkedFrom = (start, metres, end, what) => {
  close(end[0], start[0] + ahead[0] * metres, 1e-6, what + ", x");
  close(end[1], start[1] + ahead[1] * metres, 1e-6, what + ", y");
};
let walking = stateOf(state).zoomStart({ pos: [195, 422] }).zoom({ pos: [195, 422], scale: 2 });
walkedFrom(eye, WALK.pinch, view.eyeOf(walking.getViewportProps(), H), "a pinch to twice the size");
assert.strictEqual(walking.zoomEnd().getState().grab, null);
const still = stateOf(state).zoomStart({ pos: [195, 422] }).zoom({ pos: [195, 422], scale: 0 });
close(apart(view.eyeOf(still.getViewportProps(), H), eye), 0, 1e-9, "a pinch of no size walks nowhere");
walkedFrom(eye, -WALK.pinch, view.eyeOf(stateOf(state).zoom({ pos: [0, 0], scale: 0.5 }).getViewportProps(), H), "the wheel");
walkedFrom(eye, WALK.step, view.eyeOf(stateOf(state).moveUp().getViewportProps(), H), "the up arrow");
walkedFrom(eye, -WALK.step, view.eyeOf(stateOf(state).moveDown().getViewportProps(), H), "the down arrow");
close(stateOf(state).moveLeft().getViewportProps().rotationOrbit, state.rotationOrbit - WALK.turn, 1e-9, "the left arrow");
close(stateOf(state).moveRight().getViewportProps().rotationOrbit, state.rotationOrbit + WALK.turn, 1e-9, "the right arrow");

// The page's steps walk; the slider and the north button turn the look where the
// walker stands; far outside the ground the walk goes on at its height
started.step(12);
walkedFrom(eye, 12, view.eyeOf(started.view(), H), "a step of the Forward button");
started.step(-12);
eye = view.eyeOf(started.view(), H);
byId("tilt").value = "30";
byId("tilt").fire("input");
assert.strictEqual(started.view().rotationX, 30);
assert.ok(apart(view.eyeOf(started.view(), H), eye) < 1e-6, "the walker stays when the slider tilts the look");
byId("north").fire("click");
assert.strictEqual(started.view().rotationOrbit, 0);
assert.ok(apart(view.eyeOf(started.view(), H), eye) < 1e-6, "the walker stays when the look turns north");

// Down the stairs into the tunnel, through the page's steps: north from the street
// at x = 50 the stairs take the walker down to 5 m, and back up again
started.walk(false);
started.look({ target: [50, -2, 10] });
started.walk(true);
started.look({ rotationOrbit: 0 });
started.step(12);
close(view.eyeOf(started.view(), H)[2] - WALK.eye, 7.5, 1e-6, "ten metres down the stairs");
started.step(50);
close(view.eyeOf(started.view(), H)[2] - WALK.eye, 5, 1e-6, "in the tunnel, five metres under the ground");
started.look({ rotationOrbit: 180 });
started.step(60);
close(view.eyeOf(started.view(), H)[2] - WALK.eye, 10, 1e-6, "back up the stairs to the street");

// At the lift its buttons show; Up takes the walker to the next stop, 30 m, and Down
// back; away from it they hide
started.walk(false);
started.look({ target: [60, 0, 10] });
started.walk(true);
assert.strictEqual(byId("lifts").hidden, false, "the lift's buttons show");
assert.strictEqual(byId("liftUp").disabled, false);
assert.strictEqual(byId("liftDown").disabled, true);
byId("liftUp").fire("click");
close(view.eyeOf(started.view(), H)[2] - WALK.eye, 30, 1e-9, "the lift takes the walker up");
assert.strictEqual(byId("liftDown").disabled, false);
byId("liftDown").fire("click");
close(view.eyeOf(started.view(), H)[2] - WALK.eye, 10, 1e-9, "and down");
started.look({ rotationOrbit: 270 });
started.step(20);
assert.strictEqual(byId("lifts").hidden, true, "away from the lift its buttons hide");

// Leaving: a flying view over the walker, as the view was before the walk; steps do
// nothing while flying; "Start view" ends a walk and goes to the start
const here = view.eyeOf(started.view(), H);
started.walk(false);
state = started.view();
assert.strictEqual(state.walk, false);
assert.strictEqual(state.fovy, view.FLY_FOVY);
for (const key of ["zoom", "rotationX", "minZoom", "maxZoom", "minRotationX", "maxRotationX"]) {
  assert.strictEqual(state[key], flyView[key], key + " after the walk");
}
close(state.target[2], here[2] - WALK.eye, 1e-9, "the flying view turns around the ground under the walker");
assert.strictEqual(byId("moves").hidden, true);
assert.strictEqual(byId("above").hidden, false);
assert.strictEqual(byId("trueHeights").disabled, false);
started.step(10);
assert.strictEqual(started.view(), state);
started.walk(true);
started.step(25);
byId("home").fire("click");
assert.strictEqual(started.view().walk, false);
assert.deepStrictEqual(plain(started.view().target), plain(flyView.target));
byId("walk").checked = true;
byId("walk").fire("change");
assert.strictEqual(started.view().walk, true);

// The walkways and lifts of the data: the route and the lift are no walkways; between
// the tunnel and the bridge there is none; lifts list their stops
const ways = view.walkwaysOf(started.data.groups);
assert.strictEqual(ways.ends.length / 6, 4, "the street, the stairs, the tunnel and the bridge");
close(view.walkwayAt(ways, 50, 30, 5), 5, 1e-6, "in the tunnel under the bridge");
close(view.walkwayAt(ways, 50, 30, 15), 16, 1e-6, "on the bridge over the tunnel");
assert.strictEqual(view.walkwayAt(ways, 50, 30, 10), null, "between the tunnel and the bridge");
assert.strictEqual(view.walkwayAt(ways, 55, 10, 8), null, "five metres beside the stairs");
const grid = started.data.groups.find((group) => group.kind === "ground").grid;
close(view.startingAt(ways, grid, 50, 60, 0), 10, 1e-6, "over the tunnel the walk starts on the terrain");
close(view.startingAt(ways, grid, 1000, 0, 7), 7, 1e-6, "where the terrain is not known, at the height given");
close(view.groundAt(grid, 200, 200, grid.t), 10, 1e-9, "on the north-east corner of the ground");
assert.strictEqual(view.groundAt(grid, 200.5, 0, grid.t), null, "beyond its east edge");
const climb = view.climbOver(() => ways, grid);
let walker = [20, -50, 12 + WALK.eye];
walker = [walker[0], walker[1] + 1, climb(walker, walker[0], walker[1] + 1)];
close(walker[2] - WALK.eye, 11, 1e-6, "a metre walked brings the walker a metre down at most");
assert.deepStrictEqual(plain(view.liftsOf(started.data.groups).map((lift) => lift.stops)), [[10, 30]]);
const doubled = [{ kind: "lines", items: [{ p: [[0, 0, 10], [0, 0.01, 10.1], [5, 0, 10]] }] }];
assert.deepStrictEqual(plain(view.liftsOf(doubled)), [], "a doubled point is no lift");
const pair = [{ x: 0, y: 0, stops: [10, 14] }, { x: 2, y: 0, stops: [3, 10] }];
assert.deepStrictEqual(plain(view.liftAt(pair, 1, 0, 10)), { up: 14, down: 3 }, "two lifts side by side");
assert.strictEqual(view.liftAt(pair, 1, 0, 6.5), null, "between two stops");
assert.strictEqual(view.liftAt(pair, 6, 0, 10), null, "four metres from both lifts");
process.stdout.write("walk: all checks passed\n");
