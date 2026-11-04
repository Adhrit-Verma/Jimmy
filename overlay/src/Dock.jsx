import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import {
  Activity, Brain, Camera, CameraOff, Check, CloudOff, Cpu, Download, Eye, FileText, Gauge, LoaderCircle, MemoryStick, Mic, MicOff,
  Pause, PhoneCall, Play, RefreshCw, ScanEye, Wrench, X,
} from "lucide-react";

// D66: what Jimmy is doing right now, at a glance. Python sends "vitals" every 2 s (its own CPU
// and RAM, the listening windows, mic, camera, capture, brain); Electron adds the overlay's own
// load and the update's progress ("update"). Only these components re-render on them.
const bridge = window.jimmy;
const left = (until) => Math.max(0, Math.round((until - Date.now()) / 1000));
const ask = (q) => bridge?.api("ask", { q });
const busyCpu = 30;                       // % of the whole PC: above it, the pill warns

export function useVitals() {
  const [v, setV] = useState(null);
  const [u, setU] = useState(null);
  const hist = useRef([]);
  useEffect(() => {
    bridge?.updateState?.().then(setU).catch(() => {});
    return bridge?.onEvent((ev) => {
      if (ev.type === "vitals") {
        hist.current = [...hist.current, (ev.cpu || 0) + (ev.ui_cpu || 0)].slice(-30);   // the last minute
        setV(ev);
      }
      if (ev.type === "update") setU(ev);
    });
  }, []);
  return { v, u, hist: hist.current };
}

// A 1 s clock, only while something counts down.
function useSecond(active) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [active]);
}

// The listening window as a ring: full when it opens, empty when Jimmy needs its name again.
function Ring({ until, size = 14 }) {
  const total = useRef({ until: 0, s: 1 });
  if (total.current.until !== until) total.current = { until, s: Math.max(1, left(until)) };
  const frac = left(until) / total.current.s;
  const r = size / 2 - 1.5, c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} className="-rotate-90" aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="2" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#38bdf8" strokeWidth="2" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - frac)} style={{ transition: "stroke-dashoffset 1s linear" }} />
    </svg>
  );
}

// Small signals beside the pill's dot: the listening window, the camera, an update, a busy Jimmy.
export function Signals({ compact }) {
  const { v, u } = useVitals();
  const listening = v && left(v.listen_until) > 0;
  useSecond(listening);
  if (!v && !u) return null;
  const cam = v?.camera;
  const cpu = (v?.cpu || 0) + (v?.ui_cpu || 0);
  const upd = u && ["downloading", "ready", "installing"].includes(u.phase);
  return (
    <span className="flex items-center gap-1.5">
      {listening && (
        <span className="flex items-center gap-1" title="No need to say “Jimmy” until the ring runs out">
          <Ring until={v.listen_until} />
          {!compact && <span className="tabular-nums text-[11px] text-sky-300">{left(v.listen_until)}s</span>}
        </span>
      )}
      {!compact && cam?.on && (
        cam.contact ? <ScanEye size={12} className="text-sky-300" aria-label="Looking at you" />
          : <Camera size={12} className={cam.state === "present" ? "text-emerald-300/80" : "text-neutral-500"}
              aria-label={`Camera: ${cam.state || "starting"}`} />
      )}
      {!compact && v?.mic?.call?.length > 0 && <PhoneCall size={12} className="text-amber-300" aria-label="On a call" />}
      {upd && (
        <span className="relative flex" title={u.phase === "downloading" ? `Downloading Jimmy ${u.latest}` : `Jimmy ${u.latest} is ready`}>
          <Download size={12} className={u.phase === "ready" ? "text-emerald-300" : "text-sky-300"} />
          <span className="absolute -right-0.5 -top-0.5 size-1.5 animate-ping rounded-full bg-sky-400" />
        </span>
      )}
      {!compact && cpu >= busyCpu && <Activity size={12} className="text-amber-300" aria-label={`Jimmy is busy: ${Math.round(cpu)}% CPU`} />}
    </span>
  );
}

function Spark({ data }) {
  if (data.length < 2) return <div className="h-7" />;
  const max = Math.max(10, ...data);
  const pts = data.map((d, i) => `${(i / (data.length - 1)) * 100},${28 - (d / max) * 26}`).join(" ");
  return (
    <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="h-7 w-full">
      <polyline points={pts} fill="none" stroke="#38bdf8" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Tile({ icon: Icon, title, tone = "text-neutral-400", value, sub, children }) {
  return (
    <div className="flex min-h-[104px] flex-col rounded-xl bg-white/[0.04] p-3 ring-1 ring-white/[0.06]">
      <div className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-wider text-neutral-500">
        <Icon size={12} className={tone} /> {title}
      </div>
      <div className="mt-1.5 text-[13.5px] font-medium leading-snug text-neutral-100">{value}</div>
      {sub && <div className="mt-0.5 text-[11.5px] leading-snug text-neutral-400">{sub}</div>}
      {children && <div className="mt-auto flex flex-wrap gap-1.5 pt-2">{children}</div>}
    </div>
  );
}

function Btn({ onClick, children, disabled, strong }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className={`flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] transition-colors disabled:opacity-40
        ${strong ? "bg-sky-500/20 text-sky-100 hover:bg-sky-500/30" : "bg-white/[0.06] text-neutral-200 hover:bg-white/[0.12]"}`}>
      {children}
    </button>
  );
}

const CAMERA = {
  present: "Sees you", away: "No one there", watched: "More than one face", stranger: "Someone else",
  starting: "Starting…", off: "Off",
};
const UPDATE = {
  idle: "Not checked yet", checking: "Checking…", uptodate: "Up to date", downloading: "Downloading",
  ready: "Ready to install", installing: "Installing…", error: "Couldn't check", off: "Updates switched off",
  dev: "Development copy",
};

export function Dock({ onClose, hoverProps, surface }) {
  const { v, u, hist } = useVitals();
  const listening = v && left(v.listen_until) > 0;
  const nav = v && left(v.nav_until) > 0;
  useSecond(listening || nav);
  const cam = v?.camera || {};
  const mic = v?.mic || {};
  const cpu = Math.round((v?.cpu || 0) + (v?.ui_cpu || 0));
  const ram = (v?.ram_mb || 0) + (v?.ui_ram_mb || 0);
  const ph = u?.phase || "idle";
  return (
    <motion.div {...hoverProps}
      initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6 }}
      transition={{ type: "spring", stiffness: 520, damping: 36 }}
      className={`pointer-events-auto w-[520px] rounded-2xl p-3 ${surface}`}>
      <div className="mb-2 flex items-center justify-between px-1">
        <span className="flex items-center gap-1.5 text-[12px] font-medium text-neutral-200">
          <Gauge size={13} className="text-sky-300" /> Jimmy, right now
        </span>
        <span className="flex items-center gap-1">
          <Btn onClick={() => ask("make a diagnostic report")}><FileText size={11} /> Report</Btn>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-neutral-500 hover:bg-white/10 hover:text-neutral-200"
            aria-label="Close"><X size={13} /></button>
        </span>
      </div>
      {!v ? (
        <div className="flex items-center gap-2 px-1 py-6 text-[12px] text-neutral-500">
          <LoaderCircle size={14} className="animate-spin" /> Waiting for Jimmy's first reading…
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          <Tile icon={mic.on && !mic.paused ? Mic : MicOff} title="Listening" tone={listening ? "text-sky-300" : "text-neutral-400"}
            value={mic.paused ? "Paused" : !mic.on ? "Mic off" : mic.call?.length ? "On a call" : listening ? `Just talk · ${left(v.listen_until)}s` : "Say “Jimmy, …”"}
            sub={mic.call?.length ? `${mic.call.join(", ")} has the mic: say “Jimmy” first`
              : nav ? `“next”, “scroll down” work for ${left(v.nav_until)}s` : listening ? "No name needed until the ring runs out" : null}>
            {mic.call?.length > 0 && <Btn onClick={() => ask("I'm not on a call")}>Not a call</Btn>}
            <Btn onClick={() => bridge?.api(mic.paused ? "resume" : "pause", { minutes: 120 })}>
              {mic.paused ? <><Play size={11} /> Resume</> : <><Pause size={11} /> Pause 2h</>}
            </Btn>
          </Tile>
          <Tile icon={cam.on ? (cam.contact ? Eye : Camera) : CameraOff} title="Camera"
            tone={cam.on && cam.state === "present" ? "text-emerald-300" : cam.on ? "text-neutral-400" : "text-amber-300"}
            value={cam.on ? (cam.contact ? "Looking at you" : CAMERA[cam.state] || "Starting…") : "Not in use"}
            sub={cam.on ? (cam.why || (cam.faces > 1 ? `${cam.faces} faces` : null)) : cam.why || "Ask me what's wrong"}>
            <Btn onClick={() => ask("what's wrong with the camera")}>Why?</Btn>
            {(!cam.on || cam.why) && <Btn strong onClick={() => ask("fix the camera")}><Wrench size={11} /> Fix it</Btn>}
          </Tile>
          <Tile icon={Cpu} title="Jimmy's load" tone={cpu >= busyCpu ? "text-amber-300" : "text-neutral-400"}
            value={<span className="tabular-nums">{cpu}% CPU · {ram >= 1000 ? `${(ram / 1000).toFixed(1)} GB` : `${ram} MB`}</span>}
            sub={<span className="flex items-center gap-1 tabular-nums"><MemoryStick size={11} /> voice + memory {v.ram_mb} MB · screen {v.ui_ram_mb || 0} MB</span>}>
            <div className="w-full"><Spark data={hist} /></div>
          </Tile>
          <Tile icon={Download} title="Update" tone={ph === "ready" ? "text-emerald-300" : ph === "error" ? "text-amber-300" : "text-neutral-400"}
            value={ph === "downloading" ? `Jimmy ${u.latest} · ${Math.round((u.progress || 0) * 100)}%`
              : ph === "ready" || ph === "installing" ? `Jimmy ${u.latest}: ${UPDATE[ph].toLowerCase()}` : UPDATE[ph] || ph}
            sub={<>You have {u?.version || "?"}{u?.checked ? ` · checked ${new Date(u.checked).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}{u?.error ? ` · ${u.error}` : ""}</>}>
            {ph === "downloading" && (
              <div className="h-1 w-full overflow-hidden rounded-full bg-white/10">
                <div className="h-full bg-sky-400 transition-[width] duration-500" style={{ width: `${Math.round((u.progress || 0) * 100)}%` }} />
              </div>
            )}
            {ph === "ready" && <Btn strong onClick={() => bridge?.updateNow?.()}><Check size={11} /> Update now</Btn>}
            {!["dev", "off", "downloading", "installing", "checking"].includes(ph) && (
              <Btn onClick={() => bridge?.updateCheck?.()}><RefreshCw size={11} /> Check now</Btn>
            )}
          </Tile>
          <Tile icon={v.capture?.curtain ? CameraOff : Activity} title="Capture"
            tone={v.capture?.paused ? "text-amber-300" : "text-neutral-400"}
            value={v.capture?.curtain ? "Curtain down" : v.capture?.paused ? "Paused" : "Remembering"}
            sub={`${v.capture?.frames || 0} screens kept since start`}>
            <Btn onClick={() => bridge?.api("curtain", { on: !v.capture?.curtain })}>
              {v.capture?.curtain ? "Lift curtain" : "Curtain"}
            </Btn>
          </Tile>
          <Tile icon={v.brain?.online ? Brain : CloudOff} title="Brain" tone={v.brain?.online ? "text-violet-300" : "text-amber-300"}
            value={v.brain?.online ? (v.brain.model || "").split("/").pop() || "Online" : "Offline"}
            sub={v.brain?.online ? "Answers and actions" : "No key: answers show what I found"}>
            <Btn onClick={() => bridge?.openTimeline("settings")}>Settings</Btn>
          </Tile>
        </div>
      )}
    </motion.div>
  );
}
