// Fingerprint spoofs (main thread, iframes AND workers): WebGL vendor/renderer
// and an empty-label media device list when the container exposes none.
//
// Software rendering in the desk container exposes `llvmpipe`; real desktops
// expose a GPU. The override is applied through CDP in every execution context
// (see webgl-spoof-cdp.py) and is written to look native:
//  - Proxy around the *original* getParameter (same name/length, no extra prop)
//  - Function.prototype.toString answers « [native code] » for our proxies
(() => {
  const VENDOR = "__WEBGL_VENDOR__";
  const RENDERER = "__WEBGL_RENDERER__";
  const UNMASKED_VENDOR_WEBGL = 0x9245;
  const UNMASKED_RENDERER_WEBGL = 0x9246;
  const G = typeof globalThis !== "undefined" ? globalThis : self;

  const nativeToString = Function.prototype.toString;
  const fakes = new WeakMap();
  const fakeToString = new Proxy(nativeToString, {
    apply(target, thisArg, args) {
      const s = fakes.get(thisArg);
      return s !== undefined ? s : Reflect.apply(target, thisArg, args);
    },
  });
  fakes.set(fakeToString, "function toString() { [native code] }");
  try {
    Object.defineProperty(Function.prototype, "toString", {
      value: fakeToString,
      writable: true,
      configurable: true,
      enumerable: false,
    });
  } catch (_) {}

  const patch = (Ctor) => {
    if (typeof Ctor === "undefined" || !Ctor || !Ctor.prototype) return;
    const proto = Ctor.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "getParameter");
    if (!desc || typeof desc.value !== "function") return;
    const original = desc.value;
    const proxy = new Proxy(original, {
      apply(target, thisArg, args) {
        const p = args[0];
        if (p === UNMASKED_VENDOR_WEBGL) return VENDOR;
        if (p === UNMASKED_RENDERER_WEBGL) return RENDERER;
        return Reflect.apply(target, thisArg, args);
      },
    });
    fakes.set(proxy, "function getParameter() { [native code] }");
    try {
      Object.defineProperty(proto, "getParameter", { ...desc, value: proxy });
    } catch (_) {}
  };

  patch(G.WebGLRenderingContext);
  patch(G.WebGL2RenderingContext);

  // Media devices: a container has no camera / mic / speaker, so
  // enumerateDevices() resolves to []. A real desktop that has not been granted
  // permission yet reports one entry per kind with empty id / label.
  const patchMediaDevices = () => {
    const MD = G.MediaDevices;
    const Info = G.MediaDeviceInfo;
    if (typeof MD === "undefined" || !MD.prototype || typeof Info === "undefined") return;
    const desc = Object.getOwnPropertyDescriptor(MD.prototype, "enumerateDevices");
    if (!desc || typeof desc.value !== "function") return;
    const fakeInfo = (kind) => {
      const o = Object.create(Info.prototype);
      for (const [k, v] of Object.entries({ deviceId: "", kind, label: "", groupId: "" })) {
        Object.defineProperty(o, k, { value: v, enumerable: true, configurable: true });
      }
      const toJSON = function toJSON() {
        return { deviceId: "", kind, label: "", groupId: "" };
      };
      fakes.set(toJSON, "function toJSON() { [native code] }");
      Object.defineProperty(o, "toJSON", { value: toJSON, configurable: true });
      return o;
    };
    const original = desc.value;
    const proxy = new Proxy(original, {
      apply(target, thisArg, args) {
        return Reflect.apply(target, thisArg, args).then((list) =>
          Array.isArray(list) && list.length === 0
            ? ["audioinput", "videoinput", "audiooutput"].map(fakeInfo)
            : list
        );
      },
    });
    fakes.set(proxy, "function enumerateDevices() { [native code] }");
    try {
      Object.defineProperty(MD.prototype, "enumerateDevices", { ...desc, value: proxy });
    } catch (_) {}
  };
  patchMediaDevices();
})();
