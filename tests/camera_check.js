// Checks the camera of a page of a pyrosm3d view with the real deck.gl library (no
// drawing; there is no WebGL here): the page's scripts run with the library, whose
// Deck is replaced by a stand-in, and the page's controller is driven through the
// library's own orbit view. Exits with an error when a check fails.
//
// usage: node camera_check.js <page.html> <deck.gl bundle>
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

function element(id) {
  return {
    id, hidden: false, textContent: "", value: "", checked: false, className: "",
    style: {}, children: [], attributes: {}, listeners: {},
    appendChild(child) { this.children.push(child); },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(type, listener) { this.listeners[type] = listener; },
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
let made = null;
// the library's own Deck needs WebGL: a stand-in records what the page gives it
const library = Object.defineProperty(Object.create(real), "Deck", {
  value: class {
    constructor(props) { made = this; this.props = props; }
    setProps(props) { Object.assign(this.props, props); }
  },
});
const context = {
  document: { getElementById: byId, createElement: (tag) => element(tag) },
  deck: library, console, addEventListener() {}, WeakMap, Map,
};
context.window = context;
vm.createContext(context);
vm.runInContext(page.slice(page.lastIndexOf("<script>") + 8, page.lastIndexOf("</script>")), context);
assert.ok(made, "the page started: " + byId("error").textContent);
const view = context.pyrosm3d;

const close = (a, b, by, what) => assert.ok(Math.abs(a - b) <= by, what + ": " + a + " against " + b);
const orbit = new real.OrbitView({ id: "main", orbitAxis: "Z" });
const makeViewport = (props) => orbit.makeViewport({ width: props.width, height: props.height, viewState: props });
const Free = made.props.controller.type;
const controller = new Free({ eventManager: { on() {}, off() {} }, makeViewport, onViewStateChange() {}, onStateChange() {} });
const State = controller.ControllerState;
const size = { width: 390, height: 844 };
const startView = Object.assign({}, size, made.props.viewState, { minZoom: -3, maxZoom: 4.3 });

// From above and from below: a drag keeps the grabbed point of the ground under the
// finger, at the height of the point the camera turns around
for (const rotationX of [40, 75, 90, 21, -40]) {
  const start = new State(Object.assign({ makeViewport }, startView, { rotationX }));
  let state = start.panStart({ pos: [150, 500] });
  assert.ok(state.getState().grab.onGround, "a grab on the ground at tilt " + rotationX);
  const grabbed = state.getState().grab.place;
  close(grabbed[2], startView.target[2], 1e-6, "the grabbed place lies on the ground plane");
  for (const pos of [[220, 430], [100, 620], [300, 300]]) {
    state = state.pan({ pos });
    const now = state.getViewportProps();
    const pixel = makeViewport(now).project(grabbed);
    close(pixel[0], pos[0], 1.5, "the ground point stays under the finger (x) at tilt " + rotationX);
    close(pixel[1], pos[1], 1.5, "the ground point stays under the finger (y) at tilt " + rotationX);
    assert.strictEqual(now.target[2], startView.target[2]);
    assert.strictEqual(now.zoom, startView.zoom);
    assert.strictEqual(now.rotationX, rotationX);
  }
  assert.strictEqual(state.panEnd().getState().grab, null);
}

// From the side: a drag moves the view in the plane of the screen, also up and down
for (const rotationX of [0, 8, -15]) {
  const start = new State(Object.assign({ makeViewport }, startView, { rotationX }));
  let state = start.panStart({ pos: [195, 422] });
  const grab = state.getState().grab;
  assert.strictEqual(grab.onGround, false);
  state = state.pan({ pos: [195, 322] });
  const now = state.getViewportProps();
  const pixel = makeViewport(now).project(grab.place);
  close(pixel[0], 195, 1.5, "the side grab stays under the finger (x) at tilt " + rotationX);
  close(pixel[1], 322, 1.5, "the side grab stays under the finger (y) at tilt " + rotationX);
  assert.ok(now.target[2] < startView.target[2] - 5, "dragging the scene up moves the centre down: " + now.target[2]);
}

// Zooming keeps the point the camera turns around and stays within the limits
const zoomed = new State(Object.assign({ makeViewport }, startView)).zoomStart({ pos: [50, 100] }).zoom({ pos: [60, 90], scale: 2 });
close(zoomed.getViewportProps().zoom, startView.zoom + 1, 1e-9, "a pinch to twice the size zooms in by one");
assert.deepStrictEqual(zoomed.getViewportProps().target, startView.target);
const most = new State(Object.assign({ makeViewport }, startView)).zoom({ pos: [0, 0], scale: 1e9 });
assert.strictEqual(most.getViewportProps().zoom, startView.maxZoom);
const wheel = new State(Object.assign({ makeViewport }, startView)).zoomStart({ pos: [0, 0] }).zoomEnd().zoom({ pos: [0, 0], scale: 0.5 });
close(wheel.getViewportProps().zoom, startView.zoom - 1, 1e-9, "a zoom after the start of a pinch was cleared");


// With a mouse, through the library's own handling of a drag: a plain drag moves the
// view; a drag with Shift held, or with the right button, turns and tilts it by 180
// degrees for the width and the height of the screen
let shown = Object.assign({}, startView);
const options = Object.assign({ id: "main", x: 0, y: 0 }, made.props.controller, { inertia: 0 });
delete options.type;
const mouse = new Free({
  eventManager: { on() {}, off() {} }, makeViewport, onStateChange() {},
  onViewStateChange: (change) => { shown = change.viewState; mouse.setProps(Object.assign({}, options, shown)); },
});
const drag = (start, end, more) => {
  const at = (type, pos) => Object.assign({ type, offsetCenter: { x: pos[0], y: pos[1] }, srcEvent: {}, rightButton: false, stopPropagation() {} }, more);
  shown = Object.assign({}, startView);
  mouse.setProps(Object.assign({}, options, shown));
  mouse.handleEvent(at("panstart", start));
  mouse.handleEvent(at("panmove", end));
  mouse.handleEvent(at("panend", end));
  return shown;
};
const moved = drag([200, 400], [260, 440], {});
assert.strictEqual(moved.rotationX, startView.rotationX);
assert.ok(Math.hypot(moved.target[0] - startView.target[0], moved.target[1] - startView.target[1]) > 10, "a plain drag moves the view");
for (const more of [{ srcEvent: { shiftKey: true } }, { rightButton: true }]) {
  const turned = drag([200, 400], [260, 440], more);
  close(turned.rotationOrbit, startView.rotationOrbit + (60 / size.width) * 180, 1e-9, "a drag that turns");
  close(turned.rotationX, startView.rotationX + (40 / size.height) * 180, 1e-9, "a drag that tilts");
  assert.deepStrictEqual(turned.target, startView.target);
}

// The end of a pinch does not glide, also when its last two events come at the same
// time (the library divides by the time between them for the glide): the view ends
// at the zoom of the pinch, without a transition, and the inertia is kept
const pinches = [];
const pinchOptions = Object.assign({}, options, { inertia: 300 });
const pinching = new Free({
  eventManager: { on() {}, off() {} }, makeViewport, onStateChange() {},
  onViewStateChange: (change) => {
    pinches.push(change);
    pinching.setProps(Object.assign({}, pinchOptions, change.viewState));
  },
});
pinching.setProps(Object.assign({}, pinchOptions, startView));
const pinch = (type, scale, deltaTime) => pinching.handleEvent({
  type, offsetCenter: { x: 195, y: 422 }, scale, rotation: 0, deltaTime,
  srcEvent: {}, stopPropagation() {},
});
pinch("pinchstart", 1, 0);
pinch("pinchmove", 1.5, 100);
pinch("pinchend", 2, 100);
const ended = pinches[pinches.length - 1];
assert.ok(!ended.interactionState.isDragging, "the pinch has ended");
assert.ok(!ended.viewState.transitionDuration, "no glide after the pinch");
close(ended.viewState.zoom, startView.zoom + Math.log2(1.5), 1e-9, "the zoom of the pinch");
assert.strictEqual(pinching.inertia, 300);

// Touch: twisting two fingers turns the view, and three fingers moved up or down tilt
// it; both keep the point the camera turns around
const touch = (type, more) => pinching.handleEvent(Object.assign({
  type, offsetCenter: { x: 195, y: 422 }, srcEvent: {}, stopPropagation() {},
}, more));
pinching.setProps(Object.assign({}, pinchOptions, startView));
touch("pinchstart", { scale: 1, rotation: 0, deltaTime: 0 });
touch("pinchmove", { scale: 1, rotation: 30, deltaTime: 100 });
touch("pinchend", { scale: 1, rotation: 30, deltaTime: 200 });
const twisted = pinches[pinches.length - 1].viewState;
assert.ok(Math.abs(twisted.rotationOrbit - startView.rotationOrbit) > 5, "a twist turns the view: " + twisted.rotationOrbit);
assert.deepStrictEqual(twisted.target, startView.target);
pinching.setProps(Object.assign({}, pinchOptions, startView));
touch("tripanstart", { deltaX: 0, deltaY: 0 });
touch("tripanmove", { offsetCenter: { x: 215, y: 222 }, deltaX: 20, deltaY: -200 });
touch("tripanend", { offsetCenter: { x: 215, y: 222 }, deltaX: 20, deltaY: -200 });
const tilted = pinches[pinches.length - 1].viewState;
assert.ok(Math.abs(tilted.rotationX - startView.rotationX) > 5, "three fingers tilt the view: " + tilted.rotationX);
assert.strictEqual(tilted.rotationOrbit, startView.rotationOrbit);
assert.deepStrictEqual(tilted.target, startView.target);

// The page keeps the browser's menu off the view, so that a drag with the right
// button turns it
let prevented = false;
byId("canvas").listeners.contextmenu({ preventDefault() { prevented = true; } });
assert.ok(prevented, "no browser menu on the view");
process.stdout.write("camera: all checks passed\n");
