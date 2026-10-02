import { Component, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  BarChart3, Bell, CalendarClock, Check, Clock, ExternalLink, Eye, EyeOff, Globe, History, Lightbulb, MessageCircle,
  MonitorSmartphone, MoveRight, Pause, Play, Power, RotateCcw, ScanFace, ShieldCheck, Target, Timer, Trash2, X,
} from "lucide-react";
import Answer from "./Answer.jsx";

const CARD_MS = 12_000;      // a card fades on its own; × is the only real dismissal
const ANSWER_MS = 30_000;    // D35: an answer fades after 30 s unless hovered (was a minute: clutter)
const FLASH_MS = 2600;       // D31: how long the pill shows "Paused", "Copied", …
const MAX_CARDS = 2;          // D35: fewer things on screen at once
const bridge = window.jimmy; // from preload.cjs: events in, actions out

// Everything except the pill, cards and answer panels lets clicks through.
const hover = {
  onMouseEnter: () => bridge?.pointerOverUi(true),
  onMouseLeave: () => bridge?.pointerOverUi(false),
};

const surface =
  "bg-neutral-950/90 ring-1 ring-white/10 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.6)]";

// What typing offers before you've typed anything (D31). Filtered as you type.
const SUGGEST = [
  { label: "How was my day?", icon: BarChart3 },
  { label: "What's on my screen?", icon: MonitorSmartphone },
  { label: "What was I doing an hour ago?", icon: History },
  { label: "Focus on…", fill: "focus on ", icon: Target },
  { label: "Pause for 30 minutes", icon: Pause },
  { label: "Open insights", icon: BarChart3 },
];
const FLASH_ICON = {
  close_ui: X, copy_screen: Check, volume: MessageCircle, presence: Eye, enrol: ScanFace, unenrol: ScanFace,
  pause: Pause, resume: Play, focus: Target, unfocus: Target, open: ExternalLink, show: X, nav: MoveRight,
  remind: Bell, reminders: Bell, unremind: Bell, curtain: EyeOff, uncurtain: Eye, open_url: Globe,
  timer: Timer, timers: Timer, untimer: Timer, forget: Trash2, eyes: Eye, calibrate: Eye, notcall: Eye,
};

// D32: every kind of card, and how long it stays if you don't touch it.
const KINDS = {
  RECALL: { icon: History, label: "Recall", tone: "bg-white/[0.06] text-neutral-300" },
  FOCUS: { icon: Target, label: "Focus", tone: "bg-violet-400/15 text-violet-200" },
  RESUME: { icon: RotateCcw, label: "Welcome back", tone: "bg-sky-400/15 text-sky-200" },
  REMIND: { icon: Bell, label: "Reminder", tone: "bg-amber-400/15 text-amber-200", ms: 60_000 },
  DEADLINE: { icon: CalendarClock, label: "Deadline", tone: "bg-rose-400/15 text-rose-200", ms: 30_000 },
  SUGGEST: { icon: Lightbulb, label: "Suggestion", tone: "bg-violet-400/15 text-violet-200", ms: 20_000 },
  RECAP: { icon: BarChart3, label: "Your day", tone: "bg-emerald-400/15 text-emerald-200", ms: 20_000 },
};

// A render error in one panel must never blank the whole overlay (D26: one did,
// taking the pill with it). The panel is dropped, the error logged to the
// `ambient run` terminal, and everything else keeps working.
class Guard extends Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(err) { console.error(`panel failed: ${err?.message || err}`); this.props.onError?.(); }
  componentDidUpdate(prev) { if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false }); }
  render() { return this.state.failed ? null : this.props.children; }
}

function span(ms) {
  const m = Math.max(0, Math.round(ms / 60_000));
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
}

function PillButton({ onClick, label, children, danger }) {
  return (
    <motion.button
      initial={{ opacity: 0, width: 0 }} animate={{ opacity: 1, width: "auto" }} exit={{ opacity: 0, width: 0 }}
      whileTap={{ scale: 0.94 }}
      onClick={onClick} aria-label={label} title={label}
      className={`flex items-center gap-1 overflow-hidden whitespace-nowrap rounded-full px-2 py-0.5 transition-colors
        ${danger ? "bg-rose-500/80 text-white" : "bg-white/10 text-neutral-100 hover:bg-white/20"}`}
    >
      {children}
    </motion.button>
  );
}

function Equalizer() {
  return (
    <span className="eq flex h-3 w-[14px] items-end gap-[2px]" aria-hidden>
      {[0, 1, 2, 3].map((i) => <span key={i} className="block h-full w-[2px] rounded-full bg-sky-400" />)}
    </span>
  );
}

// D39: timers (and reminders due within the hour) count down on the pill, so they're
// in view whatever window you're in. Gone a few seconds after they ring.
function Timers({ timers }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!timers.length) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [timers.length]);
  return timers.filter((t) => t.due - Date.now() > -5000).map((t) => {
    const left = Math.max(0, Math.round((t.due - Date.now()) / 1000));
    const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = String(left % 60).padStart(2, "0");
    const clock = h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
    const label = t.text.endsWith("timer") ? t.text.split(", ").slice(0, -1).join(", ") : t.text;
    return (
      <span key={t.id} title={t.text}
        className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] tabular-nums
          ${left <= 10 ? "bg-rose-400/20 text-rose-100" : "bg-amber-400/15 text-amber-100"}`}>
        <Timer size={11} className="shrink-0" /> {clock}
        {label && <span className="max-w-[150px] truncate text-amber-200/70">{label}</span>}
      </span>
    );
  });
}

function Pill({ state, mood, prompt, typing, setTyping, flash, recent, onAsk, answerOpen, watched, curtain, contact }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(-1);
  const [armed, setArmed] = useState(false);     // Quit asks twice
  const input = useRef(null);
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => { if (typing) setTimeout(() => input.current?.focus(), 30); }, [typing]);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  useEffect(() => { setSel(-1); }, [q]);

  const paused = state.paused;
  const startTyping = (prefill = "") => { setQ(prefill); setTyping(true); bridge?.focusAsk(); };
  const done = () => { setTyping(false); setQ(""); bridge?.releaseFocus(); bridge?.pointerOverUi(false); };
  const send = (text) => { if (text.trim()) onAsk(text.trim()); done(); };
  const needle = q.toLowerCase().trim();
  const items = [...recent.map((r) => ({ label: r, icon: Clock, recent: true })), ...SUGGEST]
    .filter((s, i, all) => all.findIndex((x) => x.label.toLowerCase() === s.label.toLowerCase()) === i)
    .filter((s) => !needle || (s.label.toLowerCase().includes(needle) && s.label.toLowerCase() !== needle))
    .slice(0, 6);
  const choose = (s) => {
    if (s.fill) { setQ(s.fill); input.current?.focus(); } else send(s.label);
  };
  const onKey = (e) => {
    if (e.key === "Escape") done();
    else if (e.key === "ArrowDown" && items.length) { e.preventDefault(); setSel((s) => (s + 1) % items.length); }
    else if (e.key === "ArrowUp" && items.length) { e.preventDefault(); setSel((s) => (s <= 0 ? items.length - 1 : s - 1)); }
    else if (e.key === "Tab" && items.length) { e.preventDefault(); const s = items[Math.max(sel, 0)]; setQ(s.fill || s.label); }
  };
  const submit = (e) => {
    e.preventDefault();
    if (sel >= 0 && items[sel]) choose(items[sel]);
    else send(q);
  };

  const status = curtain ? <span className="text-neutral-300">Curtain down</span>
    : paused ? <span className="text-amber-300/90">Paused · {span(state.paused_until - Date.now())} left</span>
    : mood === "listening" ? <span className="text-sky-200">{prompt || "Listening… ask away"}</span>
    : mood === "thinking" ? <span className="shimmer">Thinking…</span>
    : mood === "answering" ? <span className="shimmer">Answering…</span>
    : <span className="text-neutral-400">Listening</span>;
  const dot = curtain ? "bg-neutral-500" : paused ? "bg-amber-400" : mood ? "bg-sky-400" : "bg-emerald-400";
  // D35: idle, the pill is just a dot, so it doesn't sit on other apps' tab bars and
  // title bars. Anything happening (or your pointer) brings the whole pill back.
  const timers = (state.timers || []).filter((t) => t.due - Date.now() > -5000);
  const compact = !open && !typing && !flash && !mood && !watched && !answerOpen && !timers.length;
  const FlashIcon = flash ? FLASH_ICON[flash.icon] || Check : null;

  return (
    <div className="pointer-events-none absolute inset-x-0 top-2 flex flex-col items-center gap-2">
      <motion.div
        layout
        onMouseEnter={() => { hover.onMouseEnter(); setOpen(true); }}
        onMouseLeave={() => { if (!typing) hover.onMouseLeave(); setOpen(false); setArmed(false); }}
        transition={{ type: "spring", stiffness: 500, damping: 38 }}
        className={`pointer-events-auto flex items-center gap-2 rounded-full text-[12px] ${surface}
          ${compact ? "h-4 px-1.5 opacity-70" : "h-8 px-3"} ${mood === "listening" ? "ring-sky-400/40" : ""}`}
      >
        <span className="flex h-3 w-[14px] shrink-0 items-center justify-center">
          {mood === "listening" ? <Equalizer /> : contact && !curtain && !paused ? (
            // D39: Jimmy sees you looking at the screen: just ask, no name needed
            <Eye size={11} className="text-sky-300" aria-label="I see you looking: just ask" />
          ) : (
            <span className="relative flex size-2">
              {!paused && mood && <span className="absolute inline-flex size-full animate-ping rounded-full bg-sky-400/60" />}
              <span className={`relative inline-flex size-2 rounded-full ${dot}`} />
            </span>
          )}
        </span>
        {!compact && <span className="font-medium text-neutral-100">Jimmy</span>}
        {compact ? null : typing ? (
          <form onSubmit={submit} className="flex items-center">
            <input
              ref={input} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} onBlur={done}
              placeholder={answerOpen ? "Follow up…" : 'Ask anything, or "focus on …", "pause 30 min"'}
              className="w-[340px] bg-transparent text-[12.5px] text-neutral-100 outline-none placeholder:text-neutral-500"
            />
          </form>
        ) : (
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={flash ? `f${flash.id}` : `s${paused}${mood}${curtain}`}
              initial={{ opacity: 0, y: 5, filter: "blur(2px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.16 }}
              onClick={() => !flash && !paused && startTyping()}
              className={`flex items-center gap-1.5 whitespace-nowrap ${flash || paused ? "" : "cursor-text"}`}
            >
              {flash ? <><FlashIcon size={12} className="text-emerald-300" /><span className="text-neutral-50">{flash.text}</span></> : status}
            </motion.span>
          </AnimatePresence>
        )}
        {watched && !typing && !compact && (
          <span className="flex items-center gap-1 rounded-full bg-amber-400/15 px-2 py-0.5 text-[11.5px] text-amber-200">
            <Eye size={11} /> Someone's looking · panels hidden
          </span>
        )}
        {!typing && <Timers timers={timers} />}
        {state.focus && !typing && !flash && !curtain && !watched && !compact && (
          <span title={`Focus: ${state.focus.text}`}
            className="flex max-w-[220px] items-center gap-1 rounded-full bg-violet-400/10 px-2 py-0.5 text-[11.5px] text-violet-200">
            <Target size={11} className="shrink-0" />
            <span className="truncate">{state.focus.text}</span>
            <span className="shrink-0 text-violet-300/60">· {span(Date.now() - state.focus.ts)}</span>
          </span>
        )}
        <AnimatePresence initial={false}>
          {open && !typing && (
            <motion.div key="menu" className="ml-1 flex items-center gap-1">
              <PillButton label="Ask by typing (Ctrl+Alt+Space)" onClick={() => startTyping()}>
                <MessageCircle size={12} /> Ask
              </PillButton>
              <PillButton label="Timeline (Ctrl+Alt+T)" onClick={() => bridge?.openTimeline("timeline")}>
                <History size={12} /> Timeline
              </PillButton>
              <PillButton label="Insights (Ctrl+Alt+I)" onClick={() => bridge?.openTimeline("insights")}>
                <BarChart3 size={12} /> Insights
              </PillButton>
              {state.focus ? (
                <PillButton label="Clear your focus" onClick={() => bridge?.api("focus", { text: "" })}>
                  <Target size={12} /> Unfocus
                </PillButton>
              ) : (
                <PillButton label="Say what you mean to be doing" onClick={() => startTyping("focus on ")}>
                  <Target size={12} /> Focus
                </PillButton>
              )}
              <PillButton label={state.owner ? "Forget my face" : "Remember my face, so the curtain knows you"}
                onClick={() => bridge?.api("ask", { q: state.owner ? "forget my face" : "remember my face" })}>
                <ScanFace size={12} /> {state.owner ? "Forget me" : "Remember me"}
              </PillButton>
              <PillButton label={curtain ? "Lift the curtain (Ctrl+Alt+L)" : "Privacy curtain (Ctrl+Alt+L)"}
                onClick={() => bridge?.api("curtain", { on: !curtain })}>
                {curtain ? <Eye size={12} /> : <EyeOff size={12} />} {curtain ? "Lift" : "Curtain"}
              </PillButton>
              <PillButton label={paused ? "Resume" : "Pause for 2 hours (Ctrl+Alt+J)"}
                onClick={() => bridge?.api(paused ? "resume" : "pause", { minutes: 120 })}>
                {paused ? <Play size={12} /> : <Pause size={12} />} {paused ? "Resume" : "Pause 2h"}
              </PillButton>
              <PillButton label={armed ? "Click again to quit" : "Quit Jimmy"} danger={armed}
                onClick={() => (armed ? bridge?.api("quit") : setArmed(true))}>
                <Power size={12} /> {armed ? "Sure?" : "Quit"}
              </PillButton>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
      <AnimatePresence>
        {typing && items.length > 0 && (
          <motion.div
            key="suggest"
            initial={{ opacity: 0, y: -6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -6 }}
            transition={{ type: "spring", stiffness: 520, damping: 36 }}
            className={`pointer-events-auto w-[440px] overflow-hidden rounded-xl p-1 ${surface}`}
          >
            {items.map((s, i) => {
              const Icon = s.icon;
              return (
                <button
                  key={s.label} type="button"
                  onMouseDown={(e) => { e.preventDefault(); choose(s); }}    // before the input blurs
                  onMouseEnter={() => setSel(i)}
                  className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition-colors
                    ${sel === i ? "bg-white/10 text-neutral-50" : "text-neutral-300"}`}
                >
                  <Icon size={13} className="shrink-0 text-neutral-500" />
                  <span className="truncate">{s.label}</span>
                  {s.recent && <span className="ml-auto text-[10.5px] text-neutral-600">recent</span>}
                </button>
              );
            })}
            <div className="mt-1 flex gap-3 border-t border-white/[0.06] px-2.5 pb-1 pt-1.5 text-[10.5px] text-neutral-500">
              <span>↑↓ choose</span><span>Tab fill</span><span>Enter ask</span><span>Esc close</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function CardAction({ onClick, children }) {
  return (
    <motion.button whileTap={{ scale: 0.95 }} onClick={onClick}
      className="flex items-center gap-1 rounded-md bg-white/[0.07] px-2 py-1 text-[11.5px] text-neutral-200 transition-colors hover:bg-white/15">
      {children}
    </motion.button>
  );
}

function Card({ card, onGone, onDismiss, away }) {
  const kind = KINDS[card.kind] || KINDS.RECALL;
  const total = kind.ms || CARD_MS;
  const [hover, setHover] = useState(false);
  const held = hover || away;                  // hovering, or you're not here: the card waits
  const left = useRef(total);
  useEffect(() => {
    if (held) return;
    const started = Date.now();
    const t = setTimeout(onGone, left.current);
    return () => { clearTimeout(t); left.current -= Date.now() - started; };
  }, [held]);

  const Icon = kind.icon;
  const when = new Date(card.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const used = (fn) => () => { bridge?.api("card_used", { id: card.id }); fn?.(); onGone(); };
  const acts = [];
  if (card.at && card.kind !== "FOCUS") {
    acts.push(<CardAction key="at" onClick={used(() => bridge?.openTimeline("timeline", { ts: card.at }))}>
      <ExternalLink size={11} /> {card.kind === "DEADLINE" ? "Where I saw it" : "Show me then"}</CardAction>);
  }
  if (card.url) {
    acts.push(<CardAction key="url" onClick={used(() => bridge?.openUrl(card.url))}><Globe size={11} /> Open page</CardAction>);
  }
  if (card.kind === "SUGGEST") {
    acts.push(<CardAction key="yes" onClick={used(() => bridge?.api("focus", { text: card.focus }))}><Check size={11} /> Yes, focus</CardAction>);
    acts.push(<CardAction key="no" onClick={onDismiss}>Not now</CardAction>);
  }
  if (card.kind === "RECAP") {
    acts.push(<CardAction key="ins" onClick={used(() => bridge?.openTimeline("insights"))}><BarChart3 size={11} /> Open insights</CardAction>);
  }
  if (card.kind === "FOCUS") {
    acts.push(<CardAction key="done" onClick={used(() => bridge?.api("focus", { text: "" }))}><Target size={11} /> I'm done with that</CardAction>);
  }
  if (card.kind === "REMIND") {
    acts.push(<CardAction key="ok" onClick={used()}><Check size={11} /> Done</CardAction>);
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 28, scale: 0.98 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 28, transition: { duration: 0.18 } }}
      transition={{ type: "spring", stiffness: 420, damping: 34 }}
      onMouseEnter={() => { bridge?.pointerOverUi(true); setHover(true); }}
      onMouseLeave={() => { bridge?.pointerOverUi(false); setHover(false); }}
      className={`group pointer-events-auto relative w-80 overflow-hidden rounded-2xl p-3.5 ${surface}`}
    >
      <div className="flex items-center gap-2 text-[11px] text-neutral-400">
        <span className={`flex size-5 items-center justify-center rounded-md ${kind.tone}`}>
          <Icon size={12} />
        </span>
        <span className="uppercase tracking-wider">{kind.label}</span>
        <span className="ml-auto text-neutral-500">{when}</span>
        <button
          onClick={onDismiss}
          aria-label="Dismiss" title="Not now (quiets cards for a while)"
          className="flex size-5 items-center justify-center rounded-md text-neutral-500 opacity-0 transition group-hover:opacity-100 hover:bg-white/10 hover:text-neutral-200"
        >
          <X size={12} />
        </button>
      </div>
      <p className="mt-2 text-[15px] font-medium leading-snug text-neutral-50">{card.line}</p>
      {card.why && <p className="mt-1 line-clamp-1 text-[11.5px] text-neutral-500" title={card.why}>{card.why}</p>}
      {acts.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5 opacity-70 transition group-hover:opacity-100">{acts}</div>
      )}
      {/* Time left: frozen while hovered, then runs out from where it stopped. */}
      <motion.div
        key={held ? "held" : `run-${left.current}`}
        className="absolute bottom-0 left-0 h-[2px] bg-white/25"
        initial={{ width: `${(100 * left.current) / total}%` }}
        animate={{ width: held ? `${(100 * left.current) / total}%` : "0%" }}
        transition={{ duration: held ? 0 : left.current / 1000, ease: "linear" }}
      />
    </motion.div>
  );
}

// D37: "remember my face". A live, mirrored preview with an oval to line up in,
// the face box green when the frame is good, the instruction in words (also
// spoken), three steps, and what is kept. Screen capture is off meanwhile.
const ENROL_STEPS = ["Look straight", "One side", "Other side"];
const EYE_STEPS = ["Camera", "Screen", "Keyboard", "Speak", "Quiet"];   // D40: eye calibration

function EnrolPanel({ e }) {
  const good = e.done ? !e.failed : e.ok;
  const eyes = e.kind === "eyes";                // D40: the same panel calibrates your eyes
  return (
    <div className="pointer-events-none absolute inset-x-0 top-14 z-[120] flex justify-center">
      <motion.div
        {...hover}
        initial={{ opacity: 0, y: -10, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: -10, scale: 0.97 }} transition={{ type: "spring", stiffness: 420, damping: 34 }}
        className={`pointer-events-auto w-[380px] rounded-2xl p-4 ${surface}`}
      >
        <div className="flex items-center gap-2 text-[13px] font-medium text-neutral-100">
          {eyes ? <Eye size={15} className="text-sky-300" /> : <ScanFace size={15} className="text-sky-300" />}
          {eyes ? "Eye calibration" : "Remember my face"}
          {!e.done && (
            <button onClick={() => bridge?.api("ask", { q: "cancel" })} aria-label="Cancel"
              className="ml-auto rounded-md p-1 text-neutral-500 hover:bg-white/10 hover:text-neutral-200"><X size={14} /></button>
          )}
        </div>
        {!e.done ? (
          <>
            <div className="relative mt-3 aspect-[4/3] overflow-hidden rounded-xl bg-black">
              {e.preview && <img src={e.preview} className="h-full w-full object-cover" draggable={false} />}
              <div className="absolute inset-0 grid place-items-center">
                <motion.div animate={{ borderColor: good ? "rgb(52 211 153)" : "rgba(255,255,255,0.45)" }}
                  className="h-[72%] w-[46%] rounded-[50%] border-2 shadow-[0_0_0_999px_rgba(0,0,0,0.35)]" />
              </div>
              {e.box && (
                <motion.div className={`absolute rounded-lg border-2 ${good ? "border-emerald-400" : "border-amber-300"}`}
                  animate={{ left: `${e.box[0] * 100}%`, top: `${e.box[1] * 100}%`, width: `${e.box[2] * 100}%`, height: `${e.box[3] * 100}%` }}
                  transition={{ type: "spring", stiffness: 600, damping: 40 }} />
              )}
              <div className="absolute inset-x-0 bottom-0 h-1 bg-white/10">
                <motion.div className="h-full bg-emerald-400" animate={{ width: `${Math.round((e.progress || 0) * 100)}%` }} />
              </div>
            </div>
            <div className="mt-3 flex gap-1.5">
              {(eyes ? EYE_STEPS : ENROL_STEPS).map((label, i) => (
                <span key={label} className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]
                  ${i < e.step ? "bg-emerald-400/15 text-emerald-200" : i === e.step ? "bg-white/10 text-neutral-100" : "text-neutral-500"}`}>
                  {i < e.step ? <Check size={10} /> : <span className="tabular-nums">{i + 1}</span>} {label}
                </span>
              ))}
            </div>
            <AnimatePresence mode="wait" initial={false}>
              <motion.p key={e.say} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.15 }}
                className={`mt-2.5 text-[15px] font-medium ${good ? "text-emerald-200" : "text-neutral-50"}`}>{e.say}</motion.p>
            </AnimatePresence>
          </>
        ) : (
          <motion.div initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} className="py-6 text-center">
            <div className={`mx-auto grid size-12 place-items-center rounded-full ${e.failed ? "bg-amber-400/15 text-amber-200" : "bg-emerald-400/15 text-emerald-200"}`}>
              {e.failed ? <X size={22} /> : <Check size={22} />}
            </div>
            <p className="mt-3 text-[14px] text-neutral-100">{e.say}</p>
            {e.failed && (
              <button onClick={() => bridge?.api("ask", { q: eyes ? "eye calibration" : "remember my face" })}
                className="mt-3 rounded-lg bg-white/10 px-3 py-1.5 text-[13px] text-neutral-100 hover:bg-white/15">Try again</button>
            )}
          </motion.div>
        )}
        <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-snug text-neutral-500">
          <ShieldCheck size={12} className="mt-px shrink-0" />
          {eyes ? <>Numbers only: where you look and how much your lips move, so you can ask without
            &ldquo;Jimmy&rdquo;. No photo is kept. Say &ldquo;eye calibration&rdquo; to redo it.</>
            : <>Only your face, as an encrypted template on this PC, used only for the privacy curtain. No photo is kept.
            Say &ldquo;forget my face&rdquo; any time.</>}
        </p>
      </motion.div>
    </div>
  );
}

// D34: the privacy curtain. Opaque, over everything Jimmy can cover (the main
// process grows the window to the whole display while it's down).
function Curtain({ why }) {
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, transition: { duration: 0.35 } }}
      transition={{ duration: 0.12 }}
      className="pointer-events-none absolute inset-0 z-[100] flex items-center justify-center bg-neutral-950"
    >
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(56,189,248,0.06),transparent_60%)]" />
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
        className="relative text-center">
        <EyeOff size={30} className="mx-auto text-neutral-500" />
        <div className="mt-3 text-[16px] font-medium text-neutral-200">Privacy curtain</div>
        <div className="mt-1 text-[13px] text-neutral-500">{why}</div>
      </motion.div>
    </motion.div>
  );
}

export default function App() {
  const [state, setState] = useState({ paused: false, paused_until: 0, focus: null });
  const [cards, setCards] = useState([]);
  const [answer, setAnswer] = useState(null);
  const [mood, setMood] = useState(null);      // "listening" | "thinking" | "answering" | null
  const [prompt, setPrompt] = useState(null);  // what the pill says while listening (D28)
  const [openIndex, setOpenIndex] = useState(null);
  const [typing, setTyping] = useState(false);
  const [flash, setFlash] = useState(null);    // D31: a moment of feedback in the pill
  const [recent, setRecent] = useState([]);    // this session's typed questions; never saved
  const [presence, setPresence] = useState({ state: "off", curtain: false });   // D34
  const [enrol, setEnrol] = useState(null);                                    // D37
  const enrolTimer = useRef(null);
  const hideTimer = useRef(null);
  const flashTimer = useRef(null);
  const flashN = useRef(0);
  const prev = useRef(null);
  const waiting = useRef(0);                   // a typed question sent, no answer_start yet
  const live = useRef({});                     // latest state, for event handlers set up once
  live.current = { answer, openIndex, cards };

  // D33: "next", "scroll down", "close" by voice, on what's showing here.
  const onUi = (ev) => {
    const { answer: a, openIndex: oi, cards: cs } = live.current;
    const n = a?.evidence?.length || 0;
    if (ev.action === "scroll") {
      // D35: in the first real session "scroll down" did nothing: the panel had nothing
      // to scroll. Jimmy's panel if it can move; otherwise the window you're on.
      const down = ev.dir === "down";
      const room = [...document.querySelectorAll("[data-scroll]")].filter((el) =>
        down ? el.scrollTop + el.clientHeight < el.scrollHeight - 4 : el.scrollTop > 4);
      if (oi == null && room.length) {
        room.forEach((el) => el.scrollBy({ top: (down ? 1 : -1) * el.clientHeight * 0.7, behavior: "smooth" }));
      } else bridge?.api("scroll_window", { dir: ev.dir });
    } else if (ev.action === "step" && n) setOpenIndex(oi == null ? 0 : Math.max(0, Math.min(n - 1, oi + ev.by)));
    else if (ev.action === "edge" && n) setOpenIndex(ev.to === "first" ? 0 : n - 1);
    else if (ev.action === "zoom" && n) setOpenIndex(oi ?? 0);
    else if (ev.action === "unzoom") setOpenIndex(null);
    else if (ev.action === "close") {
      if (oi != null) setOpenIndex(null);
      else if (a) closeAnswer();
      else if (cs.length) drop(cs[0].id);
    }
  };

  const say = (text, icon) => {
    clearTimeout(flashTimer.current);
    setFlash({ id: ++flashN.current, text, icon });
    flashTimer.current = setTimeout(() => setFlash(null), FLASH_MS);
  };
  const unthink = () => setMood((m) => (m === "thinking" ? null : m));

  const closeAnswer = () => {
    clearTimeout(hideTimer.current);
    setAnswer(null);
    bridge?.pointerOverUi(false);
    bridge?.api("stop-voice");
  };

  const ask = (q) => {
    setMood("thinking");                       // react now; the answer follows
    waiting.current = Date.now();
    setTimeout(() => { if (waiting.current && Date.now() - waiting.current >= 4000) { waiting.current = 0; unthink(); } }, 4000);
    setRecent((r) => [q, ...r.filter((x) => x.toLowerCase() !== q.toLowerCase())].slice(0, 3));
    bridge?.api("ask", { q });
  };

  useEffect(() => {
    return bridge?.onEvent((ev) => {
      if (ev.type === "state") {
        const p = prev.current;
        if (p && p.paused !== ev.paused) say(ev.paused ? `Paused for ${span(ev.paused_until - Date.now())}` : "Capturing again", ev.paused ? "pause" : "resume");
        else if (p && (p.focus?.text || null) !== (ev.focus?.text || null)) say(ev.focus ? `Focus: ${ev.focus.text}` : "Focus cleared", "focus");
        prev.current = ev;
        setState(ev);
      }
      if (ev.type === "toast") { waiting.current = 0; unthink(); say(ev.text, ev.icon); }
      if (ev.type === "ui") onUi(ev);
      if (ev.type === "copy") say(ev.label || "Copied", "copy");
      if (ev.type === "close_all") { setOpenIndex(null); closeAnswer(); setCards([]); }   // "Jimmy, close your UI"
      if (ev.type === "presence") setPresence(ev);
      if (ev.type === "thinking") { setMood("thinking"); setPrompt(null); }   // D38: react at once
      if (ev.type === "enrol") {
        clearTimeout(enrolTimer.current);
        setEnrol((cur) => ({ ...cur, kind: undefined, ...ev }));   // eye calibration events carry kind "eyes"
        if (ev.done) enrolTimer.current = setTimeout(() => { setEnrol(null); bridge?.pointerOverUi(false); }, ev.failed ? 8000 : 3500);
      }
      if (ev.type === "state" && "curtain" in ev) setPresence((p) => ({ ...p, curtain: ev.curtain, state: ev.presence }));
      if (ev.type === "answer_close") closeAnswer();
      if (ev.type === "card") setCards((cs) => [ev, ...cs.filter((c) => c.id !== ev.id)].slice(0, MAX_CARDS));
      if (ev.type === "focus-ask") setTyping(true);
      if (ev.type === "listening") {
        setMood("listening");
        setPrompt(ev.prompt || null);
        setTimeout(() => setMood((m) => (m === "listening" ? null : m)), ev.ms || (ev.prompt ? 20000 : 9000));
      }
      if (ev.type === "open_evidence") { waiting.current = 0; unthink(); setOpenIndex(ev.index); }
      if (ev.type === "close_evidence") setOpenIndex(null);
      if (ev.type === "answer_start") {
        waiting.current = 0;
        clearTimeout(hideTimer.current);
        setMood("thinking");
        setOpenIndex(null);
        setAnswer({ id: ev.id, question: ev.question, source: ev.source, mode: ev.mode || "recall",
                    history: ev.history || [], status: "searching", evidence: [], text: "" });
      }
      const same = (fn) => setAnswer((a) => (a && a.id === ev.id ? fn(a) : a));
      if (ev.type === "answer_evidence") {
        setMood((m) => (m === "thinking" ? "answering" : m));
        same((a) => ({ ...a, status: "answering", mode: ev.mode || a.mode, evidence: ev.evidence,
                       terms: ev.terms, days: ev.days, window: ev.window, stats: ev.stats,
                       event: ev.event ?? a.event }));
      }
      if (ev.type === "answer_delta") same((a) => ({ ...a, status: "answering", text: a.text + ev.text }));
      if (ev.type === "answer_end" || ev.type === "answer_error") {
        if (!ev.awaiting) setMood(null);   // a question back keeps the pill listening
        same((a) => ({ ...a, status: ev.type === "answer_end" ? "done" : "error", error: ev.error }));
        clearTimeout(hideTimer.current);
        hideTimer.current = setTimeout(() => setAnswer(null), ANSWER_MS);
      }
    });
  }, []);

  function drop(id) { setCards((cs) => cs.filter((c) => c.id !== id)); }
  const watched = presence.state === "watched" && !presence.curtain;   // someone else is looking
  const away = presence.curtain || presence.state === "away";
  const curtainWhy = presence.manual ? "Ctrl+Alt+L, or say \u201cJimmy, lift the curtain\u201d"
    : presence.state === "watched" ? "Someone else is looking at a private page"
    : presence.state === "stranger" ? "Someone else is at the screen"
    : "Look at the screen to lift it";

  return (
    <>
      <AnimatePresence>{presence.curtain && <Curtain key="curtain" why={curtainWhy} />}</AnimatePresence>
      <AnimatePresence>{enrol && !presence.curtain && <EnrolPanel key="enrol" e={enrol} />}</AnimatePresence>
      <div className="relative z-[110]">
        <Pill state={state} mood={mood} prompt={prompt} typing={typing} setTyping={setTyping}
          flash={flash} recent={recent} onAsk={ask} answerOpen={!!answer} watched={watched} curtain={presence.curtain}
          contact={!!presence.contact} />
      </div>
      {!watched && !presence.curtain && <>
      <div
        onMouseEnter={() => clearTimeout(hideTimer.current)}
        onMouseLeave={() => { if (answer?.status === "done") hideTimer.current = setTimeout(() => setAnswer(null), ANSWER_MS); }}
      >
        <Guard resetKey={answer?.id} onError={() => bridge?.pointerOverUi(false)}>
          <AnimatePresence>{answer && <Answer key={answer.id} answer={answer} onClose={closeAnswer}
            openIndex={openIndex} setOpenIndex={setOpenIndex}
            onFollowUp={() => { setTyping(true); bridge?.focusAsk(); }}
            onCopied={() => say("Copied", "copy")} />}</AnimatePresence>
        </Guard>
      </div>
      {!answer && (
        <Guard resetKey={cards[0]?.id}>
        <div className="pointer-events-none absolute right-4 top-4 flex flex-col items-end gap-2">
          <AnimatePresence initial={false}>
            {cards.map((c) => (
              <Card
                key={c.id}
                card={c}
                away={away}
                onGone={() => { bridge?.pointerOverUi(false); drop(c.id); }}
                onDismiss={() => { bridge?.pointerOverUi(false); drop(c.id); bridge?.api("dismiss", { id: c.id }); }}
              />
            ))}
          </AnimatePresence>
        </div>
        </Guard>
      )}
      </>}
    </>
  );
}
