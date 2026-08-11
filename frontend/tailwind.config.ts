import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "24px", screens: { "2xl": "1240px" } },
    extend: {
      fontFamily: {
        app: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
      },
      colors: {
        // Practice Management tokens (docs/ui/mockups.html :root palette)
        pm: {
          navy: "#16365C",
          "navy-hi": "#1E4675",
          ink: "#1A2430",
          slate: "#5A6B7D",
          "slate-2": "#8A9AAA",
          rule: "#E2E7ED",
          "rule-2": "#EFF2F6",
          canvas: "#F4F6F9",
          panel: "#FBFCFD",
          rec: "#C5B88F",
          nrec: "#6699C2",
          pos: "#157F4C",
          "pos-bg": "#E8F5EE",
          "pos-br": "#B5D9C6",
          neg: "#B3261E",
          "neg-bg": "#FBECEA",
          "neg-br": "#EFC6C2",
          "real-bg": "#E6F4EC",
          "real-tx": "#1A6B42",
          "der-bg": "#FBF0DC",
          "der-tx": "#8A5A00",
          "tag-bg": "#EDF1F5",
          "tag-tx": "#4A5B6D",
          ai: "#4C4EA3",
          "ai-bg": "#EEEEF8",
          "ai-br": "#C9CAE8",
          "tot-bg": "#EAF0F7",
        },
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: "hsl(var(--card))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        success: { DEFAULT: "hsl(var(--success))", foreground: "hsl(var(--success-foreground))" },
        warning: { DEFAULT: "hsl(var(--warning))", foreground: "hsl(var(--warning-foreground))" }
      }
    }
  },
  plugins: [require("tailwindcss-animate")]
};
export default config;
