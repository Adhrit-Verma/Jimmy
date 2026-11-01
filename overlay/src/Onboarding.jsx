import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowLeft, ArrowRight, Camera, Check, ChevronRight, Cpu, Database, ExternalLink, Eye, EyeOff, FolderOpen, Gauge,
  HardDrive, KeyRound, Loader2, Lock, MemoryStick, Mic, Minus, MonitorCheck, RotateCcw, ShieldCheck, Sparkles,
  TriangleAlert, X, Zap,
} from "lucide-react";
import Logo from "./Logo.jsx";

// D61/D62: the first run, in Jimmy's own look (the overlay's near-black surfaces, sky accent,
// spring motion). Eight short steps; the slow part (installing) runs while you read.
const S = window.jimmySetup;
const spring = { type: "spring", stiffness: 380, damping: 34 };
const STEPS = [
  ["hello", "Hello"], ["pc", "Your PC"], ["where", "Where"], ["size", "How much"],
  ["brain", "Brain"], ["privacy", "Privacy"], ["install", "Installing"], ["ready", "Say hi"],
];
const GB = 2 ** 30;
const gb = (b) => `${(b / GB).toFixed(b >= 10 * GB ? 0 : 1)} GB`;
const card = "rounded-2xl bg-white/[0.035] ring-1 ring-white/[0.08]";
const primary = "inline-flex items-center gap-2 rounded-xl bg-sky-500 px-5 py-2.5 text-[14px] font-medium text-white shadow-[0_8px_30px_-10px_rgba(14,165,233,0.8)] hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-40";
const quiet = "inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-[14px] text-neutral-400 hover:bg-white/[0.06] hover:text-neutral-100";

function Title({ kicker, children, sub }) {
  return (
    <div className="mb-6">
      {kicker && <div className="mb-2 text-[11.5px] font-medium uppercase tracking-[0.14em] text-sky-300/80">{kicker}</div>}
      <h1 className="text-[28px] font-semibold leading-tight tracking-tight text-neutral-50">{children}</h1>
      {sub && <p className="mt-2 max-w-[560px] text-[14.5px] leading-relaxed text-neutral-400">{sub}</p>}
    </div>
  );
}

function Row({ icon: Icon, label, value, state = "ok", action, delay = 0 }) {
  const tone = { ok: "text-emerald-300", warn: "text-amber-300", fail: "text-rose-300", info: "text-sky-300", wait: "text-neutral-500" }[state];
  const Mark = { ok: Check, warn: TriangleAlert, fail: X, info: Sparkles, wait: Loader2 }[state];
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay }}
      className="flex items-center gap-3.5 border-b border-white/[0.05] py-3 last:border-0">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-white/[0.05] text-neutral-300"><Icon size={17} /></span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] text-neutral-200">{label}</div>
        <div className="truncate text-[12.5px] text-neutral-500">{value}</div>
      </div>
      {action}
      <Mark size={17} className={`${tone} ${state === "wait" ? "animate-spin" : ""}`} />
    </motion.div>
  );
}

// --- the steps ------------------------------------------------------------------------------
function Hello() {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <motion.div initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ ...spring, delay: 0.1 }}>
        <Logo size={168} mood="listening" />
      </motion.div>
      <motion.h1 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.35 }}
        className="mt-10 text-[34px] font-semibold tracking-tight text-neutral-50">Hi, I'm Jimmy.</motion.h1>
      <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}
        className="mt-3 max-w-[480px] text-[15.5px] leading-relaxed text-neutral-400">
        I remember what you see and hear on this PC, answer when you ask, and do the clicking for you.
        Mostly, I know when to <span className="text-sky-300">stay quiet</span>.
      </motion.p>
      <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.8 }}
        className="mt-8 text-[12.5px] text-neutral-500">A few minutes, most of it downloading. Nothing leaves your PC unless you ask me something.</motion.p>
    </div>
  );
}

function PC({ pc }) {
  if (!pc) {
    return (
      <div>
        <Title kicker="Step 1" sub="Checking what this PC has, so I only install what it needs.">Your PC</Title>
        <div className={`${card} px-5`}>{["Windows", "Memory", "Graphics", "Microphone", "Camera"].map((l, i) =>
          <Row key={l} icon={MonitorCheck} label={l} value="checking…" state="wait" delay={i * 0.05} />)}</div>
      </div>
    );
  }
  const g = pc.gpu;
  return (
    <div>
      <Title kicker="Step 1" sub="Checked just now. Nothing here needs fixing unless it's red.">Your PC</Title>
      <div className={`${card} px-5`}>
        <Row icon={MonitorCheck} label={pc.windows.name} value={pc.arch.ok ? `64-bit · build ${pc.windows.build}` : `${pc.arch.value}: Jimmy needs 64-bit Windows on Intel or AMD`}
          state={!pc.arch.ok ? "fail" : pc.windows.ok ? "ok" : "warn"} />
        <Row icon={MemoryStick} label={`${pc.ram.gb} GB memory`} delay={0.05}
          value={pc.ram.ok ? (pc.ram.low ? "Enough. Lite or Balanced fits best." : "Plenty.") : "Below 8 GB: Lite will work, slowly."}
          state={pc.ram.ok ? "ok" : "warn"} />
        <Row icon={Zap} label={g.nvidia ? g.name : (g.name || "Graphics")} delay={0.1}
          value={g.nvidia ? (g.cudaOk ? "Speech runs on this GPU: fast." : `Driver ${g.driver} is old: update it for GPU speech (the CPU works meanwhile).`)
            : "No NVIDIA GPU: speech runs on the processor, with a lighter model."}
          state={g.nvidia ? (g.cudaOk ? "ok" : "warn") : "info"} />
        <Row icon={Mic} label="Microphone" delay={0.15}
          value={!pc.mic.devices.length ? "None found. Plug one in, or type to Jimmy instead." :
            pc.mic.allowed ? pc.mic.devices[0] : "Windows is blocking desktop apps from the microphone."}
          state={pc.mic.devices.length && pc.mic.allowed ? "ok" : "warn"}
          action={!pc.mic.allowed && <button onClick={() => S.open("mic")} className="mr-2 rounded-lg bg-white/10 px-2.5 py-1 text-[12px] text-neutral-100 hover:bg-white/15">Fix</button>} />
        <Row icon={Camera} label="Camera (optional)" delay={0.2}
          value={!pc.camera.devices.length ? "None: the privacy curtain stays off." :
            pc.camera.allowed ? `${pc.camera.devices[0]}: for the privacy curtain, never recorded` : "Windows is blocking desktop apps from the camera."}
          state={pc.camera.devices.length && pc.camera.allowed ? "ok" : "info"}
          action={pc.camera.devices.length > 0 && !pc.camera.allowed && <button onClick={() => S.open("cam")} className="mr-2 rounded-lg bg-white/10 px-2.5 py-1 text-[12px] text-neutral-100 hover:bg-white/15">Fix</button>} />
      </div>
    </div>
  );
}

function Where({ pc, data, setData, profile }) {
  const drive = (pc?.drives || []).find((d) => data.toUpperCase().startsWith(d.name.toUpperCase()));
  const need = (pc?.profiles?.[profile]?.gb || 5) * GB;
  const enough = !drive || drive.free > need * 1.2;
  return (
    <div>
      <Title kicker="Step 2" sub="Jimmy and everything it keeps go where you choose. Pick a drive with room: captures grow by tens of MB an hour.">Where should I live?</Title>
      <div className={`${card} p-5`}>
        <div className="text-[12px] uppercase tracking-wider text-neutral-500">Your data, models and caches</div>
        <div className="mt-2 flex items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl bg-black/40 px-3.5 py-2.5 ring-1 ring-white/10">
            <HardDrive size={16} className="shrink-0 text-sky-300" />
            <input value={data} onChange={(e) => setData(e.target.value)} spellCheck={false}
              className="min-w-0 flex-1 bg-transparent text-[14px] text-neutral-100 outline-none" />
          </div>
          <button onClick={async () => { const p = await S.pickFolder(data); if (p) setData(p); }} className={quiet}>
            <FolderOpen size={15} /> Change
          </button>
        </div>
        {drive && (
          <div className="mt-3">
            <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
              <motion.div className="h-full origin-left rounded-full bg-sky-400/80" initial={{ scaleX: 0 }}
                animate={{ scaleX: drive.used / (drive.used + drive.free) }} />
            </div>
            <div className={`mt-1.5 text-[12.5px] ${enough ? "text-neutral-500" : "text-amber-300"}`}>
              {drive.name} {gb(drive.free)} free{enough ? "" : ` · the ${profile} setup needs about ${gb(need)}`}
            </div>
          </div>
        )}
        <div className="mt-4 text-[12.5px] text-neutral-500">Jimmy itself: <span className="text-neutral-400">{pc?.install}</span></div>
      </div>
      <div className={`${card} mt-4 p-5`}>
        <div className="flex items-center gap-2 text-[13.5px] text-neutral-200"><Lock size={15} className="text-neutral-400" /> What has to stay on C: (a few KB)</div>
        <ul className="mt-2.5 space-y-1.5 text-[12.5px] text-neutral-400">
          <li>· one small file that remembers where your data is <span className="text-neutral-600">({pc?.pointer})</span></li>
          <li>· the Start menu and desktop shortcuts, and the uninstall entry</li>
          <li>· "start with Windows", if you turn it on</li>
        </ul>
        <div className="mt-2.5 text-[12.5px] text-neutral-500">No admin rights, nothing in Windows' own folders.</div>
      </div>
    </div>
  );
}

const PROFILE_TEXT = {
  lite: { name: "Lite", icon: Gauge, lines: ["Speech on the processor (lighter model)", "Recall by keywords", "No webcam"] },
  balanced: { name: "Balanced", icon: Sparkles, lines: ["Best speech model (GPU when there is one)", "Recall by keywords", "Privacy curtain with the webcam"] },
  full: { name: "Full", icon: Zap, lines: ["Everything in Balanced", "Local AI: recall by meaning, cards", "Most private, most space"] },
};

function Size({ pc, profile, setProfile, retention, setRetention, cap, setCap, recommended }) {
  return (
    <div>
      <Title kicker="Step 3" sub="How much of your PC Jimmy may use. You can change all of it later in Settings.">How much?</Title>
      <div className="grid grid-cols-3 gap-3">
        {Object.entries(PROFILE_TEXT).map(([k, t]) => {
          const p = pc?.profiles?.[k] || {};
          const on = profile === k;
          return (
            <motion.button key={k} onClick={() => setProfile(k)} whileTap={{ scale: 0.98 }}
              className={`relative rounded-2xl p-4 text-left ring-1 transition ${on ? "bg-sky-500/[0.12] ring-sky-400/60" : "bg-white/[0.035] ring-white/[0.08] hover:bg-white/[0.06]"}`}>
              {recommended === k && <span className="absolute right-3 top-3 rounded-full bg-sky-500/20 px-2 py-0.5 text-[10.5px] font-medium text-sky-200">for this PC</span>}
              <t.icon size={18} className={on ? "text-sky-300" : "text-neutral-400"} />
              <div className="mt-2.5 text-[15px] font-medium text-neutral-100">{t.name}</div>
              <div className="mt-0.5 text-[12px] text-neutral-500">~{p.gb} GB · ~{p.ramGb} GB RAM</div>
              <ul className="mt-3 space-y-1">{t.lines.map((l) => <li key={l} className="text-[12.5px] leading-snug text-neutral-400">{l}</li>)}</ul>
            </motion.button>
          );
        })}
      </div>
      <div className={`${card} mt-4 grid grid-cols-2 gap-6 p-5`}>
        <label className="block">
          <div className="flex justify-between text-[13px] text-neutral-300"><span>Keep captures for</span><span className="text-sky-300">{retention ? `${retention} days` : "ever"}</span></div>
          <input type="range" min={0} max={5} value={[7, 14, 30, 90, 365, 0].indexOf(retention)} onChange={(e) => setRetention([7, 14, 30, 90, 365, 0][+e.target.value])}
            className="mt-3 w-full accent-sky-400" />
          <div className="mt-1 text-[11.5px] text-neutral-500">Older days are deleted, oldest first.</div>
        </label>
        <label className="block">
          <div className="flex justify-between text-[13px] text-neutral-300"><span>Never use more than</span><span className="text-sky-300">{cap} GB</span></div>
          <input type="range" min={5} max={200} step={5} value={cap} onChange={(e) => setCap(+e.target.value)} className="mt-3 w-full accent-sky-400" />
          <div className="mt-1 text-[11.5px] text-neutral-500">For captures and screenshots; today is always kept.</div>
        </label>
      </div>
    </div>
  );
}

function KeyBox({ provider, label, hint, value, setValue, status, setStatus }) {
  const [shown, setShown] = useState(false);
  const test = async () => {
    setStatus("testing");
    const r = await S.testKey(provider, value);
    setStatus(r.ok ? "ok" : `fail:${r.status || r.error}`);
  };
  return (
    <div className={`${card} p-4`}>
      <div className="flex items-center justify-between">
        <div className="text-[14px] text-neutral-100">{label}</div>
        <button onClick={() => S.open(provider)} className="flex items-center gap-1 text-[12px] text-sky-300 hover:text-sky-200">Get a key <ExternalLink size={12} /></button>
      </div>
      <div className="mt-0.5 text-[12px] text-neutral-500">{hint}</div>
      <div className="mt-3 flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-xl bg-black/40 px-3 py-2 ring-1 ring-white/10">
          <KeyRound size={14} className="shrink-0 text-neutral-500" />
          <input type={shown ? "text" : "password"} value={value} onChange={(e) => { setValue(e.target.value); setStatus(""); }}
            placeholder="paste it here" spellCheck={false} autoComplete="off"
            className="min-w-0 flex-1 bg-transparent text-[13.5px] text-neutral-100 outline-none placeholder:text-neutral-600" />
          <button onClick={() => setShown((s) => !s)} className="text-neutral-500 hover:text-neutral-300">{shown ? <EyeOff size={14} /> : <Eye size={14} />}</button>
        </div>
        <button disabled={!value || status === "testing"} onClick={test}
          className="rounded-xl bg-white/10 px-3.5 py-2 text-[13px] text-neutral-100 hover:bg-white/15 disabled:opacity-40">
          {status === "testing" ? <Loader2 size={14} className="animate-spin" /> : "Test"}
        </button>
      </div>
      {status === "ok" && <div className="mt-2 flex items-center gap-1.5 text-[12.5px] text-emerald-300"><Check size={13} /> Works.</div>}
      {status.startsWith("fail") && <div className="mt-2 text-[12.5px] text-amber-300">That didn't work ({status.slice(5)}). Check the key, or skip it.</div>}
    </div>
  );
}

function Brain({ keys, setKeys, status, setStatus }) {
  return (
    <div>
      <Title kicker="Step 4" sub="I think with a cloud model when you ask me something. Both are free to start; keys are encrypted for your Windows account only.">My brain</Title>
      <div className="grid grid-cols-2 gap-3">
        <KeyBox provider="gemini" label="Google Gemini" hint="Free tier. Google may review free-tier questions."
          value={keys.GEMINI_API_KEY} setValue={(v) => setKeys((k) => ({ ...k, GEMINI_API_KEY: v }))}
          status={status.gemini} setStatus={(s) => setStatus((x) => ({ ...x, gemini: s }))} />
        <KeyBox provider="nvidia" label="NVIDIA" hint="Free. Answers when Gemini can't, or on its own."
          value={keys.NVIDIA_API_KEY} setValue={(v) => setKeys((k) => ({ ...k, NVIDIA_API_KEY: v }))}
          status={status.nvidia} setStatus={(s) => setStatus((x) => ({ ...x, nvidia: s }))} />
      </div>
      <div className="mt-4 text-[12.5px] text-neutral-500">No key? I still capture and search; answers just show what I found instead of explaining it. You can add one later.</div>
    </div>
  );
}

function Privacy({ agreed, setAgreed, webcam, setWebcam, hasCam }) {
  const items = [
    [Database, "Everything I capture stays on this PC", "Screenshots (faces blurred before they're saved), window text and what the mic hears."],
    [Lock, "Some things I never capture", "Password managers, banking sites, private/incognito windows. You can add your own."],
    [Sparkles, "The cloud sees only what you ask", "When you ask a question, the few lines it needs go to your chosen model."],
    [Eye, "I act only through Windows' accessibility", "Never in password boxes. Anything that can't be undone waits for your yes."],
  ];
  return (
    <div>
      <Title kicker="Step 5" sub="How I handle your PC. This is the deal; read it once.">Privacy</Title>
      <div className="grid grid-cols-2 gap-3">
        {items.map(([Icon, h, t], i) => (
          <motion.div key={h} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: i * 0.06 }} className={`${card} p-4`}>
            <Icon size={17} className="text-sky-300" />
            <div className="mt-2 text-[14px] text-neutral-100">{h}</div>
            <div className="mt-1 text-[12.5px] leading-relaxed text-neutral-400">{t}</div>
          </motion.div>
        ))}
      </div>
      {hasCam && (
        <label className={`${card} mt-3 flex cursor-pointer items-center gap-3 p-4`}>
          <input type="checkbox" checked={webcam} onChange={(e) => setWebcam(e.target.checked)} className="size-4 accent-sky-400" />
          <div><div className="text-[13.5px] text-neutral-100">Privacy curtain</div>
            <div className="text-[12.5px] text-neutral-500">The webcam notices when you leave and hides the screen. Nothing is recorded.</div></div>
        </label>
      )}
      <label className="mt-4 flex cursor-pointer items-center gap-2.5 text-[13.5px] text-neutral-300">
        <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="size-4 accent-sky-400" />
        I understand what Jimmy captures and where it goes.
      </label>
    </div>
  );
}

const INSTALL_STEPS = [["python", "Jimmy's own Python"], ["packages", "Its pieces"], ["settings", "Your choices"],
  ["verify", "A quick check"], ["model", "The speech model"], ["local_ai", "Local AI"]];

function Install({ progress, error, onRetry, localAi }) {
  const steps = INSTALL_STEPS.filter(([k]) => k !== "local_ai" || localAi);
  const current = steps.find(([k]) => progress[k]?.state === "running");
  return (
    <div>
      <Title kicker="Step 6" sub="Downloading and putting me together. Keep this window open; it's fine to do something else.">
        {error ? "Something went wrong" : progress.done ? "All set" : "Installing…"}</Title>
      <div className={`${card} px-5`}>
        {steps.map(([k, label], i) => {
          const p = progress[k] || {};
          const pct = p.total ? Math.min(1, (p.done || 0) / p.total) : null;
          return (
            <div key={k} className="border-b border-white/[0.05] py-3 last:border-0">
              <div className="flex items-center gap-3">
                <span className="flex size-6 items-center justify-center">
                  {p.state === "done" ? <Check size={16} className="text-emerald-300" /> :
                    p.state === "running" ? <Loader2 size={16} className="animate-spin text-sky-300" /> :
                      p.state === "failed" ? <X size={16} className="text-rose-300" /> : <Minus size={14} className="text-neutral-600" />}
                </span>
                <span className={`flex-1 text-[14px] ${p.state ? "text-neutral-100" : "text-neutral-500"}`}>{label}</span>
                {pct !== null && p.state === "running" && <span className="text-[12px] tabular-nums text-neutral-400">{gb(p.done || 0)} / {gb(p.total)}</span>}
              </div>
              {p.state === "running" && (
                <div className="ml-9 mt-2">
                  <div className="h-1 overflow-hidden rounded-full bg-white/[0.06]">
                    {pct !== null ? <motion.div className="h-full origin-left rounded-full bg-sky-400" animate={{ scaleX: pct }} />
                      : <div className="indet h-full w-1/4 rounded-full bg-gradient-to-r from-transparent via-sky-400 to-transparent" />}
                  </div>
                  {p.detail && <div className="mt-1.5 truncate text-[11.5px] text-neutral-500">{p.detail}</div>}
                </div>
              )}
              {i === 0 && null}
            </div>
          );
        })}
      </div>
      {error && (
        <div className="mt-4 flex items-center gap-3 rounded-xl bg-rose-500/10 p-3.5 text-[13px] text-rose-200 ring-1 ring-rose-400/20">
          <TriangleAlert size={16} className="shrink-0" /> <span className="flex-1">{error}</span>
          <button onClick={() => S.open("log")} className={quiet}>Show log</button>
          <button onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-neutral-100 hover:bg-white/15"><RotateCcw size={13} /> Retry</button>
        </div>
      )}
      {!error && current && <div className="mt-3 text-[12px] text-neutral-500">Now: {current[1]}</div>}
    </div>
  );
}

function Ready({ startWithWindows, setStartWithWindows }) {
  const tips = [["“Jimmy, what was I reading this morning?”", "recall"], ["“Jimmy, what's on my screen?”", "explain"],
    ["“Jimmy, search YouTube for…”", "do"], ["Ctrl + Alt + J", "pause or resume"]];
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <Logo size={150} mood="done" />
      <h1 className="mt-9 text-[30px] font-semibold tracking-tight text-neutral-50">I'm ready.</h1>
      <p className="mt-2 text-[15px] text-neutral-400">Say <span className="text-sky-300">“Jimmy”</span>, then ask. Or just look at me and talk.</p>
      <div className="mt-7 grid w-full max-w-[560px] grid-cols-2 gap-2.5 text-left">
        {tips.map(([t, k]) => (
          <div key={t} className={`${card} px-4 py-3`}>
            <div className="text-[13px] text-neutral-100">{t}</div>
            <div className="mt-0.5 text-[11.5px] uppercase tracking-wider text-neutral-500">{k}</div>
          </div>
        ))}
      </div>
      <label className="mt-6 flex cursor-pointer items-center gap-2.5 text-[13.5px] text-neutral-300">
        <input type="checkbox" checked={startWithWindows} onChange={(e) => setStartWithWindows(e.target.checked)} className="size-4 accent-sky-400" />
        Start Jimmy when I sign in to Windows
      </label>
    </div>
  );
}

// --- the frame ------------------------------------------------------------------------------
export default function Onboarding() {
  const [i, setI] = useState(() => Number(new URLSearchParams(location.hash.split("?")[1] || "").get("step") || 0));
  const [pc, setPc] = useState(null);
  const [data, setData] = useState("");
  const [profile, setProfile] = useState("balanced");
  const [retention, setRetention] = useState(30);
  const [cap, setCap] = useState(20);
  const [keys, setKeys] = useState({ GEMINI_API_KEY: "", NVIDIA_API_KEY: "" });
  const [keyStatus, setKeyStatus] = useState({ gemini: "", nvidia: "" });
  const [agreed, setAgreed] = useState(false);
  const [webcam, setWebcam] = useState(true);
  const [progress, setProgress] = useState({});
  const [error, setError] = useState("");
  const [startWithWindows, setStartWithWindows] = useState(true);
  const started = useRef(false);

  const recommended = useMemo(() => {
    if (!pc) return "balanced";
    if (!pc.gpu.nvidia || !pc.gpu.cudaOk) return pc.ram.gb >= 15.5 ? "balanced" : "lite";
    return pc.ram.gb >= 23.5 && pc.gpu.vramMb >= 5500 ? "full" : "balanced";
  }, [pc]);

  useEffect(() => {
    S.checks().then((r) => { setPc(r); setData(r.dataSuggestion); setProfile((p) => p); setWebcam(r.camera.devices.length > 0); });
    return S.onEvent((ev) => setProgress((p) => ({ ...p, [ev.step]: { ...p[ev.step], ...ev }, ...(ev.step === "done" ? { done: true } : {}) })));
  }, []);
  useEffect(() => { if (pc) setProfile(recommended); }, [pc, recommended]);

  const install = async () => {
    setError("");
    setProgress({});
    const provider = keys.GEMINI_API_KEY ? "gemini" : keys.NVIDIA_API_KEY ? "nvidia" : "";
    const gpu = !!pc?.gpu.nvidia && !!pc?.gpu.cudaOk && profile !== "lite";
    const r = await S.provision({ data, profile, gpu, localAi: profile === "full", keys,
                                  settings: { retention_days: retention, storage_cap_gb: cap, webcam, provider } });
    if (!r.ok) setError(r.error);
  };
  useEffect(() => {
    if (STEPS[i][0] === "install" && !started.current && !location.hash.includes("step=")) { started.current = true; install(); }
  }, [i]); // eslint-disable-line react-hooks/exhaustive-deps

  const key = STEPS[i][0];
  const canNext = key === "pc" ? !!pc && pc.arch.ok : key === "where" ? data.length > 3 : key === "privacy" ? agreed
    : key === "install" ? !!progress.done : true;
  const next = () => (key === "ready" ? S.finish({ startWithWindows }) : setI((x) => Math.min(x + 1, STEPS.length - 1)));

  return (
    <div className="flex h-screen items-center justify-center p-2">
      <div className="relative flex h-full w-full overflow-hidden rounded-[22px] bg-neutral-950 ring-1 ring-white/10 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8)]">
        <div className="pointer-events-none absolute -left-40 -top-40 size-[420px] rounded-full bg-sky-500/10 blur-3xl" />
        {/* the rail */}
        <aside className="relative z-10 flex w-[220px] shrink-0 flex-col border-r border-white/[0.06] bg-black/30 px-5 py-6" style={{ WebkitAppRegion: "drag" }}>
          <div className="flex items-center gap-2.5"><Logo size={44} mood={key === "install" && !progress.done ? "working" : "idle"} glow={false} />
            <span className="text-[16px] font-semibold tracking-tight text-neutral-100">Jimmy</span></div>
          <nav className="mt-10 space-y-1">
            {STEPS.map(([k, label], n) => (
              <div key={k} className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-[13.5px] ${n === i ? "text-neutral-50" : n < i ? "text-neutral-400" : "text-neutral-600"}`}>
                <span className={`flex size-5 items-center justify-center rounded-full text-[11px] ${n < i ? "bg-sky-500/20 text-sky-300" : n === i ? "bg-sky-500 text-white" : "bg-white/[0.06]"}`}>
                  {n < i ? <Check size={11} /> : n + 1}</span>
                {label}
                {n === i && <motion.span layoutId="here" className="ml-auto" transition={spring}><ChevronRight size={14} className="text-sky-300" /></motion.span>}
              </div>
            ))}
          </nav>
          <div className="mt-auto flex items-center gap-1.5 text-[11.5px] text-neutral-600"><ShieldCheck size={13} /> No admin rights needed</div>
        </aside>
        {/* the page */}
        <main className="relative z-10 flex min-w-0 flex-1 flex-col">
          <div className="flex h-11 items-center justify-end gap-1 px-3" style={{ WebkitAppRegion: "drag" }}>
            <button onClick={() => S.minimize()} style={{ WebkitAppRegion: "no-drag" }} className="rounded-md p-1.5 text-neutral-500 hover:bg-white/10 hover:text-neutral-200"><Minus size={14} /></button>
            <button onClick={() => S.quit()} style={{ WebkitAppRegion: "no-drag" }} className="rounded-md p-1.5 text-neutral-500 hover:bg-rose-500/80 hover:text-white"><X size={14} /></button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-12 pb-4 [scrollbar-width:thin]">
            <AnimatePresence mode="wait">
              <motion.div key={key} className="h-full" initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }} transition={spring}>
                {key === "hello" && <Hello />}
                {key === "pc" && <PC pc={pc} />}
                {key === "where" && <Where pc={pc} data={data} setData={setData} profile={profile} />}
                {key === "size" && <Size pc={pc} profile={profile} setProfile={setProfile} retention={retention} setRetention={setRetention}
                  cap={cap} setCap={setCap} recommended={recommended} />}
                {key === "brain" && <Brain keys={keys} setKeys={setKeys} status={keyStatus} setStatus={setKeyStatus} />}
                {key === "privacy" && <Privacy agreed={agreed} setAgreed={setAgreed} webcam={webcam} setWebcam={setWebcam} hasCam={!!pc?.camera.devices.length} />}
                {key === "install" && <Install progress={progress} error={error} localAi={profile === "full"}
                  onRetry={() => { started.current = true; install(); }} />}
                {key === "ready" && <Ready startWithWindows={startWithWindows} setStartWithWindows={setStartWithWindows} />}
              </motion.div>
            </AnimatePresence>
          </div>
          <footer className="flex items-center justify-between border-t border-white/[0.06] px-12 py-4">
            <button onClick={() => setI((x) => Math.max(0, x - 1))} className={`${quiet} ${i === 0 || key === "install" || key === "ready" ? "invisible" : ""}`}>
              <ArrowLeft size={15} /> Back</button>
            <div className="flex items-center gap-1.5">{STEPS.map((s, n) => <span key={s[0]} className={`h-1 rounded-full transition-all ${n === i ? "w-5 bg-sky-400" : "w-1.5 bg-white/15"}`} />)}</div>
            <motion.button whileTap={{ scale: 0.97 }} onClick={next} disabled={!canNext} className={primary}>
              {key === "hello" ? "Let's set me up" : key === "privacy" ? "Install" : key === "ready" ? "Start Jimmy" : "Continue"}
              {key === "ready" ? <Sparkles size={15} /> : <ArrowRight size={15} />}
            </motion.button>
          </footer>
        </main>
      </div>
    </div>
  );
}
