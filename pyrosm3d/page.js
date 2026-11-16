// The script of a page written by pyrosm3d.to_html: a button for each level, a button
// for the legend and a panel with the OpenStreetMap tags of the element that is
// clicked. It runs after plotly has drawn the figure of plot_indoor into the element
// with the id "{plot_id}", and after touch.js, which gives the view its touch controls.
(function () {
  const plot = document.getElementById("{plot_id}");
  const page = JSON.parse(document.getElementById("page-data").textContent);
  const panel = document.getElementById("tags");
  const hint = Array.from(panel.children);
  const nav = document.getElementById("levels");
  const legendButton = document.getElementById("legend");
  // A small page, such as a phone's, where the page's style lays the panel over the view
  const small = window.matchMedia("(max-width: 700px), (max-height: 500px)").matches;
  // On a small page the legend lies over the view, so that the view keeps the whole width
  const legendPlace = small
    ? { "legend.x": 0, "legend.xanchor": "left", "legend.bgcolor": "rgba(255, 255, 255, 0.9)" }
    : {};
  // Legend entries that are switched off: those that plot_indoor hides at start
  const hidden = new Set(
    plot.data.filter((trace) => trace.visible === "legendonly").map((trace) => trace.legendgroup)
  );
  let legend = !small;
  let level = null;
  let view = page.all;

  // Show the traces of one level (null: all levels, with the columns) in its view of
  // the scene. A trace that is on the level is drawn, or kept in the legend only when
  // its entry is switched off; each legend entry is listed once, by its first trace on
  // the level.
  function show(nextLevel, nextView) {
    level = nextLevel;
    view = nextView;
    const listed = new Set();
    const visible = [];
    const showlegend = [];
    plot.data.forEach((trace) => {
      const on = level === null || trace.meta.levels.indexOf(level) !== -1;
      visible.push(on ? (hidden.has(trace.legendgroup) ? "legendonly" : true) : false);
      showlegend.push(on && !listed.has(trace.legendgroup));
      if (on) listed.add(trace.legendgroup);
    });
    Plotly.update(plot, { visible: visible, showlegend: showlegend }, view);
    Array.from(nav.children).forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.level === String(level)));
    });
  }

  // A button that shows one level (null: all levels): a short label, over the number
  // of areas on the level where a count is given, and the full name for a pointer and
  // a screen reader
  function addButton(label, name, value, buttonView, count) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.title = name;
    button.setAttribute("aria-label", name);
    if (count !== null) {
      const areas = document.createElement("small");
      areas.textContent = String(count);
      button.appendChild(areas);
    }
    button.dataset.level = String(value);
    button.addEventListener("click", () => show(value, buttonView));
    nav.appendChild(button);
  }

  function showLegend(on) {
    legend = on;
    legendButton.setAttribute("aria-pressed", String(on));
    Plotly.relayout(plot, Object.assign({ showlegend: on }, legendPlace));
  }

  // The tags of the element with the key (such as "way 123") as a table in the panel,
  // with a button that brings the panel's first text back
  function showTags(key) {
    const tags = page.elements[key];
    if (!tags) return;
    const [type, id] = key.split(" ");
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "Close";
    close.addEventListener("click", () => panel.replaceChildren(...hint));
    const heading = document.createElement("h2");
    heading.textContent = tags.name || tags.ref || key;
    const note = document.createElement("p");
    note.textContent = page.about[key] || "";
    const link = document.createElement("a");
    link.href = "https://www.openstreetmap.org/" + type + "/" + id;
    link.textContent = key;
    const table = document.createElement("table");
    Object.keys(tags).sort().forEach((name) => {
      const row = document.createElement("tr");
      const head = document.createElement("th");
      const cell = document.createElement("td");
      head.textContent = name;
      cell.textContent = tags[name];
      row.appendChild(head);
      row.appendChild(cell);
      table.appendChild(row);
    });
    panel.replaceChildren(close, heading, note, link, table);
  }

  addButton("All levels", "All levels", null, page.all, null);
  page.levels.forEach((value, n) => {
    const count = page.counts[n];
    const areas = count === 1 ? "1 area" : count + " areas";
    addButton(String(value), "Level " + value + ", " + areas, value, page.views[n], count);
  });
  show(null, page.all);
  // On a small page the legend would take the room of the view: hidden at start
  showLegend(legend);
  legendButton.addEventListener("click", () => showLegend(!legend));

  plot.on("plotly_legendclick", (event) => {
    const group = event.data[event.curveNumber].legendgroup;
    if (hidden.has(group)) hidden.delete(group);
    else hidden.add(group);
    show(level, view);
    return false;
  });
  plot.on("plotly_click", (event) => {
    const point = event.points[0];
    const keys = point.data.customdata;
    const key = point.customdata !== undefined ? point.customdata : keys && keys[point.pointNumber];
    if (key) showTags(key);
  });
})();
