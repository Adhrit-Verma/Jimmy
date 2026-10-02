import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  BarChart3, CalendarPlus, Check, ChevronLeft, ChevronRight, Copy, CornerDownRight, ExternalLink, Globe, HelpCircle,
  History, Maximize2, MessageCircle, Mic, MonitorSmartphone, PenLine, Search, Sparkles, Volume2, VolumeX, X,
} from "lucide-react";
import { useThumb } from "./Timeline.jsx";
import { AppBars, Axis, CountUp, Ribbon, colorOf, short } from "./Insights.jsx";

// D25/D27/D31: a question answered where you are. Four shapes:
//   chat   — just the reply;
//   screen — "On your screen now", large, beside the reply;
//   recall — the moments the answer rests on (best match focused; click to open
//            big) beside the reply;
//   stats  — where the time went, drawn, beside a one-line answer.
const bridge = window.jimmy;
const surface = "bg-neutral-950/92 ring-1 ring-white/10 shadow-[0_18px_60px_-15px_rgba(0,0,0,0.7)]";
const hover = {
  onMouseEnter: () => bridge?.pointerOverUi(true),
  onMouseLeave: () => bridge?.pointerOverUi(false),
};
const spring = { type: "spring", stiffness: 380, damping: 34 };
const MODES = {
  recall: [History, "From your history"], screen: [MonitorSmartphone, "Your screen"],
  chat: [MessageCircle, "Chat"], stats: [BarChart3, "Your time"], clarify: [HelpCircle, "Quick check"],
  draft: [PenLine, "Draft"], event: [CalendarPlus, "Calendar"],
};

function Highlight({ text, terms }) {
  if (!terms?.length) return text;
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(re).map((part, i) =>
    i % 2 ? <mark key={i} className="rounded bg-emerald-400/20 px-0.5 text-emerald-200">{part}</mark> : part,
  );
}

// A screenshot that can grow into the lightbox: same layoutId, Motion animates between.
function Shot({ path, id, className, onClick, w }) {
  const src = useThumb(path, w);
  if (!src) return <div className={`animate-pulse bg-white/[0.05] ${className}`} />;
  return (
    <motion.img
      layoutId={`shot-${id}`} src={src} draggable={false} onClick={onClick}
      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
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

const iconBtn = "rounded-md bg-black/60 p-1 text-neutral-200 opacity-0 transition hover:bg-black/80 group-hover:opacity-100";

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
      className={`pointer-events-auto absolute left-4 top-14 flex max-h-[calc(100%-5rem)] w-[400px] flex-col overflow-hidden rounded-2xl ${surface}`}
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
      <div data-scroll className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 pb-3 [scrollbar-width:thin]">
        {status === "searching" && <Skeleton />}
        {status !== "searching" && items.length === 0 && (
          <p className="px-1 text-[13px] text-neutral-500">Nothing in what I captured matches.</p>
        )}
        {items.map((e, i) => (
          <motion.div
            key={e.ref} ref={i === 0 ? best : null}
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            transition={{ ...spring, delay: i * 0.06 }}
            className={`group rounded-xl p-2.5 transition-colors ${i === 0 ? "bg-emerald-400/[0.06] ring-1 ring-emerald-400/40" : "bg-white/[0.03] ring-1 ring-white/[0.06] hover:bg-white/[0.05]"}`}
          >
            {e.thumb && (
              <div className="relative">
                <Shot path={e.thumb} id={e.ref} w={640} onClick={() => onOpen(i)}
                  className={`w-full rounded-lg ${i === 0 ? "aspect-video" : "aspect-[16/7]"}`} />
                <div className="absolute right-1.5 top-1.5 flex gap-1">
                  {e.url && (
                    <button onClick={() => bridge?.openUrl(e.url)} aria-label="Open the page" title={e.url}
                      className={iconBtn}><Globe size={12} /></button>
                  )}
                  <button onClick={() => bridge?.openTimeline("timeline", { ts: e.ts })} aria-label="Open in timeline"
                    title="Open in timeline" className={iconBtn}><History size={12} /></button>
                  <button onClick={() => onOpen(i)} aria-label="Open large" title="Open large" className={iconBtn}>
                    <Maximize2 size={12} />
                  </button>
                </div>
              </div>
            )}
            <div className="mt-2 flex items-center gap-1.5 text-[11px] text-neutral-400">
              {e.kind === "heard" && <Mic size={11} />}
              <span className="tabular-nums text-neutral-300">{e.day} · {e.time}</span>
              {e.app && <span className="flex items-center gap-1">· <span className="size-1.5 rounded-full" style={{ background: colorOf(e.app) }} />{e.app}</span>}
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
        <MonitorSmartphone size={12} />
        {answer.mode === "draft" ? "Writing from" : answer.mode === "event" ? "Found on" : "On your screen now"}
      </div>
      {answer.status === "searching" && <div className="aspect-video animate-pulse rounded-xl bg-white/[0.05]" />}
      {e && (
        <>
          <Shot path={e.thumb} id={e.ref} onClick={() => onOpen(0)} className="aspect-video w-full rounded-xl ring-1 ring-white/10" />
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

// D31: "how was my day?" / "how long was I on Chrome?" — the numbers, drawn.
function StatsPanel({ answer }) {
  const s = answer.stats;
  const m = s?.match;
  const dim = m?.ms && s.apps.some((a) => a.app === m.name) ? m.name : null;
  const runs = m?.ms && !dim ? m.spans.map(([start, end]) => ({ app: m.name, start, end })) : s?.runs || [];
  return (
    <motion.aside
      {...hover}
      initial={{ opacity: 0, x: -24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -24 }}
      transition={spring}
      className={`pointer-events-auto absolute left-4 top-14 w-[420px] overflow-hidden rounded-2xl p-4 ${surface}`}
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-neutral-500">
        <BarChart3 size={12} /> Your time {s?.label ? `· ${s.label}` : ""}
      </div>
      {!s ? (
        <div className="mt-3 space-y-2">{[60, 100, 80, 70].map((w) => <div key={w} className="h-4 animate-pulse rounded bg-white/[0.05]" style={{ width: `${w}%` }} />)}</div>
      ) : (
        <>
          <div className="mt-2 flex items-end gap-4">
            <div>
              <div className="text-[30px] font-semibold leading-none tabular-nums text-neutral-50">
                <CountUp value={m ? m.ms : s.active_ms} format={short} />
              </div>
              <div className="mt-1 text-[12px] text-neutral-500">{m ? `on ${m.name}` : "on screen"}</div>
            </div>
            {m && (
              <div className="pb-0.5 text-[12px] text-neutral-500">
                of <span className="tabular-nums text-neutral-300">{short(s.active_ms)}</span> total
                {s.active_ms > 0 && <> · <span className="tabular-nums text-neutral-300">{Math.round((100 * m.ms) / s.active_ms)}%</span></>}
              </div>
            )}
          </div>
          {s.runs.length > 0 && (
            <div className="mt-4">
              <Ribbon runs={runs} since={s.first} until={s.last} dim={dim}
                colorFor={m?.ms && !dim ? () => "#3987e5" : colorOf} className="h-3"
                onPick={(ts) => bridge?.openTimeline("timeline", { ts })} />
              <Axis since={s.first} until={s.last} />
            </div>
          )}
          <div className="mt-3">
            <AppBars apps={s.apps} total={s.active_ms} max={5} highlight={dim} />
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-white/[0.06] pt-2.5 text-[11.5px] text-neutral-500">
            <span>{s.switches} app switches · longest {short(s.longest?.ms || 0)}</span>
            <button onClick={() => bridge?.openTimeline("insights")}
              className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-neutral-300 hover:bg-white/10">
              Full insights <ExternalLink size={11} />
            </button>
          </div>
        </>
      )}
    </motion.aside>
  );
}

// D32: the event Jimmy read off the screen, to confirm. "Add" hands an .ics to your
// own calendar app, which asks once more; nothing is added behind your back.
function EventCard({ ev }) {
  const [sent, setSent] = useState(false);
  const day = new Date(`${ev.date}T00:00`).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
      className="mt-3 rounded-xl bg-white/[0.04] p-3 ring-1 ring-white/10">
      <div className="text-[14px] font-medium text-neutral-100">{ev.title}</div>
      <div className="mt-0.5 text-[12.5px] text-neutral-400">
        {day}{ev.start ? ` · ${ev.start}${ev.end ? `–${ev.end}` : ""}` : " · all day"}{ev.where ? ` · ${ev.where}` : ""}
      </div>
      <div className="mt-2.5 flex gap-2">
        <motion.button whileTap={{ scale: 0.95 }} disabled={sent}
          onClick={() => { setSent(true); bridge?.api("accept"); }}
          className="flex items-center gap-1.5 rounded-lg bg-sky-500/80 px-3 py-1.5 text-[13px] text-white hover:bg-sky-500 disabled:opacity-60">
          {sent ? <Check size={13} /> : <CalendarPlus size={13} />} {sent ? "Sent to your calendar" : "Add to calendar"}
        </motion.button>
        {!sent && (
          <button onClick={() => bridge?.api("ask", { q: "no" })}
            className="rounded-lg px-3 py-1.5 text-[13px] text-neutral-400 hover:bg-white/10">Skip</button>
        )}
      </div>
    </motion.div>
  );
}

function FootButton({ onClick, children, title }) {
  return (
    <motion.button whileTap={{ scale: 0.94 }} onClick={onClick} title={title}
      className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-neutral-400 transition-colors hover:bg-white/10 hover:text-neutral-100">
      {children}
    </motion.button>
  );
}

function Reply({ answer, onClose, onFollowUp, onCopied }) {
  const busy = answer.status === "searching" || answer.status === "answering";
  const [copied, setCopied] = useState(false);
  const n = answer.evidence?.length || 0;
  const [ModeIcon, modeLabel] = MODES[answer.mode] || MODES.recall;
  const foot = answer.mode === "clarify" ? "Just say it, or pick one"
    : answer.mode === "draft" ? (answer.status === "done" ? "Copied to your clipboard; nothing was sent" : "")
    : answer.mode === "event" ? (answer.event ? "Say yes, or use the button" : "")
    : answer.mode === "stats" ? "Estimated from captures"
    : answer.mode === "screen" ? (n ? "From the window you're on" : "")
    : answer.mode === "recall" ? (n ? `${n} moment${n === 1 ? "" : "s"} on the left` : busy ? "" : "No matching moments")
    : "";
  const copy = () => {
    bridge?.copy(answer.text);
    setCopied(true);
    onCopied?.();
    setTimeout(() => setCopied(false), 1600);
  };
  return (
    <motion.section
      {...hover}
      initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
      transition={spring}
      className={`pointer-events-auto absolute right-4 top-14 flex max-h-[76vh] w-[420px] flex-col overflow-hidden rounded-2xl ${surface}`}
    >
      {/* Working: an indeterminate line along the top, transform-only. */}
      <div className="h-[2px] overflow-hidden">
        {busy && <div className="indet h-full w-1/4 rounded-full bg-gradient-to-r from-transparent via-sky-400 to-transparent" />}
      </div>
      <div data-scroll className="min-h-0 flex-1 overflow-y-auto px-4 pt-3 [scrollbar-width:thin]">
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
            <div className="flex items-center gap-1 text-[11px] uppercase tracking-wider text-neutral-500">
              <ModeIcon size={11} /> {modeLabel}
            </div>
            <div className="text-[14px] text-neutral-200">{answer.question}</div>
          </div>
          <button onClick={onClose} aria-label="Close" title="Close" className="rounded-md p-1 text-neutral-500 hover:bg-white/10 hover:text-neutral-200">
            <X size={14} />
          </button>
        </div>
        <div className="pb-3 pt-3">
          {answer.status === "searching" && !answer.text && (
            <div className="space-y-2 pt-1">
              <div className="h-3.5 w-11/12 animate-pulse rounded bg-white/[0.07]" />
              <div className="h-3.5 w-3/5 animate-pulse rounded bg-white/[0.05]" />
            </div>
          )}
          {answer.error && <p className="text-[14px] text-amber-300">Couldn't answer: {answer.error}</p>}
          {answer.text && (
            <motion.p initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
              className="whitespace-pre-line text-[15.5px] leading-relaxed text-neutral-50 select-text">
              {answer.text}
              {answer.status === "answering" && <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse bg-neutral-300" />}
            </motion.p>
          )}
          {answer.event && answer.status === "done" && <EventCard ev={answer.event} />}
          {answer.mode === "clarify" && answer.status === "done" && (
            // D28: Jimmy asked back. Answer by voice, or pick one.
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
              className="mt-3 flex flex-wrap gap-2">
              <motion.button whileTap={{ scale: 0.95 }} onClick={() => bridge?.api("clarify", { choice: "now" })}
                className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-[13px] text-neutral-100 hover:bg-white/15">
                <MonitorSmartphone size={13} /> On my screen now
              </motion.button>
              <motion.button whileTap={{ scale: 0.95 }} onClick={() => bridge?.api("clarify", { choice: "earlier" })}
                className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-1.5 text-[13px] text-neutral-100 hover:bg-white/15">
                <History size={13} /> Something from earlier
              </motion.button>
            </motion.div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 border-t border-white/[0.06] px-3 py-2 text-[11.5px] text-neutral-500">
        <span className="mr-auto truncate pl-1">{foot}</span>
        {answer.source === "voice" && busy && <Volume2 size={12} className="mr-1 animate-pulse" />}
        {answer.source === "voice" && !busy && (
          <FootButton onClick={() => bridge?.api("stop-voice")} title="Stop reading aloud"><VolumeX size={12} /></FootButton>
        )}
        {answer.text && !busy && (
          <FootButton onClick={copy} title="Copy the answer">
            {copied ? <Check size={12} className="text-emerald-300" /> : <Copy size={12} />} {copied ? "Copied" : "Copy"}
          </FootButton>
        )}
        {answer.mode === "recall" && n > 0 && (
          <FootButton onClick={() => bridge?.openTimeline("timeline", { ts: answer.evidence[0].ts })} title="Open the best match in the timeline">
            <History size={12} /> Timeline
          </FootButton>
        )}
        {!busy && answer.mode !== "clarify" && (
          <FootButton onClick={onFollowUp} title="Ask a follow-up (it remembers this conversation)">
            <CornerDownRight size={12} /> Follow up
          </FootButton>
        )}
      </div>
    </motion.section>
  );
}

// The moment, big. The thumbnail grows into place (shared layoutId); a click on
// the backdrop or Esc sends it back. Arrows step through the other moments.
function Lightbox({ items, index, setIndex, onClose }) {
  const item = items[index];
  const full = useThumb(item?.thumb);
  const preview = useThumb(item?.thumb, 640);
  const src = full || preview;
  useEffect(() => {
    bridge?.pointerOverUi(true);
    const onKey = (ev) => {
      if (ev.key === "Escape") onClose();
      if (ev.key === "ArrowRight") setIndex((i) => Math.min(i + 1, items.length - 1));
      if (ev.key === "ArrowLeft") setIndex((i) => Math.max(i - 1, 0));
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); bridge?.pointerOverUi(false); };
  }, [onClose, items.length, setIndex]);
  if (!item) return null;
  const nav = "pointer-events-auto absolute top-1/2 -translate-y-1/2 rounded-full bg-neutral-900/80 p-2.5 text-neutral-200 ring-1 ring-white/10 transition hover:bg-neutral-800 disabled:opacity-0";
  return (
    <motion.div
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      onClick={onClose}
      className="pointer-events-auto absolute inset-0 z-50 flex items-center justify-center bg-black/60 p-10"
    >
      {items.length > 1 && (
        <>
          <button className={`${nav} left-6`} disabled={index === 0} aria-label="Previous"
            onClick={(e) => { e.stopPropagation(); setIndex(index - 1); }}><ChevronLeft size={18} /></button>
          <button className={`${nav} right-6`} disabled={index === items.length - 1} aria-label="Next"
            onClick={(e) => { e.stopPropagation(); setIndex(index + 1); }}><ChevronRight size={18} /></button>
        </>
      )}
      <div className="flex max-h-full max-w-[min(1200px,84vw)] flex-col items-center gap-3">
        {src && (
          <motion.img key={item.ref} layoutId={`shot-${item.ref}`} src={src} draggable={false} transition={spring}
            onClick={(e) => e.stopPropagation()}
            className="max-h-[76vh] min-h-0 w-auto rounded-xl object-contain shadow-2xl ring-1 ring-white/15" />
        )}
        <motion.div key={`cap-${item.ref}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
          onClick={(e) => e.stopPropagation()}
          className={`max-w-[900px] rounded-xl px-4 py-2.5 text-center ${surface}`}>
          <div className="flex items-center justify-center gap-2 text-[12px] text-neutral-400">
            {items.length > 1 && <span className="tabular-nums text-neutral-500">{index + 1} / {items.length}</span>}
            <span>{item.day}{item.time ? ` · ${item.time}` : ""}{item.app ? ` · ${item.app}` : ""}</span>
            {item.url && (
              <button onClick={() => bridge?.openUrl(item.url)} title={item.url}
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-neutral-300 hover:bg-white/10">
                <Globe size={11} /> Open page
              </button>
            )}
            {item.ts && (
              <button onClick={() => { bridge?.openTimeline("timeline", { ts: item.ts }); onClose(); }}
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-neutral-300 hover:bg-white/10">
                <History size={11} /> Timeline
              </button>
            )}
          </div>
          <div className="text-[14px] font-medium text-neutral-100">{item.title}</div>
          {item.excerpt && <div className="mt-1 text-[13px] text-neutral-400">{item.excerpt}</div>}
        </motion.div>
      </div>
    </motion.div>
  );
}

export default function Answer({ answer, onClose, openIndex, setOpenIndex, onFollowUp, onCopied }) {
  // The open screenshot is App's state: "Jimmy, show me the best match", "next",
  // "close" (D33) and clicks all move the same index.
  const open = answer.evidence?.[openIndex] ? openIndex : null;
  const setOpen = setOpenIndex;
  const close = () => setOpenIndex(null);
  return (
    <>
      {["screen", "draft", "event"].includes(answer.mode) && answer.evidence?.length > 0 && <ScreenNow answer={answer} onOpen={setOpen} />}
      {answer.mode === "screen" && !answer.evidence?.length && <ScreenNow answer={answer} onOpen={setOpen} />}
      {answer.mode === "recall" && <Evidence answer={answer} onOpen={setOpen} />}
      {answer.mode === "stats" && <StatsPanel answer={answer} />}
      <Reply answer={answer} onClose={onClose} onFollowUp={onFollowUp} onCopied={onCopied} />
      <AnimatePresence>
        {open != null && answer.evidence?.length > 0 && (
          <Lightbox key="lb" items={answer.evidence} index={open} setIndex={setOpen} onClose={close} />
        )}
      </AnimatePresence>
    </>
  );
}
