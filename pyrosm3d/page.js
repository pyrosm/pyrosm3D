// The script of a page written by pyrosm3d.to_html: a button for each level, and a
// panel with the OpenStreetMap tags of the element that is clicked. It runs after
// plotly has drawn the figure of plot_indoor into the element with the id "{plot_id}".
(function () {
  const plot = document.getElementById("{plot_id}");
  const page = JSON.parse(document.getElementById("page-data").textContent);
  const panel = document.getElementById("tags");
  const nav = document.getElementById("levels");
  // Legend entries that are switched off: those that plot_indoor hides at start
  const hidden = new Set(
    plot.data.filter((trace) => trace.visible === "legendonly").map((trace) => trace.legendgroup)
  );
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

  function addButton(label, value, buttonView) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.dataset.level = String(value);
    button.addEventListener("click", () => show(value, buttonView));
    nav.appendChild(button);
  }

  // The tags of the element with the key (such as "way 123") as a table in the panel
  function showTags(key) {
    const tags = page.elements[key];
    if (!tags) return;
    const [type, id] = key.split(" ");
    const heading = document.createElement("h2");
    heading.textContent = tags.name || tags.ref || key;
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
    panel.replaceChildren(heading, link, table);
  }

  addButton("All levels", null, page.all);
  page.levels.forEach((value, n) => addButton("Level " + value, value, page.views[n]));
  show(null, page.all);

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
