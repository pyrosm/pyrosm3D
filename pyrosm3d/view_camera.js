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

  const radians = (degrees) => (degrees * Math.PI) / 180;

  // An orbit controller that moves like a map. The camera turns around a point and can
  // tilt from straight above to straight below. A drag keeps the grabbed point of the
  // ground under the finger (the level plane through the point the camera turns
  // around); seen from the side, where the ground has no such point, a drag moves the
  // view in the plane of the screen, so it also goes up and down. Zooming keeps the
  // point the camera turns around.
  //
  // In a walking view (walk in the view state) the camera stays where it stands: a
  // drag looks around (the scene follows the finger), a twist turns, three fingers
  // tilt the look, and a pinch, the wheel and the up and down arrows walk in the
  // direction of the look. climb gives the height of the walker's eye on the way (see
  // view.climbOver); without it the eye keeps its height.
  function freeController(climb) {
    const eyeHeightOnTheWay = climb || ((from) => from[2]);
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
            ["fovy", "walk"].forEach((key) => {
              if (options[key] !== undefined) this.more[key] = options[key];
            });
          }

          getViewportProps() {
            return Object.assign({}, super.getViewportProps(), this.more);
          }

          getState() {
            return Object.assign({}, super.getState(), { grab: this.grab });
          }

          // walking: the state turned to angles, the camera staying where it is
          turned(angles) {
            const props = this.getViewportProps();
            const next = view.turnedView(props, angles, props.height);
            return this._getUpdatedState({
              rotationX: next.rotationX, rotationOrbit: next.rotationOrbit, target: next.target,
            });
          }

          // walking: the state moved metres ahead, from eye
          walked(metres, eye) {
            const props = this.getViewportProps();
            const next = view.walkedView(props, metres, props.height, eyeHeightOnTheWay, eye);
            return this._getUpdatedState({ target: next.target });
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
            if (props.walk) {
              const grab = { pos, rotationX: props.rotationX, rotationOrbit: props.rotationOrbit };
              return this._getUpdatedState({ grab });
            }
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
            const props = this.getViewportProps();
            if (props.walk) {
              // the scene follows the finger: the look turns the other way, by the
              // angle that a pixel takes in the middle of the screen
              const fovy = radians(props.fovy || FLY_FOVY);
              const perPixel = ((2 * Math.tan(fovy / 2)) / props.height) * (180 / Math.PI);
              return this.turned({
                rotationOrbit: grab.rotationOrbit - (pos[0] - grab.pos[0]) * perPixel,
                rotationX: grab.rotationX - (pos[1] - grab.pos[1]) * perPixel,
              });
            }
            const now = this.placeUnder(this.makeViewport(grab.props), pos, grab);
            if (!now) return this;
            const target = grab.target.map((value, axis) => value + grab.place[axis] - now[axis]);
            if (grab.onGround) target[2] = grab.target[2];
            return target.every(Number.isFinite) ? this._getUpdatedState({ target }) : this;
          }

          panEnd() {
            return this._getUpdatedState({ grab: null });
          }

          rotate(params) {
            const next = super.rotate(params);
            if (next === this || !this.getViewportProps().walk) return next;
            const to = next.getViewportProps();
            return this.turned({ rotationX: to.rotationX, rotationOrbit: to.rotationOrbit });
          }

          zoomStart(params) {
            const next = super.zoomStart(params);
            const props = this.getViewportProps();
            if (!props.walk) return next;
            return next._getUpdatedState({ grab: { eye: view.eyeOf(props, props.height) } });
          }

          zoom({ scale }) {
            if (this.getViewportProps().walk) {
              if (!(scale > 0) || !Number.isFinite(scale)) return this;
              return this.walked(Math.log2(scale) * view.WALK.pinch, this.grab && this.grab.eye);
            }
            const startZoom = this.getState().startZoom;
            const from = startZoom === null ? undefined : startZoom;
            return this._getUpdatedState({
              zoom: this._calculateNewZoom({ scale, startZoom: from }),
            });
          }

          zoomEnd() {
            const next = super.zoomEnd();
            return this.getViewportProps().walk ? next._getUpdatedState({ grab: null }) : next;
          }

          // the arrow keys: the library moves the view; walking, up and down walk and
          // left and right turn
          moveUp(speed) {
            return this.getViewportProps().walk ? this.walked(view.WALK.step) : super.moveUp(speed);
          }

          moveDown(speed) {
            return this.getViewportProps().walk ? this.walked(-view.WALK.step) : super.moveDown(speed);
          }

          moveLeft(speed) {
            const props = this.getViewportProps();
            if (!props.walk) return super.moveLeft(speed);
            return this.turned({ rotationOrbit: props.rotationOrbit - view.WALK.turn });
          }

          moveRight(speed) {
            const props = this.getViewportProps();
            if (!props.walk) return super.moveRight(speed);
            return this.turned({ rotationOrbit: props.rotationOrbit + view.WALK.turn });
          }
        };
      }
    };
  }

  Object.assign(view, { FLY_FOVY, withoutPinchGlide, freeController });
})((window.pyrosm3d = window.pyrosm3d || {}));
