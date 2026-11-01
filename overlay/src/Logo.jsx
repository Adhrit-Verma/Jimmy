import { motion } from "motion/react";

// D62: Jimmy's mark: its own pill with the listening bars, the equalizer it shows while it
// hears you. Same geometry as installer/art.py (the icon). `live`: the bars breathe;
// `mood`: "idle" (still), "listening" (breathing), "working" (a wave), "done" (one bloom).
const BARS = [0.38, 0.72, 1.0, 0.62, 0.42];

export default function Logo({ size = 120, mood = "listening", glow = true }) {
  const w = size, h = size * 0.52;
  const barW = w * 0.075, gap = (w * 0.62 - BARS.length * barW) / (BARS.length - 1);
  const left = (w - (BARS.length * barW + (BARS.length - 1) * gap)) / 2, inner = h * 0.64;
  const id = `sky-${size}`;
  return (
    <div className="relative" style={{ width: w, height: h }}>
      {glow && (
        <motion.div className="absolute inset-0 -z-10 rounded-full bg-sky-500/40 blur-2xl"
          animate={{ opacity: mood === "idle" ? 0.35 : [0.35, 0.7, 0.35], scale: mood === "done" ? [1, 1.35, 1.1] : [1, 1.08, 1] }}
          transition={{ duration: mood === "done" ? 1.2 : 2.6, repeat: mood === "done" ? 0 : Infinity, ease: "easeInOut" }} />
      )}
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-label="Jimmy">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#7dd3fc" />
            <stop offset="1" stopColor="#0ea5e9" />
          </linearGradient>
        </defs>
        <rect x={1} y={1} width={w - 2} height={h - 2} rx={(h - 2) / 2} fill="#171717" stroke="#262626" strokeWidth={Math.max(1.5, w * 0.012)} />
        {BARS.map((k, i) => {
          const full = Math.max(barW, inner * k);
          const x = left + i * (barW + gap);
          const scales = mood === "idle" ? [k * 0.9 / k] :
            mood === "working" ? [0.35, 1, 0.35] : [1, 0.55 + (i % 2) * 0.25, 1];
          return (
            <motion.rect key={i} x={x} width={barW} rx={barW / 2} fill={`url(#${id})`}
              y={h / 2 - full / 2} height={full} style={{ originY: "50%", transformBox: "fill-box" }}
              animate={{ scaleY: scales }}
              transition={{ duration: mood === "working" ? 0.9 : 1.6, repeat: mood === "idle" || mood === "done" ? 0 : Infinity,
                            delay: i * (mood === "working" ? 0.12 : 0.18), ease: "easeInOut" }} />
          );
        })}
      </svg>
    </div>
  );
}
