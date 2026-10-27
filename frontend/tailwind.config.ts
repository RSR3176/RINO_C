import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        rino: {
          bg: "#F7F7F4",
          ink: "#18181B",
          muted: "#57534E",
          border: "#E7E5E4",
          indigo: "#4338CA",
          indigoDark: "#3730A3",
          indigoSoft: "#EEF2FF",
          indigoMid: "#818CF8",
          white: "#FFFFFF",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(28,25,23,.04), 0 8px 24px rgba(28,25,23,.05)",
      },
    },
  },
  plugins: [],
};

export default config;
