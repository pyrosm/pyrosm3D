// Runs the scripts of a page of a pyrosm3d view (pyrosm3d.View.to_html) without a
// browser: stand-ins for the page's elements and for deck.gl record what the scripts
// do. After the page has started and after each step, the harness notes the layers,
// the view state and the panels, and prints the notes as JSON.
//
// usage: node view_harness.js <page.html> <steps as JSON> [nodeck]
// A step is [name, ...arguments]:
//   ["click", layer id, item number]  a tap on an item of a layer
//   ["miss"]                          a tap where there is nothing
//   ["tooltip", layer id, item number]
//   ["layersAt", view, stretch]       the layers of a view with every group switched
//                                    on, heights drawn stretch times taller
// With "nodeck" the page runs without the library.
const fs = require("fs");
const vm = require("vm");

const [file, stepsText, without] = process.argv.slice(2);
const page = fs.readFileSync(file, "utf8");
const steps = JSON.parse(stepsText || "[]");

function between(text, opening, closing) {
  const from = text.indexOf(opening) + opening.length;
  return text.slice(from, text.indexOf(closing, from));
}

const elements = {};
function element(id) {
  return {
    id,
    hidden: false,
    textContent: "",
    value: "",
    checked: false,
    disabled: false,
    className: "",
    style: {},
    children: [],
    listeners: {},
    appendChild(child) { this.children.push(child); },
    addEventListener(type, listener) { this.listeners[type] = listener; },
  };
}
const byId = (id) => {
  elements[id] = elements[id] || element(id);
  return elements[id];
};
byId("data").textContent = between(page, '<script id="data" type="application/json">', "</script>");
byId("error").hidden = true;
byId("info").hidden = true;

let made = null;
class Layer {
  constructor(props) { this.props = props; }
}
const library = {
  PathLayer: class PathLayer extends Layer {},
  PolygonLayer: class PolygonLayer extends Layer {},
  ScatterplotLayer: class ScatterplotLayer extends Layer {},
  PathStyleExtension: class PathStyleExtension { constructor(options) { this.options = options; } },
  OrbitView: class OrbitView { constructor(props) { this.props = props; } },
  OrbitController: class OrbitController {},
  Deck: class Deck {
    constructor(props) { made = this; this.props = props; }
    setProps(props) { Object.assign(this.props, props); }
  },
};

const context = {
  document: { getElementById: byId, createElement: (tag) => element(tag) },
  console,
  addEventListener() {},
};
context.window = context;
if (without !== "nodeck") context.deck = library;
vm.createContext(context);
const script = page.slice(page.lastIndexOf("<script>") + "<script>".length, page.lastIndexOf("</script>"));
vm.runInContext(script, context);

// What a layer draws: its kind, how many items, and those of its properties that are
// not functions; an accessor function is noted by what it gives for the first items
function layerNote(layer) {
  const note = { type: layer.constructor.name, items: layer.props.data.length };
  Object.keys(layer.props).forEach((key) => {
    const value = layer.props[key];
    if (key === "data") return;
    if (typeof value === "function") {
      if (key.startsWith("get")) note[key] = layer.props.data.slice(0, 4).map((item) => value(item));
    } else if (key === "extensions") {
      note.extensions = value.map((extension) => extension.constructor.name);
    } else {
      note[key] = value;
    }
  });
  return note;
}

function noted(extra) {
  const props = made ? made.props : {};
  return Object.assign(
    {
      layers: (props.layers || []).map(layerNote),
      viewState: props.viewState || null,
      info: byId("info").hidden ? null : byId("info").textContent,
      error: byId("error").hidden ? null : byId("error").textContent,
    },
    extra || {}
  );
}

const layerOf = (id) => made.props.layers.find((layer) => layer.props.id === id);
const actions = {
  click(id, at) { made.props.onClick({ object: layerOf(id).props.data[at] }); },
  miss() { made.props.onClick({ object: null }); },
  tooltip(id, at) { return { tooltip: made.props.getTooltip({ object: layerOf(id).props.data[at] }) }; },
  layersAt(mode, stretch) {
    const view = context.pyrosm3d;
    const data = view.started.data;
    const shown = new Map(data.groups.map((group) => [group, true]));
    return { at: view.layersOf(data, shown, mode, stretch).map(layerNote) };
  },
};

const notes = [noted({ deck: made ? { controller: made.props.controller, pickingRadius: made.props.pickingRadius, views: made.props.views.props } : null })];
steps.forEach(([name, ...args]) => notes.push(noted(actions[name](...args))));
process.stdout.write(JSON.stringify(notes));
