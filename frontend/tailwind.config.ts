import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Core surfaces (deep navy, never pure black — avoids OLED smear)
        background: "#0A0E1A",
        surface: "#10172A",
        "surface-2": "#151E33",
        foreground: "#E8EEF9",
        muted: "#8A98B2",
        border: "#1E2A42",

        // Brand: gold = trust, purple = tech (used sparingly as accent)
        primary: { DEFAULT: "#F5A524", foreground: "#0A0E1A" },
        accent: { DEFAULT: "#8B5CF6", foreground: "#0A0E1A" },

        // Semantic status colors (mapped to the verifier's taxonomy)
        verified: "#34D399",
        wrong: "#F87171",
        "wrong-strong": "#EF4444",
        unsupported: "#FBBF24",
        ambiguous: "#60A5FA",
        unchecked: "#8A98B2",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.25rem",
      },
      transitionTimingFunction: {
        // Expo-out — the design system's signature easing
        expo: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "blob-drift": {
          "0%, 100%": { transform: "translate(0px, 0px) scale(1)" },
          "33%": { transform: "translate(30px, -40px) scale(1.08)" },
          "66%": { transform: "translate(-25px, 20px) scale(0.95)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.4s cubic-bezier(0.16,1,0.3,1)",
        "blob-drift": "blob-drift 22s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
