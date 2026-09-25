import { Component, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { History, MessageCircle, Pause, Play, Power, Target, X } from "lucide-react";
import Answer from "./Answer.jsx";

const CARD_MS = 12_000;      // a card fades on its own; × is the only real dismissal
const ANSWER_MS = 60_000;    // an answer fades after a minute unless hovered
const MAX_CARDS = 3;
const bridge = window.jimmy; // from preload.cjs: events in, actions out

// Everything except the pill, cards and answer panels lets clicks through.
const hover = {
  onMouseEnter: () => bridge?.pointerOverUi(true),
  onMouseLeave: () => bridge?.pointerOverUi(false),
};

const surface =
  "bg-neutral-950/90 ring-1 ring-white/10 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.6)]";

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

function minutesLeft(until) {
  const m = Math.max(0, Math.round((until - Date.now()) / 60_000));
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
}

function PillButton({ onClick, label, children }) {
  return (
    <motion.button
      initial={{ opacity: 0, width: 0 }} animate={{ opacity: 1, width: "auto" }} exit={{ opacity: 0, width: 0 }}
      onClick={onClick} aria-label={label}
      className="flex items-center gap-1 overflow-hidden whitespace-nowrap rounded-full bg-white/10 px-2 py-0.5 text-neutral-100 hover:bg-white/15"
    >
      {children}
    </motion.button>
  );
}

function Pill({ state, mood, typing, setTyping }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const input = useRef(null);
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 30_000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => { if (typing) setTimeout(() => input.current?.focus(), 30); }, [typing]);

  const paused = state.paused;
  const done = () => { setTyping(false); setQ(""); bridge?.releaseFocus(); bridge?.pointerOverUi(false); };
  const submit = (e) => {
    e.preventDefault();
    if (q.trim()) bridge?.api("ask", { q: q.trim() });
    done();
  };
  const status = paused ? `paused · ${minutesLeft(state.paused_until)}`
    : mood === "listening" ? "listening… ask your question"
    : mood === "thinking" ? "thinking…"
    : "listening";
  const dot = paused ? "bg-amber-400" : mood ? "bg-sky-400" : "bg-emerald-400";

  return (
    <div className="pointer-events-none absolute inset-x-0 top-2 flex justify-center">
      <motion.div
        layout
        onMouseEnter={() => { hover.onMouseEnter(); setOpen(true); }}
        onMouseLeave={() => { if (!typing) hover.onMouseLeave(); setOpen(false); }}
        transition={{ type: "spring", stiffness: 500, damping: 38 }}
        className={`pointer-events-auto flex h-8 items-center gap-2 rounded-full px-3 text-[12px] ${surface}`}
      >
        <span className="relative flex size-2">
          {!paused && <span className={`absolute inline-flex size-full animate-ping rounded-full ${mood ? "bg-sky-400/60" : "bg-emerald-400/60"}`} />}
          <span className={`relative inline-flex size-2 rounded-full ${dot}`} />
        </span>
        <span className="font-medium text-neutral-100">Jimmy</span>
        {typing ? (
          <form onSubmit={submit} className="flex items-center">
            <input
              ref={input} value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Escape" && done()} onBlur={done}
              placeholder='Ask anything… or just say "Jimmy, …"'
              className="w-[340px] bg-transparent text-[12.5px] text-neutral-100 outline-none placeholder:text-neutral-500"
            />
          </form>
        ) : (
          <span className="text-neutral-400">{status}</span>
        )}
        <AnimatePresence initial={false}>
          {open && !typing && (
            <motion.div key="menu" className="ml-1 flex items-center gap-1">
              <PillButton label="Ask by typing" onClick={() => { setTyping(true); bridge?.focusAsk(); }}>
                <MessageCircle size={12} /> Ask
              </PillButton>
              <PillButton label="Open timeline" onClick={() => bridge?.openTimeline()}>
                <History size={12} /> Timeline
              </PillButton>
              <PillButton label={paused ? "Resume" : "Pause for 2 hours"}
                onClick={() => bridge?.api(paused ? "resume" : "pause", { minutes: 120 })}>
                {paused ? <Play size={12} /> : <Pause size={12} />} {paused ? "Resume" : "Pause 2h"}
              </PillButton>
              <PillButton label="Quit Jimmy" onClick={() => bridge?.api("quit")}>
                <Power size={12} /> Quit
              </PillButton>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}

function Card({ card, onGone, onDismiss }) {
  const [held, setHeld] = useState(false);   // hovering keeps the card on screen
  const left = useRef(CARD_MS);
  useEffect(() => {
    if (held) return;
    const started = Date.now();
    const t = setTimeout(onGone, left.current);
    return () => { clearTimeout(t); left.current -= Date.now() - started; };
  }, [held]);

  const Icon = card.kind === "FOCUS" ? Target : History;
  const when = new Date(card.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 28, scale: 0.98 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 28, transition: { duration: 0.18 } }}
      transition={{ type: "spring", stiffness: 420, damping: 34 }}
      onMouseEnter={() => { bridge?.pointerOverUi(true); setHeld(true); }}
      onMouseLeave={() => { bridge?.pointerOverUi(false); setHeld(false); }}
      className={`group pointer-events-auto relative w-80 overflow-hidden rounded-2xl p-3.5 ${surface}`}
    >
      <div className="flex items-center gap-2 text-[11px] text-neutral-400">
        <span className="flex size-5 items-center justify-center rounded-md bg-white/[0.06] text-neutral-300">
          <Icon size={12} />
        </span>
        <span className="uppercase tracking-wider">{card.kind === "FOCUS" ? "Focus" : "Recall"}</span>
        <span className="ml-auto text-neutral-500">{when}</span>
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          className="flex size-5 items-center justify-center rounded-md text-neutral-500 opacity-0 transition group-hover:opacity-100 hover:bg-white/10 hover:text-neutral-200"
        >
          <X size={12} />
        </button>
      </div>
      <p className="mt-2 text-[15px] font-medium leading-snug text-neutral-50">{card.line}</p>
      {/* Time left: frozen while hovered, then runs out from where it stopped. */}
      <motion.div
        key={held ? "held" : `run-${left.current}`}
        className="absolute bottom-0 left-0 h-[2px] bg-white/25"
        initial={{ width: `${(100 * left.current) / CARD_MS}%` }}
        animate={{ width: held ? `${(100 * left.current) / CARD_MS}%` : "0%" }}
        transition={{ duration: held ? 0 : left.current / 1000, ease: "linear" }}
      />
    </motion.div>
  );
}

export default function App() {
  const [state, setState] = useState({ paused: false, paused_until: 0 });
  const [cards, setCards] = useState([]);
  const [answer, setAnswer] = useState(null);
  const [mood, setMood] = useState(null);      // "listening" | "thinking" | null
  const [typing, setTyping] = useState(false);
  const hideTimer = useRef(null);

  const closeAnswer = () => {
    clearTimeout(hideTimer.current);
    setAnswer(null);
    bridge?.pointerOverUi(false);
    bridge?.api("stop-voice");
  };

  useEffect(() => {
    bridge?.onEvent((ev) => {
      if (ev.type === "state") setState(ev);
      if (ev.type === "card") setCards((cs) => [ev, ...cs.filter((c) => c.id !== ev.id)].slice(0, MAX_CARDS));
      if (ev.type === "focus-ask") setTyping(true);
      if (ev.type === "listening") {
        setMood("listening");
        setTimeout(() => setMood((m) => (m === "listening" ? null : m)), 9000);
      }
      if (ev.type === "answer_start") {
        clearTimeout(hideTimer.current);
        setMood("thinking");
        setAnswer({ id: ev.id, question: ev.question, source: ev.source, mode: ev.mode || "recall",
                    history: ev.history || [], status: "searching", evidence: [], text: "" });
      }
      const same = (fn) => setAnswer((a) => (a && a.id === ev.id ? fn(a) : a));
      if (ev.type === "answer_evidence")
        same((a) => ({ ...a, status: "answering", mode: ev.mode || a.mode, evidence: ev.evidence,
                       terms: ev.terms, days: ev.days, window: ev.window }));
      if (ev.type === "answer_delta") same((a) => ({ ...a, status: "answering", text: a.text + ev.text }));
      if (ev.type === "answer_end" || ev.type === "answer_error") {
        setMood(null);
        same((a) => ({ ...a, status: ev.type === "answer_end" ? "done" : "error", error: ev.error }));
        clearTimeout(hideTimer.current);
        hideTimer.current = setTimeout(() => setAnswer(null), ANSWER_MS);
      }
    });
  }, []);

  const drop = (id) => setCards((cs) => cs.filter((c) => c.id !== id));

  return (
    <>
      <Pill state={state} mood={mood} typing={typing} setTyping={setTyping} />
      <div
        onMouseEnter={() => clearTimeout(hideTimer.current)}
        onMouseLeave={() => { if (answer?.status === "done") hideTimer.current = setTimeout(() => setAnswer(null), ANSWER_MS); }}
      >
        <Guard resetKey={answer?.id} onError={() => bridge?.pointerOverUi(false)}>
          <AnimatePresence>{answer && <Answer key={answer.id} answer={answer} onClose={closeAnswer} />}</AnimatePresence>
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
                onGone={() => { bridge?.pointerOverUi(false); drop(c.id); }}
                onDismiss={() => { bridge?.pointerOverUi(false); drop(c.id); bridge?.api("dismiss", { id: c.id }); }}
              />
            ))}
          </AnimatePresence>
        </div>
        </Guard>
      )}
    </>
  );
}
