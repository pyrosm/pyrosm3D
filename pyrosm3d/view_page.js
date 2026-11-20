// The page script of pyrosm3d's views: starts deck.gl on the data in the page (see
// pyrosm3d.view.View) with a camera that turns around a point, and shows what a
// tapped item is. Errors show in a box on the page.
(function (view) {
  "use strict";

  const byId = (id) => document.getElementById(id);

  function report(message) {
    const box = byId("error");
    box.hidden = false;
    box.textContent = "This page hit an error: " + message;
  }
  window.addEventListener("error", (event) => report(event.message));

  // Degrees of the field of view from top to bottom, as in a map view
  const FLY_FOVY = 36.87;

  // Starts the view of the data: the groups of a ground grid get their squares, and
  // what is switched on at the start is noted for the views of the city and for the
  // indoor view, where every kind of line of the network is on
  function begin(data) {
    let mode = data.mode || view.SOLID;
    if (mode === view.INDOOR && !data.indoor) mode = view.SOLID;
    const shownBy = { solid: new Map(), indoor: new Map() };
    data.groups.forEach((group) => {
      if (group.grid) group.items = view.squaresOf(group.grid);
      shownBy.solid.set(group, Boolean(group.visible));
      shownBy.indoor.set(group, Boolean(group.plot) || Boolean(group.visible));
    });
    const shown = mode === view.INDOOR ? shownBy.indoor : shownBy.solid;
    // the indoor view draws its heights taller, so that its levels stand apart, on the
    // background of its own
    const stretch = mode === view.INDOOR ? data.indoor.stretch : 1;
    if (mode === view.INDOOR) byId("stage").style.background = data.indoor.background;
    const info = byId("info");
    let viewState = Object.assign({ fovy: FLY_FOVY }, data.view);
    const instance = new deck.Deck({
      canvas: byId("canvas"),
      width: "100%",
      height: "100%",
      views: new deck.OrbitView({ id: "main", orbitAxis: "Z" }),
      controller: { doubleClickZoom: false },
      viewState,
      pickingRadius: 8,
      layers: view.layersOf(data, shown, mode, null, stretch),
      onViewStateChange: (change) => {
        viewState = change.viewState;
        instance.setProps({ viewState });
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
    });
    return { instance, data, view: () => viewState };
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
