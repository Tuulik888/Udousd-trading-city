"use client";

import type { EquityPoint } from "@/lib/types";

export function EquitySparkline({ points }: { points: EquityPoint[] }) {
  if (points.length < 2) {
    return <div className="py-6 text-center text-xs text-white/40">Not enough data yet.</div>;
  }

  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 300;
  const height = 80;

  const path = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * width;
      const y = height - ((p.equity - min) / range) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const last = values[values.length - 1];
  const first = values[0];
  const up = last >= first;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-20 w-full" preserveAspectRatio="none">
      <path
        d={path}
        fill="none"
        stroke={up ? "#39ff88" : "#ff3b5c"}
        strokeWidth={2}
        style={{ filter: `drop-shadow(0 0 4px ${up ? "#39ff8899" : "#ff3b5c99"})` }}
      />
    </svg>
  );
}
