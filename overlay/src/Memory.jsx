import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Bell, Brain, Check, Pencil, Plus, RotateCcw, Target, Trash2, X } from "lucide-react";

// D41: what Jimmy keeps for you, editable: reminders, goals, and things you asked it
// to remember. The same lists Jimmy changes by voice ("move that reminder to 10").
const bridge = window.jimmy;

function when(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const now = new Date();
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `today ${hm}`;
  const tmrw = new Date(now); tmrw.setDate(now.getDate() + 1);
  if (d.toDateString() === tmrw.toDateString()) return `tomorrow ${hm}`;
  return `${d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} ${hm}`;
}

function Row({ item, kind, picked, onPick, onSave, onDone, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(item.text);
  const [due, setDue] = useState("");
  const done = item.state === "done";
  const save = () => {
    if (text.trim() !== item.text || due.trim()) onSave({ text: text.trim(), when: due.trim() || undefined });
    setEditing(false);
    setDue("");
  };
  return (
    <motion.li layout initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: -12 }}
      className={`group flex items-center gap-3 rounded-lg px-3 py-2 ${picked ? "bg-sky-400/10 ring-1 ring-sky-400/30" : "hover:bg-white/[0.04]"}`}>
      <input type="checkbox" checked={picked} onChange={onPick} aria-label={`Select ${item.text}`}
        className="size-3.5 shrink-0 accent-sky-400" />
      {editing ? (
        <form className="flex min-w-0 flex-1 items-center gap-2" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <input autoFocus value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") { setText(item.text); setEditing(false); } }}
            className="min-w-0 flex-1 rounded-md bg-white/[0.07] px-2 py-1 text-[13px] text-neutral-100 outline-none ring-1 ring-white/15 focus:ring-sky-400/50" />
          {kind === "reminder" && (
            <input value={due} onChange={(e) => setDue(e.target.value)} placeholder={`when (now ${when(item.due_ts) || "an app"})`}
              className="w-44 rounded-md bg-white/[0.07] px-2 py-1 text-[12px] text-neutral-100 outline-none ring-1 ring-white/15 placeholder:text-neutral-500 focus:ring-sky-400/50" />
          )}
          <button type="submit" className="rounded-md bg-sky-500/80 px-2 py-1 text-[12px] text-white hover:bg-sky-500">Save</button>
        </form>
      ) : (
        <button onClick={() => setEditing(true)} title="Edit"
          className={`min-w-0 flex-1 truncate text-left text-[13px] ${done ? "text-neutral-500 line-through" : "text-neutral-100"}`}>
          {item.text}
        </button>
      )}
      {!editing && kind === "reminder" && (
        <span className="shrink-0 text-[12px] tabular-nums text-amber-200/80">{item.due_ts ? when(item.due_ts) : `when ${item.app} opens`}</span>
      )}
      {!editing && (
        <span className="flex shrink-0 items-center gap-0.5 opacity-60 transition group-hover:opacity-100">
          <button onClick={() => setEditing(true)} aria-label="Edit" title="Edit" className="rounded p-1 hover:bg-white/10"><Pencil size={13} /></button>
          {kind === "goal" && (
            <button onClick={onDone} aria-label={done ? "Not done" : "Done"} title={done ? "Not done yet" : "Done"}
              className="rounded p-1 hover:bg-white/10">{done ? <RotateCcw size={13} /> : <Check size={13} />}</button>
          )}
          <button onClick={onDelete} aria-label="Delete" title="Delete" className="rounded p-1 text-rose-300 hover:bg-rose-500/15"><Trash2 size={13} /></button>
        </span>
      )}
    </motion.li>
  );
}

function Section({ icon: Icon, title, kind, items, empty, sel, toggle, op, hint }) {
  const [text, setText] = useState("");
  const [due, setDue] = useState("");
  const add = (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    op({ op: "add", kind, text, when: due || undefined });
    setText("");
    setDue("");
  };
  return (
    <section className="rounded-2xl bg-white/[0.03] p-4 ring-1 ring-white/[0.06]">
      <h2 className="mb-2 flex items-center gap-2 text-[13px] font-medium text-neutral-100">
        <Icon size={15} className="text-sky-300" /> {title}
        <span className="text-neutral-500">{items.length}</span>
      </h2>
      <ul className="flex flex-col">
        <AnimatePresence initial={false}>
          {items.map((it) => (
            <Row key={it.id} item={it} kind={kind} picked={sel.has(`${kind}:${it.id}`)} onPick={() => toggle(`${kind}:${it.id}`)}
              onSave={(v) => op({ op: "update", kind, id: it.id, ...v })}
              onDone={() => op({ op: it.state === "done" ? "reopen" : "done", kind, id: it.id })}
              onDelete={() => op({ op: "delete", kind, id: it.id })} />
          ))}
        </AnimatePresence>
        {!items.length && <li className="px-3 py-2 text-[12.5px] text-neutral-500">{empty}</li>}
      </ul>
      <form onSubmit={add} className="mt-2 flex items-center gap-2">
        <Plus size={14} className="shrink-0 text-neutral-500" />
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={hint}
          className="min-w-0 flex-1 rounded-md bg-transparent px-1 py-1 text-[13px] text-neutral-100 outline-none placeholder:text-neutral-600 focus:bg-white/[0.05]" />
        {kind === "reminder" && (
          <input value={due} onChange={(e) => setDue(e.target.value)} placeholder='when: "at 5", "in 20 minutes"'
            className="w-48 rounded-md bg-transparent px-1 py-1 text-[12.5px] text-neutral-100 outline-none placeholder:text-neutral-600 focus:bg-white/[0.05]" />
        )}
      </form>
    </section>
  );
}

export default function Memory() {
  const [data, setData] = useState(null);
  const [sel, setSel] = useState(() => new Set());
  const loading = useRef(false);
  const load = useCallback(() => {
    if (loading.current) return;
    loading.current = true;
    bridge?.get("memory").then((d) => { if (d) setData(d); }).finally(() => { loading.current = false; });
  }, []);
  useEffect(() => {
    load();
    return bridge?.onEvent((ev) => { if (ev.type === "memory_changed") load(); });
  }, [load]);
  const op = async (body) => { await bridge?.api("memory", body); load(); };
  const toggle = (key) => setSel((s) => { const n = new Set(s); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const deleteSelected = async () => {
    for (const key of sel) {
      const [kind, id] = key.split(":");
      await bridge?.api("memory", { op: "delete", kind, id: Number(id) });
    }
    setSel(new Set());
    load();
  };
  if (!data) return <div className="grid flex-1 place-items-center text-[13px] text-neutral-500">Loading…</div>;
  return (
    <main data-scroll="memory" className="relative flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
      <p className="text-[12.5px] text-neutral-500">
        Click a line to edit it. Or just say it: &ldquo;Jimmy, move the railway reminder to 10 tomorrow&rdquo;,
        &ldquo;mark the essay goal done&rdquo;, &ldquo;forget that I take the 8:15 train&rdquo;.
      </p>
      <Section icon={Bell} title="Reminders" kind="reminder" items={data.reminders} sel={sel} toggle={toggle} op={op}
        empty="No reminders." hint="New reminder…" />
      <Section icon={Target} title="Goals" kind="goal" items={data.goals} sel={sel} toggle={toggle} op={op}
        empty="No goals yet. Saying “focus on …” adds one too." hint="New goal…" />
      <Section icon={Brain} title="Things I remember" kind="memory" items={data.memories} sel={sel} toggle={toggle} op={op}
        empty="Nothing yet. Say “Jimmy, remember that …”." hint="Something to remember…" />
      <AnimatePresence>
        {sel.size > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 12 }}
            className="sticky bottom-0 mx-auto flex items-center gap-3 rounded-full bg-neutral-900 px-4 py-2 text-[12.5px] ring-1 ring-white/10">
            <span className="text-neutral-300">{sel.size} selected</span>
            <button onClick={deleteSelected} className="flex items-center gap-1 rounded-full bg-rose-500/80 px-3 py-1 text-white hover:bg-rose-500">
              <Trash2 size={12} /> Delete
            </button>
            <button onClick={() => setSel(new Set())} aria-label="Clear selection" className="rounded-full p-1 text-neutral-400 hover:bg-white/10">
              <X size={13} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}
