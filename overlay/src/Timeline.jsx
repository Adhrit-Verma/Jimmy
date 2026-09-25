import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ChevronLeft, ChevronRight, Mic, Search, X } from "lucide-react";

// Stage 5: "what was that thing I saw on Tuesday". A day of blurred thumbnails
// on a scrub strip, the text each capture stored, speech nearby, and a search
// that understands meaning and times ("pricing page on Tuesday").
const bridge = window.jimmy;
const thumbCache = new Map();          // thumb path -> data URL (images arrive via the main process)

const hm = (ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const niceDay = (d) =>
  new Date(`${d}T00:00`).toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
const appName = (a) => (a || "").replace(/\.exe$/i, "");

export function useThumb(path) {
  const [src, setSrc] = useState(path ? thumbCache.get(path) : null);
  useEffect(() => {
    if (!path || thumbCache.has(path)) {
      setSrc(thumbCache.get(path) || null);
      return;                                      // effects return nothing or a cleanup (D26)
    }
    let live = true;
    bridge?.get("thumb", { path }).then((r) => {
      if (r?.data) thumbCache.set(path, r.data);
      if (live) setSrc(r?.data || null);
    });
    return () => { live = false; };
  }, [path]);
  return src;
}

export function Thumb({ path, className }) {
  const src = useThumb(path);
  return src
    ? <img src={src} className={`object-cover ${className}`} draggable={false} />
    : <div className={`bg-white/[0.04] ${className}`} />;
}

// One tile per minute that has captures, so a full day stays a short strip.
function Strip({ frames, selected, onSelect }) {
  const minutes = useMemo(() => {
    const out = [];
    for (const [i, f] of frames.entries()) {
      const key = Math.floor(f.ts / 60_000);
      if (!out.length || out[out.length - 1].key !== key) out.push({ key, first: i, frame: f });
    }
    return out;
  }, [frames]);
  const ref = useRef(null);
  const activeKey = frames[selected] ? Math.floor(frames[selected].ts / 60_000) : null;

  useEffect(() => {
    ref.current?.querySelector("[data-active=true]")?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }, [activeKey]);

  return (
    <div ref={ref} className="flex gap-2 overflow-x-auto px-5 pb-4 pt-3 [scrollbar-width:thin]">
      {minutes.map((m) => {
        const active = m.key === activeKey;
        return (
          <button
            key={m.key}
            data-active={active}
            onClick={() => onSelect(m.first)}
            className="group shrink-0 text-left"
          >
            <Thumb
              path={m.frame.thumb_path}
              className={`h-[68px] w-[120px] rounded-lg ring-1 transition ${active ? "ring-2 ring-emerald-400/80" : "ring-white/10 opacity-70 group-hover:opacity-100"}`}
            />
            <div className={`mt-1 text-[11px] ${active ? "text-neutral-200" : "text-neutral-500"}`}>{hm(m.frame.ts)}</div>
          </button>
        );
      })}
    </div>
  );
}

function Preview({ frame }) {
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    setDetail(null);
    if (frame) bridge?.get("frame", { id: frame.id }).then(setDetail);
  }, [frame?.id]);
  if (!frame) return <div className="grid flex-1 place-items-center text-neutral-500">No captures this day.</div>;

  const text = (detail?.text || []).map((t) => t.text).join("\n");
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-5 px-5">
      <div className="min-h-0">
        <Thumb path={frame.thumb_path} className="aspect-video w-full rounded-xl ring-1 ring-white/10" />
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-[15px] font-medium text-neutral-100">{hm(frame.ts)}</span>
          <span className="text-[13px] text-neutral-400">{appName(frame.app)}</span>
          {frame.face_count > 0 && <span className="text-[11px] text-neutral-500">· {frame.face_count} face(s) blurred</span>}
        </div>
        <div className="truncate text-[13px] text-neutral-500">{frame.title}</div>
      </div>
      <div className="flex min-h-0 flex-col gap-3">
        <section className="min-h-0 flex-1 overflow-y-auto rounded-xl bg-white/[0.03] p-3 ring-1 ring-white/[0.06]">
          <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-neutral-500">New on screen</h3>
          <p className="whitespace-pre-line break-words text-[13px] leading-relaxed text-neutral-300 [overflow-wrap:anywhere]">
            {text || <span className="text-neutral-500">Nothing new: the same screen as the capture before.</span>}
          </p>
        </section>
        {detail?.speech?.length > 0 && (
          <section className="max-h-[35%] overflow-y-auto rounded-xl bg-white/[0.03] p-3 ring-1 ring-white/[0.06]">
            <h3 className="mb-1.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-neutral-500">
              <Mic size={11} /> Heard nearby
            </h3>
            {detail.speech.map((s) => (
              <p key={s.ts_start} className="text-[13px] leading-relaxed text-neutral-300">
                <span className="mr-2 text-neutral-500">{hm(s.ts_start)}</span>{s.text}
              </p>
            ))}
          </section>
        )}
      </div>
    </div>
  );
}

function Results({ data, onPick, onClose }) {
  return (
    <motion.aside
      initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -16 }}
      className="flex w-[360px] shrink-0 flex-col border-r border-white/[0.06]"
    >
      <div className="flex items-center justify-between px-4 py-2.5 text-[11px] uppercase tracking-wider text-neutral-500">
        <span>{data.results.length} results{data.window ? ` · ${data.window}` : ""}</span>
        <button onClick={onClose} aria-label="Close results" className="rounded p-1 hover:bg-white/10"><X size={12} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {data.results.length === 0 && <p className="px-2 text-[13px] text-neutral-500">Nothing found.</p>}
        {data.results.map((r) => (
          <button key={r.ref} onClick={() => onPick(r)}
            className="mb-1 w-full rounded-lg px-2.5 py-2 text-left hover:bg-white/[0.06]">
            <div className="flex items-center gap-2 text-[11px] text-neutral-500">
              <span>{new Date(r.ts).toLocaleDateString([], { weekday: "short" })} {hm(r.ts)}</span>
              <span className="truncate">{r.ref > 0 ? appName(r.app) : "heard"}</span>
              <span className="ml-auto rounded bg-white/[0.06] px-1.5 py-px">{r.via}</span>
            </div>
            <p className="mt-0.5 line-clamp-2 text-[13px] text-neutral-200">{r.text}</p>
          </button>
        ))}
      </div>
    </motion.aside>
  );
}

export default function Timeline() {
  const [data, setData] = useState({ day: null, days: [], frames: [] });
  const [selected, setSelected] = useState(0);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const jumpTo = useRef(null);         // ts to select once a day has loaded

  const load = useCallback((day) => {
    bridge?.get("timeline", day ? { day } : {}).then((d) => {
      if (!d) return;
      setData(d);
      let i = d.frames.length - 1;
      if (jumpTo.current != null) {
        const t = jumpTo.current;
        i = d.frames.reduce((best, f, k) => (Math.abs(f.ts - t) < Math.abs(d.frames[best].ts - t) ? k : best), 0);
        jumpTo.current = null;
      }
      setSelected(Math.max(0, i));
    });
  }, []);
  useEffect(() => {
    load(null);
    // Deep link: #timeline?q=... opens with that search already run.
    const q = new URLSearchParams(location.hash.split("?")[1] || "").get("q");
    if (q) {
      setQuery(q);
      bridge?.get("search", { q }).then(setResults);
    }
  }, [load]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === "INPUT") return;
      if (e.key === "ArrowRight") setSelected((s) => Math.min(s + 1, data.frames.length - 1));
      if (e.key === "ArrowLeft") setSelected((s) => Math.max(s - 1, 0));
      if (e.key === "Escape") bridge?.closeWindow();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [data.frames.length]);

  const dayIdx = data.days.indexOf(data.day);
  const search = async (e) => {
    e.preventDefault();
    if (!query.trim()) return setResults(null);
    setBusy(true);
    setResults(await bridge?.get("search", { q: query }));
    setBusy(false);
  };
  const pick = (r) => {
    const day = new Date(r.ts).toLocaleDateString("sv");   // YYYY-MM-DD in local time
    jumpTo.current = r.ts;
    load(day);
  };

  return (
    <div className="flex h-screen flex-col bg-neutral-950 text-neutral-200">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-white/[0.06] px-4 [-webkit-app-region:drag]">
        <span className="flex items-center gap-2 text-[13px]">
          <span className="size-2 rounded-full bg-emerald-400" />
          <span className="font-medium text-neutral-100">Jimmy</span>
          <span className="text-neutral-500">Timeline</span>
        </span>
        <div className="ml-4 flex items-center gap-1 [-webkit-app-region:no-drag]">
          <button disabled={dayIdx < 0 || dayIdx >= data.days.length - 1} onClick={() => load(data.days[dayIdx + 1])}
            aria-label="Earlier day" className="rounded-md p-1 hover:bg-white/10 disabled:opacity-30"><ChevronLeft size={16} /></button>
          <span className="min-w-40 text-center text-[13px] text-neutral-300">{data.day ? niceDay(data.day) : "…"}</span>
          <button disabled={dayIdx <= 0} onClick={() => load(data.days[dayIdx - 1])}
            aria-label="Later day" className="rounded-md p-1 hover:bg-white/10 disabled:opacity-30"><ChevronRight size={16} /></button>
        </div>
        <form onSubmit={search} className="mx-auto flex w-full max-w-md items-center gap-2 rounded-lg bg-white/[0.05] px-3 py-1.5 ring-1 ring-white/10 focus-within:ring-white/25 [-webkit-app-region:no-drag]">
          <Search size={14} className="text-neutral-500" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} autoFocus
            placeholder='What was that thing… e.g. "pricing page on Tuesday"'
            className="w-full bg-transparent text-[13px] text-neutral-100 outline-none placeholder:text-neutral-500" />
          {busy && <span className="size-3 animate-spin rounded-full border border-white/30 border-t-transparent" />}
        </form>
        <span className="text-[12px] text-neutral-500">{data.frames.length ? `${selected + 1} / ${data.frames.length}` : ""}</span>
        <button onClick={() => bridge?.closeWindow()} aria-label="Close"
          className="rounded-md p-1.5 text-neutral-400 hover:bg-white/10 hover:text-neutral-100 [-webkit-app-region:no-drag]"><X size={15} /></button>
      </header>
      <div className="flex min-h-0 flex-1">
        <AnimatePresence>
          {results && <Results data={results} onPick={pick} onClose={() => setResults(null)} />}
        </AnimatePresence>
        <main className="flex min-w-0 flex-1 flex-col pt-4">
          <Preview frame={data.frames[selected]} />
          <Strip frames={data.frames} selected={selected} onSelect={setSelected} />
        </main>
      </div>
    </div>
  );
}
