import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Maximize2, Mic, MonitorSmartphone, Search, Sparkles, Volume2, VolumeX, X } from "lucide-react";
import { useThumb } from "./Timeline.jsx";

// D25/D27: a question answered where you are. Three shapes:
//   chat   — just the reply;
//   screen — "On your screen now", large, beside the reply;
//   recall — the moments the answer rests on (best match focused; click to open
//            big) beside the reply.
const bridge = window.jimmy;
const surface = "bg-neutral-950/92 ring-1 ring-white/10 shadow-[0_18px_60px_-15px_rgba(0,0,0,0.7)]";
const hover = {
  onMouseEnter: () => bridge?.pointerOverUi(true),
  onMouseLeave: () => bridge?.pointerOverUi(false),
};
const spring = { type: "spring", stiffness: 380, damping: 34 };

function Highlight({ text, terms }) {
  if (!terms?.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(re).map((part, i) =>
    i % 2 ? <mark key={i} className="rounded bg-emerald-400/20 px-0.5 text-emerald-200">{part}</mark> : part,
  );
}

// A screenshot that can grow into the lightbox: same layoutId, Motion animates between.
function Shot({ path, id, className, onClick }) {
  const src = useThumb(path);
  if (!src) return <div className={`animate-pulse bg-white/[0.05] ${className}`} />;
  return (
    <motion.img
      layoutId={`shot-${id}`} src={src} draggable={false} onClick={onClick}
      className={`object-cover object-top ${onClick ? "cursor-zoom-in" : ""} ${className}`}
      transition={spring}
    />
  );
}

function Skeleton() {
  return [0, 1, 2].map((i) => (
    <div key={i} className="space-y-2 rounded-xl bg-white/[0.03] p-2.5 ring-1 ring-white/[0.06]">
      <div className="aspect-[16/7] animate-pulse rounded-lg bg-white/[0.05]" />
      <div className="h-3 w-2/5 animate-pulse rounded bg-white/[0.06]" />
      <div className="h-3 w-4/5 animate-pulse rounded bg-white/[0.04]" />
    </div>
  ));
}

function Evidence({ answer, onOpen }) {
  const { evidence: items = [], terms, days, window: label, status } = answer;
  const best = useRef(null);
  useEffect(() => {
    best.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [items]);
  return (
    <motion.aside
      {...hover}
      initial={{ opacity: 0, x: -24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
      transition={spring}
      className={`pointer-events-auto absolute bottom-6 left-4 top-14 flex w-[400px] flex-col overflow-hidden rounded-2xl ${surface}`}
    >
      <div className="flex items-center gap-2 px-4 pb-2 pt-3.5 text-[11px] uppercase tracking-wider text-neutral-500">
        <Search size={12} />
        <span>Evidence</span>
        <span className="ml-auto normal-case tracking-normal">
          {items.length ? `${items.length} moment${items.length === 1 ? "" : "s"}` : ""}
          {days?.length > 1 ? ` · ${days.length} days` : days?.length ? ` · ${days[0]}` : ""}
          {label ? ` · ${label}` : ""}
        </span>
      </div>
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 pb-3 [scrollbar-width:thin]">
        {status === "searching" && <Skeleton />}
        {status !== "searching" && items.length === 0 && (
          <p className="px-1 text-[13px] text-neutral-500">Nothing in what I captured matches.</p>
        )}
        {items.map((e, i) => (
          <motion.div
            key={e.ref} ref={i === 0 ? best : null}
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring, delay: i * 0.06 }}
            className={`group rounded-xl p-2.5 ${i === 0 ? "bg-emerald-400/[0.06] ring-1 ring-emerald-400/40" : "bg-white/[0.03] ring-1 ring-white/[0.06] hover:bg-white/[0.05]"}`}
          >
            {e.thumb && (
              <div className="relative">
                <Shot path={e.thumb} id={e.ref} onClick={() => onOpen(e)}
                  className={`w-full rounded-lg ${i === 0 ? "aspect-video" : "aspect-[16/7]"}`} />
                <button onClick={() => onOpen(e)} aria-label="Open large"
                  className="absolute right-1.5 top-1.5 rounded-md bg-black/60 p-1 text-neutral-200 opacity-0 transition group-hover:opacity-100">
                  <Maximize2 size={12} />
                </button>
              </div>
            )}
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-neutral-400">
              {e.kind === "heard" && <Mic size={11} />}
              <span className="text-neutral-300">{e.day} · {e.time}</span>
              {e.app && <span>· {e.app}</span>}
              {i === 0 && <span className="ml-auto rounded bg-emerald-400/15 px-1.5 py-px text-emerald-300">best match</span>}
            </div>
            {e.title && e.kind !== "heard" && <div className="mt-0.5 truncate text-[13px] font-medium text-neutral-100">{e.title}</div>}
            {e.excerpt && (
              <p className="mt-1 line-clamp-3 text-[12.5px] leading-snug text-neutral-400 [overflow-wrap:anywhere]">
                {e.kind === "heard" ? "“" : ""}<Highlight text={e.excerpt} terms={terms} />{e.kind === "heard" ? "”" : ""}
              </p>
            )}
          </motion.div>
        ))}
      </div>
    </motion.aside>
  );
}

function ScreenNow({ answer, onOpen }) {
  const e = answer.evidence?.[0];
  return (
    <motion.aside
      {...hover}
      initial={{ opacity: 0, x: -24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
      transition={spring}
      className={`pointer-events-auto absolute left-4 top-14 w-[min(640px,48vw)] overflow-hidden rounded-2xl p-3 ${surface}`}
    >
      <div className="mb-2 flex items-center gap-2 px-1 text-[11px] uppercase tracking-wider text-neutral-500">
        <MonitorSmartphone size={12} /> On your screen now
      </div>
      {answer.status === "searching" && <div className="aspect-video animate-pulse rounded-xl bg-white/[0.05]" />}
      {e && (
        <>
          <Shot path={e.thumb} id={e.ref} onClick={() => onOpen(e)} className="aspect-video w-full rounded-xl ring-1 ring-white/10" />
          <div className="mt-2 px-1">
            <div className="truncate text-[14px] font-medium text-neutral-100">{e.title}</div>
            <div className="text-[12px] text-neutral-500">{e.app}</div>
          </div>
        </>
      )}
      {!e && answer.status !== "searching" && (
        <p className="px-1 py-6 text-[13px] text-neutral-500">I can't see a window I'm allowed to read right now.</p>
      )}
    </motion.aside>
  );
}

function Reply({ answer, onClose }) {
  const busy = answer.status === "searching" || answer.status === "answering";
  const n = answer.evidence?.length || 0;
  const foot = answer.mode === "chat" ? "Conversation"
    : answer.mode === "screen" ? (n ? "From the window you're on" : "")
    : n ? `Based on ${n} moment${n === 1 ? "" : "s"} on the left` : busy ? "…" : "No matching moments";
  return (
    <motion.section
      {...hover}
      initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
      transition={spring}
      className={`pointer-events-auto absolute right-4 top-14 flex max-h-[76vh] w-[440px] flex-col rounded-2xl ${surface}`}
    >
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pt-3.5 [scrollbar-width:thin]">
        {answer.history?.map((t, i) => (
          <div key={i} className="mb-3 border-b border-white/[0.06] pb-3 opacity-60">
            <div className="text-[12.5px] text-neutral-400">{t.q}</div>
            <div className="mt-0.5 line-clamp-2 text-[13px] text-neutral-300">{t.a}</div>
          </div>
        ))}
        <div className="flex items-start gap-2">
          <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-white/[0.06] text-neutral-300">
            {answer.source === "voice" ? <Mic size={13} /> : <Sparkles size={13} />}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] uppercase tracking-wider text-neutral-500">You asked</div>
            <div className="text-[14px] text-neutral-200">{answer.question}</div>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 text-neutral-500 hover:bg-white/10 hover:text-neutral-200">
            <X size={14} />
          </button>
        </div>
        <div className="pb-3 pt-3">
          {answer.status === "searching" && (
            <p className="flex items-center gap-2 text-[14px] text-neutral-400">
              <span className="size-3 animate-spin rounded-full border border-white/30 border-t-transparent" />
              {answer.mode === "chat" ? "Thinking…" : answer.mode === "screen" ? "Reading your screen…" : "Looking through your days…"}
            </p>
          )}
          {answer.error && <p className="text-[14px] text-amber-300">Couldn't answer: {answer.error}</p>}
          {answer.text && (
            <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              className="whitespace-pre-line text-[15.5px] leading-relaxed text-neutral-50">
              {answer.text}
              {answer.status === "answering" && <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse bg-neutral-300" />}
            </motion.p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 border-t border-white/[0.06] px-4 py-2.5 text-[11.5px] text-neutral-500">
        <span>{foot}</span>
        {answer.source === "voice" && !busy && (
          <button onClick={() => bridge?.api("stop-voice")} className="ml-auto flex items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-white/10 hover:text-neutral-200">
            <VolumeX size={12} /> Stop voice
          </button>
        )}
        {answer.source === "voice" && busy && <Volume2 size={12} className="ml-auto" />}
      </div>
    </motion.section>
  );
}

// The moment, big. The thumbnail grows into place (shared layoutId); a click
// anywhere or Esc sends it back.
function Lightbox({ item, onClose }) {
  const src = useThumb(item.thumb);
  useEffect(() => {
    bridge?.pointerOverUi(true);
    const onKey = (ev) => { if (ev.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); bridge?.pointerOverUi(false); };
  }, [onClose]);
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onClose}
      className="pointer-events-auto absolute inset-0 z-50 flex items-center justify-center bg-black/55 p-10"
    >
      <div className="flex max-h-full max-w-[min(1200px,88vw)] flex-col items-center gap-3">
        {src && (
          <motion.img layoutId={`shot-${item.ref}`} src={src} draggable={false} transition={spring}
            className="max-h-[78vh] min-h-0 w-auto rounded-xl object-contain shadow-2xl ring-1 ring-white/15" />
        )}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}
          className={`max-w-[900px] rounded-xl px-4 py-2.5 text-center ${surface}`}>
          <div className="text-[12px] text-neutral-400">{item.day}{item.time ? ` · ${item.time}` : ""}{item.app ? ` · ${item.app}` : ""}</div>
          <div className="text-[14px] font-medium text-neutral-100">{item.title}</div>
          {item.excerpt && <div className="mt-1 text-[13px] text-neutral-400">{item.excerpt}</div>}
        </motion.div>
      </div>
    </motion.div>
  );
}

export default function Answer({ answer, onClose }) {
  const [open, setOpen] = useState(null);
  return (
    <>
      {answer.mode === "screen" && <ScreenNow answer={answer} onOpen={setOpen} />}
      {answer.mode === "recall" && <Evidence answer={answer} onOpen={setOpen} />}
      <Reply answer={answer} onClose={onClose} />
      <AnimatePresence>{open && <Lightbox key="lb" item={open} onClose={() => setOpen(null)} />}</AnimatePresence>
    </>
  );
}
