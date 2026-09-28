"use client";

import type { AgentActivity } from "@/lib/types";

const STATUS_COLOR: Record<AgentActivity, { top: string; left: string; front: string; glow: string }> = {
  idle: { top: "#4a4478", left: "#241f4a", front: "#332c66", glow: "#8b5cf6" },
  thinking: { top: "#6a3fd6", left: "#2c1a5c", front: "#4c2aa8", glow: "#8b5cf6" },
  backtesting: { top: "#2fd9de", left: "#123f43", front: "#1c8a90", glow: "#33fff0" },
  trading: { top: "#3dff92", left: "#0b4226", front: "#149a4c", glow: "#39ff88" },
  frozen: { top: "#ff5470", left: "#4a1120", front: "#96233d", glow: "#ff3b5c" },
};

const FLOORS_BY_STATUS: Record<AgentActivity, number> = {
  idle: 2,
  thinking: 2,
  backtesting: 3,
  trading: 4,
  frozen: 1,
};

export function IsoBuilding({
  status,
  size = 72,
}: {
  status: AgentActivity;
  size?: number;
}) {
  const colors = STATUS_COLOR[status];
  const floors = FLOORS_BY_STATUS[status];
  const footprint = size * 0.62;
  const half = footprint / 2;
  const height = size * 0.55 + floors * (size * 0.32);
  const pulse = status === "thinking" || status === "backtesting" || status === "trading";
  const floorHeight = height / floors;

  return (
    <div
      className="relative mx-auto"
      style={{ width: size * 1.7, height: size * 1.55, perspective: 640 }}
    >
      <div
        className="absolute left-1/2 top-1/2"
        style={{
          transformStyle: "preserve-3d",
          transform: "translate(-50%, -50%) rotateX(-25deg) rotateY(-40deg)",
        }}
      >
        {/* front face */}
        <div
          className={pulse ? "animate-pulse" : ""}
          style={{
            position: "absolute",
            width: footprint,
            height,
            left: -half,
            top: -height / 2,
            background: `${colors.front} repeating-linear-gradient(to bottom, rgba(255,255,255,0) 0px, rgba(255,255,255,0) ${
              floorHeight - 3
            }px, rgba(255,255,255,0.14) ${floorHeight - 3}px, rgba(255,255,255,0.14) ${floorHeight}px)`,
            transform: `translateZ(${half}px)`,
            boxShadow: `0 0 18px ${colors.glow}55`,
          }}
        />
        {/* side face */}
        <div
          style={{
            position: "absolute",
            width: footprint,
            height,
            left: -half,
            top: -height / 2,
            background: colors.left,
            transform: `rotateY(-90deg) translateZ(${half}px)`,
          }}
        />
        {/* roof */}
        <div
          style={{
            position: "absolute",
            width: footprint,
            height: footprint,
            left: -half,
            top: -half,
            background: colors.top,
            transform: `rotateX(90deg) translateZ(${height / 2}px)`,
            boxShadow: `0 0 22px ${colors.glow}66`,
          }}
        />
      </div>
    </div>
  );
}
