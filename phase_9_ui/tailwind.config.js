/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          base:    "#0a0a0f",
          raised:  "#13131f",
          overlay: "#1c1c2e",
          float:   "#23233a",
          hover:   "#2a2a45",
        },
        accent: {
          DEFAULT: "#6366f1",
          light:   "#818cf8",
          muted:   "rgba(99,102,241,0.15)",
          border:  "rgba(99,102,241,0.35)",
        },
        violet: {
          DEFAULT: "#8b5cf6",
          muted:   "rgba(139,92,246,0.15)",
        },
        ink: {
          primary:   "#e2e8f0",
          secondary: "#94a3b8",
          muted:     "#4a5568",
          faint:     "#2d3748",
        },
        border: {
          subtle: "rgba(255,255,255,0.05)",
          DEFAULT:"rgba(255,255,255,0.08)",
          strong: "rgba(255,255,255,0.14)",
        },
        success: "#34d399",
        danger:  "#f87171",
        warn:    "#fbbf24",
      },
      backgroundImage: {
        "accent-gradient":   "linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)",
        "surface-gradient":  "linear-gradient(180deg, #13131f 0%, #0a0a0f 100%)",
        "glow-accent":       "radial-gradient(circle at 50% 0%, rgba(99,102,241,0.12) 0%, transparent 70%)",
      },
      boxShadow: {
        "glow-sm": "0 0 12px rgba(99,102,241,0.25)",
        "glow":    "0 0 24px rgba(99,102,241,0.35)",
        "card":    "0 4px 24px rgba(0,0,0,0.4)",
        "float":   "0 8px 40px rgba(0,0,0,0.6)",
      },
      animation: {
        "fade-in":    "fadeIn 0.2s ease-out",
        "slide-up":   "slideUp 0.25s ease-out",
        "pulse-dot":  "pulseDot 1.4s ease-in-out infinite",
        "shimmer":    "shimmer 1.6s linear infinite",
      },
      keyframes: {
        fadeIn:   { from: { opacity: "0" }, to: { opacity: "1" } },
        slideUp:  { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        pulseDot: {
          "0%, 80%, 100%": { transform: "scale(0.6)", opacity: "0.4" },
          "40%":           { transform: "scale(1)",   opacity: "1" },
        },
        shimmer: {
          from: { backgroundPosition: "-200% 0" },
          to:   { backgroundPosition:  "200% 0" },
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.5rem",
        "4xl": "2rem",
      },
    },
  },
  plugins: [],
};
