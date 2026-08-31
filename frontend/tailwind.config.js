/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        serif: ['"Newsreader"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      colors: {
        sm: {
          azzurro: '#0072ce',
          'azzurro-light': '#5c9ad2',
          'azzurro-dark': '#005599',
          'azzurro-glow': '#38bdf8',
          bianco: '#ffffff',
          'bianco-soft': '#f1f5f9',
          oro: '#d4a359',
          'oro-light': '#e5be7a',
          'oro-dark': '#b3843b',
          notte: '#0a0f1d',
          card: '#11192e',
          cardHover: '#17223e',
          border: '#1e2942',
          borderLight: '#2b3959',
          text: '#f1f5f9',
          muted: '#94a3b8',
        }
      }
    },
  },
  plugins: [],
}
