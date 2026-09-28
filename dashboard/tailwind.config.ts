import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        city: {
          bg: "#05040f",
          panel: "#0d0a20",
          border: "#241b4d",
        },
        neon: {
          cyan: "#33fff0",
          magenta: "#ff3df0",
          violet: "#8b5cf6",
          amber: "#ffb020",
          red: "#ff3b5c",
          green: "#39ff88",
        },
      },
      boxShadow: {
        neon: "0 0 12px var(--tw-shadow-color), 0 0 32px var(--tw-shadow-color)",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
