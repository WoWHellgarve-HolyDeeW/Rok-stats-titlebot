/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{ts,tsx,js,jsx}",
    "./components/**/*.{ts,tsx,js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Dark theme - Professional gaming/stats feel
        bg: {
          DEFAULT: "#0a0e17",
          secondary: "#0f1520",
          tertiary: "#141d2b",
        },
        card: {
          DEFAULT: "#111827",
          hover: "#1a2332",
          border: "#1f2937",
        },
        text: {
          DEFAULT: "#f1f5f9",
          secondary: "#94a3b8",
          muted: "#64748b",
        },
        accent: {
          DEFAULT: "#3b82f6",
          light: "#60a5fa",
          dark: "#2563eb",
        },
        accent2: {
          DEFAULT: "#f59e0b",
          light: "#fbbf24",
        },
        // Stat colors
        power: "#8b5cf6",
        kills: {
          t4: "#06b6d4",
          t5: "#f97316",
        },
        deaths: "#ef4444",
        kp: "#22c55e",
        dkp: "#a855f7",
        // Status colors
        success: "#10b981",
        warning: "#f59e0b",
        danger: "#ef4444",
        info: "#3b82f6",
        // Border
        border: "#1e293b",
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        'glow-blue': '0 0 20px rgba(59, 130, 246, 0.3)',
        'glow-purple': '0 0 20px rgba(168, 85, 247, 0.3)',
        'glow-green': '0 0 20px rgba(34, 197, 94, 0.3)',
        'card': '0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -2px rgba(0, 0, 0, 0.2)',
        'card-hover': '0 20px 40px -15px rgba(0, 0, 0, 0.5)',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'hero-glow': 'radial-gradient(circle at 50% 0%, rgba(59,130,246,0.15), transparent 50%)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(59, 130, 246, 0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(59, 130, 246, 0.4)' },
        },
      },
    },
  },
  plugins: [],
};
