import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

// Set VITE_API_URL in dashboard/.env (local) and in Amplify's environment variables.
// With no API URL, the dashboard runs on fake data so you can build the UI right away.
const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
const DEVICE_ID = import.meta.env.VITE_DEVICE_ID || "kid-001";
const POLL_MS = 1500;
const MOCK = !API;

const TVOC_YELLOW = 220;
const TVOC_RED = 660;

const RISK = {
  green: { label: "Good", title: "The air is clean", tip: "No action needed. Breathe easy." },
  yellow: { label: "Fair", title: "The air is getting worse", tip: "Open a window and skip sprays or strong cleaners." },
  red: { label: "Bad", title: "The air is unhealthy", tip: "Move to cleaner air and keep the inhaler close." },
};

// ---------------- Fake data (used when VITE_API_URL is empty) ----------------
const mock = { tvoc: 120, history: [], puffs: [] };
function mockStatus() {
  const spike = Math.random() < 0.08 ? 1800 : 0;
  mock.tvoc = Math.max(20, Math.min(3000, mock.tvoc * 0.8 + 30 + spike + (Math.random() - 0.5) * 40));
  const tvoc = Math.round(mock.tvoc);
  const humidity = 45 + Math.round(Math.random() * 6);
  const risk = tvoc > TVOC_RED ? "red" : tvoc >= TVOC_YELLOW ? "yellow" : "green";
  mock.history = [...mock.history, { ts: Date.now(), tvoc, risk }].slice(-60);
  return {
    deviceId: DEVICE_ID, name: "Jayden", risk, reasons: [],
    latest: { tvoc, eco2: 400 + tvoc, tempC: 21.5, humidity },
    puffs24h: mock.puffs.length, lastPuffDurationMs: 1400, lastPuffMs: Date.now() - 600000,
    updatedMs: Date.now(), online: true, history: mock.history,
  };
}
function mockKids() {
  const me = mockStatus();
  return [
    me,
    { deviceId: "kid-002", name: "Amira", risk: "yellow", latest: { tvoc: 340 }, puffs24h: 1, updatedMs: Date.now(), online: true },
    { deviceId: "kid-003", name: "Marcus", risk: "green", latest: { tvoc: 90 }, puffs24h: 0, updatedMs: Date.now(), online: true },
  ].sort((a, b) => ["red", "yellow", "green"].indexOf(a.risk) - ["red", "yellow", "green"].indexOf(b.risk));
}

// ---------------- Data hooks ----------------
function usePoll(path, mockFn) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    async function load() {
      try {
        const next = MOCK ? mockFn() : await fetch(API + path).then((r) => {
          if (!r.ok) throw new Error(`API returned ${r.status}`);
          return r.json();
        });
        if (alive) { setData(next); setError(""); }
      } catch (e) {
        if (alive) setError(e.message || "Can't reach the API");
      }
    }
    load();
    const id = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, [path, mockFn]);
  return { data, error };
}

function useNow(ms = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(id); }, [ms]);
  return now;
}

function ago(ms, now) {
  if (!ms) return "never";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  return new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
const clock = (ms) => new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });

// ---------------- City backdrop: clear sky when good, smog when bad ----------------
const BUILDINGS = [
  // x, width, height  (a Detroit-ish skyline; the RenCen cluster sits in the middle)
  [0, 70, 120], [64, 50, 170], [110, 80, 95], [186, 46, 200], [228, 72, 140], [296, 40, 225],
  [332, 64, 160], [392, 90, 110], [478, 54, 185], [528, 38, 230],
  [600, 44, 255], [652, 56, 310], [716, 44, 255], [770, 44, 240], // RenCen
  [830, 60, 175], [886, 84, 125], [966, 46, 235], [1008, 70, 150], [1074, 52, 205],
  [1122, 90, 105], [1208, 48, 180], [1252, 66, 135], [1314, 44, 225], [1354, 86, 120],
];
function CityBackdrop({ risk, cleanse }) {
  const windows = useMemo(() => {
    const out = [];
    BUILDINGS.forEach(([x, w, h], b) => {
      for (let yy = 330 - h + 14; yy < 316; yy += 18)
        for (let xx = x + 8; xx < x + w - 10; xx += 14)
          if ((xx * 7 + yy * 3 + b) % 5 < 2) out.push([xx, yy]);
    });
    return out;
  }, []);
  return (
    <div className={`city ${risk} ${cleanse ? "cleanse" : ""}`} aria-hidden="true">
      <div className="sky sky-green" /><div className="sky sky-yellow" /><div className="sky sky-red" />
      <div className="sun" />
      <svg className="skyline" viewBox="0 0 1440 330" preserveAspectRatio="xMidYMax slice">
        <rect x="0" y="300" width="1440" height="30" className="ground" />
        {BUILDINGS.map(([x, w, h], i) => (
          <rect key={i} x={x} y={330 - h} width={w} height={h} rx={i >= 10 && i <= 13 ? 14 : 2} className="bldg" />
        ))}
        <rect x="677" y="2" width="6" height="20" className="bldg" />
        {windows.map(([x, y], i) => <rect key={i} x={x} y={y} width="5" height="7" className="win" />)}
      </svg>
      <div className="smog-bank" />
      <div className="smog smog-1" /><div className="smog smog-2" /><div className="smog smog-3" />
      <div className="haze" />
      {cleanse && (
        <div className="wind" key={cleanse}>
          <div className="gust" />
          {[12, 24, 33, 47, 58, 66, 78, 88].map((top, i) => (
            <span key={i} className="streak" style={{ top: `${top}%`, animationDelay: `${(i % 4) * 0.18}s` }} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------- Chart: compressed scale so spikes don't flatten everything else ----------------
function VocChart({ history }) {
  const points = (history || []).filter((h) => h.tvoc != null);
  const [hover, setHover] = useState(null);
  const svgRef = useRef(null);
  if (points.length < 2) return <p className="muted">Waiting for readings…</p>;

  const W = 760, H = 240, padL = 48, padR = 14, padT = 14, padB = 30;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const maxV = Math.max(...points.map((p) => p.tvoc));
  const top = Math.max(1000, Math.ceil((maxV * 1.08) / 100) * 100);
  // square-root scale: small values get room, big spikes stay on the chart
  const y = (v) => padT + (1 - Math.sqrt(Math.max(0, Math.min(v, top))) / Math.sqrt(top)) * innerH;
  const x = (i) => padL + (i / (points.length - 1)) * innerW;
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.tvoc).toFixed(1)}`).join(" ");
  const area = `${line} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const ticks = [0, 50, TVOC_YELLOW, TVOC_RED, 1000, ...(top > 1500 ? [top] : [])];
  const last = points[points.length - 1];

  function onMove(e) {
    const r = svgRef.current.getBoundingClientRect();
    const mx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((mx - padL) / innerW) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  }
  const h = hover != null ? points[hover] : null;
  const tipX = h ? Math.min(Math.max(x(hover), padL + 70), W - padR - 70) : 0;

  return (
    <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="chart" role="img"
         aria-label="VOC level over the last few minutes" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <defs>
        <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <rect x={padL} y={y(TVOC_YELLOW)} width={innerW} height={y(0) - y(TVOC_YELLOW)} className="zone green" />
      <rect x={padL} y={y(TVOC_RED)} width={innerW} height={y(TVOC_YELLOW) - y(TVOC_RED)} className="zone yellow" />
      <rect x={padL} y={y(top)} width={innerW} height={y(TVOC_RED) - y(top)} className="zone red" />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} className={`grid ${t === TVOC_YELLOW ? "yellow" : t === TVOC_RED ? "red" : ""}`} />
          <text x={padL - 8} y={y(t)} className="tick" textAnchor="end" dominantBaseline="central">{t}</text>
        </g>
      ))}
      <path d={area} fill="url(#areaFill)" />
      <path d={line} className="trend" />
      <circle cx={x(points.length - 1)} cy={y(last.tvoc)} r="6" className={`dot ${last.risk}`} />
      <circle cx={x(points.length - 1)} cy={y(last.tvoc)} r="11" className={`pulse ${last.risk}`} />
      <text x={padL} y={H - 8} className="tick">{ago(points[0].ts, Date.now())}</text>
      <text x={W - padR} y={H - 8} className="tick" textAnchor="end">now</text>
      {h && (
        <g className="hover">
          <line x1={x(hover)} x2={x(hover)} y1={padT} y2={padT + innerH} />
          <circle cx={x(hover)} cy={y(h.tvoc)} r="5" className={`dot ${h.risk}`} />
          <rect x={tipX - 68} y={padT + 4} width="136" height="40" rx="8" className="tipbox" />
          <text x={tipX} y={padT + 20} textAnchor="middle" className="tipval">{h.tvoc} ppb</text>
          <text x={tipX} y={padT + 35} textAnchor="middle" className="tiptime">{clock(h.ts)}</text>
        </g>
      )}
    </svg>
  );
}

function Gauge({ value, risk }) {
  const v = Math.max(0, value || 0);
  const frac = Math.min(1, Math.sqrt(v) / Math.sqrt(1000));
  const R = 70, C = Math.PI * R;
  return (
    <svg viewBox="0 0 180 104" className="gauge" aria-hidden="true">
      <path d="M20 94 A70 70 0 0 1 160 94" className="gauge-track" />
      <path d="M20 94 A70 70 0 0 1 160 94" className={`gauge-fill ${risk}`} style={{ strokeDasharray: `${C * frac} ${C}` }} />
    </svg>
  );
}

function Metric({ label, value, unit, sub }) {
  return (
    <div className="metric glass">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value ?? "–"}<span>{value != null ? unit : ""}</span></div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

// ---------------- Views ----------------
function ParentView({ onRisk, onPuff }) {
  const { data, error } = usePoll(`/status/${DEVICE_ID}`, mockStatus);
  const now = useNow();
  const [summary, setSummary] = useState("");
  const [loadingSummary, setLoadingSummary] = useState(false);
  const prevRisk = useRef(null);
  const prevPuff = useRef(undefined);
  const [flash, setFlash] = useState(false);

  useEffect(() => {  // a new puff came in: blow the smog away for a few seconds
    if (!data) return;
    const p = data.lastPuffMs || null;
    if (prevPuff.current !== undefined && p && p !== prevPuff.current) onPuff(data.lastPuffDurationMs);
    prevPuff.current = p;
  }, [data, onPuff]);

  useEffect(() => {  // flash the card when risk changes, so the demo moment pops
    if (!data) return;
    onRisk(data.risk || "green");
    if (prevRisk.current && prevRisk.current !== data.risk) {
      setFlash(true);
      const id = setTimeout(() => setFlash(false), 1400);
      prevRisk.current = data.risk;
      return () => clearTimeout(id);
    }
    prevRisk.current = data.risk;
  }, [data, onRisk]);

  async function getSummary() {
    setLoadingSummary(true);
    try {
      const res = MOCK
        ? { summary: "Demo mode: the air was mostly good today, with one short spike this evening. No inhaler use was logged. Keep using a fan when cleaning." }
        : await fetch(`${API}/summary/${DEVICE_ID}`).then((r) => r.json());
      setSummary(res.summary || res.error || "No summary returned.");
    } catch {
      setSummary("Couldn't get a summary right now.");
    }
    setLoadingSummary(false);
  }

  if (!data) return <div className="glass panel muted">{error ? `Can't reach the API: ${error}` : "Connecting to the sensor…"}</div>;
  const risk = data.risk || "green";
  const l = data.latest || {};
  const tempF = l.tempC != null ? Math.round(l.tempC * 9 / 5 + 32) : null;
  const held = data.lastPuffDurationMs != null ? (data.lastPuffDurationMs / 1000).toFixed(1) : null;

  return (
    <>
      {error && <div className="warn">Connection hiccup: {error}. Showing the last data received.</div>}

      <section className={`hero glass ${risk} ${flash ? "flash" : ""}`}>
        <div className="hero-text">
          <div className="status-row">
            <span className={`status-pill ${risk}`}>{RISK[risk].label}</span>
            <span className={`live ${data.online ? "on" : "off"}`}>
              <i /> {data.online ? `Live · updated ${ago(data.updatedMs, now)}` : `Offline · last seen ${ago(data.updatedMs, now)}`}
            </span>
          </div>
          <h2>{RISK[risk].title}</h2>
          <p className="hero-tip">{data.name}'s bedroom · {RISK[risk].tip}</p>
          {data.reasons?.length > 0 && (
            <div className="chips">{data.reasons.map((r) => <span key={r} className="chip">{r}</span>)}</div>
          )}
        </div>
        <div className="hero-gauge">
          <Gauge value={l.tvoc} risk={risk} />
          <div className="gauge-num">{l.tvoc ?? "–"}</div>
          <div className="gauge-unit">ppb VOCs</div>
        </div>
      </section>

      <section className="metrics">
        <Metric label="VOCs (fumes)" value={l.tvoc} unit=" ppb" sub={`Fair ${TVOC_YELLOW}+ · Bad ${TVOC_RED}+`} />
        <Metric label="CO₂ estimate" value={l.eco2} unit=" ppm" />
        <Metric label="Temperature" value={tempF} unit="°F" />
        <Metric label="Humidity" value={l.humidity} unit="%" sub="Above 60% raises risk" />
        <Metric label="Inhaler puffs · 24 h" value={data.puffs24h} unit="" sub="2+ raises risk" />
        <Metric label="Last puff hold" value={held} unit=" s"
                sub={data.lastPuffMs ? clock(data.lastPuffMs) : "No puffs yet"} />
      </section>

      <section className="glass panel">
        <div className="panel-head">
          <h3>VOC level · last few minutes</h3>
          <div className="legend"><span className="lg green">Good</span><span className="lg yellow">Fair</span><span className="lg red">Bad</span></div>
        </div>
        <VocChart history={data.history} />
        <p className="muted small">Hover for exact readings. The scale is compressed so everyday levels stay readable next to big spikes.</p>
      </section>

      <section className="glass panel">
        <div className="panel-head">
          <h3>Daily summary</h3>
          <span className="badge">Amazon Bedrock</span>
        </div>
        <p className="muted small">A plain-English recap of today's air and inhaler use, written for parents and doctors.</p>
        <button className="primary" onClick={getSummary} disabled={loadingSummary}>
          {loadingSummary ? "Writing summary…" : "Generate today's summary"}
        </button>
        {summary && <p className="summary">{summary}</p>}
      </section>
    </>
  );
}

function NurseView({ onRisk }) {
  const { data, error } = usePoll("/kids", mockKids);
  const now = useNow();
  useEffect(() => { if (data?.length) onRisk(data[0].risk || "green"); }, [data, onRisk]);
  if (!data) return <div className="glass panel muted">{error ? `Can't reach the API: ${error}` : "Loading students…"}</div>;
  const counts = { red: 0, yellow: 0, green: 0 };
  data.forEach((k) => { counts[k.risk] = (counts[k.risk] || 0) + 1; });
  return (
    <>
      <section className="metrics four">
        <Metric label="Students monitored" value={data.length} unit="" />
        <Metric label="Bad air now" value={counts.red} unit="" sub="Check on these first" />
        <Metric label="Fair air" value={counts.yellow} unit="" />
        <Metric label="Good air" value={counts.green} unit="" />
      </section>
      <section className="glass panel">
        <div className="panel-head"><h3>All students · highest risk first</h3></div>
        {error && <div className="warn">Connection hiccup: {error}</div>}
        <table className="kids">
          <thead><tr><th>Student</th><th>Risk</th><th>VOCs</th><th>Puffs · 24 h</th><th>Updated</th></tr></thead>
          <tbody>
            {data.map((k) => (
              <tr key={k.deviceId}>
                <td className="name">{k.name}</td>
                <td><span className={`status-pill sm ${k.risk}`}>{RISK[k.risk]?.label || k.risk}</span></td>
                <td>{k.latest?.tvoc ?? "–"} <span className="muted">ppb</span></td>
                <td>{k.puffs24h}</td>
                <td className="muted">{k.online ? "Live" : ago(k.updatedMs, now)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

export default function App() {
  const [view, setView] = useState("parent");
  const [risk, setRisk] = useState("green");
  const [cleanse, setCleanse] = useState(0);        // timestamp of the latest puff (0 = none showing)
  const [puffHeld, setPuffHeld] = useState(null);
  const timer = useRef(null);
  const onPuff = useCallback((heldMs) => {
    setPuffHeld(heldMs);
    setCleanse(Date.now());
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCleanse(0), 5000);
  }, []);
  return (
    <>
      <CityBackdrop risk={risk} cleanse={cleanse} />
      {cleanse > 0 && (
        <div className="puff-banner" key={cleanse}>
          <span className="puff-icon" aria-hidden="true" />
          Inhaler puff{puffHeld ? ` · held ${(puffHeld / 1000).toFixed(1)} s` : ""} · fresh air
        </div>
      )}
      <div className="app">
        <header className="glass topbar">
          <div className="brand">
            <div className="logo" aria-hidden="true"><span /></div>
            <div>
              <h1>Breathe<span>Detroit</span></h1>
              <p className="tagline">Asthma-trigger monitoring for kids</p>
            </div>
          </div>
          <nav className="seg">
            <button className={view === "parent" ? "on" : ""} onClick={() => setView("parent")}>Parent</button>
            <button className={view === "nurse" ? "on" : ""} onClick={() => setView("nurse")}>School nurse</button>
          </nav>
        </header>
        {MOCK && <div className="warn">Demo mode: fake data. Set VITE_API_URL to use the real API.</div>}
        {view === "parent" ? <ParentView onRisk={setRisk} onPuff={onPuff} /> : <NurseView onRisk={setRisk} />}
        <footer>Monitors asthma triggers and alerts caregivers. Not a medical device.</footer>
      </div>
    </>
  );
}
