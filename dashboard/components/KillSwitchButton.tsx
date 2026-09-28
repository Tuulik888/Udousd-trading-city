"use client";

import { useState } from "react";
import { activateKillSwitch, deactivateKillSwitch } from "@/lib/api";

export function KillSwitchButton({
  active,
  onChanged,
}: {
  active: boolean;
  onChanged: (active: boolean) => void;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (active) {
      setBusy(true);
      try {
        const res = await deactivateKillSwitch();
        onChanged(res.active);
      } finally {
        setBusy(false);
      }
      return;
    }

    if (!armed) {
      setArmed(true);
      window.setTimeout(() => setArmed(false), 4000);
      return;
    }

    setBusy(true);
    try {
      const res = await activateKillSwitch();
      onChanged(res.active);
    } finally {
      setBusy(false);
      setArmed(false);
    }
  }

  if (active) {
    return (
      <button
        onClick={handleClick}
        disabled={busy}
        className="flex items-center gap-2 rounded-full border border-red-500/60 bg-red-500/10 px-4 py-2 text-xs font-mono uppercase tracking-wide text-red-300 shadow-[0_0_16px_rgba(255,59,92,0.35)] transition active:scale-95 disabled:opacity-50"
      >
        <span className="h-2 w-2 animate-pulse rounded-full bg-red-400" />
        Kill switch ON — tap to resume
      </button>
    );
  }

  return (
    <button
      onClick={handleClick}
      disabled={busy}
      className={`rounded-full border px-4 py-2 text-xs font-mono uppercase tracking-wide transition active:scale-95 disabled:opacity-50 ${
        armed
          ? "border-red-500 bg-red-500 text-white"
          : "border-white/15 bg-white/5 text-white/70 hover:border-red-400/60 hover:text-red-300"
      }`}
    >
      {armed ? "Tap again to confirm STOP" : "Kill switch"}
    </button>
  );
}
