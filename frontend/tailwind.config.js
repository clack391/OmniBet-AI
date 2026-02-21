/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        "primary": "#0d59f2",
        "accent-green": "#10b981",
        "accent-purple": "#8b5cf6",
        "background-light": "#f5f6f8",
        "background-dark": "#101623",
        "card-dark": "#182234",
        "card-glass": "rgba(24, 34, 52, 0.6)",
      },
      fontFamily: {
        "display": ["Manrope", "sans-serif"]
      },
    },
  },
  plugins: [],
}

