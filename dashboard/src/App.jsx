import { useEffect, useRef, useState } from "react";
import "./App.css";

// Set VITE_API_URL in dashboard/.env (local) and in Amplify's environment variables.
// With no API URL, the dashboard runs on fake data so you can build the UI right away.
const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
const DEVICE_ID = import.meta.env.VITE_DEVICE_ID || "kid-001";
const POLL_MS = 1500;
const MOCK = !API;

const TVOC_YELLOW = 220;
const TVOC_RED = 660;

const RISK_TEXT = {
  green: { title: "Air is good", tip: "No action needed." },
  yellow: { title: "Air is getting worse", tip: "Open a window and avoid sprays or strong cleaners." },
  red: { title: "Air is bad right now", tip: "Move to cleaner air and keep the inhaler close." },
};

// ---------------- Fake data (used when VITE_API_URL is empty) ----------------
const mock = { tvoc: 120, history: [], puffs: [] };
function mockStatus() {
  const spike = Math.random() < 0.08 ? 600 : 0;
  mock.tvoc = Math.max(20, Math.min(1100, mock.tvoc * 0.85 + 30 + spike + (Math.random() - 0.5) * 40));
  const tvoc = Math.round(mock.tvoc);
  const humidity = 45 + Math.round(Math.random() * 6);
  const risk = tvoc > TVOC_RED ? "red" : tvoc >= TVOC_YELLOW ? "yellow" : "green";
  mock.history = [...mock.history, { ts: Date.now(), tvoc, risk }].slice(-60);
  return {
    deviceId: DEVICE_ID,
    name: "Jayden",
    risk,
    reasons: [],
    latest: { tvoc, eco2: 400 + tvoc, tempC: 21.5, humidity },
    puffs24h: mock.puffs.length,
    updatedMs: Date.now(),
    online: true,
    history: mock.history,
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

// ---------------- Data hook ----------------
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

// ---------------- Pieces ----------------
function Sparkline({ history }) {
  const points = (history || []).filter((h) => h.tvoc != null);
  if (points.length < 2) return <p className="muted">Waiting for readings…</p>;
  const W = 600, H = 140, pad = 6;
  const max = Math.max(800, ...points.map((p) => p.tvoc));
  const x = (i) => pad + (i / (points.length - 1)) * (W - pad * 2);
  const y = (v) => H - pad - (v / max) * (H - pad * 2);
  const line = points.map((p, i) => `${x(i)},${y(p.tvoc)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="spark" role="img" aria-label="VOC level over the last few minutes">
      <line x1={pad} x2={W - pad} y1={y(TVOC_RED)} y2={y(TVOC_RED)} className="band red" />
      <line x1={pad} x2={W - pad} y1={y(TVOC_YELLOW)} y2={y(TVOC_YELLOW)} className="band yellow" />
      <polyline points={line} className="trend" />
      <circle cx={x(points.length - 1)} cy={y(points[points.length - 1].tvoc)} r="5" className={`dot ${points[points.length - 1].risk}`} />
    </svg>
  );
}

function Metric({ label, value, unit }) {
  return (
    <div className="metric">
      <div className="metric-value">{value ?? "–"}<span>{value != null ? unit : ""}</span></div>
      <div className="metric-label">{label}</div>
    </div>
  );
}

function ParentView() {
  const { data, error } = usePoll(`/status/${DEVICE_ID}`, mockStatus);
  const [summary, setSummary] = useState("");
  const [loadingSummary, setLoadingSummary] = useState(false);
  const prevRisk = useRef(null);
  const [flash, setFlash] = useState(false);

  useEffect(() => {  // flash the card when risk changes, so the demo moment pops
    if (data && prevRisk.current && prevRisk.current !== data.risk) {
      setFlash(true);
      const id = setTimeout(() => setFlash(false), 1200);
      return () => clearTimeout(id);
    }
    if (data) prevRisk.current = data.risk;
  }, [data]);
  useEffect(() => { if (data) prevRisk.current = data.risk; }, [data]);

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

  if (!data) return <p className="muted">{error ? `⚠ ${error}` : "Loading…"}</p>;
  const risk = data.risk || "green";
  const l = data.latest || {};
  const tempF = l.tempC != null ? Math.round(l.tempC * 9 / 5 + 32) : null;

  return (
    <>
      {error && <p className="warn">⚠ {error}. Showing the last data received.</p>}
      <section className={`risk-card ${risk} ${flash ? "flash" : ""}`}>
        <div className="risk-label">{risk.toUpperCase()}</div>
        <h2>{RISK_TEXT[risk].title}</h2>
        <p>{data.name}'s room · {RISK_TEXT[risk].tip}</p>
        {data.reasons?.length > 0 && <p className="reasons">Also: {data.reasons.join(", ")}</p>}
        {!data.online && <p className="reasons">Device offline. Last update {new Date(data.updatedMs).toLocaleTimeString()}</p>}
      </section>

      <section className="metrics">
        <Metric label="VOCs (fumes)" value={l.tvoc} unit=" ppb" />
        <Metric label="CO₂ estimate" value={l.eco2} unit=" ppm" />
        <Metric label="Temperature" value={tempF} unit="°F" />
        <Metric label="Humidity" value={l.humidity} unit="%" />
        <Metric label="Inhaler puffs (24 h)" value={data.puffs24h} unit="" />
      </section>

      <section className="panel">
        <h3>VOC level, last few minutes</h3>
        <Sparkline history={data.history} />
        <p className="muted small">Dashed lines: yellow at {TVOC_YELLOW} ppb, red above {TVOC_RED} ppb.</p>
      </section>

      <section className="panel">
        <h3>Daily summary <span className="muted small">(Amazon Bedrock)</span></h3>
        <button onClick={getSummary} disabled={loadingSummary}>{loadingSummary ? "Writing…" : "Get today's summary"}</button>
        {summary && <p className="summary">{summary}</p>}
      </section>
    </>
  );
}

function NurseView() {
  const { data, error } = usePoll("/kids", mockKids);
  if (!data) return <p className="muted">{error ? `⚠ ${error}` : "Loading…"}</p>;
  return (
    <section className="panel">
      <h3>All students, highest risk first</h3>
      {error && <p className="warn">⚠ {error}</p>}
      <table className="kids">
        <thead><tr><th>Student</th><th>Risk</th><th>VOCs</th><th>Puffs (24 h)</th><th>Updated</th></tr></thead>
        <tbody>
          {data.map((k) => (
            <tr key={k.deviceId}>
              <td>{k.name}</td>
              <td><span className={`pill ${k.risk}`}>{k.risk}</span></td>
              <td>{k.latest?.tvoc ?? "–"} ppb</td>
              <td>{k.puffs24h}</td>
              <td className="muted">{k.online ? "live" : new Date(k.updatedMs).toLocaleTimeString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function App() {
  const [view, setView] = useState("parent");
  return (
    <div className="app">
      <header>
        <h1>Breathe<span>Detroit</span></h1>
        <nav>
          <button className={view === "parent" ? "on" : ""} onClick={() => setView("parent")}>Parent</button>
          <button className={view === "nurse" ? "on" : ""} onClick={() => setView("nurse")}>School nurse</button>
        </nav>
      </header>
      {MOCK && <p className="warn">Demo mode: fake data. Set VITE_API_URL to use the real API.</p>}
      {view === "parent" ? <ParentView /> : <NurseView />}
      <footer className="muted small">Monitors asthma triggers and alerts caregivers. Not a medical device.</footer>
    </div>
  );
}
