/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
    // per-project frontend folders at the repo root
    '../../backtesting/frontend/**/*.{js,ts,jsx,tsx}',
    '../../stress_testing/frontend/**/*.{js,ts,jsx,tsx}',
    '../../forward_testing/frontend/**/*.{js,ts,jsx,tsx}',
    '../../paper_trading/frontend/**/*.{js,ts,jsx,tsx}',
    '../../reel_to_backtest/frontend/**/*.{js,ts,jsx,tsx}',
    '../../reel_to_pipeline/frontend/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        bg:     'var(--tv-bg)',
        card:   'var(--tv-s1)',
        card2:  'var(--tv-s2)',
        border: 'var(--tv-border)',
        accent: 'var(--tv-accent)',
        green:  'var(--tv-green)',
        teal:   'var(--tv-accent2)',
        red:    'var(--tv-red)',
        orange: 'var(--tv-amber)',
        grey:   'var(--tv-muted)',
        dim:    'var(--tv-dim)',
        text:   'var(--tv-text)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        'glow-green': '0 0 16px rgba(0,200,150,0.25)',
        'glow-red':   '0 0 16px rgba(255,71,87,0.20)',
      },
    },
  },
  plugins: [],
}
