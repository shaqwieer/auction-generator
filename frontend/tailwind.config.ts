import type { Config } from "tailwindcss";

/**
 * Tokens come straight from `Matbaa Design Plan.dc.html`. Seven colours, one
 * accent used sparingly, hairline borders instead of shadows.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0E2A3A",
        paper: "#FAFAF7",
        surface: "#FFFFFF",
        accent: { DEFAULT: "#D6006F", hover: "#B00059" },
        ok: "#1F7A6B",
        bad: "#C2410C",
        line: "#E6E8EA",
        muted: { DEFAULT: "#45606E", soft: "#7B8B94" },
        edge: "#C7CDD1",
      },
      fontFamily: {
        // Supplied by next/font in app/layout.tsx.
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: { DEFAULT: "4px", lg: "8px" },
      fontSize: {
        xs: ["12px", "1.5"],
        sm: ["13px", "1.6"],
        base: ["14px", "1.7"],
        md: ["15px", "1.7"],
        lg: ["17px", "1.6"],
        xl: ["22px", "1.4"],
        "2xl": ["24px", "1.35"],
        "4xl": ["40px", "1.2"],
      },
    },
  },
  plugins: [],
};

export default config;
