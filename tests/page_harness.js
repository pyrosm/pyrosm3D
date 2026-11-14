// Runs the scripts of a page written by pyrosm3d.to_html without a browser: stand-ins
// for the few page elements and for Plotly record what the page script does. Presses
// every level button, switches one legend entry off and clicks one point, and prints
// what was shown as JSON.
//
// usage: node page_harness.js <page.html> <legend entry to switch off> <trace to click>
const fs = require("fs");
const vm = require("vm");

const [file, entry, clicked] = process.argv.slice(2);
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

const plot = element("div");
plot.handlers = {};
plot.on = function (name, handler) { this.handlers[name] = handler; };
const data = element("script");
data.textContent = /<script type="application\/json" id="page-data">([\s\S]*?)<\/script>/.exec(page)[1];
const elements = { plot: plot, "page-data": data, tags: element("aside"), levels: element("nav") };
const updates = [];
const sandbox = {
  document: { getElementById: (id) => elements[id], createElement: element },
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

setImmediate(() => {
  const out = { buttons: [], views: {} };
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
  out.link = elements.tags.children[1].href;
  plot.handlers.plotly_click({ points: [{ data: { customdata: [null] }, pointNumber: 0 }] });
  out.tagsAfterEmptyClick = text(elements.tags);
  console.log(JSON.stringify(out));
});
