import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, CircleDashed, Hand, Loader2, MinusCircle, Play, Square, TriangleAlert, X } from "lucide-react";

// D56: Intelligent UI. An answer can carry one card from a fixed set of templates; the
// data was checked in Python (ambient/ui.py) and every string here renders as text.
// The rules, after OpenAI's own for in-chat UI: a card earns its place or isn't shown;
// at most two actions; no scrolling inside; anything a button does can also be said.
// Buttons send their words through "ask", exactly as if they'd been spoken.
const bridge = window.jimmy;
const say = (q) => bridge?.api("ask", { q });
const hover = {
  onMouseEnter: () => bridge?.pointerOverUi(true),
  onMouseLeave: () => bridge?.pointerOverUi(false),
};
const box = "mt-3 rounded-xl bg-white/[0.04] p-3 ring-1 ring-white/10";
const primary = "rounded-lg bg-sky-500/80 px-3 py-1.5 text-[13px] text-white hover:bg-sky-500 disabled:opacity-60";
const quiet = "rounded-lg px-3 py-1.5 text-[13px] text-neutral-400 hover:bg-white/10 disabled:opacity-60";
const fadeIn = { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 } };

function Title({ children }) {
  return children ? <div className="mb-2 text-[12px] font-medium uppercase tracking-wider text-neutral-500">{children}</div> : null;
}

const STEP_ICON = {
  done: <Check size={13} className="text-emerald-300" />,
  running: <Loader2 size={13} className="animate-spin text-sky-300" />,
  failed: <TriangleAlert size={13} className="text-amber-300" />,
  skipped: <MinusCircle size={13} className="text-neutral-600" />,
  pending: <CircleDashed size={13} className="text-neutral-600" />,
};

// D57: the plan, live. Proposed: Start / Cancel. Running: Stop. Done: just the ticks.
export function Steps({ data, flat }) {
  const [sent, setSent] = useState(false);
  const label = { proposed: "Plan", running: data.auto ? "On it (say stop)" : "Working", done: "Done",
                  failed: "Stopped at a problem", stopped: "Stopped" }[data.state];
  return (
    <motion.div {...fadeIn} className={flat ? "pt-3" : box}>
      <Title>{label}</Title>
      <ol className="space-y-1.5">
        {data.steps.map((s, i) => (
          <motion.li key={i} layout className={`flex items-start gap-2 text-[13.5px] ${
            data.status[i] === "running" ? "text-neutral-50" : data.status[i] === "done" ? "text-neutral-300"
              : data.status[i] === "failed" ? "text-amber-200" : "text-neutral-500"}`}>
            <span className="mt-[3px] shrink-0">{STEP_ICON[data.status[i]] || STEP_ICON.pending}</span>
            <span><span className="mr-1 text-neutral-600">{i + 1}.</span>{s}</span>
          </motion.li>
        ))}
      </ol>
      {data.state === "proposed" && (
        <div className="mt-3 flex gap-2">
          <motion.button whileTap={{ scale: 0.95 }} disabled={sent} onClick={() => { setSent(true); say("yes"); }}
            className={`flex items-center gap-1.5 ${primary}`}><Play size={12} /> Start</motion.button>
          <button disabled={sent} onClick={() => { setSent(true); say("no"); }} className={quiet}>Cancel</button>
        </div>
      )}
      {data.state === "running" && (
        <div className="mt-3">
          <button onClick={() => say("stop")} className={`flex items-center gap-1.5 ${quiet}`}>
            <Square size={11} /> Stop
          </button>
        </div>
      )}
    </motion.div>
  );
}

// D55: Jimmy isn't sure which control you meant. Tap one, or say it ("the second one").
export function Choice({ data }) {
  const [picked, setPicked] = useState(null);
  return (
    <motion.div {...fadeIn} transition={{ delay: 0.1 }} className="mt-3 flex flex-wrap gap-2">
      {data.options.map((o, i) => (
        <motion.button key={i} whileTap={{ scale: 0.95 }} disabled={picked !== null}
          onClick={() => { setPicked(i); say(o); }}
          className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] ${
            picked === i ? "bg-sky-500/80 text-white" : "bg-white/10 text-neutral-100 hover:bg-white/15"} disabled:opacity-70`}>
          <span className="text-neutral-400">{i + 1}</span> {o}
        </motion.button>
      ))}
    </motion.div>
  );
}

// A yes/no about one action: two buttons, the same as saying yes or no.
export function Confirm({ data }) {
  const [sent, setSent] = useState(null);
  return (
    <motion.div {...fadeIn} className="mt-3 flex gap-2">
      <motion.button whileTap={{ scale: 0.95 }} disabled={sent !== null} onClick={() => { setSent("yes"); say("yes"); }}
        className={`flex items-center gap-1.5 ${primary}`}>
        {sent === "yes" ? <Check size={13} /> : <Hand size={13} />} {data.yes}
      </motion.button>
      <button disabled={sent !== null} onClick={() => { setSent("no"); say("no"); }} className={`flex items-center gap-1 ${quiet}`}>
        <X size={12} /> {data.no}
      </button>
    </motion.div>
  );
}

export function List({ data }) {
  return (
    <motion.div {...fadeIn} className={box}>
      <Title>{data.title}</Title>
      <ul className="space-y-1">
        {data.items.map((it, i) => (
          <li key={i} className="flex items-baseline justify-between gap-3 text-[13.5px] text-neutral-200">
            <span className="min-w-0 truncate">{it.text}</span>
            {it.note && <span className="shrink-0 text-[12px] text-neutral-500">{it.note}</span>}
          </li>
        ))}
      </ul>
      {data.more > 0 && <div className="mt-1.5 text-[12px] text-neutral-500">and {data.more} more</div>}
    </motion.div>
  );
}

export function Table({ data }) {
  return (
    <motion.div {...fadeIn} className={`${box} overflow-hidden p-0`}>
      {data.title && <div className="px-3 pt-3"><Title>{data.title}</Title></div>}
      <table className="w-full table-fixed text-left text-[12.5px]">
        <thead>
          <tr className="text-neutral-500">
            {data.columns.map((c, i) => <th key={i} className="truncate px-3 py-1.5 font-medium">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r, i) => (
            <tr key={i} className="border-t border-white/[0.06] text-neutral-200">
              {r.map((c, j) => <td key={j} className={`px-3 py-1.5 align-top ${j === 0 ? "text-neutral-100" : ""}`}>{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </motion.div>
  );
}

// Steps the user follows themselves: ticks are theirs, kept only while the card is open.
export function Checklist({ data }) {
  const [done, setDone] = useState(() => data.items.map(() => false));
  return (
    <motion.div {...fadeIn} className={box}>
      <Title>{data.title}</Title>
      <ul className="space-y-1.5">
        {data.items.map((it, i) => (
          <li key={i}>
            <button onClick={() => setDone((d) => d.map((x, j) => (j === i ? !x : x)))}
              className="flex w-full items-start gap-2 text-left text-[13.5px]">
              <span className={`mt-[2px] flex size-4 shrink-0 items-center justify-center rounded ring-1 ${
                done[i] ? "bg-emerald-500/70 ring-emerald-400/60" : "ring-white/25"}`}>
                {done[i] && <Check size={11} className="text-white" />}
              </span>
              <span className={done[i] ? "text-neutral-500 line-through" : "text-neutral-200"}>{it}</span>
            </button>
          </li>
        ))}
      </ul>
    </motion.div>
  );
}

export function Chart({ data }) {
  const top = Math.max(...data.bars.map((b) => b.value), 1e-9);
  const fmt = (v) => `${Number.isInteger(v) ? v : v.toFixed(1)}${data.unit ? ` ${data.unit}` : ""}`;
  return (
    <motion.div {...fadeIn} className={box}>
      <Title>{data.title}</Title>
      <div className="space-y-1.5">
        {data.bars.map((b, i) => (
          <div key={i} className="grid grid-cols-[96px_1fr_auto] items-center gap-2 text-[12.5px]">
            <span className="truncate text-neutral-300">{b.label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-white/[0.06]">
              {/* transform-only, like the rest of the overlay's motion */}
              <motion.div className="h-full origin-left rounded-full bg-sky-400/80"
                initial={{ scaleX: 0 }} animate={{ scaleX: b.value / top }} transition={{ delay: 0.05 * i }} />
            </div>
            <span className="tabular-nums text-neutral-400">{fmt(b.value)}</span>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

const REGISTRY = { steps: Steps, choice: Choice, confirm: Confirm, list: List, table: Table, checklist: Checklist, chart: Chart };

// One card, by name. An unknown template renders nothing (Python already refused it).
export default function Template({ ui }) {
  const Card = ui && REGISTRY[ui.template];
  return Card ? <Card data={ui.data} /> : null;
}

// D57: the live plan while it runs, when no answer panel is open (top right, where the
// answer will appear). It leaves a few seconds after the plan ends.
export function StepsFloat({ ui }) {
  return (
    <AnimatePresence>
      {ui && (
        <motion.section key="steps" {...hover}
          initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
          className="pointer-events-auto absolute right-4 top-14 w-[340px] rounded-2xl bg-neutral-950/92 px-3 pb-3 ring-1 ring-white/10 shadow-[0_18px_60px_-15px_rgba(0,0,0,0.7)]">
          <Steps data={ui.data} flat />
        </motion.section>
      )}
    </AnimatePresence>
  );
}
