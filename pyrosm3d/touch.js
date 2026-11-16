// The touch controls of a 3D figure of pyrosm3d: two fingers zoom and move the view,
// touches on the view do not scroll or zoom the page, and the view stays as it was
// turned when a tool of plotly's toolbar is picked. It runs after plotly has drawn the
// figure into the element with the id "{plot_id}".
(function () {
  const plot = document.getElementById("{plot_id}");
  plot.style.touchAction = "none";

  // The two fingers on the view at their last move: which they are, where they were,
  // and the camera's distance
  let pinch = null;

  // Plotly's 3D scene of the plot, or null when plotly does not keep it here
  function scene() {
    const layout = plot._fullLayout;
    return (layout && layout.scene && layout.scene._scene) || null;
  }

  // Plotly sets the view from the camera in the layout whenever the plot changes or a
  // tool of its toolbar is picked, and writes the camera there after a mouse drag but
  // not after a touch. This script writes it when the last finger is lifted from the plot,
  // so that the view stays as it was turned.
  function saveCamera() {
    const drawn = scene();
    if (drawn) drawn.saveLayout(plot.layout);
  }

  // Which two touches these are (the same in either order: a list of touches has no
  // fixed order), how far apart (a pixel at least), and the point between them
  function fingers(touches) {
    const [first, second] = [touches[0], touches[1]];
    const apart = Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY);
    return {
      pair: [first.identifier, second.identifier].sort((a, b) => a - b).join(" "),
      apart: Math.max(apart, 1),
      x: (first.clientX + second.clientX) / 2,
      y: (first.clientY + second.clientY) / 2,
    };
  }

  // The touches of the event that began on the plot
  function onPlot(event) {
    return Array.from(event.touches).filter((touch) => plot.contains(touch.target));
  }

  function startPinch(event) {
    const drawn = scene();
    const touches = onPlot(event);
    if (!drawn || touches.length !== 2) return;
    pinch = Object.assign(fingers(touches), { distance: drawn.camera.distance });
  }

  // Plotly follows one finger only and would turn the view with it, so it gets no move
  // from the second finger's touch until every finger is lifted from the plot. This
  // script moves the camera itself: closer to the point it looks at as the fingers
  // spread, and sideways with them, by the step that plotly's own pan takes. Each move
  // is measured from the one before it. One finger or three move nothing, and two
  // other fingers than at the last move start anew.
  function movePinch(event) {
    if (!pinch) return;
    event.stopPropagation();
    event.preventDefault();
    const touches = onPlot(event);
    if (touches.length !== 2) {
      pinch.pair = null;
      return;
    }
    const now = fingers(touches);
    now.distance = pinch.distance;
    if (now.pair === pinch.pair) {
      now.distance = (pinch.distance * pinch.apart) / now.apart;
      const step = now.distance / plot.clientHeight;
      const camera = scene().camera;
      camera.distance = now.distance;
      camera.pan(-(now.x - pinch.x) * step, (now.y - pinch.y) * step, 0);
    }
    pinch = now;
  }

  function endTouch(event) {
    if (onPlot(event).length > 0) return;
    pinch = null;
    saveCamera();
  }

  plot.addEventListener("touchstart", startPinch, { capture: true, passive: true });
  plot.addEventListener("touchmove", movePinch, { capture: true, passive: false });
  plot.addEventListener("touchend", endTouch, { capture: true, passive: true });
  plot.addEventListener("touchcancel", endTouch, { capture: true, passive: true });
})();
