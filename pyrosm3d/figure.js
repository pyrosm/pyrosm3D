// The script of a figure of pyrosm3d that is shown as HTML outside a page of to_html,
// such as in a notebook or on a documentation page. On a small page, such as a
// phone's, the legend would take the room of the view: it is hidden at start, and a
// button in the figure shows it over the view or hides it. It runs after plotly has
// drawn the figure into the element with the id "{plot_id}".
(function () {
  const plot = document.getElementById("{plot_id}");
  const small = window.matchMedia("(max-width: 700px), (max-height: 500px)").matches;
  // A figure with buttons of its own keeps its legend as it is
  if (!small || plot.layout.updatemenus) return;
  const button = {
    label: "Legend",
    method: "relayout",
    args: ["showlegend", true],
    args2: ["showlegend", false],
  };
  Plotly.relayout(plot, {
    showlegend: false,
    "legend.x": 0,
    "legend.xanchor": "left",
    "legend.bgcolor": "rgba(255, 255, 255, 0.9)",
    updatemenus: [
      {
        type: "buttons",
        buttons: [button],
        showactive: false,
        x: 1,
        xanchor: "right",
        y: 0,
        yanchor: "bottom",
      },
    ],
  });
})();
