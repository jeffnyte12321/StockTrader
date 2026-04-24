import React from "react";
import ReactDOM from "react-dom/client";
import Chart from "chart.js/auto";
import "chartjs-adapter-date-fns";
import "./styles.css";
const { useState, useEffect, useCallback, useRef } = React;

const API = "/api";

// ─── Auth helpers ───────────────────────────────────────────────────────────
function getToken() { return localStorage.getItem("sb_token"); }
function setToken(token) { localStorage.setItem("sb_token", token); }
function getRefreshToken() { return localStorage.getItem("sb_refresh_token"); }
function setRefreshToken(token) { localStorage.setItem("sb_refresh_token", token); }
function clearToken() {
  localStorage.removeItem("sb_token");
  localStorage.removeItem("sb_refresh_token");
  localStorage.removeItem("sb_user");
  localStorage.removeItem("pending_brokerage_sync");
}
function getUser() { try { return JSON.parse(localStorage.getItem("sb_user")); } catch { return null; } }
function setUser(user) { localStorage.setItem("sb_user", JSON.stringify(user)); }

function authHeaders() {
  const token = getToken();
  return token ? { "Authorization": `Bearer ${token}` } : {};
}

let refreshInFlight = null;

async function refreshSession() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) {
        clearToken();
        return false;
      }
      const data = await response.json();
      if (!data.session?.access_token || !data.session?.refresh_token) {
        clearToken();
        return false;
      }
      setToken(data.session.access_token);
      setRefreshToken(data.session.refresh_token);
      if (data.user) setUser(data.user);
      return true;
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function authFetch(url, opts = {}, attemptRefresh = true) {
  const response = await fetch(url, {
    ...opts,
    headers: { ...opts.headers, ...authHeaders() },
  });
  if (response.status === 401 && attemptRefresh) {
    const refreshed = await refreshSession();
    if (refreshed) {
      return authFetch(url, opts, false);
    }
  }
  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new CustomEvent("auth-expired"));
  }
  return response;
}

// ─── Login / Signup page ────────────────────────────────────────────────────
function AuthPage({ onLogin, toast }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) { toast("Fill in all fields", "error"); return; }
    if (password.length < 6) { toast("Password must be at least 6 characters", "error"); return; }
    setLoading(true);
    try {
      const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
      const r = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Auth failed");
      if (d.session && d.session.access_token) {
        setToken(d.session.access_token);
        setRefreshToken(d.session.refresh_token);
        setUser(d.user);
        toast(mode === "login" ? "Welcome back!" : "Account created!", "success");
        onLogin(d.user, d.session.access_token);
      } else {
        toast(d.message || "Check your email to confirm your account", "info");
      }
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <div style={{ width: "100%", maxWidth: 400 }}>
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 40 }}>
          <div className="nav-brand">
            <div className="nav-brand-icon">★</div>
            <div className="brand-copy">
              <div className="brand-name" style={{ fontSize: 28 }}>Northstar</div>
            </div>
          </div>
        </div>
        <div className="card" style={{ padding: 28 }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
            <button type="button" className={`btn btn-full ${mode === "login" ? "btn-primary" : "btn-ghost"}`} style={{ flex: 1 }} onClick={() => setMode("login")}>Sign In</button>
            <button type="button" className={`btn btn-full ${mode === "signup" ? "btn-primary" : "btn-ghost"}`} style={{ flex: 1 }} onClick={() => setMode("signup")}>Sign Up</button>
          </div>
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label>Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" />
            </div>
            <div className="form-group">
              <label>Password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Min 6 characters" />
            </div>
            <button type="submit" className="btn btn-primary btn-full" disabled={loading} style={{ marginTop: 8 }}>
              {loading ? <span className="spinner" /> : (mode === "login" ? "Sign In" : "Create Account")}
            </button>
          </form>
        </div>
        <div style={{ textAlign: "center", marginTop: 16, fontSize: 12, color: "#64748b" }}>
          Track synced holdings, cash, alerts, and research
        </div>
      </div>
    </div>
  );
}

// ─── Toast system ────────────────────────────────────────────────────────────
function useToasts() {
  const [toasts, setToasts] = useState([]);
  const add = useCallback((msg, type = "info") => {
    const id = Date.now();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  }, []);
  return { toasts, add };
}

function ToastContainer({ toasts }) {
  return (
    <div className="toast-container">
      {toasts.map(t => (
        <div key={t.id} className={`toast ${t.type}`}>
          <span>{t.msg}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Formatting helpers ───────────────────────────────────────────────────────
const fmt$ = (v) => {
  const abs = Math.abs(v);
  const str = abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return v < 0 ? `-$${str}` : `$${str}`;
};
const fmtPct = (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const fmtDateTime = (ts) => new Date(ts * 1000).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const fmtCompact = (v) => Number(v || 0).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });
const fmtCalendarDate = (value) => {
  if (!value) return "N/A";
  const date = typeof value === "number" ? new Date(value) : new Date(value);
  if (Number.isNaN(date.getTime())) return "N/A";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};
const toDateInputValue = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
};

function getChartStats(data) {
  if (!data || data.length === 0) return null;
  const first = Number(data[0].close || 0);
  const last = Number(data[data.length - 1].close || 0);
  const high = Math.max(...data.map((item) => Number(item.high || item.close || 0)));
  const lows = data.map((item) => Number(item.low || item.close || 0)).filter((value) => value > 0);
  const low = lows.length ? Math.min(...lows) : 0;
  const avgVolume = data.reduce((sum, item) => sum + Number(item.volume || 0), 0) / data.length;
  const change = last - first;
  const changePct = first ? (change / first) * 100 : 0;
  return { first, last, high, low, avgVolume, change, changePct };
}

function roundRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function buildConicGradient(entries, total) {
  if (!entries.length || total <= 0) return "#e5e7eb";
  let cursor = 0;
  const stops = entries.map((entry) => {
    const start = cursor;
    cursor += (Number(entry.value || 0) / total) * 360;
    return `${entry.color} ${start.toFixed(1)}deg ${cursor.toFixed(1)}deg`;
  });
  return `conic-gradient(${stops.join(", ")})`;
}

// ─── Research price chart ───────────────────────────────────────────────────
function PriceChart({ data, color, mode = "candles", showVolume = true }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !data || data.length === 0) return;

    const canvas = canvasRef.current;
    const ctx = canvasRef.current.getContext("2d");
    const candles = data
      .map((d) => {
        const close = Number(d.close || 0);
        return {
          time: Number(d.time || Date.now()),
          open: Number(d.open || close),
          high: Number(d.high || close),
          low: Number(d.low || close),
          close,
          volume: Number(d.volume || 0),
        };
      })
      .filter((d) => d.close > 0 && d.high > 0 && d.low > 0);
    if (!candles.length) return;

    let hoverIndex = null;
    let frameId = null;
    const isPositive = color === "#34d399";

    const draw = () => {
      const bounds = canvas.getBoundingClientRect();
      const width = bounds.width;
      const height = bounds.height;
      if (width <= 0 || height <= 0) return;

      const dpr = window.devicePixelRatio || 1;
      const targetWidth = Math.floor(width * dpr);
      const targetHeight = Math.floor(height * dpr);
      if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
        canvas.width = targetWidth;
        canvas.height = targetHeight;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const left = 14;
      const right = 96;
      const top = 16;
      const bottom = 34;
      const volumeAvailable = showVolume && candles.some((d) => d.volume > 0);
      const volumeHeight = volumeAvailable ? Math.min(92, Math.max(58, height * 0.2)) : 0;
      const volumeGap = volumeAvailable ? 18 : 0;
      const priceBottom = height - bottom - volumeHeight - volumeGap;
      const plotWidth = Math.max(1, width - left - right);
      const priceHeight = Math.max(1, priceBottom - top);
      const chartRight = left + plotWidth;

      const highs = candles.map((d) => d.high);
      const lows = candles.map((d) => d.low);
      const maxHigh = Math.max(...highs);
      const minLow = Math.min(...lows);
      const priceRange = Math.max(maxHigh - minLow, maxHigh * 0.01, 1);
      const maxPrice = maxHigh + priceRange * 0.14;
      const minPrice = Math.max(0, minLow - priceRange * 0.14);
      const scaleRange = Math.max(maxPrice - minPrice, 1);
      const firstClose = candles[0].close;
      const last = candles[candles.length - 1];
      const xForIndex = (index) => candles.length === 1
        ? left + plotWidth / 2
        : left + (plotWidth * index) / (candles.length - 1);
      const yForPrice = (value) => priceBottom - ((value - minPrice) / scaleRange) * priceHeight;
      const isIntraday = candles[candles.length - 1].time - candles[0].time < 1000 * 60 * 60 * 36;
      const dateLabel = (ms) => isIntraday
        ? new Date(ms).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
        : new Date(ms).toLocaleDateString("en-US", { month: "short", day: "numeric" });
      const fullDateLabel = (ms) => isIntraday
        ? new Date(ms).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
        : new Date(ms).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

      ctx.save();
      const panelGradient = ctx.createLinearGradient(0, top, 0, height);
      panelGradient.addColorStop(0, "rgba(255,255,255,0.025)");
      panelGradient.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = panelGradient;
      ctx.fillRect(left, top, plotWidth, priceBottom - top);
      ctx.restore();

      ctx.font = "600 11px IBM Plex Sans, sans-serif";
      ctx.textBaseline = "middle";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i += 1) {
        const y = top + (priceHeight * i) / 4;
        const value = maxPrice - (scaleRange * i) / 4;
        ctx.strokeStyle = "rgba(140,160,184,0.08)";
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(chartRight, y);
        ctx.stroke();
        ctx.fillStyle = "#7b8da3";
        ctx.fillText(fmt$(value), chartRight + 12, y);
      }

      const tickCount = Math.min(6, candles.length);
      ctx.textBaseline = "alphabetic";
      ctx.fillStyle = "#7b8da3";
      for (let i = 0; i < tickCount; i += 1) {
        const index = tickCount === 1 ? 0 : Math.round((candles.length - 1) * i / (tickCount - 1));
        const x = xForIndex(index);
        ctx.strokeStyle = "rgba(140,160,184,0.05)";
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, priceBottom);
        ctx.stroke();
        const label = dateLabel(candles[index].time);
        const labelWidth = ctx.measureText(label).width;
        ctx.fillText(label, Math.max(left, Math.min(x - labelWidth / 2, chartRight - labelWidth)), height - 9);
      }

      const baselineY = yForPrice(firstClose);
      if (baselineY >= top && baselineY <= priceBottom) {
        ctx.strokeStyle = "rgba(148,163,184,0.18)";
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(left, baselineY);
        ctx.lineTo(chartRight, baselineY);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      if (mode === "line") {
        const lineGradient = ctx.createLinearGradient(0, top, 0, priceBottom);
        lineGradient.addColorStop(0, isPositive ? "rgba(52,211,153,0.22)" : "rgba(248,113,113,0.22)");
        lineGradient.addColorStop(0.62, isPositive ? "rgba(52,211,153,0.08)" : "rgba(248,113,113,0.08)");
        lineGradient.addColorStop(1, "rgba(0,0,0,0)");

        const linePoints = candles.map((point, index) => ({
          x: xForIndex(index),
          y: yForPrice(point.close),
        }));
        ctx.beginPath();
        linePoints.forEach((point, index) => {
          if (index === 0) ctx.moveTo(point.x, point.y);
          else ctx.lineTo(point.x, point.y);
        });
        ctx.lineTo(chartRight, priceBottom);
        ctx.lineTo(left, priceBottom);
        ctx.closePath();
        ctx.fillStyle = lineGradient;
        ctx.fill();

        ctx.beginPath();
        linePoints.forEach((point, index) => {
          if (index === 0) ctx.moveTo(point.x, point.y);
          else ctx.lineTo(point.x, point.y);
        });
        ctx.strokeStyle = color;
        ctx.lineWidth = 3;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.stroke();
      } else {
        const step = candles.length > 1 ? plotWidth / (candles.length - 1) : plotWidth;
        const bodyWidth = Math.max(4, Math.min(14, step * 0.56));
        candles.forEach((point, index) => {
          const x = xForIndex(index);
          const up = point.close >= point.open;
          const candleColor = up ? "#34d399" : "#f87171";
          const yHigh = yForPrice(point.high);
          const yLow = yForPrice(point.low);
          const yOpen = yForPrice(point.open);
          const yClose = yForPrice(point.close);
          const bodyTop = Math.min(yOpen, yClose);
          const bodyHeight = Math.max(Math.abs(yClose - yOpen), 2);

          ctx.strokeStyle = candleColor;
          ctx.globalAlpha = 0.9;
          ctx.lineWidth = 1.3;
          ctx.beginPath();
          ctx.moveTo(x, yHigh);
          ctx.lineTo(x, yLow);
          ctx.stroke();

          ctx.globalAlpha = up ? 0.72 : 0.82;
          ctx.fillStyle = candleColor;
          roundRect(ctx, x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight, 2);
          ctx.fill();
          ctx.globalAlpha = 1;
        });
      }

      if (volumeAvailable) {
        const volumeTop = priceBottom + volumeGap;
        const maxVolume = Math.max(...candles.map((d) => d.volume), 1);
        const step = candles.length > 1 ? plotWidth / (candles.length - 1) : plotWidth;
        const barWidth = Math.max(2, Math.min(11, step * 0.55));
        ctx.fillStyle = "#7b8da3";
        ctx.font = "700 10px IBM Plex Sans, sans-serif";
        ctx.fillText("VOL", left, volumeTop - 7);
        candles.forEach((point, index) => {
          const x = xForIndex(index);
          const barHeight = (point.volume / maxVolume) * volumeHeight;
          const up = point.close >= point.open;
          ctx.fillStyle = up ? "rgba(52,211,153,0.28)" : "rgba(248,113,113,0.3)";
          ctx.fillRect(x - barWidth / 2, volumeTop + volumeHeight - barHeight, barWidth, barHeight);
        });
      }

      const lastY = yForPrice(last.close);
      ctx.strokeStyle = isPositive ? "rgba(52,211,153,0.24)" : "rgba(248,113,113,0.24)";
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(left, lastY);
      ctx.lineTo(chartRight, lastY);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(chartRight, lastY, 4.5, 0, Math.PI * 2);
      ctx.fill();

      const priceLabel = fmt$(last.close);
      ctx.font = "800 12px IBM Plex Sans, sans-serif";
      const labelWidth = ctx.measureText(priceLabel).width + 18;
      const labelHeight = 24;
      const labelX = chartRight + 8;
      const labelY = Math.max(top, Math.min(lastY - labelHeight / 2, priceBottom - labelHeight));
      ctx.fillStyle = isPositive ? "rgba(20,83,45,0.96)" : "rgba(127,29,29,0.96)";
      roundRect(ctx, labelX, labelY, labelWidth, labelHeight, 7);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.textBaseline = "middle";
      ctx.fillText(priceLabel, labelX + 9, labelY + labelHeight / 2);

      if (hoverIndex !== null) {
        const point = candles[hoverIndex];
        const x = xForIndex(hoverIndex);
        const y = yForPrice(point.close);
        const rangeChange = point.close - firstClose;
        const rangePct = firstClose ? (rangeChange / firstClose) * 100 : 0;
        ctx.strokeStyle = "rgba(214,228,245,0.38)";
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, priceBottom);
        ctx.moveTo(left, y);
        ctx.lineTo(chartRight, y);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();

        const lines = [
          fullDateLabel(point.time),
          `O ${fmt$(point.open)}   H ${fmt$(point.high)}`,
          `L ${fmt$(point.low)}   C ${fmt$(point.close)}`,
          `${rangeChange >= 0 ? "+" : ""}${fmt$(rangeChange)} (${fmtPct(rangePct)})`,
          `Vol ${fmtCompact(point.volume)}`,
        ];
        ctx.font = "700 12px IBM Plex Sans, sans-serif";
        const tooltipWidth = Math.max(...lines.map((line) => ctx.measureText(line).width)) + 24;
        const tooltipHeight = 18 + lines.length * 18;
        const rawTooltipX = x + tooltipWidth + 18 > chartRight ? x - tooltipWidth - 18 : x + 18;
        const tooltipX = Math.max(left, Math.min(rawTooltipX, chartRight - tooltipWidth));
        const tooltipY = Math.max(top + 4, Math.min(y - tooltipHeight / 2, priceBottom - tooltipHeight - 4));
        ctx.fillStyle = "rgba(5,11,18,0.96)";
        roundRect(ctx, tooltipX, tooltipY, tooltipWidth, tooltipHeight, 8);
        ctx.fill();
        ctx.strokeStyle = "rgba(214,228,245,0.12)";
        ctx.stroke();
        lines.forEach((line, index) => {
          ctx.fillStyle = index === 0 ? "#8ca0b8" : index === 3 ? color : "#edf4ff";
          ctx.fillText(line, tooltipX + 12, tooltipY + 20 + index * 18);
        });
      }
    };

    const scheduleDraw = () => {
      if (frameId) cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(draw);
    };

    const handleMove = (event) => {
      const bounds = canvas.getBoundingClientRect();
      const left = 14;
      const right = 96;
      const plotWidth = Math.max(1, bounds.width - left - right);
      const x = event.clientX - bounds.left;
      if (x < left || x > left + plotWidth) {
        hoverIndex = null;
      } else {
        const ratio = (x - left) / plotWidth;
        hoverIndex = Math.max(0, Math.min(candles.length - 1, Math.round(ratio * (candles.length - 1))));
      }
      scheduleDraw();
    };

    const handleLeave = () => {
      hoverIndex = null;
      scheduleDraw();
    };

    const resizeObserver = new ResizeObserver(scheduleDraw);
    resizeObserver.observe(canvas.parentElement || canvas);
    canvas.addEventListener("mousemove", handleMove);
    canvas.addEventListener("mouseleave", handleLeave);
    scheduleDraw();

    return () => {
      if (frameId) cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      canvas.removeEventListener("mousemove", handleMove);
      canvas.removeEventListener("mouseleave", handleLeave);
    };
  }, [data, color, mode, showVolume]);

  return <canvas ref={canvasRef} className="price-chart-canvas" />;
}

// ─── Chart component using Chart.js ──────────────────────────────────────────
function LegacyPriceChart({ data, color }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !data || data.length === 0) return;

    if (chartRef.current) {
      chartRef.current.destroy();
    }

    const ctx = canvasRef.current.getContext("2d");
    const closes = data.map(d => Number(d.close || 0));
    const firstClose = closes[0] || 0;
    const minClose = Math.min(...closes);
    const maxClose = Math.max(...closes);
    const rangePadding = Math.max((maxClose - minClose) * 0.16, maxClose * 0.006, 0.5);
    const isPositive = color === "#34d399";
    const gradient = ctx.createLinearGradient(0, 0, 0, 390);
    gradient.addColorStop(0, isPositive ? "rgba(52,211,153,0.22)" : "rgba(248,113,113,0.22)");
    gradient.addColorStop(0.58, isPositive ? "rgba(52,211,153,0.08)" : "rgba(248,113,113,0.08)");
    gradient.addColorStop(1, "rgba(0,0,0,0)");

    const hoverLine = {
      id: "hoverLine",
      afterDatasetsDraw(chart) {
        const active = chart.tooltip?.getActiveElements?.() || [];
        if (!active.length) return;
        const { ctx, chartArea } = chart;
        const x = active[0].element.x;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.lineWidth = 1;
        ctx.strokeStyle = "rgba(140,160,184,0.38)";
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.restore();
      },
    };
    const lastPriceMarker = {
      id: "lastPriceMarker",
      afterDatasetsDraw(chart) {
        const meta = chart.getDatasetMeta(0);
        const point = meta?.data?.[meta.data.length - 1];
        if (!point) return;
        const { ctx, chartArea } = chart;
        const price = closes[closes.length - 1] || 0;
        const label = fmt$(price);
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(chartArea.left, point.y);
        ctx.lineTo(chartArea.right, point.y);
        ctx.lineWidth = 1;
        ctx.strokeStyle = isPositive ? "rgba(52,211,153,0.18)" : "rgba(248,113,113,0.18)";
        ctx.setLineDash([5, 5]);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = color;
        ctx.strokeStyle = "#06101a";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.font = "700 12px IBM Plex Sans, sans-serif";
        const labelWidth = ctx.measureText(label).width + 18;
        const labelHeight = 24;
        const labelX = Math.min(point.x + 12, chartArea.right - labelWidth);
        const labelY = Math.max(chartArea.top + 2, Math.min(point.y - 12, chartArea.bottom - labelHeight));
        ctx.fillStyle = isPositive ? "rgba(20,83,45,0.94)" : "rgba(127,29,29,0.94)";
        roundRect(ctx, labelX, labelY, labelWidth, labelHeight, 7);
        ctx.fill();
        ctx.fillStyle = "#ffffff";
        ctx.textBaseline = "middle";
        ctx.fillText(label, labelX + 9, labelY + labelHeight / 2);
        ctx.restore();
      },
    };

    chartRef.current = new Chart(ctx, {
      type: "line",
      data: {
        labels: data.map(d => new Date(d.time)),
        datasets: [
          {
            type: "line",
            label: "Close",
            data: closes,
            yAxisID: "price",
            borderColor: color,
            borderWidth: 3,
            backgroundColor: gradient,
            fill: true,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHitRadius: 16,
            pointHoverBackgroundColor: color,
            pointHoverBorderColor: "#ffffff",
            pointHoverBorderWidth: 2,
            tension: 0.36,
            order: 1,
          },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        normalized: true,
        animation: { duration: 550, easing: "easeOutQuart" },
        layout: { padding: { top: 10, right: 8, bottom: 0, left: 8 } },
        interaction: { intersect: false, mode: "index" },
        elements: { line: { borderCapStyle: "round", borderJoinStyle: "round" } },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(7,16,24,0.96)",
            borderColor: "rgba(255,255,255,0.12)",
            borderWidth: 1,
            titleColor: "#8ca0b8",
            bodyColor: "#edf4ff",
            bodyFont: { weight: "bold", size: 14 },
            padding: 12,
            cornerRadius: 12,
            displayColors: false,
            callbacks: {
              title: (items) => new Date(items[0].parsed.x).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
              label: (item) => {
                const value = Number(item.parsed.y || 0);
                const change = value - firstClose;
                const pct = firstClose ? (change / firstClose) * 100 : 0;
                return `Close ${fmt$(value)}  ${change >= 0 ? "+" : ""}${fmt$(change)} (${fmtPct(pct)})`;
              }
            }
          }
        },
        scales: {
          x: {
            type: "time",
            grid: { color: "rgba(140,160,184,0.05)", drawTicks: false, drawBorder: false },
            ticks: { color: "#7b8da3", font: { size: 11, weight: 600 }, maxTicksLimit: 6, padding: 10 },
            border: { display: false }
          },
          price: {
            position: "right",
            suggestedMin: Math.max(0, minClose - rangePadding),
            suggestedMax: maxClose + rangePadding,
            grid: { color: "rgba(140,160,184,0.08)", drawTicks: false, drawBorder: false },
            ticks: {
              color: "#7b8da3",
              font: { size: 11, weight: 600 },
              maxTicksLimit: 6,
              padding: 10,
              callback: (v) => {
                const value = Number(v);
                const decimals = value >= 100 ? 0 : 2;
                return "$" + value.toLocaleString(undefined, {
                  minimumFractionDigits: decimals,
                  maximumFractionDigits: decimals,
                });
              }
            },
            border: { display: false }
          }
        }
      },
      plugins: [hoverLine, lastPriceMarker],
    });

    return () => {
      if (chartRef.current) chartRef.current.destroy();
    };
  }, [data, color]);

  return <canvas ref={canvasRef} />;
}

function buildSmoothChartPath(points) {
  if (points.length < 2) return "";
  let d = `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const cur = points[i];
    const cx1 = prev.x + (cur.x - prev.x) * 0.4;
    const cy1 = prev.y;
    const cx2 = prev.x + (cur.x - prev.x) * 0.6;
    const cy2 = cur.y;
    d += ` C${cx1.toFixed(1)},${cy1.toFixed(1)} ${cx2.toFixed(1)},${cy2.toFixed(1)} ${cur.x.toFixed(1)},${cur.y.toFixed(1)}`;
  }
  return d;
}

function PortfolioTrendChart({ points, positive = true, range = "1M", benchmarkPoints = [], benchmarkLabel = "" }) {
  const svgRef = useRef(null);
  const [hover, setHover] = useState(null);
  const data = (points || [])
    .map((point) => ({
      time: Number(point.time),
      value: Number(point.value),
    }))
    .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
  const benchmarkData = (benchmarkPoints || [])
    .map((point) => ({
      time: Number(point.time),
      value: Number(point.value),
    }))
    .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));

  if (data.length < 2) return null;

  const W = 700;
  const H = 220;
  const pad = { top: 10, right: 18, bottom: 30, left: 62 };
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;
  const startValue = data[0].value;
  const values = data.map((point) => point.value);
  const benchmarkValues = benchmarkData.map((point) => point.value);
  const scaleValues = [...values, ...benchmarkValues, startValue];
  const rawMin = Math.min(...scaleValues);
  const rawMax = Math.max(...scaleValues);
  const span = rawMax - rawMin;
  const yPad = span > 0 ? span * 0.14 : Math.max(rawMax * 0.01, 1);
  const minV = Math.max(0, rawMin - yPad);
  const maxV = rawMax + yPad;
  const scaleRange = Math.max(maxV - minV, 1);
  const lineColor = positive ? "#22c55e" : "#ef4444";
  const mutedLine = "rgba(0,0,0,0.1)";
  const tickText = "rgba(0,0,0,0.5)";
  const gradientId = `portfolioArea-${range}`;
  const clipId = `portfolioClip-${range}`;

  const xForIndex = (index) => pad.left + (index / Math.max(data.length - 1, 1)) * chartW;
  const yForValue = (value) => pad.top + chartH - ((value - minV) / scaleRange) * chartH;
  const chartPoints = data.map((point, index) => ({
    ...point,
    x: xForIndex(index),
    y: yForValue(point.value),
  }));
  const benchmarkChartPoints = benchmarkData.map((point, index) => ({
    ...point,
    x: xForIndex(Math.min(index, Math.max(data.length - 1, 0))),
    y: yForValue(point.value),
  }));
  const linePath = buildSmoothChartPath(chartPoints);
  const benchmarkPath = benchmarkChartPoints.length > 1 ? buildSmoothChartPath(benchmarkChartPoints) : "";
  const areaPath = `${linePath} L${pad.left + chartW},${pad.top + chartH} L${pad.left},${pad.top + chartH} Z`;
  const yTicks = Array.from({ length: 5 }, (_, index) => minV + ((maxV - minV) * index) / 4);
  const xTickCount = Math.min(5, data.length);
  const xTickIndexes = xTickCount > 1
    ? Array.from({ length: xTickCount }, (_, index) => Math.round((index / (xTickCount - 1)) * (data.length - 1)))
    : [];
  const baselineY = yForValue(startValue);

  const dateLabel = (ms) => new Date(ms).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const fullDateLabel = (ms) => new Date(ms).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const axisPrice = (value) => {
    const amount = Math.abs(value);
    if (amount >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
    if (amount >= 1000) return `$${(value / 1000).toFixed(1)}k`;
    return `$${value.toFixed(0)}`;
  };

  const handleMove = (event) => {
    if (!svgRef.current || chartPoints.length === 0) return;
    const bounds = svgRef.current.getBoundingClientRect();
    const mouseX = (event.clientX - bounds.left) * (W / Math.max(bounds.width, 1));
    let nearest = chartPoints[0];
    let minDistance = Infinity;
    for (const point of chartPoints) {
      const distance = Math.abs(point.x - mouseX);
      if (distance < minDistance) {
        nearest = point;
        minDistance = distance;
      }
    }
    setHover(nearest);
  };

  return (
    <div className="portfolio-svg-wrap">
      <svg
        ref={svgRef}
        className="portfolio-svg-chart"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Portfolio value chart for ${range}`}
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.22" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
          <clipPath id={clipId}>
            <rect x={pad.left} y={pad.top} width={chartW} height={chartH} />
          </clipPath>
        </defs>

        {yTicks.map((value, index) => {
          const y = yForValue(value);
          return (
            <g key={index}>
              <line x1={pad.left} y1={y} x2={pad.left + chartW} y2={y} stroke={mutedLine} strokeWidth="1" />
              <text x={pad.left - 8} y={y + 4} textAnchor="end" fontSize="10" fill={tickText} fontFamily="DM Sans, sans-serif">
                {axisPrice(value)}
              </text>
            </g>
          );
        })}

        {xTickIndexes.map((index) => {
          const point = chartPoints[index];
          if (!point) return null;
          return (
            <text key={index} x={point.x} y={H - 8} textAnchor="middle" fontSize="10" fill={tickText} fontFamily="DM Sans, sans-serif">
              {dateLabel(point.time)}
            </text>
          );
        })}

        <line x1={pad.left} y1={baselineY} x2={pad.left + chartW} y2={baselineY} stroke="rgba(255,255,255,0.38)" strokeWidth="1" strokeDasharray="4 5" />
        <g clipPath={`url(#${clipId})`}>
          <path d={areaPath} fill={`url(#${gradientId})`} />
          {benchmarkPath && (
            <path d={benchmarkPath} fill="none" stroke="rgba(147,197,253,0.88)" strokeWidth="1.8" strokeDasharray="6 5" strokeLinejoin="round" strokeLinecap="round" />
          )}
          <path d={linePath} fill="none" stroke={lineColor} strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" />
        </g>

        {benchmarkPath && (
          <text x={pad.left + chartW - 4} y={pad.top + 13} textAnchor="end" fontSize="10" fill="rgba(147,197,253,0.95)" fontFamily="DM Sans, sans-serif" fontWeight="700">
            {benchmarkLabel}
          </text>
        )}

        {hover && (
          <g>
            <line x1={hover.x} y1={pad.top} x2={hover.x} y2={pad.top + chartH} stroke={lineColor} strokeWidth="1" strokeDasharray="4 3" opacity="0.75" />
            <circle cx={hover.x} cy={hover.y} r="4" fill={lineColor} stroke="#ffffff" strokeWidth="2" />
          </g>
        )}
      </svg>
      {hover && (
        <div
          className="portfolio-chart-tooltip"
          style={{
            left: `${(hover.x / W) * 100}%`,
            top: Math.max(8, hover.y - 40),
          }}
        >
          {fmt$(hover.value)} · {fullDateLabel(hover.time)}
        </div>
      )}
    </div>
  );
}

// ─── Dashboard ───────────────────────────────────────────────────────────────
function Dashboard({ toast, onNavigate, onOpenPosition, viewMode = "simple" }) {
  const [portfolio, setPortfolio] = useState(null);
  const [equityCurve, setEquityCurve] = useState([]);
  const [benchmarkCurve, setBenchmarkCurve] = useState([]);
  const [benchmark, setBenchmark] = useState("SPY");
  const [chartRange, setChartRange] = useState("1M");
  const [chartLoading, setChartLoading] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const portfolioResponse = await authFetch(`${API}/portfolio?range=${chartRange}`);
      const portfolioData = await portfolioResponse.json();
      if (!portfolioResponse.ok) throw new Error(portfolioData.detail || "Failed to load portfolio");
      setPortfolio(portfolioData);
    } catch (_) {
      toast("Failed to load portfolio", "error");
    } finally {
      setLoading(false);
    }
  }, [toast, chartRange]);

  const loadEquityCurve = useCallback(async (range, selectedBenchmark) => {
    setChartLoading(true);
    try {
      const resp = await authFetch(`${API}/portfolio/equity-curve?range=${encodeURIComponent(range)}&benchmark=${encodeURIComponent(selectedBenchmark)}`);
      if (!resp.ok) throw new Error();
      const data = await resp.json();
      setEquityCurve((data.points || [])
        .filter((point) => Number.isFinite(Number(point.time)) && Number.isFinite(Number(point.value)))
        .sort((a, b) => Number(a.time) - Number(b.time)));
      setBenchmarkCurve((data.benchmark?.points || [])
        .filter((point) => Number.isFinite(Number(point.time)) && Number.isFinite(Number(point.value)))
        .sort((a, b) => Number(a.time) - Number(b.time)));
    } catch (_) {
      setEquityCurve([]);
      setBenchmarkCurve([]);
    } finally {
      setChartLoading(false);
    }
  }, []);

  useEffect(() => { loadEquityCurve(chartRange, benchmark); }, [chartRange, benchmark, loadEquityCurve]);

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);

  if (loading) return <div style={{ textAlign: "center", padding: 80 }}><div className="spinner" style={{ width: 36, height: 36 }} /></div>;
  if (!portfolio) return null;

  const pnlClass = portfolio.total_pnl >= 0 ? "up" : "down";
  const holdings = portfolio.holdings || [];
  const totalValue = Number(portfolio.total_value || 0);
  const portfolioValue = Number(portfolio.portfolio_value || 0);
  const cash = Number(portfolio.cash || 0);
  const largest = holdings[0] || null;
  const largestPct = largest && totalValue > 0 ? (largest.value / totalValue) * 100 : 0;
  const allocationColors = ["#2563eb", "#16a34a", "#0ea5e9", "#7c3aed", "#64748b"];
  const allocationBase = totalValue > 0 ? totalValue : Math.max(portfolioValue + cash, 1);
  const allocationEntries = [
    ...holdings.slice(0, 4).map((holding, index) => ({
      label: holding.symbol,
      value: Number(holding.value || 0),
      color: allocationColors[index],
    })),
    { label: "Cash", value: cash, color: allocationColors[4] },
  ].filter((entry) => entry.value > 0);
  const topAllocation = allocationEntries.reduce((best, entry) => entry.value > (best?.value || 0) ? entry : best, null);
  const allocationGradient = buildConicGradient(allocationEntries, allocationBase);
  const displayedHoldings = holdings;
  const trendPoints = equityCurve.length > 1 ? equityCurve : [];
  const benchmarkPoints = benchmark !== "OFF" && benchmarkCurve.length > 1 ? benchmarkCurve : [];
  const hasTrend = trendPoints.length > 1;
  const chartPositive = trendPoints.length > 1
    ? trendPoints[trendPoints.length - 1].value >= trendPoints[0].value
    : (portfolio.total_pnl || 0) >= 0;
  const rangeStartValue = trendPoints.length ? trendPoints[0].value : 0;
  const rangeEndValue = trendPoints.length ? trendPoints[trendPoints.length - 1].value : 0;
  const rangeDelta = rangeEndValue - rangeStartValue;
  const rangeDeltaPct = rangeStartValue ? (rangeDelta / rangeStartValue) * 100 : 0;
  const twrLabel = portfolio.twr_pct === null || portfolio.twr_pct === undefined ? "N/A" : fmtPct(Number(portfolio.twr_pct || 0));
  const irrLabel = portfolio.irr_pct === null || portfolio.irr_pct === undefined ? "N/A" : fmtPct(Number(portfolio.irr_pct || 0));
  const now = new Date();
  const todayLabel = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
  const minutes = now.getHours() * 60 + now.getMinutes();
  const marketOpen = now.getDay() >= 1 && now.getDay() <= 5 && minutes >= 570 && minutes < 960;
  const concentrated = largest && largestPct > 20;
  const positionSummary = holdings.length
    ? `${holdings.slice(0, 3).map((h) => `${h.symbol} ${((Number(h.value || 0) / allocationBase) * 100).toFixed(0)}%`).join(" · ")}${cash > 0 ? ` · Cash ${((cash / allocationBase) * 100).toFixed(0)}%` : ""}`
    : "";
  const plainExplainer = holdings.length
    ? `📖 Your portfolio holds ${holdings.length === 1 ? "a single position" : `${holdings.length} positions`}${largest ? `, led by ${largest.symbol}` : ""}. Tap any row to dig into a name.`
    : "📖 Connect a brokerage to populate this view with your real holdings.";
  const advancedExplainer = holdings.length
    ? `Portfolio weight: ${positionSummary}. Largest single-name concentration: ${largest ? `${largest.symbol} at ${largestPct.toFixed(1)}%` : "—"}${concentrated ? " — above the 20% threshold for diversification." : " — within a balanced range."}`
    : "Connect and sync a brokerage to populate holdings, allocation, and account risk.";

  const trustBadges = [
    { icon: "✓", label: "Read-only brokerage sync" },
    { icon: "🔒", label: "User-scoped portfolio data" },
    { icon: "📊", label: "Research and alerts" },
  ];

  const pnlPositive = (portfolio.total_pnl || 0) >= 0;
  const pnlArrow = pnlPositive ? "▲" : "▼";
  const pnlPrefix = pnlPositive ? "+" : "-";

  return (
    <div>
      <div className="ns-context">
        <div className="ns-date">{todayLabel}</div>
        <div className={`market-badge ${marketOpen ? "" : "closed"}`} role="status" aria-label={marketOpen ? "Market is open" : "Market is closed"}>
          <span className="market-badge-dot" aria-hidden="true" /> {marketOpen ? "Market open" : "Market closed"}
        </div>
      </div>

      <div className="bento">
        {/* Portfolio hero */}
        <section className="tile tile-portfolio" role="region" aria-label="Portfolio overview">
          <div className="tile-label">Total portfolio value</div>
          <div className="portfolio-value" aria-label={fmt$(totalValue)}>{fmt$(totalValue)}</div>
          <div className="portfolio-pnl-row">
            <span className={`pnl-badge ${pnlPositive ? "up" : "down"}`}>
              <span aria-hidden="true">{pnlArrow}</span>
              <span className="tabular">{pnlPrefix}{fmt$(Math.abs(portfolio.total_pnl || 0))}</span>
              <span style={{ opacity: 0.75 }}>({fmtPct(portfolio.total_pnl_pct || 0)})</span>
            </span>
            <span className="pnl-label">unrealized</span>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, color: "var(--ns-gray-500)", fontSize: 12, fontWeight: 700 }}>
            <span>TWR {twrLabel}</span>
            <span style={{ opacity: 0.45 }}>·</span>
            <span>IRR {irrLabel}</span>
            <span style={{ opacity: 0.45 }}>·</span>
            <span>{portfolio.returns_range || chartRange}</span>
          </div>
          <div className="chart-range-row" role="tablist" aria-label="Chart range">
            {["1W", "1M", "3M", "6M", "1Y", "ALL"].map((r) => (
              <button
                key={r}
                type="button"
                className={`chart-range-btn${chartRange === r ? " active" : ""}`}
                onClick={() => setChartRange(r)}
                aria-pressed={chartRange === r}
              >
                {r}
              </button>
            ))}
            <div style={{ display: "inline-flex", gap: 4, marginLeft: 8 }} aria-label="Benchmark">
              {["SPY", "QQQ", "OFF"].map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`chart-range-btn${benchmark === item ? " active" : ""}`}
                  onClick={() => setBenchmark(item)}
                  aria-pressed={benchmark === item}
                >
                  {item === "OFF" ? "No benchmark" : item}
                </button>
              ))}
            </div>
            {hasTrend && <span style={{
              marginLeft: "auto",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              color: rangeDelta >= 0 ? "var(--ns-green)" : "var(--ns-red)",
              fontSize: 12,
              fontWeight: 700,
            }}>
              <span aria-hidden="true">{rangeDelta >= 0 ? "▲" : "▼"}</span>
              <span className="tabular">{rangeDelta >= 0 ? "+" : "-"}{fmt$(Math.abs(rangeDelta))}</span>
              <span style={{ opacity: 0.85 }}>({rangeDelta >= 0 ? "+" : ""}{rangeDeltaPct.toFixed(2)}%)</span>
              <span style={{ color: "var(--ns-gray-400)", fontWeight: 500 }}>· {chartRange}</span>
            </span>}
          </div>
          <div className="mini-chart" aria-label={`Portfolio value over ${chartRange}`}>
            {chartLoading && equityCurve.length === 0
              ? <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--ns-gray-500)", fontSize: 13 }}>Loading…</div>
              : hasTrend
                ? <PortfolioTrendChart points={trendPoints} positive={chartPositive} range={chartRange} benchmarkPoints={benchmarkPoints} benchmarkLabel={benchmark} />
                : <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--ns-gray-500)", fontSize: 13, textAlign: "center" }}>No historical transaction or snapshot data yet</div>}
          </div>
        </section>

        {/* Summary cards */}
        <section className="tile-summary" aria-label="Portfolio summary">
          <div className="summary-card">
            <div>
              <div className="summary-card-label">Available cash</div>
              <div className="summary-card-value">{fmt$(cash)}</div>
            </div>
            <div className="summary-card-note">Ready to invest</div>
          </div>
          <div className="summary-card">
            <div>
              <div className="summary-card-label">Open positions</div>
              <div className="summary-card-value" style={{ color: "var(--ns-blue-700)" }}>{portfolio.positions_count || 0}</div>
            </div>
            <div className="summary-card-note">{holdings.slice(0, 2).map((h) => h.symbol).join(" · ") || "None synced"}</div>
          </div>
          <div className={`summary-card ${(portfolio.winners_count || 0) > 0 ? "accent-up" : "accent-neutral"}`}>
            <div>
              <div className="summary-card-label">Winning positions</div>
              <div className="summary-card-value up">▲ {portfolio.winners_count || 0}</div>
            </div>
            <div className="summary-card-note">{(portfolio.winners_count || 0) > 0 ? "Positive unrealized P&L" : "None in the green today"}</div>
          </div>
          <div className={`summary-card ${(portfolio.losers_count || 0) > 0 ? "" : "accent-neutral"}`} style={(portfolio.losers_count || 0) > 0 ? { borderLeft: "3px solid var(--ns-red)" } : undefined}>
            <div>
              <div className="summary-card-label">Losing positions</div>
              <div className="summary-card-value" style={{ color: (portfolio.losers_count || 0) > 0 ? "var(--ns-red)" : "var(--ns-gray-400)" }}>
                {(portfolio.losers_count || 0) > 0 ? "▼" : "—"} {portfolio.losers_count || 0}
              </div>
            </div>
            <div className="summary-card-note">{(portfolio.losers_count || 0) > 0 ? "Negative unrealized P&L" : "None today"}</div>
          </div>
        </section>

        {/* Holdings */}
        <section className="tile tile-positions" role="region" aria-label="Your holdings">
          <div className="tile-header">
            <div>
              <div className="tile-label" style={{ marginBottom: 2 }}>Your holdings</div>
              {viewMode === "simple" && displayedHoldings.length > 0 && (
                <div style={{ fontSize: 12, color: "var(--ns-gray-400)" }}>Tap any position to see details</div>
              )}
            </div>
            {displayedHoldings.length > 0 && (
              <span className="positions-count">{displayedHoldings.length} live {displayedHoldings.length === 1 ? "position" : "positions"}</span>
            )}
          </div>

          {displayedHoldings.length === 0 ? (
            <div className="ns-empty">
              <div className="ns-empty-title">No synced brokerage positions yet</div>
              <div style={{ marginBottom: 14 }}>Connect your brokerage, then sync holdings to fill the dashboard.</div>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => onNavigate("brokerage")}>Open Brokerage</button>
            </div>
          ) : (
            <>
              {viewMode === "advanced" && (
                <div className="positions-adv-head" role="row">
                  <span>Stock</span>
                  <span>Value</span>
                  <span>Price / Change</span>
                  <span>Shares</span>
                </div>
              )}

              {displayedHoldings.map((holding) => {
                const hasPnl = holding.pnl !== null && holding.pnl !== undefined && Number.isFinite(Number(holding.pnl));
                const up = hasPnl ? Number(holding.pnl) >= 0 : true;
                const priceLabel = holding.current_price === null || holding.current_price === undefined ? "N/A" : fmt$(holding.current_price);
                const pnlPctLabel = holding.pnl_pct === null || holding.pnl_pct === undefined ? "N/A" : fmtPct(holding.pnl_pct);
                const openPosition = () => onOpenPosition?.(holding.symbol);
                return (
                  <div
                    className={`position-row${viewMode === "advanced" ? " is-advanced" : ""}`}
                    key={holding.symbol}
                    role="button"
                    tabIndex={0}
                    onClick={openPosition}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openPosition();
                      }
                    }}
                    aria-label={`Open ${holding.symbol} in research. ${holding.quantity} shares, ${priceLabel}, ${pnlPctLabel}`}
                  >
                    <div className="position-main">
                      <div className="position-icon" aria-hidden="true">{holding.symbol.slice(0, 3)}</div>
                      <div style={{ minWidth: 0 }}>
                        <div className="position-symbol">{holding.symbol}</div>
                        <div className="position-meta">{holding.name || `${holding.quantity} shares`}</div>
                      </div>
                    </div>
                    <div className="position-value">
                      <div>{fmt$(holding.value || 0)}</div>
                      <div className="position-value-sub">Value</div>
                    </div>
                    <div className="position-right">
                      <div className="position-price">{priceLabel}</div>
                      <div className={`position-change ${hasPnl ? (up ? "up" : "down") : ""}`}>{hasPnl ? (up ? "▲" : "▼") : "—"} {pnlPctLabel}</div>
                    </div>
                    {viewMode === "advanced" && (
                      <div style={{ color: "var(--ns-gray-400)", fontSize: 13, fontVariantNumeric: "tabular-nums", textAlign: "right", whiteSpace: "nowrap" }}>
                        {holding.quantity} sh
                      </div>
                    )}
                  </div>
                );
              })}

              <div className="positions-explainer" aria-live="polite">
                {viewMode === "simple" ? plainExplainer : advancedExplainer}
              </div>
            </>
          )}
        </section>

        {/* Allocation */}
        <section className="tile tile-allocation" role="region" aria-label="Portfolio allocation">
          <div className="tile-label">Allocation</div>
          <div className="allocation-total">{fmt$(allocationBase)}</div>
          <div
            className="alloc-bar-wrap"
            role="img"
            aria-label={`Portfolio allocation: ${allocationEntries.map((e) => `${e.label} ${((e.value / allocationBase) * 100).toFixed(0)}%`).join(", ") || "No allocation"}`}
          >
            {allocationEntries.length === 0 ? (
              <div style={{ flex: 1, background: "var(--ns-gray-200)" }} />
            ) : (
              allocationEntries.map((entry) => (
                <div
                  key={entry.label}
                  className="alloc-segment"
                  style={{ width: `${(entry.value / allocationBase) * 100}%`, background: entry.color, height: "100%" }}
                  title={`${entry.label}: ${((entry.value / allocationBase) * 100).toFixed(1)}%`}
                />
              ))
            )}
          </div>
          <div className="alloc-legend">
            {allocationEntries.length === 0 ? (
              <div className="alloc-legend-row">
                <span className="alloc-dot" style={{ background: "var(--ns-gray-200)" }} />
                <span className="alloc-name">No allocation yet</span>
                <span className="alloc-pct">0%</span>
              </div>
            ) : allocationEntries.map((entry) => (
              <div className="alloc-legend-row" key={entry.label}>
                <span className="alloc-dot" style={{ background: entry.color }} />
                <span className="alloc-name">
                  {entry.label === "Cash" ? "Cash" : entry.label}
                  {entry.label !== "Cash" && <span className="alloc-ticker">{entry.label}</span>}
                </span>
                <span className="alloc-pct">{((entry.value / allocationBase) * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
          {concentrated && (
            <div className="risk-warning">
              ⚠ {largest.symbol} is {largestPct.toFixed(0)}% of your portfolio — consider diversifying to manage risk.
            </div>
          )}
        </section>

      </div>

      <div className="trust-row" role="contentinfo" aria-label="Security and regulatory information">
        {trustBadges.map(({ icon, label }) => (
          <div className="trust-badge" key={label}>
            <span className="trust-icon" aria-hidden="true">{icon}</span>
            <span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Research page ────────────────────────────────────────────────────────────
function ResearchPage({ toast, initialSymbol = "" }) {
  const [search, setSearch] = useState("");
  const [quote, setQuote] = useState(null);
  const [history, setHistory] = useState([]);
  const [period, setPeriod] = useState("1mo");
  const [loadingQuote, setLoadingQuote] = useState(false);
  const [loadingChart, setLoadingChart] = useState(false);
  const [loadingResearch, setLoadingResearch] = useState(false);
  const [portfolioSnapshot, setPortfolioSnapshot] = useState(null);
  const [chartMode, setChartMode] = useState("candles");
  const [showVolume, setShowVolume] = useState(true);
  const [chartSource, setChartSource] = useState("");
  const [chartError, setChartError] = useState("");
  const [researchError, setResearchError] = useState("");
  const [journalEntries, setJournalEntries] = useState([]);
  const [events, setEvents] = useState([]);
  const [thesis, setThesis] = useState(null);
  const [thesisDraft, setThesisDraft] = useState({
    thesis_text: "",
    catalyst: "",
    target_price: "",
    invalidation_criteria: "",
    time_horizon_date: "",
  });
  const [noteBody, setNoteBody] = useState("");
  const [savingThesis, setSavingThesis] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const researchRequestRef = useRef(0);
  const chartRequestRef = useRef(0);

  const periods = ["1d", "5d", "1mo", "3mo", "6mo", "1y"];
  const popularSymbols = ["AAPL", "NVDA", "MSFT", "TSLA", "AMZN", "META"];

  const draftFromThesis = useCallback((data = {}, symbol = "") => ({
    thesis_text: data.thesis_text || "",
    catalyst: data.catalyst || "",
    target_price: data.target_price != null ? String(data.target_price) : "",
    invalidation_criteria: data.invalidation_criteria || "",
    time_horizon_date: toDateInputValue(data.time_horizon_date),
    symbol,
  }), []);

  const loadPortfolio = useCallback(() => {
    authFetch(`${API}/portfolio`).then(r => r.json()).then(setPortfolioSnapshot).catch(() => {});
  }, []);

  useEffect(() => {
    loadPortfolio();
  }, [loadPortfolio]);

  const loadResearchArtifacts = useCallback(async (sym, requestId = researchRequestRef.current) => {
    const symbol = sym.trim().toUpperCase();
    if (!symbol) return;
    if (requestId !== researchRequestRef.current) return;
    setLoadingResearch(true);
    try {
      const fetchJson = async (url) => {
        const response = await authFetch(url);
        const data = await response.json().catch(() => ({}));
        return { response, data };
      };
      const [journalResult, thesisResult, eventsResult] = await Promise.allSettled([
        fetchJson(`${API}/journal?symbol=${encodeURIComponent(symbol)}`),
        fetchJson(`${API}/theses/${encodeURIComponent(symbol)}`),
        fetchJson(`${API}/events?symbols=${encodeURIComponent(symbol)}&limit=12`),
      ]);

      if (requestId !== researchRequestRef.current) return;

      if (journalResult.status === "fulfilled" && journalResult.value.response.ok) {
        setJournalEntries(journalResult.value.data.entries || []);
      } else {
        setJournalEntries([]);
      }

      if (thesisResult.status === "fulfilled" && thesisResult.value.response.ok) {
        setThesis(thesisResult.value.data);
        setThesisDraft(draftFromThesis(thesisResult.value.data, symbol));
      } else {
        setThesis(null);
        setThesisDraft(draftFromThesis({}, symbol));
      }

      if (eventsResult.status === "fulfilled" && eventsResult.value.response.ok) {
        setEvents(eventsResult.value.data.events || []);
      } else {
        setEvents([]);
      }
    } finally {
      if (requestId === researchRequestRef.current) setLoadingResearch(false);
    }
  }, [draftFromThesis]);

  const fetchChart = useCallback(async (sym, p, requestId = chartRequestRef.current) => {
    if (requestId !== chartRequestRef.current) return;
    setLoadingChart(true);
    setChartError("");
    setChartSource("");
    try {
      const interval = p === "1d" ? "5m" : "1d";
      const r = await authFetch(`${API}/history/${encodeURIComponent(sym)}?period=${p}&interval=${interval}`);
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "No chart data");
      if (requestId !== chartRequestRef.current) return;
      setHistory(d.data || []);
      setChartSource(d.source || "yfinance");
    } catch (e) {
      if (requestId !== chartRequestRef.current) return;
      setHistory([]);
      setChartError(e.message || "No chart data");
    }
    finally {
      if (requestId === chartRequestRef.current) setLoadingChart(false);
    }
  }, []);

  const fetchQuote = useCallback(async (sym) => {
    sym = sym.trim().toUpperCase();
    if (!sym) return;
    const requestId = researchRequestRef.current + 1;
    researchRequestRef.current = requestId;
    const chartRequestId = chartRequestRef.current + 1;
    chartRequestRef.current = chartRequestId;
    setLoadingQuote(true);
    setHistory([]);
    setResearchError("");
    setChartError("");
    try {
      const r = await authFetch(`${API}/quote/${encodeURIComponent(sym)}`);
      const q = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(q.detail || `Could not load ${sym}`);
      if (requestId !== researchRequestRef.current) return;
      setQuote(q);
      fetchChart(sym, period, chartRequestId);
      loadResearchArtifacts(sym, requestId);
    } catch (e) {
      if (requestId !== researchRequestRef.current) return;
      const message = e.message || "Could not load quote";
      toast(message, "error");
      setResearchError(message);
      setQuote(null);
      setJournalEntries([]);
      setEvents([]);
      setThesis(null);
    } finally {
      if (requestId === researchRequestRef.current) setLoadingQuote(false);
    }
  }, [fetchChart, loadResearchArtifacts, period, toast]);

  const lastInitialSymbolRef = useRef("");
  useEffect(() => {
    const sym = initialSymbol.trim().toUpperCase();
    if (!sym || lastInitialSymbolRef.current === sym) return;
    lastInitialSymbolRef.current = sym;
    setSearch(sym);
    fetchQuote(sym);
  }, [initialSymbol, fetchQuote]);

  const handlePeriod = (p) => {
    setPeriod(p);
    if (quote) {
      const requestId = chartRequestRef.current + 1;
      chartRequestRef.current = requestId;
      fetchChart(quote.symbol, p, requestId);
    }
  };

  const handleSearch = (e) => {
    e.preventDefault();
    fetchQuote(search);
  };

  const handleSaveThesis = async (e) => {
    e.preventDefault();
    if (!quote) return;
    const thesisText = thesisDraft.thesis_text.trim();
    if (!thesisText) {
      toast("Add a thesis before saving", "error");
      return;
    }
    setSavingThesis(true);
    try {
      const payload = {
        symbol: quote.symbol,
        thesis_text: thesisText,
        catalyst: thesisDraft.catalyst.trim() || null,
        target_price: thesisDraft.target_price ? Number(thesisDraft.target_price) : null,
        invalidation_criteria: thesisDraft.invalidation_criteria.trim() || null,
        time_horizon_date: thesisDraft.time_horizon_date || null,
      };
      const response = await authFetch(`${API}/theses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Could not save thesis");
      setThesis(data);
      setThesisDraft(draftFromThesis(data, quote.symbol));
      toast("Thesis saved", "success");
    } catch (e) {
      toast(e.message || "Could not save thesis", "error");
    } finally {
      setSavingThesis(false);
    }
  };

  const handleAddJournal = async (e) => {
    e.preventDefault();
    if (!quote) return;
    const body = noteBody.trim();
    if (!body) {
      toast("Write a note first", "error");
      return;
    }
    setSavingNote(true);
    try {
      const response = await authFetch(`${API}/journal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: quote.symbol, body, tags: ["research"] }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Could not save note");
      setJournalEntries((entries) => [data, ...entries]);
      setNoteBody("");
      toast("Note saved", "success");
    } catch (e) {
      toast(e.message || "Could not save note", "error");
    } finally {
      setSavingNote(false);
    }
  };

  const handleDeleteJournal = async (entryId) => {
    try {
      const response = await authFetch(`${API}/journal/${entryId}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Could not delete note");
      }
      setJournalEntries((entries) => entries.filter((entry) => entry.id !== entryId));
      toast("Note removed", "info");
    } catch (e) {
      toast(e.message || "Could not delete note", "error");
    }
  };

  const cash = portfolioSnapshot?.cash ?? null;
  const holdings = portfolioSnapshot?.holdings || [];
  const currentHolding = quote
    ? holdings.find((holding) => holding.symbol === quote.symbol)
    : null;
  const heldSymbols = holdings.map((holding) => holding.symbol).filter(Boolean);
  const symbolChips = [...new Set([...heldSymbols.slice(0, 6), ...popularSymbols])].slice(0, 10);
  const availableShares = currentHolding ? Number(currentHolding.quantity || 0) : 0;
  const chartStats = getChartStats(history);
  const chartColor = chartStats
    ? chartStats.change >= 0 ? "#34d399" : "#f87171"
    : quote && quote.change >= 0 ? "#34d399" : "#f87171";
  const sourceLabel = quote?.source === "alpha_vantage"
    ? "Alpha Vantage"
    : quote?.source === "stooq"
      ? "Stooq market data"
      : quote ? "Yahoo Finance" : "Market data";
  const chartSourceLabel = chartSource === "alpha_vantage"
    ? "Alpha Vantage"
    : chartSource === "stooq"
      ? "Stooq"
      : chartSource === "yfinance"
        ? "Yahoo Finance"
        : chartSource;
  const asOfLabel = quote?.as_of ? fmtCalendarDate(quote.as_of) : "Latest close";
  const dayRange = quote?.day_range;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Research</div>
        </div>
        <div className="page-tag"><strong>{quote?.symbol || "Ticker"}</strong> workspace</div>
      </div>

      <form onSubmit={handleSearch} className="search-bar">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search stock symbol (AAPL, TSLA, MSFT, GOOGL, AMZN...)"
        />
        <button type="submit" className="btn btn-primary" disabled={loadingQuote} style={{ minWidth: 100 }}>
          {loadingQuote ? <span className="spinner" /> : "Search"}
        </button>
      </form>

      <div className="symbol-chip-row">
        {symbolChips.map((symbol) => (
          <button
            key={symbol}
            type="button"
            className="chip-btn"
            onClick={() => {
              setSearch(symbol);
              fetchQuote(symbol);
            }}
          >
            {symbol}
          </button>
        ))}
      </div>

      {quote && (
        <div className="status-line">
          <span>Selected ticker: <strong style={{ color: "#0f172a" }}>{quote.symbol}</strong></span>
          <span>Held shares: <strong style={{ color: "#0f172a" }}>{availableShares.toFixed(2)}</strong></span>
          {currentHolding && (
            <span>Position value: <strong style={{ color: "#0f172a" }}>{fmt$(currentHolding.value)}</strong></span>
          )}
          <span>Data: <strong style={{ color: "#0f172a" }}>{sourceLabel}</strong></span>
        </div>
      )}

      {researchError && <div className="research-error">{researchError}</div>}

      {quote && (
        <div className="split-card">
          <div>
            <div className="quote-card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <div className="quote-symbol">{quote.symbol}</div>
                  <div className={`quote-price ${quote.change >= 0 ? "up" : "down"}`}>{fmt$(quote.price)}</div>
                  <div className={`quote-change ${quote.change >= 0 ? "up" : "down"}`}>
                    {quote.change >= 0 ? "▲" : "▼"} {fmt$(Math.abs(quote.change))} ({fmtPct(quote.change_pct)})
                  </div>
                </div>
                <div style={{ textAlign: "right", color: "#475569", fontSize: 13 }}>
                  <div>{asOfLabel}</div>
                  <div style={{ color: "#94a3b8", fontWeight: 600, fontSize: 16 }}>{fmt$(quote.prev_close)}</div>
                </div>
              </div>

              <div className="research-source-row">
                <span className="research-pill">{sourceLabel}</span>
                {quote.currency && <span className="research-pill">{quote.currency}</span>}
                {chartSourceLabel && <span className="research-pill">Chart {chartSourceLabel}</span>}
              </div>

              <div className="quote-kpi-grid">
                <div className="mini-panel">
                  <div className="mini-panel-label">Previous Close</div>
                  <div className="mini-panel-value" style={{ fontSize: 18 }}>{fmt$(quote.prev_close)}</div>
                </div>
                <div className="mini-panel">
                  <div className="mini-panel-label">Day Range</div>
                  <div className="mini-panel-value" style={{ fontSize: 18 }}>
                    {dayRange ? `${fmt$(dayRange.low)} - ${fmt$(dayRange.high)}` : "N/A"}
                  </div>
                </div>
                <div className="mini-panel">
                  <div className="mini-panel-label">Volume</div>
                  <div className="mini-panel-value" style={{ fontSize: 18 }}>{quote.volume ? fmtCompact(quote.volume) : "N/A"}</div>
                </div>
                <div className="mini-panel">
                  <div className="mini-panel-label">Position Value</div>
                  <div className="mini-panel-value" style={{ fontSize: 18 }}>{currentHolding ? fmt$(currentHolding.value) : fmt$(0)}</div>
                </div>
              </div>
            </div>

            <div className="period-selector">
              {periods.map(p => (
                <button type="button" key={p} className={`period-btn ${period === p ? "active" : ""}`} onClick={() => handlePeriod(p)}>{p.toUpperCase()}</button>
              ))}
            </div>

            <div className="card chart-panel">
              <div className="chart-head">
                <div>
                  <div className="card-title">Price Chart</div>
                  <div className="chart-title">{quote.symbol} {period.toUpperCase()} performance</div>
                  <div className="chart-subtitle">OHLC range view</div>
                </div>
                <div className="chart-toolbar">
                  <div className="chart-mode-control" aria-label="Chart mode">
                    <button
                      type="button"
                      className={`chart-mode-button ${chartMode === "candles" ? "active" : ""}`}
                      onClick={() => setChartMode("candles")}
                    >
                      Candles
                    </button>
                    <button
                      type="button"
                      className={`chart-mode-button ${chartMode === "line" ? "active" : ""}`}
                      onClick={() => setChartMode("line")}
                    >
                      Line
                    </button>
                  </div>
                  <label className="chart-toggle-control">
                    <input
                      type="checkbox"
                      checked={showVolume}
                      onChange={(event) => setShowVolume(event.target.checked)}
                    />
                    Volume
                  </label>
                </div>
              </div>
              {chartStats && (
                <div className="chart-stat-grid">
                  <div className="chart-stat">
                    <div className="chart-stat-label">Range Return</div>
                    <div className={`chart-stat-value ${chartStats.change >= 0 ? "up" : "down"}`}>{fmt$(chartStats.change)} ({fmtPct(chartStats.changePct)})</div>
                  </div>
                  <div className="chart-stat">
                    <div className="chart-stat-label">High</div>
                    <div className="chart-stat-value">{fmt$(chartStats.high)}</div>
                  </div>
                  <div className="chart-stat">
                    <div className="chart-stat-label">Low</div>
                    <div className="chart-stat-value">{fmt$(chartStats.low)}</div>
                  </div>
                  <div className="chart-stat">
                    <div className="chart-stat-label">Avg Volume</div>
                    <div className="chart-stat-value">{fmtCompact(chartStats.avgVolume)}</div>
                  </div>
                </div>
              )}
              {loadingChart ? (
                <div style={{ textAlign: "center", padding: 80 }}><div className="spinner" /></div>
              ) : history.length > 0 ? (
                <div className="chart-wrap enhanced">
                  <PriceChart data={history} color={chartColor} mode={chartMode} showVolume={showVolume} />
                </div>
              ) : (
                <div className="empty"><div className="empty-text">{chartError || "No chart data"}</div></div>
              )}
            </div>
          </div>

          <div className="card-stack">
            <div className="card">
              <div className="card-title">Holding</div>
              <div className="surface-row">
                <div style={{ fontWeight: 700, color: "#0f172a" }}>Shares</div>
                <strong>{availableShares.toFixed(2)}</strong>
              </div>
              <div className="surface-row">
                <div style={{ fontWeight: 700, color: "#0f172a" }}>Value</div>
                <strong>{currentHolding ? fmt$(currentHolding.value) : fmt$(0)}</strong>
              </div>
              <div className="surface-row">
                <div style={{ fontWeight: 700, color: "#0f172a" }}>Avg cost</div>
                <strong>{currentHolding && currentHolding.avg_cost != null ? fmt$(currentHolding.avg_cost) : "N/A"}</strong>
              </div>
              <div className="surface-row">
                <div style={{ fontWeight: 700, color: "#0f172a" }}>Unrealized P&amp;L</div>
                <strong className={currentHolding && currentHolding.pnl >= 0 ? "up" : "down"}>
                  {currentHolding ? fmt$(currentHolding.pnl) : fmt$(0)}
                </strong>
              </div>
            </div>

            <div className="card">
              <div className="card-title">Portfolio</div>
              <div className="surface-row">
                <div style={{ fontWeight: 700, color: "#0f172a" }}>Cash</div>
                <strong>{cash !== null ? fmt$(cash) : "N/A"}</strong>
              </div>
              <div className="surface-row">
                <div style={{ fontWeight: 700, color: "#0f172a" }}>Weight</div>
                <strong>
                  {currentHolding && portfolioSnapshot?.total_value > 0
                    ? `${((currentHolding.value / portfolioSnapshot.total_value) * 100).toFixed(1)}%`
                    : "0.0%"}
                </strong>
              </div>
              <div className="surface-row">
                <div style={{ fontWeight: 700, color: "#0f172a" }}>Source</div>
                <strong>SnapTrade</strong>
              </div>
            </div>

            <div className="card">
              <form onSubmit={handleSaveThesis}>
                <div className="card-title">Thesis</div>
                <textarea
                  className="research-textarea"
                  value={thesisDraft.thesis_text}
                  onChange={(event) => setThesisDraft((draft) => ({ ...draft, thesis_text: event.target.value }))}
                  placeholder={`Why own or watch ${quote.symbol}?`}
                />
                <div className="research-field-grid">
                  <div className="form-group">
                    <label>Target Price</label>
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={thesisDraft.target_price}
                      onChange={(event) => setThesisDraft((draft) => ({ ...draft, target_price: event.target.value }))}
                      placeholder="0.00"
                    />
                  </div>
                  <div className="form-group">
                    <label>Time Horizon</label>
                    <input
                      type="date"
                      value={thesisDraft.time_horizon_date}
                      onChange={(event) => setThesisDraft((draft) => ({ ...draft, time_horizon_date: event.target.value }))}
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label>Catalyst</label>
                  <input
                    value={thesisDraft.catalyst}
                    onChange={(event) => setThesisDraft((draft) => ({ ...draft, catalyst: event.target.value }))}
                    placeholder="Earnings, product cycle, macro setup..."
                  />
                </div>
                <div className="form-group">
                  <label>Invalidation</label>
                  <input
                    value={thesisDraft.invalidation_criteria}
                    onChange={(event) => setThesisDraft((draft) => ({ ...draft, invalidation_criteria: event.target.value }))}
                    placeholder="What would prove this wrong?"
                  />
                </div>
                {thesis && (
                  <div className="research-muted">
                    Status: {thesis.status || "active"}{thesis.updated_at ? ` - Updated ${fmtCalendarDate(thesis.updated_at)}` : ""}
                  </div>
                )}
                <div className="research-actions">
                  <button type="submit" className="btn btn-primary btn-sm" disabled={savingThesis || loadingResearch}>
                    {savingThesis ? <span className="spinner" /> : "Save Thesis"}
                  </button>
                </div>
              </form>
            </div>

            <div className="card">
              <div className="card-title">Research Notes</div>
              <form onSubmit={handleAddJournal}>
                <textarea
                  className="research-textarea"
                  style={{ minHeight: 88 }}
                  value={noteBody}
                  onChange={(event) => setNoteBody(event.target.value)}
                  placeholder={`Add a note for ${quote.symbol}`}
                />
                <div className="research-actions">
                  <button type="submit" className="btn btn-primary btn-sm" disabled={savingNote}>
                    {savingNote ? <span className="spinner" /> : "Add Note"}
                  </button>
                </div>
              </form>
              {journalEntries.length > 0 ? (
                <div className="research-list" style={{ marginTop: 14 }}>
                  {journalEntries.map((entry) => (
                    <div className="research-note" key={entry.id}>
                      <div className="research-note-head">
                        <span>{fmtCalendarDate(entry.created_at)}</span>
                        <button type="button" className="research-note-delete" onClick={() => handleDeleteJournal(entry.id)}>Delete</button>
                      </div>
                      <div className="research-note-body">{entry.body}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="research-empty-state" style={{ marginTop: 14 }}>
                  No notes for {quote.symbol} yet.
                </div>
              )}
            </div>

            <div className="card">
              <div className="card-title">Events</div>
              {events.length > 0 ? (
                <div className="research-list">
                  {events.map((event) => (
                    <div className="research-event" key={event.id || `${event.symbol}-${event.event_type}-${event.event_date}`}>
                      <div className="research-event-head">
                        <span>{event.event_type}</span>
                        <span>{fmtCalendarDate(event.event_date)}</span>
                      </div>
                      <div className="research-note-body" style={{ fontWeight: 700 }}>{event.title}</div>
                      {event.body && <div className="research-event-body" style={{ marginTop: 6 }}>{event.body}</div>}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="research-empty-state">
                  No events recorded for {quote.symbol}.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {!quote && !loadingQuote && (
        <div className="empty" style={{ marginTop: 80 }}>
          <div className="empty-icon">📈</div>
          <div className="empty-text">Search a symbol.</div>
        </div>
      )}
    </div>
  );
}

// ─── Alerts page ─────────────────────────────────────────────────────────────
function AlertsPage({ toast }) {
  const [alerts, setAlerts] = useState([]);
  const [symbol, setSymbol] = useState("");
  const [condition, setCondition] = useState("above");
  const [targetPrice, setTargetPrice] = useState("");
  const [checking, setChecking] = useState(false);
  const [currentPrice, setCurrentPrice] = useState(null);

  const load = useCallback(() => {
    authFetch(`${API}/alerts`).then(r => r.json()).then(d => setAlerts(d.alerts || [])).catch(() => {});
  }, []);

  useEffect(() => { load(); }, []);

  const lookupPrice = useCallback(async (sym) => {
    if (!sym.trim()) { setCurrentPrice(null); return; }
    try {
      const r = await authFetch(`${API}/quote/${sym.trim().toUpperCase()}`);
      if (r.ok) { const d = await r.json(); setCurrentPrice(d.price); }
      else { setCurrentPrice(null); }
    } catch (_) { setCurrentPrice(null); }
  }, []);

  const handleCreate = async (e) => {
    e.preventDefault();
    const sym = symbol.trim().toUpperCase();
    if (!sym || !targetPrice || isNaN(targetPrice) || Number(targetPrice) <= 0) {
      toast("Fill in all fields correctly", "error"); return;
    }
    try {
      const r = await authFetch(`${API}/alerts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: sym, condition, target_price: Number(targetPrice) }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail);
      toast(`Alert: ${sym} ${condition} ${fmt$(Number(targetPrice))}`, "success");
      setSymbol(""); setTargetPrice(""); setCurrentPrice(null);
      load();
    } catch (e) { toast(e.message, "error"); }
  };

  const handleDelete = async (id) => {
    await authFetch(`${API}/alerts/${id}`, { method: "DELETE" });
    load();
    toast("Alert removed", "info");
  };

  const handleCheck = async () => {
    setChecking(true);
    try {
      const r = await authFetch(`${API}/alerts/check`);
      const d = await r.json();
      if (d.triggered.length > 0) {
        d.triggered.forEach(a => toast(`${a.symbol} hit ${fmt$(a.triggered_price)} (${a.condition} ${fmt$(a.target_price)})`, "success"));
      } else {
        toast(`Checked ${d.checked} alert(s). None triggered.`, "info");
      }
      load();
    } catch (_) { toast("Check failed", "error"); }
    finally { setChecking(false); }
  };

  const active = alerts.filter(a => !a.triggered);
  const triggered = alerts.filter(a => a.triggered);

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Alerts</div>
        </div>
        <div className="page-tag"><strong>{active.length}</strong> active alerts</div>
      </div>

      <div className="grid-2" style={{ gap: 22 }}>
      <div className="card">
        <div className="card-title">Create Price Alert</div>
        <form onSubmit={handleCreate}>
          <div className="form-group">
            <label>Stock Symbol</label>
            <input value={symbol} onChange={e => { setSymbol(e.target.value); lookupPrice(e.target.value); }} placeholder="AAPL, TSLA..." />
            {currentPrice && <div style={{ fontSize: 12, color: "#475569", marginTop: 6 }}>Current: <span style={{ color: "#34d399", fontWeight: 700 }}>{fmt$(currentPrice)}</span></div>}
          </div>
          <div className="form-group">
            <label>Condition</label>
            <select value={condition} onChange={e => setCondition(e.target.value)}>
              <option value="above">Price goes above</option>
              <option value="below">Price drops below</option>
            </select>
          </div>
          <div className="form-group">
            <label>Target Price ($)</label>
            <input type="number" min="0" step="0.01" value={targetPrice} onChange={e => setTargetPrice(e.target.value)} placeholder="0.00" />
          </div>
          <button type="submit" className="btn btn-primary btn-full">Set Alert</button>
        </form>
      </div>

      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, gap: 12 }}>
          <div style={{ fontWeight: 800, fontSize: 16, color: "#0f172a" }}>Active Alerts</div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={handleCheck} disabled={checking || active.length === 0}>
            {checking ? <span className="spinner" style={{ width: 14, height: 14 }} /> : "Check Now"}
          </button>
        </div>
        {active.length === 0 ? (
          <div className="card empty"><div className="empty-icon">🔕</div><div className="empty-text">No active alerts</div></div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {active.map(a => (
              <div key={a.id} className="card" style={{ padding: "16px 18px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <span className="alert-dot active" />
                  <strong style={{ color: "#60a5fa", fontSize: 15 }}>{a.symbol}</strong>
                  <span style={{ color: "#64748b", fontSize: 13, margin: "0 8px" }}>{a.condition}</span>
                  <strong style={{ color: "#0f172a" }}>{fmt$(a.target_price)}</strong>
                  <div style={{ fontSize: 11, color: "#334155", marginTop: 4 }}>Created {fmtDateTime(a.created_at)}</div>
                </div>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => handleDelete(a.id)}>Remove</button>
              </div>
            ))}
          </div>
        )}

        {triggered.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <div style={{ fontWeight: 800, fontSize: 16, marginBottom: 14, color: "#3b82f6" }}>Triggered ({triggered.length})</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {triggered.map(a => (
                <div key={a.id} className="card" style={{ padding: "16px 18px", display: "flex", justifyContent: "space-between", alignItems: "center", borderColor: "rgba(59,130,246,0.2)" }}>
                  <div>
                    <span className="alert-dot triggered" />
                    <strong style={{ color: "#3b82f6" }}>{a.symbol}</strong>
                    <span style={{ color: "#64748b", fontSize: 13, margin: "0 8px" }}>{a.condition}</span>
                    <strong>{fmt$(a.target_price)}</strong>
                    <div style={{ fontSize: 11, color: "#334155", marginTop: 4 }}>
                      Hit {fmt$(a.triggered_price)} at {fmtDateTime(a.triggered_at)}
                    </div>
                  </div>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => handleDelete(a.id)}>Clear</button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
    </div>
  );
}

// ─── Premium Insights ────────────────────────────────────────────────────────
function InsightsPage({ toast }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [customSymbols, setCustomSymbols] = useState("");
  const [searching, setSearching] = useState(false);

  const load = useCallback((symbols = "") => {
    setLoading(true);
    const cleanedSymbols = symbols
      .split(",")
      .map(symbol => symbol.trim().toUpperCase())
      .filter(Boolean)
      .join(",");
    const url = cleanedSymbols ? `${API}/insights?symbols=${encodeURIComponent(cleanedSymbols)}` : `${API}/insights`;
    authFetch(url)
      .then(r => r.json())
      .then(setData)
      .catch(() => toast("Failed to load insights", "error"))
      .finally(() => { setLoading(false); setSearching(false); });
  }, []);

  useEffect(() => { load(); }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    if (!customSymbols.trim()) { load(); return; }
    setSearching(true);
    load(customSymbols.trim());
  };

  const getRsiColor = (rsi) => {
    if (rsi < 30) return "#34d399";
    if (rsi < 45) return "#6ee7b7";
    if (rsi > 70) return "#f87171";
    if (rsi > 55) return "#60a5fa";
    return "#94a3b8";
  };

  if (loading) return <div style={{ textAlign: "center", padding: 80 }}><div className="spinner" style={{ width: 36, height: 36 }} /></div>;

  return (
    <div>
      <div className="premium-header">
        <div className="premium-badge">Signal Desk</div>
        <div className="premium-title">
          {data && data.market_open
            ? `Market Insights | ${data.day}, ${data.date}`
            : "Markets Closed"}
        </div>
        <div className="premium-sub">
          {data && data.market_open
            ? `RSI, MACD, and moving averages across ${data.total_analyzed} stocks.`
            : data?.message || "Insights update Monday through Friday"}
        </div>
      </div>

      <form onSubmit={handleSearch} className="search-insights">
        <input
          value={customSymbols}
          onChange={e => setCustomSymbols(e.target.value)}
          placeholder="AAPL, TSLA, NVDA (blank for watchlist)"
        />
        <button type="submit" className="btn btn-primary" disabled={searching} style={{ minWidth: 110 }}>
          {searching ? <span className="spinner" /> : "Analyze"}
        </button>
      </form>

      {data && data.market_open && data.insights.length > 0 && (
        <>
          <div className="summary-cards">
            <div className="summary-card">
              <div className="summary-num up">{data.summary.buys}</div>
              <div className="summary-label">Buy Signals</div>
            </div>
            <div className="summary-card">
              <div className="summary-num" style={{ color: "#64748b" }}>{data.summary.holds}</div>
              <div className="summary-label">Hold</div>
            </div>
            <div className="summary-card">
              <div className="summary-num down">{data.summary.sells}</div>
              <div className="summary-label">Sell Signals</div>
            </div>
          </div>

          <div className="insight-grid">
            {data.insights.map(stock => (
              <div key={stock.symbol} className="insight-card">
                <div className="insight-card-header">
                  <div>
                    <div className="insight-symbol">{stock.symbol}</div>
                    <div className="insight-price">
                      {fmt$(stock.price)}
                      <span className={stock.change_pct >= 0 ? "up" : "down"} style={{ marginLeft: 8, fontSize: 13 }}>
                        {stock.change_pct >= 0 ? "▲" : "▼"} {fmtPct(stock.change_pct)}
                      </span>
                    </div>
                  </div>
                  <span className={`signal-tag ${stock.action_color}`}>{stock.action}</span>
                </div>

                <div style={{ marginBottom: 12 }}>
                  <div className="indicator-row">
                    <span className="indicator-label">RSI (14)</span>
                    <span className="indicator-value" style={{ color: getRsiColor(stock.rsi) }}>{stock.rsi}</span>
                  </div>
                  <div className="rsi-bar">
                    <div className="rsi-fill" style={{ width: `${stock.rsi}%`, background: getRsiColor(stock.rsi) }} />
                  </div>
                </div>

                <div className="indicator-row">
                  <span className="indicator-label">MACD</span>
                  <span className={`indicator-value ${stock.macd.bullish ? "up" : "down"}`}>
                    {stock.macd.bullish ? "Bullish" : "Bearish"} ({stock.macd.histogram > 0 ? "+" : ""}{stock.macd.histogram})
                  </span>
                </div>
                <div className="indicator-row">
                  <span className="indicator-label">SMA 20</span>
                  <span className={`indicator-value ${stock.price > stock.sma20 ? "up" : "down"}`}>
                    {fmt$(stock.sma20)} {stock.price > stock.sma20 ? "▲ Above" : "▼ Below"}
                  </span>
                </div>
                <div className="indicator-row">
                  <span className="indicator-label">SMA 50</span>
                  <span className={`indicator-value ${stock.price > stock.sma50 ? "up" : "down"}`}>
                    {fmt$(stock.sma50)} {stock.price > stock.sma50 ? "▲ Above" : "▼ Below"}
                  </span>
                </div>
                <div className="indicator-row">
                  <span className="indicator-label">Volume</span>
                  <span className="indicator-value" style={{ color: stock.vol_spike > 1.5 ? "#3b82f6" : "#94a3b8" }}>
                    {stock.vol_spike}x avg {stock.vol_spike > 1.5 ? "Spike" : ""}
                  </span>
                </div>
                <div className="indicator-row">
                  <span className="indicator-label">3M Range</span>
                  <span className="indicator-value neutral">
                    {stock.pct_from_high}% from high
                  </span>
                </div>

                <div className="signal-list">
                  {stock.signals.map((s, i) => (
                    <span key={i} className="signal-chip">{s}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div style={{ textAlign: "center", marginTop: 24, fontSize: 11, color: "#334155", lineHeight: 1.6 }}>
            Signals are based on technical indicators (RSI, MACD, SMA) and are for educational purposes only.<br />
            This is not financial advice. Always do your own research before making investment decisions.
          </div>
        </>
      )}

      {data && !data.market_open && (
        <div className="empty" style={{ marginTop: 40 }}>
          <div className="empty-icon">🌙</div>
          <div className="empty-text">Markets closed. Insights update weekdays.</div>
        </div>
      )}

      {data && data.market_open && data.insights.length === 0 && (
        <div className="empty" style={{ marginTop: 40 }}>
          <div className="empty-icon">📊</div>
          <div className="empty-text">No results.</div>
        </div>
      )}
    </div>
  );
}

// ─── Brokerage page ──────────────────────────────────────────────────────────
function BrokeragePage({ toast, onPortfolioChange, onOpenPosition }) {
  const [loading, setLoading] = useState(false);
  const [connections, setConnections] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [holdings, setHoldings] = useState([]);
  const [portfolio, setPortfolio] = useState(null);

  const loadConnections = useCallback(async () => {
    try {
      const r = await authFetch(`${API}/brokerage/connections`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed to load connections");
      setConnections(d.connections || []);
    } catch (e) {
      toast(e.message, "error");
    }
  }, [toast]);

  const loadHoldings = useCallback(async () => {
    try {
      const r = await authFetch(`${API}/brokerage/holdings`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed to load brokerage data");
      setAccounts(d.accounts || []);
      setHoldings(d.holdings || []);
    } catch (e) {
      toast(e.message, "error");
    }
  }, [toast]);

  const loadPortfolio = useCallback(async () => {
    try {
      const r = await authFetch(`${API}/brokerage/portfolio`);
      const d = await r.json();
      if (r.status === 404) {
        setPortfolio(null);
        return;
      }
      if (!r.ok) throw new Error(d.detail || "No synced brokerage portfolio yet");
      setPortfolio(d);
    } catch (e) {
      setPortfolio(null);
      toast(e.message, "info");
    }
  }, [toast]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadConnections(), loadHoldings(), loadPortfolio()]);
  }, [loadConnections, loadHoldings, loadPortfolio]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const handleConnect = async () => {
    setLoading("connect");
    try {
      const r = await authFetch(`${API}/brokerage/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          custom_redirect: `${window.location.origin}/`,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed to create SnapTrade link");
      if (!d.redirect_uri) throw new Error("SnapTrade did not return a connection link");
      const portalUrl = new URL(d.redirect_uri);
      localStorage.setItem("pending_brokerage_sync", "1");
      window.location.assign(portalUrl.href);
    } catch (e) {
      toast(e.message, "error");
      setLoading(false);
    }
  };

  const handleSync = async (refreshRemote = false) => {
    setLoading(refreshRemote ? "broker" : "cached");
    try {
      const r = await authFetch(`${API}/brokerage/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_remote: refreshRemote }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Failed to sync brokerage");
      if (d.sync.refresh_queued) {
        toast(`Robinhood refresh requested. Imported ${d.sync.accounts_synced} account(s) and ${d.sync.positions_synced} position(s). Rechecking shortly.`, "success");
      } else {
        toast(`Synced ${d.sync.accounts_synced} account(s) and ${d.sync.positions_synced} position(s)`, "success");
      }
      setPortfolio(d.portfolio || null);
      await Promise.all([loadConnections(), loadHoldings()]);
      onPortfolioChange?.();
      if (d.sync.refresh_queued) {
        window.setTimeout(async () => {
          try {
            const retry = await authFetch(`${API}/brokerage/sync`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ refresh_remote: false }),
            });
            const retryData = await retry.json();
            if (!retry.ok) throw new Error(retryData.detail || "Failed to recheck brokerage");
            setPortfolio(retryData.portfolio || null);
            await Promise.all([loadConnections(), loadHoldings()]);
            onPortfolioChange?.();
            toast(`Robinhood recheck imported ${retryData.sync.accounts_synced} account(s) and ${retryData.sync.positions_synced} position(s)`, "success");
          } catch (e) {
            toast(e.message, "error");
          }
        }, 45000);
      }
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const returnedFromBrokerage =
      params.get("status") === "SUCCESS" ||
      params.has("connection_id") ||
      params.has("authorizationId");
    const pendingSync = localStorage.getItem("pending_brokerage_sync");

    if (pendingSync || returnedFromBrokerage) {
      localStorage.removeItem("pending_brokerage_sync");
      if (returnedFromBrokerage) {
        window.history.replaceState({}, document.title, window.location.pathname);
      }
      handleSync(true);
    }
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-title">Brokerage</div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button type="button" className="btn btn-ghost" onClick={refreshAll} disabled={!!loading}>Refresh View</button>
          <button type="button" className="btn btn-primary" onClick={() => handleSync(false)} disabled={!!loading}>
            {loading === "cached" ? <span className="spinner" /> : "Sync Holdings"}
          </button>
          <button type="button" className="btn btn-buy" onClick={() => handleSync(true)} disabled={!!loading}>
            {loading === "broker" ? <span className="spinner" /> : "Refresh Robinhood"}
          </button>
          <button type="button" className="btn btn-primary" onClick={handleConnect} disabled={!!loading}>
            {loading === "connect" ? <span className="spinner" /> : "Connect Brokerage"}
          </button>
        </div>
      </div>

      <div className="grid-3" style={{ marginBottom: 22 }}>
        <div className="card">
          <div className="card-title">Connections</div>
          <div className="stat-value">{connections.length}</div>
          <div className="stat-sub neutral">Linked broker logins known to SnapTrade</div>
        </div>
        <div className="card">
          <div className="card-title">Accounts</div>
          <div className="stat-value">{accounts.length}</div>
          <div className="stat-sub neutral">Brokerage accounts pulled into the app</div>
        </div>
        <div className="card">
          <div className="card-title">Holdings</div>
          <div className="stat-value">{holdings.length}</div>
          <div className="stat-sub neutral">Synced positions across all linked accounts</div>
        </div>
      </div>

      <div className="split-card">
        <div className="card">
          <div className="card-title">Connections</div>
          {connections.length === 0 ? (
            <div className="empty">
              <div className="empty-icon">🔗</div>
              <div className="empty-text">No connected brokerage. Click Connect Brokerage.</div>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Brokerage</th>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Last Sync</th>
                  </tr>
                </thead>
                <tbody>
                  {connections.map((connection) => (
                    <tr key={connection.authorization_id}>
                      <td>{connection.brokerage_name || connection.brokerage_slug || "Unknown"}</td>
                      <td>{connection.connection_name || "Unnamed"}</td>
                      <td className={connection.disabled ? "down" : "up"}>{connection.disabled ? "Disabled" : "Active"}</td>
                      <td>{connection.last_synced_at ? new Date(connection.last_synced_at).toLocaleString() : "Never"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card-stack">
          <div className="card">
            <div className="card-title">Brokerage Portfolio</div>
            {portfolio ? (
              <div style={{ display: "grid", gap: 12 }}>
                <div className="surface-row">
                  <div style={{ fontWeight: 700, color: "#0f172a" }}>Total value</div>
                  <strong>{fmt$(portfolio.total_value)}</strong>
                </div>
                <div className="surface-row">
                  <div style={{ fontWeight: 700, color: "#0f172a" }}>Cash</div>
                  <strong>{fmt$(portfolio.cash)}</strong>
                </div>
                <div className="surface-row">
                  <div style={{ fontWeight: 700, color: "#0f172a" }}>P&amp;L</div>
                  <strong className={portfolio.total_pnl >= 0 ? "up" : "down"}>{fmt$(portfolio.total_pnl)}</strong>
                </div>
              </div>
            ) : (
              <div className="empty">
                <div className="empty-icon">📁</div>
                <div className="empty-text">Click Sync Holdings to load portfolio.</div>
              </div>
            )}
          </div>

          <div className="card">
            <div className="card-title">Synced Holdings</div>
            {holdings.length === 0 ? (
              <div className="surface-copy">No synced holdings yet.</div>
            ) : (
              <div style={{ display: "grid", gap: 10, maxHeight: 320, overflow: "auto" }}>
                {holdings.map((holding) => {
                  const openPosition = () => onOpenPosition?.(holding.symbol);
                  return (
                    <div
                      key={`${holding.account_id}-${holding.symbol}`}
                      className="surface-row holding-link-row"
                      role="button"
                      tabIndex={0}
                      onClick={openPosition}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          openPosition();
                        }
                      }}
                      aria-label={`Open ${holding.symbol} in research`}
                    >
                      <div>
                        <div style={{ fontWeight: 700, color: "#0f4c81" }}>{holding.symbol}</div>
                        <div className="surface-copy">
                          {holding.description || holding.account_id}
                          {holding.synced_at ? ` - ${new Date(holding.synced_at).toLocaleString()}` : ""}
                        </div>
                      </div>
                      <strong>{holding.quantity}</strong>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── App root ─────────────────────────────────────────────────────────────────
function App() {
  const [tab, setTab] = useState("dashboard");
  const [dashboardView, setDashboardView] = useState("simple");
  const [researchSymbol, setResearchSymbol] = useState("");
  const [portfolioSummary, setPortfolioSummary] = useState(null);
  const [authed, setAuthed] = useState(!!(getToken() || getRefreshToken()));
  const [userEmail, setUserEmail] = useState(getUser()?.email || null);
  const { toasts, add: toast } = useToasts();

  const loadPortfolioSummary = useCallback(() => {
    if (!getToken() && !getRefreshToken()) {
      setPortfolioSummary(null);
      return;
    }
    authFetch(`${API}/portfolio`)
      .then(async (r) => {
        if (r.status === 401) {
          clearToken();
          setAuthed(false);
          setUserEmail(null);
          setPortfolioSummary(null);
          throw new Error("Session expired");
        }
        return r.json();
      })
      .then(setPortfolioSummary)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!authed) return;
    loadPortfolioSummary();
  }, [authed, tab, loadPortfolioSummary]);

  useEffect(() => {
    const handleExpired = () => {
      setAuthed(false);
      setUserEmail(null);
      setPortfolioSummary(null);
      setTab("dashboard");
      toast("Session expired. Sign in again.", "info");
    };
    window.addEventListener("auth-expired", handleExpired);
    return () => window.removeEventListener("auth-expired", handleExpired);
  }, [toast]);

  useEffect(() => {
    if (authed && localStorage.getItem("pending_brokerage_sync")) {
      setTab("brokerage");
    }
  }, [authed]);

  const handleLogin = (user, token) => {
    setAuthed(true);
    setUserEmail(user.email);
  };

  const handleLogout = () => {
    clearToken();
    setAuthed(false);
    setUserEmail(null);
    setPortfolioSummary(null);
    setTab("dashboard");
    toast("Signed out", "info");
  };

  const openResearchForSymbol = useCallback((symbol) => {
    const normalized = String(symbol || "").trim().toUpperCase();
    if (!normalized) return;
    setResearchSymbol(normalized);
    setTab("research");
  }, []);

  if (!authed) {
    return (
      <div className="app">
        <AuthPage onLogin={handleLogin} toast={toast} />
        <ToastContainer toasts={toasts} />
      </div>
    );
  }

  const tabs = [
    { id: "dashboard", label: "Dashboard" },
    { id: "brokerage", label: "Brokerage" },
    { id: "insights", label: "Insights" },
    { id: "research", label: "Research" },
    { id: "alerts", label: "Alerts" },
  ];
  const visibleTabs = tabs;
  const activeTab = visibleTabs.find((item) => item.id === tab) || visibleTabs[0];
  const todayLabel = new Date().toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
  const pnlClass = (portfolioSummary?.total_pnl ?? 0) >= 0 ? "up" : "down";
  const leadPosition = portfolioSummary?.largest_holding_symbol || "—";
  const avatarInitial = (userEmail || "U").trim().slice(0, 1).toUpperCase();

  return (
    <div className="app">
      <div className="shell">
        <div className="nav-wrap">
          <nav className="nav">
            <div className="nav-brand">
              <div className="nav-brand-icon">★</div>
              <div className="brand-copy">
                <div className="brand-name">Northstar</div>
              </div>
            </div>
            <div className="nav-tabs">
              {visibleTabs.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`nav-tab ${tab === item.id ? "active" : ""}`}
                  onClick={() => {
                    setTab(item.id);
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="nav-right">
              {tab === "dashboard" && (
                <div className="view-toggle" aria-label="Dashboard view">
                  <button
                    type="button"
                    className={dashboardView === "simple" ? "active" : ""}
                    onClick={() => setDashboardView("simple")}
                  >
                    Simple
                  </button>
                  <button
                    type="button"
                    className={dashboardView === "advanced" ? "active" : ""}
                    onClick={() => setDashboardView("advanced")}
                  >
                    Advanced
                  </button>
                </div>
              )}
              <span className="status-pill">{todayLabel}</span>
              {portfolioSummary && <span className="cash-badge">{fmt$(portfolioSummary.cash)}</span>}
              <button type="button" className="avatar-button" onClick={handleLogout} title="Sign out">{avatarInitial}</button>
            </div>
          </nav>
        </div>

        <main className="main">
          {tab !== "dashboard" && <section className="hero">
            <div className="hero-grid">
              <div>
                <div className="hero-title">{activeTab.label}</div>
                <div className="hero-meta">
                  <div className="meta-chip">Capital <strong>{portfolioSummary ? fmt$(portfolioSummary.total_value) : "—"}</strong></div>
                  <div className="meta-chip">Lead name <strong>{leadPosition}</strong></div>
                  <div className="meta-chip">Open positions <strong>{portfolioSummary?.positions_count ?? 0}</strong></div>
                </div>
              </div>

              <div className="hero-rail">
                <div className="signal-panel">
                  <div className="signal-label">Net P&amp;L</div>
                  <div className={`signal-value ${pnlClass}`}>
                    {portfolioSummary ? fmt$(portfolioSummary.total_pnl) : "—"}
                  </div>
                  {portfolioSummary && (
                    <div className="signal-note">{fmtPct(portfolioSummary.total_pnl_pct)}</div>
                  )}
                </div>

                <div className="mini-grid">
                  <div className="mini-panel">
                    <div className="mini-panel-label">Winners</div>
                    <div className="mini-panel-value up">{portfolioSummary?.winners_count ?? 0}</div>
                  </div>
                  <div className="mini-panel">
                    <div className="mini-panel-label">Lagging</div>
                    <div className="mini-panel-value down">{portfolioSummary?.losers_count ?? 0}</div>
                  </div>
                </div>
              </div>
            </div>
          </section>}

          {tab === "dashboard" && <Dashboard toast={toast} onNavigate={setTab} onOpenPosition={openResearchForSymbol} viewMode={dashboardView} />}
          {tab === "brokerage" && <BrokeragePage toast={toast} onPortfolioChange={loadPortfolioSummary} onOpenPosition={openResearchForSymbol} />}
          {tab === "insights" && <InsightsPage toast={toast} />}
          {tab === "research" && <ResearchPage toast={toast} initialSymbol={researchSymbol} />}
          {tab === "alerts" && <AlertsPage toast={toast} />}
        </main>
      </div>

      <ToastContainer toasts={toasts} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
