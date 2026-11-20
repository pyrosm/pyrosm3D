// The camera of pyrosm3d's views: deck.gl's orbit controller made to move like a map,
// and the geometry of where the camera stands.
(function (view) {
  "use strict";

  // Degrees of the field of view from top to bottom while flying, as in a map view
  const FLY_FOVY = 36.87;
  // Degrees of tilt from the horizon under which the camera counts as seen from the
  // side
  const FROM_THE_SIDE = 20;

  // A controller of deck.gl without the glide of the zoom after a pinch (the library
  // divides by the time between the last two touch events, which can be zero, and the
  // zoom then jumps)
  function withoutPinchGlide(Controller) {
    return class extends Controller {
      _onPinchEnd(event) {
        const glide = this.inertia;
        this.inertia = 0;
        const done = super._onPinchEnd(event);
        this.inertia = glide;
        return done;
      }
    };
  }

  // An orbit controller that moves like a map. The camera turns around a point and can
  // tilt from straight above to straight below. A drag keeps the grabbed point of the
  // ground under the finger (the level plane through the point the camera turns
  // around); seen from the side, where the ground has no such point, a drag moves the
  // view in the plane of the screen, so it also goes up and down. Zooming keeps the
  // point the camera turns around.
  function freeController() {
    return class extends withoutPinchGlide(deck.OrbitController) {
      constructor(props) {
        super(props);
        const State = this.ControllerState;
        this.ControllerState = class extends State {
          constructor(options) {
            super(options);
            this.grab = options.grab || null;
            // what the library's state does not keep of the view state
            this.more = {};
            ["fovy"].forEach((key) => {
              if (options[key] !== undefined) this.more[key] = options[key];
            });
          }

          getViewportProps() {
            return Object.assign({}, super.getViewportProps(), this.more);
          }

          getState() {
            return Object.assign({}, super.getState(), { grab: this.grab });
          }

          // The place under the pixel pos: where the line of sight meets the grabbed
          // level plane (none when it does not, or runs along it), or the place at the
          // grabbed distance from the camera
          placeUnder(viewport, pos, grab) {
            if (!grab.onGround) return viewport.unproject([pos[0], pos[1], grab.depth]);
            const near = viewport.unproject([pos[0], pos[1], 0]);
            const far = viewport.unproject([pos[0], pos[1], 1]);
            const along = (grab.target[2] - near[2]) / (far[2] - near[2]);
            if (!(along > 0) || !Number.isFinite(along)) return null;
            const place = near.map((value, axis) => value + along * (far[axis] - value));
            return place.every(Number.isFinite) ? place : null;
          }

          panStart({ pos }) {
            const props = this.getViewportProps();
            const viewport = this.makeViewport(props);
            const grab = {
              props: Object.assign({}, props),
              target: props.target.slice(),
              onGround: Math.abs(props.rotationX) >= FROM_THE_SIDE,
              depth: viewport.project(props.target)[2],
            };
            grab.place = this.placeUnder(viewport, pos, grab);
            if (!grab.place) {
              grab.onGround = false;
              grab.place = this.placeUnder(viewport, pos, grab);
            }
            return this._getUpdatedState({ grab });
          }

          pan({ pos }) {
            const grab = this.grab;
            if (!grab) return this;
            const now = this.placeUnder(this.makeViewport(grab.props), pos, grab);
            if (!now) return this;
            const target = grab.target.map((value, axis) => value + grab.place[axis] - now[axis]);
            if (grab.onGround) target[2] = grab.target[2];
            return target.every(Number.isFinite) ? this._getUpdatedState({ target }) : this;
          }

          panEnd() {
            return this._getUpdatedState({ grab: null });
          }

          zoom({ scale }) {
            const startZoom = this.getState().startZoom;
            const from = startZoom === null ? undefined : startZoom;
            return this._getUpdatedState({
              zoom: this._calculateNewZoom({ scale, startZoom: from }),
            });
          }
        };
      }
    };
  }

  Object.assign(view, { FLY_FOVY, withoutPinchGlide, freeController });
})((window.pyrosm3d = window.pyrosm3d || {}));
