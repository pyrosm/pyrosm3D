// Runs the scripts of a page written by pyrosm3d.to_html without a browser: stand-ins
// for the few page elements, for Plotly and for its 3D scene record what the page
// script does. Presses every level button and the legend button, switches one legend
// entry off, clicks one point, closes the tags panel and moves two fingers on the
// view, and prints what was shown as JSON.
//
// usage: node page_harness.js <page.html> <legend entry to switch off> <trace to click>
//        <small or wide: the size of the page>
const fs = require("fs");
const vm = require("vm");

const [file, entry, clicked, size] = process.argv.slice(2);
const page = fs.readFileSync(file, "utf8");

function element(tag) {
  const made = {
    tag: tag,
    children: [],
    dataset: {},
    attributes: {},
    listeners: {},
    textContent: "",
    appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, listener) { this.listeners[name] = listener; },
  };
  return made;
}

// The text of an element and of everything in it
function text(node) {
  return [node.textContent, ...node.children.map(text)].filter(Boolean).join(" | ");
}

// Plotly's 3D scene: its camera, and how many times the camera was written to the layout
const scene = {
  camera: { distance: 4, pans: [], pan(x, y, z) { this.pans.push([x, y, z]); } },
  saves: 0,
  saveLayout() { this.saves += 1; },
};

const plot = element("div");
plot.handlers = {};
plot.on = function (name, handler) { this.handlers[name] = handler; };
plot.clientHeight = 200;
plot.contains = (node) => node === plot;
plot._fullLayout = { scene: { _scene: scene } };
const data = element("script");
data.textContent = /<script type="application\/json" id="page-data">([\s\S]*?)<\/script>/.exec(page)[1];
const panel = element("aside");
const hint = element("p");
hint.textContent = /<aside id="tags"><p>(.*?)<\/p>/.exec(page)[1];
panel.children.push(hint);
const elements = {
  plot: plot,
  "page-data": data,
  tags: panel,
  levels: element("nav"),
  legend: element("button"),
};
const updates = [];
// The layout of the legend, as the calls of Plotly.relayout have left it
const legendLayout = {};
const sandbox = {
  document: { getElementById: (id) => elements[id], createElement: element },
  matchMedia: () => ({ matches: size === "small" }),
  Plotly: {
    newPlot(id, traces, layout) {
      plot.data = traces;
      plot.layout = layout;
      return Promise.resolve(plot);
    },
    update(target, traceUpdate, layoutUpdate) {
      Object.keys(traceUpdate).forEach((key) => {
        target.data.forEach((trace, n) => { trace[key] = traceUpdate[key][n]; });
      });
      updates.push(layoutUpdate);
    },
    relayout(target, layoutUpdate) { Object.assign(legendLayout, layoutUpdate); },
  },
};
sandbox.window = sandbox;

const scripts = page.match(/<script(?: type="text\/javascript")?>[\s\S]*?<\/script>/g);
scripts.forEach((script) => {
  vm.runInNewContext(script.replace(/^<script[^>]*>|<\/script>$/g, ""), sandbox);
});

// What the plot shows now: the names of the drawn traces, and the legend entries
function shown() {
  return {
    drawn: plot.data.map((trace, n) => (trace.visible === true ? n : null)).filter((n) => n !== null),
    legendonly: plot.data.map((trace, n) => (trace.visible === "legendonly" ? n : null)).filter((n) => n !== null),
    listed: plot.data.filter((trace) => trace.showlegend).map((trace) => trace.legendgroup),
    view: updates[updates.length - 1],
  };
}

// The legend button's state and the layout of the legend
function legend() {
  const pressed = elements.legend.attributes["aria-pressed"];
  return { pressed: pressed, layout: Object.assign({}, legendLayout) };
}

// Send a touch event to the plot, with the fingers [number, x, y] on the plot or, with
// a fourth value, elsewhere on the page; true when the page kept the event from plotly
function touch(name, fingers) {
  const event = {
    touches: fingers.map(([number, x, y, elsewhere]) => (
      { identifier: number, clientX: x, clientY: y, target: elsewhere ? elements.levels : plot }
    )),
    kept: false,
    stopPropagation() { this.kept = true; },
    preventDefault() {},
  };
  plot.listeners[name](event);
  return event.kept;
}

// Finger 0 lands on the plot while finger 9 is on the header, moves and is lifted.
// Fingers 0 and 1 land on the plot 100 px apart, spread to 200 px apart and move 20 px
// down. Finger 2 lands, the three move, and finger 0 is lifted. Fingers 1 and 2 move
// once as they are, then close to half as far apart around the same point. Finger 1
// is lifted, finger 2 moves and is lifted, and a finger moves once more.
// "kept" and "distances" (the camera's) are listed for each move, "saves" (the
// camera's writes to the layout so far) for each lift.
function touches() {
  const kept = [];
  const distances = [];
  const saves = [];
  const move = (fingers) => {
    kept.push(touch("touchmove", fingers));
    distances.push(scene.camera.distance);
  };
  const lift = (fingers) => {
    touch("touchend", fingers);
    saves.push(scene.saves);
  };
  touch("touchstart", [[0, 100, 100], [9, 300, 10, "header"]]);
  move([[0, 110, 100], [9, 300, 10, "header"]]);
  lift([[9, 300, 10, "header"]]);
  touch("touchstart", [[0, 100, 100], [1, 200, 100]]);
  move([[0, 50, 120], [1, 250, 120]]);
  touch("touchstart", [[0, 50, 120], [1, 250, 120], [2, 150, 300]]);
  move([[0, 60, 120], [1, 240, 120], [2, 150, 300]]);
  lift([[1, 240, 120], [2, 150, 300]]);
  move([[1, 240, 120], [2, 150, 300]]);
  move([[1, 217.5, 165], [2, 172.5, 255]]);
  lift([[2, 172.5, 255]]);
  move([[2, 180, 260]]);
  lift([]);
  move([[3, 70, 140]]);
  return { kept: kept, distances: distances, pans: scene.camera.pans, saves: saves };
}

setImmediate(() => {
  const out = { buttons: [], views: {}, legendAtStart: legend() };
  elements.legend.listeners.click();
  out.legendAfterClick = legend();
  elements.levels.children.forEach((button) => {
    out.buttons.push(button.textContent);
    button.listeners.click();
    const pressed = elements.levels.children.filter((b) => b.attributes["aria-pressed"] === "true");
    out.views[button.textContent] = Object.assign(shown(), { pressed: pressed.map((b) => b.textContent) });
  });
  elements.levels.children[0].listeners.click();
  const curve = plot.data.findIndex((trace) => trace.legendgroup === entry);
  out.legendclick = plot.handlers.plotly_legendclick({ data: plot.data, curveNumber: curve });
  out.afterLegendclick = shown();
  const trace = plot.data.find((candidate) => candidate.name === clicked);
  plot.handlers.plotly_click({ points: [{ data: trace, pointNumber: 0 }] });
  out.tags = text(elements.tags);
  out.link = elements.tags.children.find((child) => child.tag === "a").href;
  plot.handlers.plotly_click({ points: [{ data: { customdata: [null] }, pointNumber: 0 }] });
  out.tagsAfterEmptyClick = text(elements.tags);
  elements.tags.children.find((child) => child.tag === "button").listeners.click();
  out.tagsAfterClose = text(elements.tags);
  out.touches = touches();
  console.log(JSON.stringify(out));
});
