import { useCallback, useEffect, useState } from "react";
import { motion } from "motion/react";
import { Check, Database, FolderOpen, Gauge, HardDrive, Loader2, Power, RotateCcw, Sparkles, Trash2, Zap } from "lucide-react";

// D60: Settings → Storage & performance, in the timeline window. What Jimmy uses, the
// limits (applied at once), the profile (at the next start), the caches, start with Windows.
const bridge = window.jimmy;
const GB = 1e9;
const size = (b) => (b >= GB ? `${(b / GB).toFixed(b >= 10 * GB ? 0 : 1)} GB` : `${Math.max(0, Math.round(b / 1e6))} MB`);
const card = "rounded-2xl bg-white/[0.035] p-5 ring-1 ring-white/[0.08]";
const PARTS = [["captures", "Captures", "#38bdf8"], ["thumbnails", "Screenshots", "#818cf8"], ["models", "Models", "#34d399"],
  ["runtime", "Jimmy's Python", "#fbbf24"], ["memory", "Memory", "#f472b6"], ["cache", "Downloads cache", "#a3a3a3"], ["logs", "Logs", "#737373"]];
const PROFILES = [["lite", "Lite", Gauge, "Lighter speech on the processor, no webcam"],
  ["balanced", "Balanced", Sparkles, "Best speech, GPU if there is one"], ["full", "Full", Zap, "+ local AI: recall by meaning"]];

function Section({ title, children, right }) {
  return (
    <section className={card}>
      <div className="mb-4 flex items-center justify-between"><h2 className="text-[13px] font-medium uppercase tracking-wider text-neutral-400">{title}</h2>{right}</div>
      {children}
    </section>
  );
}

export default function Settings() {
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [login, setLogin] = useState(null);

  const load = useCallback(() => bridge?.get("storage").then(setS).catch(() => setS({ error: true })), []);
  useEffect(() => { load(); bridge?.loginItem().then(setLogin); }, [load]);

  const change = async (changes) => {
    setBusy("settings");
    const r = await bridge?.api("settings", { changes });
    setBusy("");
    if (r?.settings) setS((x) => ({ ...x, settings: r.settings, bytes: r.usage?.bytes || x.bytes }));
    setNote(r?.restart ? "Saved. This one applies the next time Jimmy starts." : "Saved.");
  };
  const clear = async (what) => {
    setBusy(what);
    const r = await bridge?.api("storage_clear", { what });
    setBusy("");
    if (r?.usage) setS((x) => ({ ...x, bytes: r.usage.bytes }));
    setNote(r?.freed !== undefined ? `Freed ${size(r.freed)}.` : "");
  };

  if (!s) return <div className="flex h-full items-center justify-center text-neutral-500"><Loader2 className="animate-spin" size={18} /></div>;
  if (s.error) return <div className="p-8 text-[13px] text-neutral-500">Settings need Jimmy running.</div>;
  const st = s.settings || {};
  const parts = PARTS.filter(([k]) => s.bytes[k] !== undefined && s.bytes[k] > 0);
  const total = parts.reduce((a, [k]) => a + s.bytes[k], 0) || 1;

  return (
    <div data-scroll className="h-full overflow-y-auto px-6 py-5 [scrollbar-width:thin]">
      <div className="mx-auto grid max-w-[860px] gap-4">
        <Section title="Storage" right={<span className="text-[13px] text-neutral-300">{size(s.bytes.total)} in all</span>}>
          <div className="flex h-2.5 overflow-hidden rounded-full bg-white/[0.06]">
            {parts.map(([k, , c], i) => (
              <motion.div key={k} className="h-full" style={{ background: c }} initial={{ width: 0 }}
                animate={{ width: `${(100 * s.bytes[k]) / total}%` }} transition={{ delay: i * 0.04 }} />
            ))}
          </div>
          <div className="mt-3 grid grid-cols-4 gap-x-4 gap-y-2">
            {parts.map(([k, label, c]) => (
              <div key={k} className="flex items-center gap-2 text-[12.5px]">
                <span className="size-2 rounded-full" style={{ background: c }} />
                <span className="text-neutral-400">{label}</span><span className="ml-auto tabular-nums text-neutral-200">{size(s.bytes[k])}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-2 rounded-xl bg-black/30 px-3.5 py-2.5 text-[12.5px] text-neutral-400 ring-1 ring-white/[0.06]">
            <HardDrive size={14} className="text-sky-300" /> <span className="truncate">{s.data_dir}</span>
            <button onClick={() => bridge?.openData(s.data_dir)} className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-neutral-300 hover:bg-white/10"><FolderOpen size={13} /> Open</button>
          </div>
        </Section>

        <Section title="Limits">
          <div className="grid grid-cols-2 gap-6">
            <label className="block">
              <div className="flex justify-between text-[13px] text-neutral-300"><span>Keep captures for</span>
                <span className="text-sky-300">{st.retention_days ? `${st.retention_days} days` : "ever"}</span></div>
              <input type="range" min={0} max={5} value={Math.max(0, [7, 14, 30, 90, 365, 0].indexOf(st.retention_days))}
                onChange={(e) => setS((x) => ({ ...x, settings: { ...x.settings, retention_days: [7, 14, 30, 90, 365, 0][+e.target.value] } }))}
                onMouseUp={(e) => change({ retention_days: [7, 14, 30, 90, 365, 0][+e.target.value] })} className="mt-3 w-full accent-sky-400" />
            </label>
            <label className="block">
              <div className="flex justify-between text-[13px] text-neutral-300"><span>Never use more than</span>
                <span className="text-sky-300">{st.storage_cap_gb ? `${st.storage_cap_gb} GB` : "no limit"}</span></div>
              <input type="range" min={0} max={200} step={5} value={st.storage_cap_gb || 0}
                onChange={(e) => setS((x) => ({ ...x, settings: { ...x.settings, storage_cap_gb: +e.target.value } }))}
                onMouseUp={(e) => change({ storage_cap_gb: +e.target.value })} className="mt-3 w-full accent-sky-400" />
            </label>
          </div>
          <div className="mt-2 text-[12px] text-neutral-500">Applied now. The oldest days go first; today is always kept.</div>
        </Section>

        <Section title="Performance">
          <div className="grid grid-cols-3 gap-3">
            {PROFILES.map(([k, label, Icon, t]) => (
              <button key={k} onClick={() => change({ profile: k, local_ai: k === "full", ...(k === "lite" ? { whisper_model: "small", whisper_device: "cpu", webcam: false } : { whisper_model: "", whisper_device: "" }) })}
                className={`rounded-xl p-3.5 text-left ring-1 transition ${st.profile === k ? "bg-sky-500/[0.12] ring-sky-400/60" : "bg-white/[0.03] ring-white/[0.08] hover:bg-white/[0.06]"}`}>
                <Icon size={16} className={st.profile === k ? "text-sky-300" : "text-neutral-400"} />
                <div className="mt-2 text-[14px] text-neutral-100">{label}</div>
                <div className="mt-0.5 text-[12px] text-neutral-500">{t}</div>
              </button>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3">
            {[["webcam", "Privacy curtain (webcam)"], ["local_ai", "Local AI (needs the Full setup's models)"],
              ["auto_update", "Update Jimmy automatically"]].map(([k, label]) => (
              <label key={k} className="flex cursor-pointer items-center gap-2.5 text-[13px] text-neutral-300">
                <input type="checkbox" checked={k === "auto_update" ? st[k] !== false : !!st[k]} onChange={(e) => change({ [k]: e.target.checked })} className="size-4 accent-sky-400" /> {label}
              </label>
            ))}
            <label className="flex cursor-pointer items-center gap-2.5 text-[13px] text-neutral-300">
              <input type="checkbox" checked={st.gpu_release_away_s > 0} onChange={(e) => change({ gpu_release_away_s: e.target.checked ? 600 : 0 })} className="size-4 accent-sky-400" />
              Free GPU memory when I'm away
            </label>
            {login !== null && (
              <label className="flex cursor-pointer items-center gap-2.5 text-[13px] text-neutral-300">
                <input type="checkbox" checked={!!login} onChange={async (e) => setLogin(await bridge?.loginItem(e.target.checked))} className="size-4 accent-sky-400" />
                <Power size={13} className="text-neutral-500" /> Start with Windows
              </label>
            )}
          </div>
        </Section>

        <Section title="Clean up">
          <div className="grid grid-cols-3 gap-3">
            {[["cache", "Downloads cache", "Installers and partial downloads"], ["logs", "Old logs", "Keeps today's log"],
              ["index", "Meaning-search index", "Rebuilt while Jimmy runs"]].map(([k, label, t]) => (
              <button key={k} onClick={() => clear(k)} disabled={!!busy}
                className="flex items-start gap-3 rounded-xl bg-white/[0.03] p-3.5 text-left ring-1 ring-white/[0.08] hover:bg-white/[0.06] disabled:opacity-50">
                {busy === k ? <Loader2 size={15} className="mt-0.5 animate-spin text-sky-300" /> : <Trash2 size={15} className="mt-0.5 text-neutral-400" />}
                <div><div className="text-[13.5px] text-neutral-100">{label}</div><div className="text-[12px] text-neutral-500">{t}</div></div>
              </button>
            ))}
          </div>
          <div className="mt-3 text-[12px] text-neutral-500">To delete what Jimmy captured in a span, say "Jimmy, forget 1 to 15 September".</div>
        </Section>

        <div className="flex items-center justify-between pb-4">
          <span className="flex items-center gap-1.5 text-[12.5px] text-emerald-300/90">{note && <><Check size={13} /> {note}</>}</span>
          {s.installed && (
            <button onClick={() => bridge?.runSetup()} className="flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-[13px] text-neutral-400 hover:bg-white/[0.06] hover:text-neutral-100">
              <RotateCcw size={13} /> Run setup again</button>
          )}
          <Database size={0} />
        </div>
      </div>
    </div>
  );
}
