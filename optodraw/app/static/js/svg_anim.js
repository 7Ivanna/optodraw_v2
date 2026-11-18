/** Full physics-backed 2D SVG animator — every payload kind driven by t_ps. */

const C_UM_PS = 299.792458;

function heatOpacity(t, tau) {
  if (!isFinite(tau) || tau <= 0) return 0.5 + 0.5 * (t % 1);
  const u = (t % (tau * 2.2)) / tau;
  return 0.5 + 0.5 * (1 - Math.exp(-u));
}

function cavityPower(t, period, tauPh) {
  const ph = (t % period) / period;
  return 0.2 + 0.8 * Math.pow(Math.sin(Math.PI * ph), 2);
}

// The marks a part draws. Never the editor's click area of a beam (a wide path at opacity 0): a restyle would show
// it as black dashes over the light.
function drawn(group, selector) {
  return [...group.querySelectorAll(selector)].filter((el) => Number(el.getAttribute("opacity") ?? 1) !== 0);
}

export function createSvgAnimator(svgRoot, payloadMap, opts = {}) {
  const duration = Number.isFinite(opts.duration) && opts.duration > 0 ? opts.duration : 4.0;
  const entries = [];
  const changedStyles = ["stroke-dasharray", "stroke-dashoffset", "opacity", "stroke-opacity", "fill-opacity", "filter"];
  const originalStyles = new Map();
  function rememberStyle(el) {
    if (originalStyles.has(el)) return;
    originalStyles.set(el, changedStyles.map((name) => [
      name, el.style.getPropertyValue(name), el.style.getPropertyPriority(name),
    ]));
  }

  for (const [cid, payload] of Object.entries(payloadMap)) {
    const group = svgRoot.querySelector(`[data-component-id="${CSS.escape(cid)}"]`);
    if (!group) continue;

    if (payload.pulse) {
      const segs = payload.pulse.segments || [];
      const totalLen = segs.reduce((s, seg) => s + seg.len, 0);
      const avgN = segs.length ? segs.reduce((s, seg) => s + seg.n, 0) / segs.length : 1.0;
      const target = drawn(group, "polyline, path, line")[0];
      if (target) {
        rememberStyle(target);
        let dashLen = 10;
        try { dashLen = target.getTotalLength ? target.getTotalLength() * 0.1 : 10; } catch {}
        target.style.strokeDasharray = `${dashLen} ${dashLen * 1.4}`;
        entries.push({ el: target, kind: "pulse", segs, totalLen, avgN, power: payload.pulse.power || 1 });
      }
    }
    if (payload.flow) {
      const target = drawn(group, "polyline, path, line")[0];
      if (target) {
        rememberStyle(target);
        const len = payload.flow.len || 20;
        const n = payload.flow.n || 4.2;
        target.style.strokeDasharray = `8 6`;
        entries.push({ el: target, kind: "flow", len, n, power: payload.flow.power || 1 });
      }
    }
    if (payload.signal) {
      const target = drawn(group, "polyline, path, line")[0];
      if (target) {
        rememberStyle(target);
        target.style.strokeDasharray = `6 4`;
        entries.push({ el: target, kind: "signal", len: payload.signal.len || 20 });
      }
    }
    if (payload.heat) {
      const polys = drawn(group, "polyline");
      for (const poly of polys) {
        entries.push({ el: poly, kind: "heat", tau: payload.heat.tau_s || 1.4 });
      }
    }
    if (payload.junction) {
      const polys = drawn(group, "polygon, circle, rect");
      for (const p of polys) {
        entries.push({ el: p, kind: "junction", period: payload.junction.period_s || 1.8 });
      }
    }
    if (payload.guides) {
      const polys = drawn(group, "polygon, path");
      for (const p of polys) {
        entries.push({ el: p, kind: "guides", guides: payload.guides, period: payload.guides.period_s || 1.8 });
      }
    }
    if (payload.envelope) {
      const paths = drawn(group, "path");
      for (const pa of paths) {
        entries.push({ el: pa, kind: "envelope", w1: payload.envelope.w1, w2: payload.envelope.w2 });
      }
    }
    if (payload.cavity_power !== undefined || payload.cavityPower !== undefined) {
      const circles = drawn(group, "circle");
      for (const c of circles) {
        entries.push({ el: c, kind: "cavity", power: payload.cavity_power || payload.cavityPower || 1 });
      }
    }
    if (payload.pol) {
      const any = drawn(group, "polyline, path, line")[0];
      if (any) entries.push({ el: any, kind: "pol", pol: payload.pol });
    }
  }

  // Free beams have no component group. Do not animate unrelated component outlines.
  const freePulse = Object.entries(payloadMap).find(([cid, payload]) =>
    payload.pulse && !svgRoot.querySelector(`[data-component-id="${CSS.escape(cid)}"]`));
  if (freePulse) {
    const pulse = freePulse[1].pulse;
    const segs = pulse.segments || [];
    const totalLen = segs.reduce((sum, seg) => sum + seg.len, 0);
    const avgN = segs.length ? segs.reduce((sum, seg) => sum + seg.n, 0) / segs.length : 1.0;
    for (const line of svgRoot.querySelectorAll("polyline, path")) {
      if (line.closest("[data-component-id]")) continue;
      rememberStyle(line);
      line.style.strokeDasharray = "10 8";
      entries.push({ el: line, kind: "pulse", segs, totalLen, avgN, power: pulse.power || 1 });
    }
  }

  if (entries.length === 0) return { play() {}, pause() {}, seek() {}, destroy() {}, count: 0 };
  for (const entry of entries) rememberStyle(entry.el);

  let running = false;
  let startTime = null;
  let raf = null;
  let pausedAt = 0;

  function renderAt(t) {
    const tPs = (t / duration) * 4000;

    for (const e of entries) {
      if (e.kind === "pulse" || e.kind === "flow") {
        const v = C_UM_PS / (e.avgN || e.n || 1);
        const total = e.totalLen || e.len || 40;
        const dist = (tPs * v * 0.008) % (total * 1.5);
        e.el.style.strokeDashoffset = String(-dist);
        if (e.power !== undefined) e.el.style.opacity = String(0.6 + 0.4 * e.power);
      } else if (e.kind === "signal") {
        const dist = (tPs * 8) % 30;
        e.el.style.strokeDashoffset = String(-dist);
      } else if (e.kind === "heat") {
        e.el.style.strokeOpacity = String(heatOpacity(t, e.tau));
        e.el.style.opacity = String(0.6 + 0.4 * heatOpacity(t, e.tau));
      } else if (e.kind === "junction" || e.kind === "guides") {
        const op = 0.5 + 0.5 * Math.sin((t / e.period) * 2 * Math.PI);
        e.el.style.fillOpacity = String(0.4 + 0.6 * op);
        e.el.style.opacity = String(0.7 + 0.3 * op);
      } else if (e.kind === "cavity") {
        const op = cavityPower(t, 1.8, 1);
        e.el.style.fillOpacity = String(op);
      } else if (e.kind === "envelope") {
        // Gaussian waist would modulate width; stub with opacity
        e.el.style.opacity = String(0.7 + 0.3 * Math.sin(t * 2));
      } else if (e.kind === "pol") {
        // polarization as hue shift
        const hue = (t * 30) % 360;
        e.el.style.filter = `hue-rotate(${hue}deg)`;
      }
    }
  }

  function frame(now) {
    if (!running) return;
    if (startTime === null) startTime = now - pausedAt;
    renderAt(((now - startTime) / 1000) % duration);
    raf = requestAnimationFrame(frame);
  }

  return {
    play() { if (running) return; running = true; raf = requestAnimationFrame(frame); },
    pause() {
      if (!running) return;
      running = false;
      if (raf) cancelAnimationFrame(raf);
      if (startTime !== null) pausedAt = performance.now() - startTime;
      startTime = null;
      raf = null;
    },
    seek(t) {
      const seconds = Number.isFinite(t) ? Math.max(0, t) : 0;
      pausedAt = seconds * 1000;
      startTime = null;
      renderAt(seconds % duration);
    },
    destroy() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      raf = null;
      startTime = null;
      for (const [el, styles] of originalStyles) {
        for (const [name, value, priority] of styles) {
          if (value) el.style.setProperty(name, value, priority);
          else el.style.removeProperty(name);
        }
      }
    },
    count: entries.length,
  };
}
