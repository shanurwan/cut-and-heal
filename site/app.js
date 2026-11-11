// cut-and-heal explorer.
//
// A replay, not a simulation. Every flash, building height, wall movement and number on
// this page is a value measured in a run and exported by `cah site`. One thing is not
// measured and is drawn only to make the picture readable: who is connected to whom.
// Runs record each pod's mesh size, not its peer list, so the links are a seeded random
// graph of about the right degree.
//
// The layout assumes what every scenario so far has: two regions and one border.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const C = {
  ir: new THREE.Color(css("--ir")),
  world: new THREE.Color(css("--world")),
  open: new THREE.Color(css("--open")),
  shut: new THREE.Color(css("--shut")),
  live: new THREE.Color(0x22303f),
  shutCap: new THREE.Color(0x5a1f24),
  white: new THREE.Color(0xffffff),
  black: new THREE.Color(0x000000),
};
const SPEEDS = [0.1, 1, 10, 30, 60];
const SPACING = 2.4;
const GAP = 4.2;
const ROWS = 10;
const BRICK_H = 1.0;

const query = new URLSearchParams(location.search);
const S = {
  data: null, run: null, model: null,
  t: 0, speed: 30, playing: true,
  selected: -1, lastEmit: 0, msgCursor: 0,
  camGoal: null,
};

// ---------- helpers ----------------------------------------------------------------

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const pct = (r) => (r == null ? "-" : `${(r * 100).toFixed(r > 0 && r < 0.995 ? 1 : 0)}%`);
const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };

// ---------- the model: everything derived from one run's data ------------------------

function buildModel(data, run) {
  const pods = data.pods;
  const n = pods.length;
  const border = Object.values(data.borders)[0];
  const borderId = Object.keys(data.borders)[0];
  const gated = border.gated;
  const other = border.between.find((r) => r !== gated);
  const gatedPods = pods.map((p, i) => (p.region === gated ? i : -1)).filter((i) => i >= 0);
  const phases = data.phases;
  const total = data.regions[gated].nodes;
  const openCount = phases.map((ph) => ph.open_nodes[borderId]);

  // Positions: gated region on the left, the rest of the world on the right.
  const rnd = mulberry32(1000 + run.seed);
  const pos = new Array(n);
  const grid = new Array(n); // [col, row] within the region
  for (const region of [gated, other]) {
    const members = pods.map((p, i) => (p.region === region ? i : -1)).filter((i) => i >= 0);
    const cols = Math.ceil(members.length / ROWS);
    members.forEach((i, k) => {
      const col = Math.floor(k / ROWS), row = k % ROWS;
      const x = region === gated ? -GAP - (cols - 1 - col) * SPACING : GAP + col * SPACING;
      const z = (row - (ROWS - 1) / 2) * SPACING;
      pos[i] = new THREE.Vector3(x + (rnd() - 0.5) * 0.5, 0, z + (rnd() - 0.5) * 0.5);
      grid[i] = [col, row];
    });
  }

  // Illustrative peer graph.
  const adj = Array.from({ length: n }, () => new Set());
  const link = (a, b) => { adj[a].add(b); adj[b].add(a); };
  for (let i = 0; i < n; i++) {
    let guard = 0;
    while (adj[i].size < 6 && guard++ < 200) {
      const j = Math.floor(rnd() * n);
      if (j !== i && adj[j].size < 10) link(i, j);
    }
  }
  const otherPods = pods.map((p, i) => (p.region === other ? i : -1)).filter((i) => i >= 0);
  for (const i of gatedPods) {
    while ([...adj[i]].filter((j) => pods[j].region === other).length < 2) link(i, otherPods[Math.floor(rnd() * otherPods.length)]);
  }
  const links = [];
  for (let a = 0; a < n; a++) for (const b of adj[a]) if (a < b) {
    const cross = pods[a].region !== pods[b].region;
    links.push({ a, b, cross, gatedEnd: cross ? (pods[a].region === gated ? a : b) : -1 });
  }

  // Border state per pod and phase, shifted by the lateness each shaper reported.
  const openIn = phases.map((ph) => {
    const list = run.open[ph.name];
    return list ? new Set(list) : new Set(gatedPods);
  });
  const lateS = phases.map((ph) => (run.shaper_late_ms[ph.name] || []).map((ms) => (ms == null ? 0 : ms / 1000)));
  const phaseAt = (t) => { for (let k = phases.length - 1; k >= 0; k--) if (t >= phases[k].start_s) return k; return 0; };
  const effPhase = (pod, t) => {
    const k = phaseAt(t);
    return k > 0 && t < phases[k].start_s + (lateS[k][pod] || 0) ? k - 1 : k;
  };
  const isOpen = (pod, t) => openIn[effPhase(pod, t)].has(pod);

  // When did something first cross after a border with no open node got one?
  const msg = run.messages;
  const dialUntil = phases.map((ph, k) => {
    if (k === 0 || openCount[k] === 0 || openCount[k - 1] !== 0) return ph.start_s;
    for (let i = 0; i < msg.t_s.length; i++) {
      if (msg.t_s[i] < ph.start_s) continue;
      const src = pods[msg.origin[i]].region;
      if (msg.delivered[src === gated ? other : gated][i] > 0) return msg.t_s[i];
    }
    return ph.end_s;
  });

  // When did each shut pod's own mesh size move by more than 10%?
  const step = data.step_s;
  const bin = (t) => Math.max(0, Math.floor(t / step));
  const meshOf = (pod, t) => { const s = run.mesh_x10[pod]; const v = s && s[Math.min(bin(t), s.length - 1)]; return v == null ? null : v / 10; };
  const end0 = (k) => { let j = k; while (j + 1 < phases.length && openCount[j + 1] === 0) j++; return phases[j].end_s; };
  const closedSince = phases.map(() => new Float64Array(n).fill(-1));
  const prunedAt = phases.map(() => new Float64Array(n).fill(Infinity));
  for (const pod of gatedPods) {
    for (let k = 0; k < phases.length; k++) {
      if (openIn[k].has(pod)) continue;
      const cont = k > 0 && !openIn[k - 1].has(pod);
      closedSince[k][pod] = cont ? closedSince[k - 1][pod] : phases[k].start_s;
      if (cont && prunedAt[k - 1][pod] < Infinity) { prunedAt[k][pod] = prunedAt[k - 1][pod]; continue; }
      const start = meshOf(pod, closedSince[k][pod]);
      if (start == null || start <= 0) continue;
      for (let t = closedSince[k][pod]; t < phases[k].end_s; t += step) {
        const v = meshOf(pod, t);
        if (v != null && Math.abs(v - start) / start > 0.1) { prunedAt[k][pod] = bin(t) * step; break; }
      }
    }
  }
  // A pod whose own mesh size never moved that far takes its region's reaction time.
  for (let k = 0; k < phases.length; k++) {
    if (openCount[k] !== 0 || (k > 0 && openCount[k - 1] === 0)) continue;
    const s = run.mesh_mean_x10[gated] || [], start = s[bin(phases[k].start_s)];
    let at = Infinity;
    for (let t = phases[k].start_s; start && t < end0(k); t += step) {
      const v = s[bin(t)];
      if (v != null && Math.abs(v - start) / start > 0.1) { at = bin(t) * step; break; }
    }
    for (let j = k; j < phases.length && openCount[j] === 0; j++) for (const pod of gatedPods) prunedAt[j][pod] = Math.min(prunedAt[j][pod], at);
  }
  for (let k = 1; k < phases.length; k++) for (const pod of gatedPods) {
    if (!openIn[k].has(pod) && !openIn[k - 1].has(pod)) prunedAt[k][pod] = Math.min(prunedAt[k][pod], prunedAt[k - 1][pod]);
  }
  // 0 live, 1 stale (still counted, unreachable), 2 dialling (open, nothing crossing yet), 3 gone
  const crossState = (pod, t) => {
    const k = effPhase(pod, t);
    if (openIn[k].has(pod)) return t < dialUntil[k] ? 2 : 0;
    return t < prunedAt[k][pod] ? 1 : 3;
  };

  // Delivery per pair in 5 s bins, for the strip under the timeline.
  const end = phases[phases.length - 1].end_s;
  const SB = 5, nb = Math.ceil(end / SB);
  const pairs = {};
  for (const src of [gated, other]) for (const dst of [gated, other]) pairs[`${src}>${dst}`] = { d: new Float64Array(nb), of: new Float64Array(nb) };
  for (let i = 0; i < msg.t_s.length; i++) {
    const src = pods[msg.origin[i]].region, b = Math.min(nb - 1, Math.floor(msg.t_s[i] / SB));
    for (const dst of [gated, other]) { const p = pairs[`${src}>${dst}`]; p.d[b] += msg.delivered[dst][i]; p.of[b] += msg.of[dst][i]; }
  }
  const windowRatio = (src, dst, t, span = 10) => {
    let d = 0, of = 0;
    for (let i = lowerBound(msg.t_s, t - span); i < msg.t_s.length && msg.t_s[i] <= t; i++) {
      if (pods[msg.origin[i]].region !== src) continue;
      d += msg.delivered[dst][i]; of += msg.of[dst][i];
    }
    return of ? d / of : null;
  };
  const steady = (phase, src, dst) => run.steady.find((c) => c.phase === phase && c.src === src && c.dst === dst);
  const meanMesh = (region, t) => { const s = run.mesh_mean_x10[region]; const v = s && s[Math.min(bin(t), s.length - 1)]; return v == null ? null : v / 10; };
  const bytesOf = (pod, t) => {
    const s = run.bytes_per_s[pod]; if (!s || !s.length) return null;
    const x = clamp(t / step - 0.5, 0, s.length - 1), i = Math.floor(x), j = Math.min(s.length - 1, i + 1);
    const a = s[i] ?? s[j], b = s[j] ?? s[i];
    return a == null ? null : a + (b - a) * (x - i);
  };

  const firstShut = openCount.findIndex((c) => c === 0);
  const reopen = firstShut < 0 ? -1 : openCount.findIndex((c, k) => k > firstShut && c > 0);
  return {
    pods, n, gated, other, gatedPods, phases, total, openCount, pos, grid, adj, links, end, borderId, border,
    openIn, lateS, phaseAt, effPhase, isOpen, dialUntil, crossState, prunedAt, meshOf, meanMesh, bytesOf,
    pairs, SB, nb, windowRatio, steady, msg, firstShut, reopen,
  };
}

function lowerBound(arr, x) {
  let lo = 0, hi = arr.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] < x) lo = mid + 1; else hi = mid; }
  return lo;
}

// ---------- three.js scene -----------------------------------------------------------

const canvas = $("scene");
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: query.has("shot") });
} catch (err) {
  fail("This page needs WebGL, which this browser did not provide.");
  throw err;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
scene.background = new THREE.Color(css("--bg"));
scene.fog = new THREE.Fog(scene.background, 60, 140);
const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 400);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.49;
controls.minDistance = 8;
controls.maxDistance = 110;
scene.add(new THREE.AmbientLight(0xffffff, 0.75));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(-18, 30, 22);
scene.add(sun);

const CAMS = {
  overview: { pos: [-34, 27, 33], look: [4, 0, -2] },
  inside: { pos: [-34, 15, 16], look: [-8, 0, 0] },
  wall: { pos: [-25, 13, 12], look: [0, 2, 0] },
  top: { pos: [3, 52, 0.01], look: [3, 0, 0] },
};
function setCam(name, instant = false) {
  const c = CAMS[name];
  const goal = { pos: new THREE.Vector3(...c.pos), look: new THREE.Vector3(...c.look) };
  if (instant) { camera.position.copy(goal.pos); controls.target.copy(goal.look); controls.update(); } else S.camGoal = goal;
}
controls.addEventListener("start", () => { S.camGoal = null; });

const world = new THREE.Group();
scene.add(world);
let G = null; // per-run scene objects

function buildScene(m) {
  world.clear();
  const dummy = new THREE.Object3D();

  // District plates.
  for (const region of [m.gated, m.other]) {
    const xs = m.pods.map((p, i) => (p.region === region ? m.pos[i].x : null)).filter((x) => x != null);
    const w = Math.max(...xs) - Math.min(...xs) + SPACING * 1.4, d = ROWS * SPACING + 1.2;
    const plate = new THREE.Mesh(new THREE.BoxGeometry(w, 0.3, d), new THREE.MeshLambertMaterial({ color: 0x111a24 }));
    plate.position.set((Math.max(...xs) + Math.min(...xs)) / 2, -0.16, 0);
    world.add(plate);
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(plate.geometry),
      new THREE.LineBasicMaterial({ color: region === m.gated ? C.ir : C.world, transparent: true, opacity: 0.35 }));
    edge.position.copy(plate.position);
    world.add(edge);
  }

  // Buildings: one per pod.
  const box = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0);
  const bodies = new THREE.InstancedMesh(box, new THREE.MeshLambertMaterial(), m.n);
  bodies.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  world.add(bodies);
  // A cap on each gated pod: amber while its border is open, red while it is shut.
  const caps = new THREE.InstancedMesh(box, new THREE.MeshBasicMaterial(), m.gatedPods.length);
  world.add(caps);

  // The border: one brick per gated pod, because every pod enforces its own border.
  const cols = Math.ceil(m.gatedPods.length / ROWS);
  const bricks = new THREE.InstancedMesh(new THREE.BoxGeometry(0.5, BRICK_H * 0.9, SPACING * 0.94),
    new THREE.MeshLambertMaterial({ transparent: true, opacity: 0.82 }), m.gatedPods.length);
  bricks.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  world.add(bricks);
  const brickPos = m.gatedPods.map((pod) => {
    const [col, row] = m.grid[pod];
    return new THREE.Vector3(0, 0.1 + BRICK_H * (col + 0.5), (row - (ROWS - 1) / 2) * SPACING);
  });
  const frame = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(0.5, BRICK_H * cols, ROWS * SPACING)),
    new THREE.LineBasicMaterial({ color: 0x3a4656 }));
  frame.position.set(0, 0.1 + (BRICK_H * cols) / 2, 0);
  world.add(frame);

  // Peer links.
  const lp = new Float32Array(m.links.length * 6);
  m.links.forEach((l, i) => {
    const a = m.pos[l.a], b = m.pos[l.b];
    lp.set([a.x, 0.06, a.z, b.x, l.cross ? 0.06 : 0.06, b.z], i * 6);
  });
  const lg = new THREE.BufferGeometry();
  lg.setAttribute("position", new THREE.BufferAttribute(lp, 3));
  lg.setAttribute("color", new THREE.BufferAttribute(new Float32Array(m.links.length * 6), 3));
  const lines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ vertexColors: true, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false }));
  world.add(lines);

  // Message particles.
  const MAXP = 4000;
  const pg = new THREE.BufferGeometry();
  pg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(MAXP * 3), 3));
  pg.setAttribute("color", new THREE.BufferAttribute(new Float32Array(MAXP * 3), 3));
  const points = new THREE.Points(pg, new THREE.PointsMaterial({ size: 0.42, vertexColors: true, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false }));
  points.frustumCulled = false;
  world.add(points);

  const marker = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1.5, 1, 1.5).translate(0, 0.5, 0)), new THREE.LineBasicMaterial({ color: 0xffffff }));
  marker.visible = false;
  world.add(marker);

  G = {
    dummy, bodies, caps, bricks, brickPos, lines, points, marker, MAXP,
    flash: new Float32Array(m.n), tint: Array.from({ length: m.n }, () => new THREE.Color()),
    brickScale: new Float32Array(m.gatedPods.length).fill(1),
    particles: [], flashes: [], height: new Float32Array(m.n).fill(1),
  };

  labelSpecs.length = 0;
  const depth = -(ROWS * SPACING) / 2 - 1.2;
  const mid = (region) => { const xs = m.pods.map((p, i) => (p.region === region ? m.pos[i].x : null)).filter((x) => x != null); return (Math.max(...xs) + Math.min(...xs)) / 2; };
  addLabel(new THREE.Vector3(mid(m.gated), 5.2, depth), `INSIDE<small>${m.total} pods on one Kubernetes node, own pod CIDR</small>`);
  addLabel(new THREE.Vector3(mid(m.other), 5.2, depth), `OUTSIDE<small>${S.data.regions[m.other].nodes} pods on another node</small>`);
  addLabel(new THREE.Vector3(0, 0.1 + BRICK_H * cols + 1.0, depth + 1.2), `BORDER<small>one brick per inside pod: its own tc rules</small>`);
}

const labelSpecs = [];
function addLabel(at, html) {
  const el = document.createElement("div");
  el.className = "label3d"; el.innerHTML = html;
  labelSpecs.push({ at, el });
}
function placeLabels() {
  const host = $("labels");
  if (host.childElementCount !== labelSpecs.length) host.replaceChildren(...labelSpecs.map((l) => l.el));
  const v = new THREE.Vector3();
  for (const l of labelSpecs) {
    v.copy(l.at).project(camera);
    const x = (v.x * 0.5 + 0.5) * innerWidth;
    l.el.style.display = v.z > 1 || x < 300 || x > innerWidth - 340 ? "none" : "";
    l.el.style.left = `${x}px`;
    l.el.style.top = `${(-v.y * 0.5 + 0.5) * innerHeight}px`;
  }
}

// ---------- replaying messages --------------------------------------------------------

// Breadth-first order from the publishing pod over the links a message could use.
function spread(m, origin, crossAllowed, t) {
  const depth = new Int16Array(m.n).fill(-1), parent = new Int16Array(m.n).fill(-1), order = [];
  depth[origin] = 0;
  const queue = [origin];
  for (let q = 0; q < queue.length; q++) {
    const a = queue[q];
    for (const b of m.adj[a]) {
      if (depth[b] >= 0) continue;
      if (m.pods[a].region !== m.pods[b].region) {
        const g = m.pods[a].region === m.gated ? a : b;
        if (!crossAllowed || !m.isOpen(g, t)) continue;
      }
      depth[b] = depth[a] + 1; parent[b] = a; queue.push(b); order.push(b);
    }
  }
  return { depth, parent, order };
}

function emit(m, i, now) {
  const origin = m.msg.origin[i], t = m.msg.t_s[i];
  const src = m.pods[origin].region, dst = src === m.gated ? m.other : m.gated;
  const crossed = m.msg.delivered[dst][i] > 0;
  const { depth, parent, order } = spread(m, origin, crossed, t);
  const color = src === m.gated ? C.ir : C.world;
  const plan = [];
  for (const region of [src, dst]) {
    const want = m.msg.delivered[region][i];
    const got = order.filter((p) => m.pods[p].region === region).slice(0, want);
    if (!got.length) continue;
    const mid = median(got.map((p) => depth[p])) || 1;
    const p50 = m.msg.p50_ms[region][i] ?? 100;
    for (const p of got) plan.push({ pod: p, ms: (p50 * depth[p]) / mid });
  }
  if (!plan.length) return;
  const at = new Map(plan.map((x) => [x.pod, x.ms]));
  at.set(origin, 0);
  const longest = Math.max(...plan.map((x) => x.ms)) / 1000;
  // At 1x and below this is real time. Faster than that, a message would be over in a
  // frame, so its animation is stretched to stay visible.
  const k = Math.max(longest / S.speed, 0.55) / longest;
  G.flashes.push({ pod: origin, at: now, color: C.white });
  for (const x of plan) {
    const from = parent[x.pod];
    const t0 = now + ((at.get(from) ?? 0) / 1000) * k, t1 = now + (x.ms / 1000) * k;
    G.flashes.push({ pod: x.pod, at: t1, color });
    if (G.particles.length < G.MAXP) G.particles.push({ a: m.pos[from], b: m.pos[x.pod], t0, t1: Math.max(t1, t0 + 0.05), color, ha: G.height[from], hb: G.height[x.pod] });
  }
  // Nothing crossed: show a few copies reaching the wall and stopping there.
  if (!crossed && m.msg.of[dst][i] > 0) {
    let shown = 0;
    for (const x of plan) {
      if (shown >= 5 || m.pods[x.pod].region !== src) continue;
      if (![...m.adj[x.pod]].some((j) => m.pods[j].region !== src)) continue;
      const a = m.pos[x.pod], t0 = now + (x.ms / 1000) * k;
      G.particles.push({ a, b: new THREE.Vector3(0, 0, a.z), t0, t1: t0 + 0.45, color: C.shut, ha: G.height[x.pod], hb: 1.2 });
      shown++;
    }
  }
}

// ---------- per-frame update ----------------------------------------------------------

const clock = new THREE.Clock();
let linkTick = 0;

function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(clock.getDelta(), 0.1), now = clock.elapsedTime;
  const m = S.model;
  if (!m) return;

  if (S.playing) {
    const before = S.t;
    S.t = Math.min(m.end, S.t + dt * S.speed);
    if (S.t >= m.end) { S.playing = false; syncPlay(); }
    // Emit the messages published in this slice of time, thinned so each stays visible.
    const hi = lowerBound(m.msg.t_s, S.t);
    for (let i = Math.max(S.msgCursor, lowerBound(m.msg.t_s, before)); i < hi; i++) {
      const inside = m.pods[m.msg.origin[i]].region === m.gated;
      if (!(inside ? $("v-inside").checked : $("v-outside").checked)) continue;
      if (now - S.lastEmit < 0.4 && S.speed > 1) continue;
      emit(m, i, now); S.lastEmit = now;
    }
    S.msgCursor = hi;
  }
  const t = S.t;

  // Buildings.
  const useHeight = $("v-height").checked;
  for (let i = G.flashes.length - 1; i >= 0; i--) {
    const f = G.flashes[i];
    if (now >= f.at) { G.flash[f.pod] = 1; G.tint[f.pod].copy(f.color); G.flashes.splice(i, 1); }
  }
  const col = new THREE.Color();
  for (let i = 0; i < m.n; i++) {
    const b = m.bytesOf(i, t);
    const target = useHeight && b != null ? 0.5 + 3.4 * clamp(b / 20000, 0, 1) : 1.2;
    G.height[i] += (target - G.height[i]) * Math.min(1, dt * 6);
    G.dummy.position.copy(m.pos[i]); G.dummy.scale.set(1.1, G.height[i], 1.1); G.dummy.updateMatrix();
    G.bodies.setMatrixAt(i, G.dummy.matrix);
    G.flash[i] *= Math.exp(-dt * 7);
    col.copy(m.pods[i].region === m.gated ? C.ir : C.world).multiplyScalar(0.34).lerp(G.tint[i], G.flash[i] * 0.8);
    G.bodies.setColorAt(i, col);
  }
  G.bodies.instanceMatrix.needsUpdate = true;
  G.bodies.instanceColor.needsUpdate = true;

  // Caps and bricks.
  m.gatedPods.forEach((pod, k) => {
    const open = m.isOpen(pod, t);
    G.dummy.position.set(m.pos[pod].x, G.height[pod], m.pos[pod].z); G.dummy.scale.set(0.62, 0.16, 0.62); G.dummy.updateMatrix();
    G.caps.setMatrixAt(k, G.dummy.matrix);
    G.caps.setColorAt(k, open ? C.open : C.shutCap);
    const goal = open ? 0 : 1;
    G.brickScale[k] += (goal - G.brickScale[k]) * Math.min(1, dt * 14);
    G.dummy.position.copy(G.brickPos[k]); G.dummy.scale.setScalar(G.brickScale[k] < 0.02 ? 0 : 1); G.dummy.scale.y = G.brickScale[k] < 0.02 ? 0 : G.brickScale[k]; G.dummy.updateMatrix();
    G.bricks.setMatrixAt(k, G.dummy.matrix);
    G.bricks.setColorAt(k, pod === S.selected ? C.white : C.shut);
  });
  G.caps.instanceMatrix.needsUpdate = true; G.caps.instanceColor.needsUpdate = true;
  G.bricks.instanceMatrix.needsUpdate = true; G.bricks.instanceColor.needsUpdate = true;

  // Links.
  G.lines.visible = $("v-links").checked;
  if (G.lines.visible && now - linkTick > 0.08) {
    linkTick = now;
    const arr = G.lines.geometry.attributes.color.array;
    const blink = 0.45 + 0.4 * Math.sin(now * 7);
    m.links.forEach((l, i) => {
      let c = C.live, k = 1;
      if (l.cross) {
        const st = m.crossState(l.gatedEnd, t);
        if (st === 1) { c = C.shut; k = 0.5; } else if (st === 2) { c = C.open; k = blink; } else if (st === 3) { c = C.black; } else { c = C.live; k = 1.6; }
      }
      if (S.selected >= 0 && (l.a === S.selected || l.b === S.selected) && c !== C.black) { c = c === C.live ? C.white : c; k = Math.max(k, 0.8); }
      arr.set([c.r * k, c.g * k, c.b * k, c.r * k, c.g * k, c.b * k], i * 6);
    });
    G.lines.geometry.attributes.color.needsUpdate = true;
  }

  // Particles.
  const pp = G.points.geometry.attributes.position.array, pc = G.points.geometry.attributes.color.array;
  let live = 0;
  for (let i = G.particles.length - 1; i >= 0; i--) if (now > G.particles[i].t1) G.particles.splice(i, 1);
  for (const p of G.particles) {
    if (now < p.t0 || live >= G.MAXP) continue;
    const u = (now - p.t0) / (p.t1 - p.t0);
    const y = p.ha + (p.hb - p.ha) * u + Math.sin(u * Math.PI) * 1.1 + 0.2;
    pp.set([p.a.x + (p.b.x - p.a.x) * u, y, p.a.z + (p.b.z - p.a.z) * u], live * 3);
    pc.set([p.color.r, p.color.g, p.color.b], live * 3);
    live++;
  }
  G.points.geometry.setDrawRange(0, live);
  G.points.geometry.attributes.position.needsUpdate = true;
  G.points.geometry.attributes.color.needsUpdate = true;

  if (S.selected >= 0) {
    G.marker.visible = true;
    G.marker.position.copy(m.pos[S.selected]); G.marker.scale.set(1, G.height[S.selected] + 0.3, 1);
  } else G.marker.visible = false;

  if (S.camGoal) {
    camera.position.lerp(S.camGoal.pos, Math.min(1, dt * 3));
    controls.target.lerp(S.camGoal.look, Math.min(1, dt * 3));
    if (camera.position.distanceTo(S.camGoal.pos) < 0.05) S.camGoal = null;
  }
  controls.autoRotate = $("v-spin").checked;
  controls.autoRotateSpeed = 0.5;
  controls.update();
  renderer.render(scene, camera);
  placeLabels();
  hud(now);
}

// ---------- panels -------------------------------------------------------------------

let hudTick = 0, hudPhase = -1;
function hud(now) {
  const m = S.model, t = S.t;
  $("playhead").style.left = `${(t / m.end) * 100}%`;
  if (now - hudTick < 0.12) return;
  hudTick = now;
  const k = m.phaseAt(t), ph = m.phases[k];
  $("clock").textContent = mmss(t);
  $("phase-name").textContent = ph.name;
  $("phase-note").textContent = ph.note;
  const openNow = m.gatedPods.filter((p) => m.isOpen(p, t)).length;
  $("border-count").textContent = `${openNow} of ${m.total}`;

  const names = { [m.gated]: "inside", [m.other]: "outside" };
  const rows = [[m.gated, m.gated], [m.gated, m.other], [m.other, m.gated], [m.other, m.other]];
  $("delivery").innerHTML = rows.map(([s, d]) => {
    const r = m.windowRatio(s, d, t);
    const color = r == null ? "#333" : r >= 0.99 ? css("--ok") : r > 0.01 ? css("--open") : css("--shut");
    return `<div class="bar"><span>${names[s]} to ${names[d]}</span><div class="track"><div class="fill" style="width:${(r ?? 0) * 100}%;background:${color}"></div></div><span class="val">${pct(r)}</span></div>`;
  }).join("");
  if (k !== hudPhase) {
    hudPhase = k;
    $("latency").innerHTML = rows.map(([s, d]) => {
      const c = m.steady(ph.name, s, d);
      return `<span>${names[s]} to ${names[d]}</span><b>${c && c.p50_ms != null ? `${Math.round(c.p50_ms)} ms` : "none delivered"}</b>`;
    }).join("");
  }
  $("mesh").innerHTML = [m.gated, m.other].map((r) => {
    const v = m.meanMesh(r, t);
    return `<span>${names[r]}, mean peers in mesh</span><b>${v == null ? "-" : v.toFixed(1)}</b>`;
  }).join("");

  let note = "";
  const since = Math.floor(t - ph.start_s);
  if (k > 0 && m.openCount[k] === 0) {
    note = `Border shut ${since} s ago. Inside pods still report a mesh of ${m.meanMesh(m.gated, t)?.toFixed(1)} peers.`;
  } else if (k > 0 && t < m.dialUntil[k]) {
    note = `${m.openCount[k]} of ${m.total} reopened ${since} s ago. Nothing has crossed yet.`;
  } else if (k > 0 && m.dialUntil[k] > ph.start_s && t - m.dialUntil[k] < 45) {
    note = `First message crossed ${Math.round(m.dialUntil[k] - ph.start_s)} s after ${m.openCount[k]} pods reopened.`;
  }
  $("event").textContent = note;
  if (S.selected >= 0 && !$("tab-pod").hidden) podPanel();
}

function podPanel() {
  const m = S.model, i = S.selected, t = S.t;
  if (i < 0) return;
  const pod = m.pods[i], inside = pod.region === m.gated, k = m.phaseAt(t), ph = m.phases[k];
  const open = inside ? m.isOpen(i, t) : true;
  const own = S.data.regions[pod.region].domestic, b = m.border.healthy;
  const late = m.lateS[k][i];
  const mesh = m.meshOf(i, t), bytes = m.bytesOf(i, t);
  const far = inside ? "outside" : "inside";
  const borderRule = inside && !open
    ? `<span class="drop">drop</span>`
    : `<span class="pass">netem ${b.delay_ms}ms &plusmn;${b.jitter_ms}ms, loss ${b.loss_pct}%, ${b.rate_mbit} Mbit</span>`;
  $("tab-pod").innerHTML = `
    <table class="kv">
      <tr><td><b>${pod.name}</b></td><td class="muted">${inside ? "inside" : "outside"} (${pod.region})</td></tr>
      ${inside ? `<tr><td>Border on this pod</td><td style="color:${open ? css("--open") : css("--shut")}">${open ? "open" : "shut"}</td></tr>` : ""}
      <tr><td>Mesh size</td><td>${mesh == null ? "-" : mesh.toFixed(1)} peers</td></tr>
      <tr><td>Sending</td><td>${bytes == null ? "-" : (bytes / 1000).toFixed(1)} kB/s</td></tr>
      <tr><td>Applied "${ph.name}"</td><td>${late == null ? "-" : `${Math.round(late * 1000)} ms after schedule`}</td></tr>
    </table>
    <h2>What its shaper is doing now</h2>
<pre class="tc">shaper sidecar, same network namespace
egress: prio, by destination CIDR
  same region
    netem ${own.delay_ms}ms &plusmn;${own.jitter_ms}ms, ${own.rate_mbit} Mbit
  to ${far}
    ${borderRule}
  control plane
    unshaped
ingress
  from ${far}
    ${inside && !open ? `<span class="drop">drop</span>` : `<span class="pass">pass</span>`}</pre>
    <p class="muted small">The whole timeline was loaded before the run. The shaper applies each phase at an absolute time; nothing is sent to the pod at the moment of the cut.${inside ? "" : " Outside pods are never gated: an inside pod with a shut border drops the traffic on arrival."}</p>`;
}

function buildPanels() {
  const m = S.model, run = S.run;
  // Timeline.
  $("total").textContent = mmss(m.end);
  $("phases").innerHTML = m.phases.map((ph, k) => {
    const f = m.openCount[k] / m.total;
    const bg = f === 0 ? css("--shut") : f === 1 ? css("--ok") : css("--open");
    return `<div style="flex:${ph.end_s - ph.start_s};background:${bg}" title="${ph.note}">${ph.name} &middot; ${m.openCount[k]}/${m.total}</div>`;
  }).join("");
  drawSpark();

  // Numbers the cards quote, all from this run.
  const cut = m.firstShut, re = m.reopen;
  const late = cut >= 0 ? m.gatedPods.map((p) => m.lateS[cut][p] * 1000) : [];
  const lateAll = Object.values(run.shaper_late_ms).flat().filter((x) => x != null);
  const gap = re >= 0 ? Math.round(m.dialUntil[re] - m.phases[re].start_s) : null;
  const noticed = cut >= 0 ? median(m.gatedPods.map((p) => m.prunedAt[cut][p]).filter((x) => x < Infinity)) : null;
  const inside = cut >= 0 ? m.steady(m.phases[cut].name, m.gated, m.gated) : null;
  const base = m.steady(m.phases[0].name, m.gated, m.other);
  const partial = [...m.phases.keys()].reverse().find((k) => m.openCount[k] > 0 && m.openCount[k] < m.total);
  const slow = partial != null ? m.steady(m.phases[partial].name, m.gated, m.other) : null;
  const withdrawn = S.data.runs.filter((r) => !r.valid);
  const num = (x) => `<span class="num">${x}</span>`;
  const go = (t, speed, cam) => ({ t, speed, cam });

  const how = [
    ["An outage becomes a timeline", `A public traffic signal for the real event is cut into levels. Each level becomes a phase: how many inside nodes still have a border. That is the bar at the bottom: ${num(m.phases.length)} phases, replayed in ${num(mmss(m.end))}.`, go(0, 30, "overview")],
    ["Regions are Kubernetes nodes", `Each district is one cluster node with its own pod address range. Each building is a pod running the gossipsub node under test, ${num(m.n)} in all. Height is how many bytes it is sending.`, go(20, 10, "inside")],
    ["Every pod carries its own border", `There is no central firewall. A sidecar in each pod sorts traffic by destination range with <code>tc</code>: same region, across the border, or dropped. So the wall is ${num(m.total)} bricks, one per inside pod. Click a building to see its rules.`, go(cut >= 0 ? m.phases[cut].start_s + 12 : 0, 1, "wall")],
    ["The cut lands on the clock", cut >= 0 ? `Every shaper holds the whole timeline and acts at an absolute time. In this run the ${num(m.total)} bricks went up between ${num(Math.round(Math.min(...late)))} and ${num(Math.round(Math.max(...late)))} ms after the scheduled instant. Watch it at a tenth of real speed.` : "This scenario has no full cut.", go(cut >= 0 ? m.phases[cut].start_s - 0.25 : 0, 0.1, "wall")],
    ["One publisher, one clock", `Once a second the controller asks one pod to publish. Every flash is a pod that logged receiving that message; a red spark is a copy that reached a shut border.`, go(cut >= 0 ? m.phases[cut].start_s + 40 : 30, 1, "overview")],
    ["Evidence first, then a verdict", `The run only collects logs. Seven validity rules judge them afterwards, and a run that breaks one is withdrawn. ${withdrawn.length ? `Here ${withdrawn.map((r) => `seed ${r.seed} was withdrawn under ${r.failed.map((f) => f.rule).join(", ")}`).join("; ")}.` : "No run of this scenario was withdrawn."} Shapers in this run were at most ${num(Math.round(Math.max(...lateAll)))} ms late against a limit of 500.`, go(S.t, S.speed, "overview")],
  ];
  const found = [];
  if (cut >= 0) {
    found.push(["Inside, nothing is lost", `Through the shutdown, inside-to-inside delivery was ${num(pct(inside?.ratio))} at a median of ${num(Math.round(inside?.p50_ms ?? 0))} ms.`, go(m.phases[cut].start_s - 6, 10, "inside")]);
    if (noticed != null) found.push(["The mesh notices late", `Inside pods kept counting unreachable peers. Half of them had changed mesh size ${num(Math.round(noticed - m.phases[cut].start_s))} s after the cut (${S.data.step_s} s resolution). Red links are peers still counted.`, go(noticed - 25, 10, "overview")]);
  }
  if (re >= 0) {
    found.push([`${m.openCount[re]} of ${m.total} reopen, and nothing crosses`, `For ${num(gap)} s after the border reopened on ${m.openCount[re]} pods, no message crossed in either direction.`, go(m.phases[re].start_s - 4, 10, "wall")]);
    found.push(["Then everything crosses", `From ${num(mmss(m.dialUntil[re]))} delivery across the border goes from 0% to 100% through those ${m.openCount[re]} pods.`, go(m.dialUntil[re] - 5, 1, "overview")]);
  }
  if (slow && base) found.push(["Outward stays slow", `With ${m.openCount[partial]} of ${m.total} open, inside to outside took a median of ${num(Math.round(slow.p50_ms))} ms against ${num(Math.round(base.p50_ms))} ms before the cut.`, go(m.phases[partial].start_s + 30, 1, "overview")]);

  const cards = (list, host) => {
    host.innerHTML = list.map(([title, body], i) => `<div class="step" data-i="${i}"><h3><span>${i + 1}</span>${title}</h3><p>${body}</p></div>`).join("");
    host.querySelectorAll(".step").forEach((el) => el.addEventListener("click", () => {
      document.querySelectorAll(".step").forEach((x) => x.classList.remove("on"));
      el.classList.add("on");
      const g = list[+el.dataset.i][2];
      seek(g.t); setSpeed(g.speed); setCam(g.cam); S.playing = true; syncPlay();
    }));
  };
  cards(how, $("tab-how"));
  cards(found, $("tab-found"));
}

function drawSpark() {
  const m = S.model, cv = $("spark"), w = cv.clientWidth, h = 46, dpr = Math.min(devicePixelRatio, 2);
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext("2d");
  g.scale(dpr, dpr); g.clearRect(0, 0, w, h);
  g.strokeStyle = "rgba(255,255,255,.08)"; g.beginPath(); g.moveTo(0, 3.5); g.lineTo(w, 3.5); g.moveTo(0, h - 3.5); g.lineTo(w, h - 3.5); g.stroke();
  const draw = (key, color, width) => {
    const p = m.pairs[key];
    g.strokeStyle = color; g.lineWidth = width; g.beginPath();
    let pen = false;
    for (let b = 0; b < m.nb; b++) {
      if (!p.of[b]) { continue; }
      const x = ((b + 0.5) * m.SB / m.end) * w, y = h - 4 - (p.d[b] / p.of[b]) * (h - 8);
      if (pen) g.lineTo(x, y); else g.moveTo(x, y);
      pen = true;
    }
    g.stroke();
  };
  draw(`${m.gated}>${m.gated}`, "#5b6b7d", 1.5);
  draw(`${m.other}>${m.gated}`, css("--world"), 2);
  draw(`${m.gated}>${m.other}`, css("--ir"), 2);
}

// ---------- controls -----------------------------------------------------------------

function seek(t) {
  const m = S.model;
  S.t = clamp(t, 0, m.end);
  S.msgCursor = lowerBound(m.msg.t_s, S.t);
  G.particles.length = 0; G.flashes.length = 0;
  hudTick = 0;
}
function setSpeed(v) {
  S.speed = v;
  document.querySelectorAll("#speeds button").forEach((b) => b.classList.toggle("on", +b.dataset.v === v));
}
function syncPlay() { $("play").textContent = S.playing ? "Pause" : "Play"; }
function fail(text) { const e = $("error"); e.hidden = false; e.textContent = text; }

function selectRun(seed) {
  S.run = S.data.runs.find((r) => r.seed === seed && r.valid) || S.data.runs.find((r) => r.valid);
  S.model = buildModel(S.data, S.run);
  S.selected = -1; hudPhase = -1;
  buildScene(S.model);
  buildPanels();
  seek(Math.min(S.t, S.model.end));
  $("run").value = String(S.run.seed);
}

async function loadScenario(id) {
  const res = await fetch(`data/${id}.json`);
  if (!res.ok) throw new Error(`data/${id}.json: ${res.status}`);
  S.data = await res.json();
  $("run").innerHTML = S.data.runs.map((r) =>
    `<option value="${r.seed}" ${r.valid ? "" : "disabled"}>seed ${r.seed}${r.valid ? "" : ` (withdrawn: ${r.failed.map((f) => f.rule).join(", ")})`}</option>`).join("");
  const link = $("evidence");
  link.href = S.data.evidence_url || "#"; link.hidden = !S.data.evidence_url;
  S.t = 0;
  selectRun(+(query.get("seed") || 0));
}

function wire() {
  $("speeds").innerHTML = SPEEDS.map((v) => `<button data-v="${v}">${v}&times;</button>`).join("");
  $("speeds").addEventListener("click", (e) => { if (e.target.dataset.v) setSpeed(+e.target.dataset.v); });
  $("play").addEventListener("click", () => {
    if (!S.playing && S.t >= S.model.end) seek(0);
    S.playing = !S.playing; syncPlay();
  });
  addEventListener("keydown", (e) => { if (e.code === "Space" && e.target.tagName !== "SELECT") { e.preventDefault(); $("play").click(); } });
  $("run").addEventListener("change", (e) => selectRun(+e.target.value));
  $("scenario").addEventListener("change", (e) => loadScenario(e.target.value).catch((err) => fail(String(err))));

  const tl = $("timeline");
  const scrub = (e) => { const r = tl.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * S.model.end); };
  tl.addEventListener("pointerdown", (e) => { tl.setPointerCapture(e.pointerId); scrub(e); tl.onpointermove = scrub; });
  tl.addEventListener("pointerup", () => { tl.onpointermove = null; });

  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

  // Click a building to inspect its pod.
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5 || !G) return;
    mouse.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObject(G.bodies)[0];
    S.selected = hit ? hit.instanceId : -1;
    if (hit) { showTab("pod"); podPanel(); }
  });

  const resize = () => {
    renderer.setSize(innerWidth, innerHeight, false);
    camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
    if (S.model) drawSpark();
  };
  addEventListener("resize", resize);
  resize();
}

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  for (const t of ["how", "found", "pod", "view"]) $(`tab-${t}`).hidden = t !== name;
}

async function main() {
  wire();
  setCam("overview", true);
  const index = await (await fetch("data/index.json")).json();
  $("scenario").innerHTML = index.map((s) => `<option value="${s.id}">${s.label}</option>`).join("");
  const first = index.find((s) => s.id === query.get("scenario")) || index[0];
  $("scenario").value = first.id;
  await loadScenario(first.id);
  setSpeed(query.has("speed") ? +query.get("speed") : 30);
  if (query.has("t")) seek(+query.get("t"));
  if (query.has("cam") && CAMS[query.get("cam")]) setCam(query.get("cam"), true);
  if (query.has("tab")) showTab(query.get("tab"));
  if (query.has("pod")) { S.selected = S.model.pods.findIndex((p) => p.name === query.get("pod")); podPanel(); }
  syncPlay();
  frame();
}

main().catch((err) => { console.error(err); fail(`Could not load the replay data: ${err.message}`); });
