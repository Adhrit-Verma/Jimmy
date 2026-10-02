import { useEffect, useRef, useState } from "react";
import { animate, motion } from "motion/react";
import { Activity, AppWindow, Ear, Hourglass, ScanText, ShieldCheck, Shuffle } from "lucide-react";

// D31: where the day went, drawn from captures already on disk. The pieces here
// (colours, bars, the day map) are shared with the overlay's "how was my day?" panel.

// The reference categorical palette, dark-surface steps (validated as a set).
const CAT = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
// Colour follows the app, never its rank: the same app is the same colour every day.
const FIXED = { Chrome: 0, Claude: 1, "VS Code": 2, Teams: 4, Discord: 6 };
const FREE = [3, 5, 7];
export const OTHER = "#5c5c58";

// ponytail: apps outside FIXED hash into the three free slots, so two of them can
// share a colour (never with a FIXED app). Every mark is also labelled by name;
// give an app its own slot here if it matters.
export function colorOf(app) {
  if (app in FIXED) return CAT[FIXED[app]];
  let h = 7;
  for (const c of app || "") h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return CAT[FREE[h % FREE.length]];
}

export const hm = (ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
export function short(ms) {
  const m = Math.round(ms / 60_000);
  if (m < 1) return ms > 0 ? "<1m" : "0m";
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
const pct = (a, b) => `${Math.round((100 * a) / Math.max(1, b))}%`;
const spring = { type: "spring", stiffness: 160, damping: 24 };

// One tooltip per chart, following the pointer, kept on screen.
export function useTip() {
  const [tip, setTip] = useState(null);
  const bind = (content) => ({
    onMouseMove: (e) => setTip({ x: e.clientX, y: e.clientY, content }),
    onMouseLeave: () => setTip(null),
  });
  const node = tip && (
    <div
      className="pointer-events-none fixed z-[60] -translate-x-1/2 whitespace-nowrap rounded-lg bg-neutral-800/95 px-2.5 py-1.5 text-[12px] text-neutral-100 shadow-xl ring-1 ring-white/10"
      style={{ left: Math.min(Math.max(tip.x, 90), window.innerWidth - 90), top: tip.y - 38 }}
    >
      {tip.content}
    </div>
  );
  return [node, bind];
}

export function CountUp({ value, format }) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const c = animate(from.current, value || 0, {
      duration: 0.9, ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => { from.current = v; setShown(v); },
    });
    return () => c.stop();
  }, [value]);
  return format ? format(shown) : Math.round(shown).toLocaleString();
}

// Horizontal bars, longest first; the tail folds into "Other".
export function AppBars({ apps, total, max = 6, highlight, onPick }) {
  const [tip, bind] = useTip();
  const top = apps.slice(0, max);
  const rest = apps.slice(max).reduce((s, a) => s + a.ms, 0);
  const rows = rest > 0 ? [...top, { app: "Other", ms: rest, other: true }] : top;
  const peak = Math.max(1, ...rows.map((r) => r.ms));
  return (
    <div className="space-y-1">
      {rows.map((a, i) => {
        const color = a.other ? OTHER : colorOf(a.app);
        return (
          <button
            key={a.app} type="button" {...bind(`${a.app} · ${short(a.ms)} · ${pct(a.ms, total)} of the time`)}
            onClick={() => !a.other && onPick?.(a.app)}
            className={`grid w-full grid-cols-[minmax(0,7.5rem)_1fr_3.6rem] items-center gap-2.5 rounded-md px-1.5 py-1 text-left transition
              ${onPick && !a.other ? "hover:bg-white/[0.05]" : "cursor-default"}
              ${highlight && highlight !== a.app ? "opacity-40" : ""}`}
          >
            <span className="flex min-w-0 items-center gap-2 text-[12.5px] text-neutral-200">
              <span className="size-2 shrink-0 rounded-full" style={{ background: color }} />
              <span className="truncate">{a.app}</span>
            </span>
            <span className="h-2 overflow-hidden rounded-full bg-white/[0.04]">
              <motion.span
                className="block h-full rounded-full" style={{ background: color }}
                initial={{ width: 0 }} animate={{ width: `${Math.max(2, (100 * a.ms) / peak)}%` }}
                transition={{ ...spring, delay: i * 0.04 }}
              />
            </span>
            <span className="text-right text-[12px] tabular-nums text-neutral-400">{short(a.ms)}</span>
          </button>
        );
      })}
      {tip}
    </div>
  );
}

// A strip of time: one coloured block per stretch in one app. Click to jump there.
export function Ribbon({ runs, since, until, onPick, marker, dim, colorFor = colorOf, className = "h-3" }) {
  const [tip, bind] = useTip();
  const span = Math.max(1, until - since);
  const x = (t) => `${(100 * (Math.min(Math.max(t, since), until) - since)) / span}%`;
  return (
    <div className={`relative rounded-[4px] bg-white/[0.04] ${className}`}>
      {runs.map((r) => (
        <div
          key={`${r.app}-${r.start}`} {...bind(`${r.app} · ${hm(r.start)}–${hm(r.end)} · ${short(r.end - r.start)}`)}
          onClick={() => onPick?.(r.start)}
          className={`absolute inset-y-0 rounded-[2px] transition-opacity hover:brightness-125 ${onPick ? "cursor-pointer" : ""}`}
          style={{
            left: x(r.start), width: `max(2px, calc(${x(r.end)} - ${x(r.start)}))`,
            background: colorFor(r.app), opacity: dim && dim !== r.app ? 0.18 : 1,
            boxShadow: "inset 1px 0 0 rgba(10,10,10,0.9)",
          }}
        />
      ))}
      {marker != null && marker >= since && marker <= until && (
        <motion.div layout className="pointer-events-none absolute -inset-y-1 w-[2px] rounded bg-white shadow-[0_0_8px_rgba(255,255,255,0.7)]"
          style={{ left: x(marker) }} transition={{ type: "spring", stiffness: 500, damping: 40 }} />
      )}
      {tip}
    </div>
  );
}

export function Axis({ since, until }) {
  const span = until - since;
  const step = (span > 14 * 3600e3 ? 3 : span > 6 * 3600e3 ? 2 : 1) * 3600e3;
  const first = new Date(since);
  first.setMinutes(0, 0, 0);
  const ticks = [];
  for (let t = first.getTime() + (first.getTime() < since ? 3600e3 : 0); t <= until; t += 3600e3) {
    if (new Date(t).getHours() % (step / 3600e3) === 0) ticks.push(t);
  }
  return (
    <div className="relative mt-1.5 h-4 text-[10.5px] tabular-nums text-neutral-500">
      {ticks.map((t) => (
        <span key={t} className="absolute -translate-x-1/2" style={{ left: `clamp(16px, ${(100 * (t - since)) / span}%, calc(100% - 16px))` }}>
          {new Date(t).getHours().toString().padStart(2, "0")}:00
        </span>
      ))}
    </div>
  );
}

// The active stretch of a day, widened to whole hours, for the day map.
export function dayRange(d) {
  if (!d?.first) return [d?.since || 0, d?.until || 1];
  const lo = new Date(d.first);
  lo.setMinutes(0, 0, 0);
  const hi = new Date(d.last);
  if (hi.getMinutes() || hi.getSeconds()) hi.setHours(hi.getHours() + 1, 0, 0, 0);
  return [lo.getTime(), Math.max(hi.getTime(), lo.getTime() + 3600e3)];
}

function HourBars({ hours, order }) {
  const [tip, bind] = useTip();
  const tot = hours.map((h) => Object.values(h).reduce((a, b) => a + b, 0));
  const on = tot.map((t, i) => (t > 0 ? i : -1)).filter((i) => i >= 0);
  if (!on.length) return null;
  let lo = Math.min(...on), hi = Math.max(...on);
  while (hi - lo < 5) { if (lo > 0) lo -= 1; if (hi - lo < 5 && hi < 23) hi += 1; }
  const peak = Math.max(...tot, 1);
  const cols = [];
  for (let h = lo; h <= hi; h++) cols.push(h);
  return (
    <div>
      <div className="flex h-32 items-end gap-[3px]">
        {cols.map((h, i) => {
          const segs = order.filter((a) => hours[h][a]).map((a) => [a, hours[h][a]]);
          const label = `${String(h).padStart(2, "0")}:00 · ${short(tot[h])}` +
            (segs.length ? ` · ${segs.slice(0, 3).map(([a, ms]) => `${a} ${short(ms)}`).join(", ")}` : "");
          return (
            <div key={h} {...bind(label)} className="flex h-full flex-1 flex-col-reverse gap-[2px] rounded-sm hover:bg-white/[0.03]">
              {segs.map(([a, ms]) => (
                <motion.div
                  key={a} className="w-full rounded-[2px] first:rounded-b-[4px] last:rounded-t-[4px]"
                  style={{ background: colorOf(a), height: `${(100 * ms) / peak}%`, originY: 1 }}
                  initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} transition={{ ...spring, delay: i * 0.02 }}
                />
              ))}
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex gap-[3px] text-[10.5px] tabular-nums text-neutral-500">
        {cols.map((h) => <span key={h} className="flex-1 text-center">{h % 3 === 0 ? String(h).padStart(2, "0") : ""}</span>)}
      </div>
      {tip}
    </div>
  );
}

function WeekHeat({ week, day, onDay }) {
  const [tip, bind] = useTip();
  const peak = Math.max(30 * 60_000, ...week.flatMap((w) => w.hours));
  return (
    <div>
      <div className="space-y-[3px]">
        {week.map((w) => (
          <div key={w.day} className="flex items-center gap-2">
            <button onClick={() => onDay?.(w.day)}
              className={`w-9 shrink-0 text-left text-[11px] ${w.day === day ? "font-semibold text-neutral-100" : "text-neutral-500 hover:text-neutral-300"}`}>
              {w.label}
            </button>
            <div className="grid flex-1 gap-[2px]" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}>
              {w.hours.map((ms, h) => (
                <div key={h} onClick={() => onDay?.(w.day)} {...bind(`${w.label} ${String(h).padStart(2, "0")}:00 · ${short(ms)}`)}
                  className={`aspect-square cursor-pointer rounded-[3px] transition hover:ring-1 hover:ring-white/40 ${w.day === day ? "ring-1 ring-white/[0.06]" : ""}`}
                  style={{ background: ms ? `rgba(57,135,229,${0.15 + (0.85 * ms) / peak})` : "rgba(255,255,255,0.03)" }} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex pl-11 text-[10.5px] text-neutral-500">
        {[0, 6, 12, 18].map((h) => <span key={h} className="flex-1">{String(h).padStart(2, "0")}:00</span>)}
      </div>
      {tip}
    </div>
  );
}

function Tile({ icon: Icon, label, value, sub, color, i }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring, delay: i * 0.05 }}
      className="rounded-xl bg-white/[0.03] p-3.5 ring-1 ring-white/[0.06]"
    >
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-neutral-500">
        <Icon size={12} /> {label}
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-[22px] font-semibold tabular-nums text-neutral-50">
        {color && <span className="size-2.5 shrink-0 rounded-full" style={{ background: color }} />}
        <span className="truncate">{value}</span>
      </div>
      <div className="mt-0.5 truncate text-[12px] text-neutral-500">{sub}</div>
    </motion.div>
  );
}

function Panel({ title, right, children, className = "" }) {
  return (
    <section className={`rounded-xl bg-white/[0.03] p-4 ring-1 ring-white/[0.06] ${className}`}>
      <div className="mb-3 flex items-center justify-between text-[11px] uppercase tracking-wider text-neutral-500">
        <span>{title}</span>{right}
      </div>
      {children}
    </section>
  );
}

// The day map: one lane per app, so "where was I" reads at a glance.
function DayMap({ d, onJump }) {
  const [lo, hi] = dayRange(d);
  const lanes = d.apps.slice(0, 6).map((a) => a.app);
  const rest = d.runs.filter((r) => !lanes.includes(r.app));
  return (
    <div className="space-y-1.5">
      {lanes.map((app) => (
        <div key={app} className="grid grid-cols-[7.5rem_1fr] items-center gap-3">
          <span className="flex min-w-0 items-center gap-2 text-[12px] text-neutral-300">
            <span className="size-2 shrink-0 rounded-full" style={{ background: colorOf(app) }} />
            <span className="truncate">{app}</span>
          </span>
          <Ribbon runs={d.runs.filter((r) => r.app === app)} since={lo} until={hi} onPick={onJump} className="h-4" />
        </div>
      ))}
      {rest.length > 0 && (
        <div className="grid grid-cols-[7.5rem_1fr] items-center gap-3">
          <span className="flex items-center gap-2 text-[12px] text-neutral-500">
            <span className="size-2 rounded-full" style={{ background: OTHER }} /> Other
          </span>
          <Ribbon runs={rest} since={lo} until={hi} onPick={onJump} colorFor={() => OTHER} className="h-4" />
        </div>
      )}
      <div className="grid grid-cols-[7.5rem_1fr] gap-3"><span /><Axis since={lo} until={hi} /></div>
    </div>
  );
}

export default function Insights({ data: d, loading, onJump, onDay }) {
  if (!d) {
    return (
      <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3 p-5">
        {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-[92px] animate-pulse rounded-xl bg-white/[0.04]" />)}
      </div>
    );
  }
  if (!d.active_ms) {
    return <div className="grid flex-1 place-items-center text-[14px] text-neutral-500">No captures this day.</div>;
  }
  const top = d.apps[0];
  const activeH = Math.max(1, d.active_ms / 3600e3);
  const tiles = [
    { icon: Hourglass, label: "On screen", value: <CountUp value={d.active_ms} format={short} />,
      sub: `${hm(d.first)} – ${hm(d.last)}` },
    { icon: AppWindow, label: "Most used", value: top.app, color: colorOf(top.app),
      sub: `${short(top.ms)} · ${pct(top.ms, d.active_ms)} of the day` },
    { icon: Activity, label: "Longest stretch", value: <CountUp value={d.longest?.ms || 0} format={short} />,
      sub: d.longest ? `${d.longest.app} from ${hm(d.longest.start)}` : "" },
    { icon: Shuffle, label: "App switches", value: <CountUp value={d.switches} />,
      sub: `${(d.switches / activeH).toFixed(1)} an hour` },
    { icon: Ear, label: "Heard", value: <CountUp value={d.speech.ms} format={short} />,
      sub: `${d.speech.segments} line${d.speech.segments === 1 ? "" : "s"} · ${d.commands} to Jimmy` },
    { icon: ScanText, label: "New text", value: <CountUp value={d.words} />, sub: "words that appeared on screen" },
  ];
  return (
    <div data-scroll="insights" className={`min-h-0 flex-1 space-y-3 overflow-y-auto px-5 pb-6 pt-4 transition-opacity [scrollbar-width:thin] ${loading ? "opacity-50" : ""}`}>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] gap-3">
        {tiles.map((t, i) => <Tile key={t.label} i={i} {...t} />)}
      </div>
      <Panel title="Day map" right={<span className="normal-case tracking-normal">click a block to open that moment</span>}>
        <DayMap d={d} onJump={onJump} />
      </Panel>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Where the time went"><AppBars apps={d.apps} total={d.active_ms} max={7} /></Panel>
        <Panel title="Hour by hour"><HourBars hours={d.hours} order={d.apps.map((a) => a.app)} /></Panel>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="This week" right={<span className="normal-case tracking-normal">pick a day</span>}>
          <WeekHeat week={d.week} day={d.day} onDay={onDay} />
        </Panel>
        <Panel title="Most time on">
          <div className="space-y-1">
            {d.titles.map((t) => (
              <div key={`${t.app}-${t.title}`} className="flex items-center gap-2.5 rounded-md px-1.5 py-1 text-[12.5px]">
                <span className="size-2 shrink-0 rounded-full" style={{ background: colorOf(t.app) }} />
                <span className="min-w-0 flex-1 truncate text-neutral-200">{t.title}</span>
                <span className="shrink-0 tabular-nums text-neutral-500">{short(t.ms)}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
      <p className="flex items-center gap-1.5 px-1 text-[11.5px] text-neutral-500">
        <ShieldCheck size={12} />
        {d.faces} face{d.faces === 1 ? "" : "s"} blurred · {(d.cards.shown || 0) + (d.cards.dismissed || 0)} cards ·
        estimated: each capture counts until the next; gaps over {Math.round((d.gap_s || 300) / 60)} min count as away.
      </p>
    </div>
  );
}
