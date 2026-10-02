import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { BarChart3, ChevronLeft, ChevronRight, Globe, History, Mic, Search, X } from "lucide-react";
import Insights, { Axis, Ribbon, colorOf, dayRange, hm } from "./Insights.jsx";

// Stage 5: "what was that thing I saw on Tuesday". A day of blurred thumbnails
// on a scrub strip, the text each capture stored, speech nearby, and a search
// that understands meaning and times ("pricing page on Tuesday"). D31: the same
// window shows Insights (where the day went), and a day map to scrub by.
const bridge = window.jimmy;
const thumbCache = new Map();          // "path|width" -> data URL (images arrive via the main process)
const spring = { type: "spring", stiffness: 420, damping: 36 };

const niceDay = (d) =>
  new Date(`${d}T00:00`).toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
const dayOf = (ts) => new Date(ts).toLocaleDateString("sv");   // YYYY-MM-DD in local time

// ponytail: a plain insertion-ordered Map trimmed to 400 entries. Full-size
// thumbs are ~200 KB of base64 each; the strip asks for 320 px ones (~15 KB).
function remember(key, data) {
  thumbCache.delete(key);
  thumbCache.set(key, data);
  if (thumbCache.size > 400) thumbCache.delete(thumbCache.keys().next().value);
}

// `w`: ask for a scaled-down copy. `lazyRef`: fetch only once it scrolls into view.
export function useThumb(path, w, lazyRef) {
  const key = path ? `${path}|${w || ""}` : null;
  const [src, setSrc] = useState(key ? thumbCache.get(key) : null);
  const [seen, setSeen] = useState(!lazyRef);
  useEffect(() => {
    if (seen || !lazyRef?.current) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setSeen(true); io.disconnect(); }
    }, { rootMargin: "600px" });
    io.observe(lazyRef.current);
    return () => io.disconnect();
  }, [seen, lazyRef]);
  useEffect(() => {
    if (!key || !seen) return;
    if (thumbCache.has(key)) {
      setSrc(thumbCache.get(key));
      return;                                      // effects return nothing or a cleanup (D26)
    }
    let live = true;
    bridge?.get("thumb", w ? { path, w } : { path }).then((r) => {
      if (r?.data) remember(key, r.data);
      if (live) setSrc(r?.data || null);
    });
    return () => { live = false; };
  }, [key, seen]);
  return src;
}

export function Thumb({ path, className, w, lazy }) {
  const ref = useRef(null);
  const src = useThumb(path, w, lazy ? ref : null);
  return src
    ? <img ref={ref} src={src} className={`object-cover ${className}`} draggable={false} />
    : <div ref={ref} className={`animate-pulse bg-white/[0.04] ${className}`} />;
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
          <button key={m.key} data-active={active} onClick={() => onSelect(m.first)} className="group shrink-0 text-left">
            <Thumb
              path={m.frame.thumb_path} w={320} lazy
              className={`h-[68px] w-[120px] rounded-lg ring-1 transition ${active ? "ring-2 ring-emerald-400/80" : "ring-white/10 opacity-70 group-hover:opacity-100"}`}
            />
            <div className="mt-1 h-[3px] rounded-full" style={{ background: colorOf(m.frame.name), opacity: active ? 1 : 0.55 }} />
            <div className={`mt-0.5 text-[11px] tabular-nums ${active ? "text-neutral-200" : "text-neutral-500"}`}>{hm(m.frame.ts)}</div>
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
  if (!frame) return <div className="grid flex-1 place-items-center text-neutral-500">No captures here.</div>;

  const text = (detail?.text || []).map((t) => t.text).join("\n");
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-5 px-5">
      <div className="min-h-0">
        <Thumb path={frame.thumb_path} className="aspect-video w-full rounded-xl ring-1 ring-white/10" />
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-[15px] font-medium tabular-nums text-neutral-100">{hm(frame.ts)}</span>
          <span className="flex items-center gap-1.5 text-[13px] text-neutral-400">
            <span className="size-2 rounded-full" style={{ background: colorOf(frame.name) }} />{frame.name}
          </span>
          {frame.face_count > 0 && <span className="text-[11px] text-neutral-500">· {frame.face_count} face(s) blurred</span>}
        </div>
        <div className="flex items-center gap-2">
          <span className="min-w-0 truncate text-[13px] text-neutral-500">{frame.title}</span>
          {frame.url && (
            <button onClick={() => bridge?.openUrl(frame.url)} title={frame.url}
              className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] text-neutral-300 hover:bg-white/10">
              <Globe size={12} /> Open page
            </button>
          )}
        </div>
      </div>
      <div className="flex min-h-0 flex-col gap-3">
        <section className="min-h-0 flex-1 overflow-y-auto rounded-xl bg-white/[0.03] p-3 ring-1 ring-white/[0.06] [scrollbar-width:thin]">
          <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-neutral-500">New on screen</h3>
          {!detail ? (
            <div className="space-y-2">{[90, 70, 80].map((w) => <div key={w} className="h-3 animate-pulse rounded bg-white/[0.05]" style={{ width: `${w}%` }} />)}</div>
          ) : (
            <p className="whitespace-pre-line break-words text-[13px] leading-relaxed text-neutral-300 [overflow-wrap:anywhere] select-text">
              {text || <span className="text-neutral-500">Nothing new: the same screen as the capture before.</span>}
            </p>
          )}
        </section>
        {detail?.speech?.length > 0 && (
          <section className="max-h-[35%] overflow-y-auto rounded-xl bg-white/[0.03] p-3 ring-1 ring-white/[0.06]">
            <h3 className="mb-1.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-neutral-500">
              <Mic size={11} /> Heard nearby
            </h3>
            {detail.speech.map((s) => (
              <p key={s.ts_start} className="text-[13px] leading-relaxed text-neutral-300">
                <span className="mr-2 tabular-nums text-neutral-500">{hm(s.ts_start)}</span>{s.text}
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
      initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -16 }} transition={spring}
      className="flex w-[360px] shrink-0 flex-col border-r border-white/[0.06]"
    >
      <div className="flex items-center justify-between px-4 py-2.5 text-[11px] uppercase tracking-wider text-neutral-500">
        <span>{data.results.length} results{data.window ? ` · ${data.window}` : ""}</span>
        <button onClick={onClose} aria-label="Close results" className="rounded p-1 hover:bg-white/10"><X size={12} /></button>
      </div>
      <div data-scroll className="min-h-0 flex-1 overflow-y-auto px-2 pb-3 [scrollbar-width:thin]">
        {data.results.length === 0 && <p className="px-2 text-[13px] text-neutral-500">Nothing found. Try fewer words, or another day.</p>}
        {data.results.map((r, i) => (
          <motion.button key={r.ref} onClick={() => onPick(r)}
            initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: Math.min(i, 10) * 0.025 }}
            className="mb-1 w-full rounded-lg px-2.5 py-2 text-left hover:bg-white/[0.06]">
            <div className="flex items-center gap-2 text-[11px] text-neutral-500">
              <span className="tabular-nums">{new Date(r.ts).toLocaleDateString([], { weekday: "short" })} {hm(r.ts)}</span>
              <span className="truncate">{r.ref > 0 ? (r.app || "").replace(/\.exe$/i, "") : "heard"}</span>
              <span className="ml-auto rounded bg-white/[0.06] px-1.5 py-px">{r.via}</span>
            </div>
            <p className="mt-0.5 line-clamp-2 text-[13px] text-neutral-200">{r.text}</p>
          </motion.button>
        ))}
      </div>
    </motion.aside>
  );
}

// The day as coloured blocks, with the selected moment marked; pick an app to filter.
function DayBar({ ins, frame, filter, setFilter, onPick }) {
  if (!ins?.runs?.length) return null;
  const [lo, hi] = dayRange(ins);
  const chip = (app, label = app) => (
    <button key={app || "all"} onClick={() => setFilter(app)}
      className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11.5px] transition
        ${filter === app ? "bg-white/15 text-neutral-100" : "text-neutral-400 hover:bg-white/[0.06] hover:text-neutral-200"}`}>
      {app && <span className="size-2 rounded-full" style={{ background: colorOf(app) }} />}{label}
    </button>
  );
  return (
    <div className="px-5 pt-3">
      <div className="mb-2 flex flex-wrap items-center gap-1">
        {chip(null, "All apps")}
        {ins.apps.slice(0, 7).map((a) => chip(a.app))}
      </div>
      <Ribbon runs={ins.runs} since={lo} until={hi} marker={frame?.ts} dim={filter} onPick={onPick} className="h-3.5" />
      <Axis since={lo} until={hi} />
    </div>
  );
}

function Tabs({ view, setView }) {
  return (
    <div className="flex rounded-lg bg-white/[0.05] p-0.5 [-webkit-app-region:no-drag]">
      {[["timeline", History, "Timeline"], ["insights", BarChart3, "Insights"]].map(([v, Icon, label], i) => (
        <button key={v} onClick={() => setView(v)} title={`${label} (${i + 1})`}
          className={`relative flex items-center gap-1.5 rounded-md px-3 py-1 text-[12.5px] transition ${view === v ? "text-neutral-50" : "text-neutral-400 hover:text-neutral-200"}`}>
          {view === v && <motion.span layoutId="tab" className="absolute inset-0 rounded-md bg-white/10" transition={spring} />}
          <Icon size={13} className="relative" /><span className="relative">{label}</span>
        </button>
      ))}
    </div>
  );
}

const startView = location.hash.startsWith("#insights") ? "insights" : "timeline";

// "chrome" -> "Chrome", whichever app on this day the words name; null if none.
function appIn(frames, words) {
  const w = (words || "").toLowerCase().trim();
  if (!w) return null;
  const names = [...new Set(frames.map((f) => f.name).filter(Boolean))];
  return names.find((n) => n.toLowerCase() === w) || names.find((n) => n.toLowerCase().includes(w) || w.includes(n.toLowerCase())) || null;
}

export default function Timeline() {
  const [view, setView] = useState(startView);
  const [data, setData] = useState({ day: null, days: [], frames: [] });
  const [ins, setIns] = useState(null);
  const [insLoading, setInsLoading] = useState(false);
  const [selected, setSelected] = useState(0);
  const [filter, setFilter] = useState(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const jumpTo = useRef(null);         // ts to select once a day has loaded
  const wantFilter = useRef(null);     // an app to filter to once a day has loaded
  const input = useRef(null);
  const latest = useRef({});           // current state, for handlers registered once
  const onUi = useRef(() => {});

  const shown = useMemo(() => (filter ? data.frames.filter((f) => f.name === filter) : data.frames),
                        [data.frames, filter]);
  const nearest = (frames, t) =>
    frames.reduce((best, f, k) => (Math.abs(f.ts - t) < Math.abs(frames[best].ts - t) ? k : best), 0);

  const load = useCallback((day) => {
    bridge?.get("timeline", day ? { day } : {}).then((d) => {
      if (!d) return;
      setData(d);
      setFilter(appIn(d.frames, wantFilter.current));
      wantFilter.current = null;
      setSelected(jumpTo.current != null && d.frames.length ? nearest(d.frames, jumpTo.current) : Math.max(0, d.frames.length - 1));
      jumpTo.current = null;
    });
  }, []);

  // Insights for the day on show: the Insights view, and the day bar above the strip.
  useEffect(() => {
    if (!data.day) return;
    let live = true;
    setInsLoading(true);
    bridge?.get("insights", { day: data.day }).then((r) => {
      if (!live) return;
      setIns(r);
      setInsLoading(false);
    });
    return () => { live = false; };
  }, [data.day]);

  const search = useCallback(async (q) => {
    if (!q.trim()) return setResults(null);
    setBusy(true);
    setResults(await bridge?.get("search", { q }));
    setBusy(false);
  }, []);

  // Deep links: #timeline?ts=…&q=…&filter=… on open, or a "goto" event when
  // already open ("Jimmy, show me yesterday at 3", "only Chrome", D33).
  const goto = useCallback((p, first = false) => {
    if (p.view) setView(p.view);
    if (p.q) { setQuery(p.q); search(p.q); }
    const loads = p.ts || p.day || first;
    if ("filter" in p) {
      if (loads) wantFilter.current = p.filter;
      else {
        const app = appIn(latest.current.frames || [], p.filter);
        const n = (app ? latest.current.frames.filter((f) => f.name === app) : latest.current.frames || []).length;
        setView("timeline");
        setFilter(app);
        setSelected(Math.max(0, n - 1));
      }
    }
    if (p.ts) { jumpTo.current = Number(p.ts); load(dayOf(Number(p.ts))); }
    else if (p.day || first) load(p.day || null);
  }, [load, search]);
  useEffect(() => {
    goto(Object.fromEntries(new URLSearchParams(location.hash.split("?")[1] || "")), true);
    return bridge?.onEvent((ev) => {
      if (ev.type === "goto") goto(ev);
      if (ev.type === "ui") onUi.current(ev);
    });
  }, [goto]);

  const dayIdx = data.days.indexOf(data.day);
  const older = dayIdx >= 0 && dayIdx < data.days.length - 1 ? data.days[dayIdx + 1] : null;
  const newer = dayIdx > 0 ? data.days[dayIdx - 1] : null;

  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === "INPUT") {
        if (e.key === "Escape") e.target.blur();
        return;
      }
      const n = shown.length;
      const step = e.shiftKey ? 10 : 1;
      if (e.key === "ArrowRight" && view === "timeline") setSelected((s) => Math.min(s + step, n - 1));
      else if (e.key === "ArrowLeft" && view === "timeline") setSelected((s) => Math.max(s - step, 0));
      else if (e.key === "Home") setSelected(0);
      else if (e.key === "End") setSelected(Math.max(0, n - 1));
      else if (e.key === "[" && older) load(older);
      else if (e.key === "]" && newer) load(newer);
      else if (e.key === "1") setView("timeline");
      else if (e.key === "2") setView("insights");
      else if (e.key === "/") { e.preventDefault(); input.current?.focus(); }
      else if (e.key === "Escape") bridge?.closeWindow();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown.length, view, older, newer, load]);

  latest.current = { frames: data.frames };
  // D33: "next", "scroll down", "previous day", "close" by voice.
  onUi.current = (ev) => {
    const n = shown.length;
    if (ev.action === "scroll") {
      const box = document.querySelector(view === "insights" ? "[data-scroll=insights]" : results ? "[data-scroll]" : null);
      if (box) box.scrollBy({ top: (ev.dir === "down" ? 1 : -1) * box.clientHeight * 0.7, behavior: "smooth" });
      else setSelected((s) => Math.max(0, Math.min(n - 1, s + (ev.dir === "down" ? 10 : -10))));
    } else if (ev.action === "step") {
      setView("timeline");
      setSelected((s) => Math.max(0, Math.min(n - 1, s + ev.by)));
    } else if (ev.action === "edge") {
      setView("timeline");
      setSelected(ev.to === "first" ? 0 : Math.max(0, n - 1));
    } else if (ev.action === "day") {
      if (ev.by > 0 && newer) load(newer);
      if (ev.by < 0 && older) load(older);
    } else if (ev.action === "close") bridge?.closeWindow();
  };

  const pick = (r) => {
    setView("timeline");
    jumpTo.current = r.ts;
    load(dayOf(r.ts));
  };
  const jump = (ts) => {                         // from the day map / day bar
    setView("timeline");
    if (dayOf(ts) !== data.day) { jumpTo.current = ts; load(dayOf(ts)); return; }
    setFilter(null);
    setSelected(nearest(data.frames, ts));
  };
  const frame = shown[selected] || shown[shown.length - 1];

  return (
    <div className="flex h-screen flex-col bg-neutral-950 text-neutral-200">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-white/[0.06] px-4 [-webkit-app-region:drag]">
        <span className="flex items-center gap-2 text-[13px]">
          <span className="size-2 rounded-full bg-emerald-400" />
          <span className="font-medium text-neutral-100">Jimmy</span>
        </span>
        <Tabs view={view} setView={setView} />
        <div className="ml-2 flex items-center gap-1 [-webkit-app-region:no-drag]">
          <button disabled={!older} onClick={() => load(older)} title="Earlier day ( [ )"
            aria-label="Earlier day" className="rounded-md p-1 hover:bg-white/10 disabled:opacity-30"><ChevronLeft size={16} /></button>
          <AnimatePresence mode="wait" initial={false}>
            <motion.span key={data.day} initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }}
              transition={{ duration: 0.12 }} className="min-w-40 text-center text-[13px] text-neutral-300">
              {data.day ? niceDay(data.day) : "…"}
            </motion.span>
          </AnimatePresence>
          <button disabled={!newer} onClick={() => load(newer)} title="Later day ( ] )"
            aria-label="Later day" className="rounded-md p-1 hover:bg-white/10 disabled:opacity-30"><ChevronRight size={16} /></button>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); setView("timeline"); search(query); }}
          className="mx-auto flex w-full max-w-md items-center gap-2 rounded-lg bg-white/[0.05] px-3 py-1.5 ring-1 ring-white/10 transition focus-within:bg-white/[0.07] focus-within:ring-white/25 [-webkit-app-region:no-drag]">
          <Search size={14} className="text-neutral-500" />
          <input ref={input} value={query} onChange={(e) => setQuery(e.target.value)} autoFocus={startView === "timeline"}
            placeholder='What was that thing… e.g. "pricing page on Tuesday"'
            className="w-full bg-transparent text-[13px] text-neutral-100 outline-none placeholder:text-neutral-500" />
          {busy ? <span className="size-3 animate-spin rounded-full border border-white/30 border-t-transparent" />
            : <kbd className="rounded bg-white/[0.06] px-1.5 text-[10.5px] text-neutral-500">/</kbd>}
        </form>
        <span className="text-[12px] tabular-nums text-neutral-500">
          {view === "timeline" && shown.length ? `${Math.min(selected, shown.length - 1) + 1} / ${shown.length}` : ""}
        </span>
        <button onClick={() => bridge?.closeWindow()} aria-label="Close" title="Close (Esc)"
          className="rounded-md p-1.5 text-neutral-400 hover:bg-white/10 hover:text-neutral-100 [-webkit-app-region:no-drag]"><X size={15} /></button>
      </header>
      <div className="flex min-h-0 flex-1">
        <AnimatePresence>
          {results && <Results data={results} onPick={pick} onClose={() => setResults(null)} />}
        </AnimatePresence>
        {view === "insights" ? (
          <Insights data={ins} loading={insLoading} onJump={jump} onDay={(d) => load(d)} />
        ) : (
          <main className="flex min-w-0 flex-1 flex-col pt-4">
            <Preview frame={frame} />
            <DayBar ins={ins} frame={frame} filter={filter} onPick={(ts) => setSelected(nearest(shown, ts))}
              setFilter={(app) => { setFilter(app); setSelected(Math.max(0, (app ? data.frames.filter((f) => f.name === app) : data.frames).length - 1)); }} />
            <Strip frames={shown} selected={selected} onSelect={setSelected} />
          </main>
        )}
      </div>
    </div>
  );
}
