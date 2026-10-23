/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // The /d/ frame, after the Koach (כוח פלוס) reference: navy chrome, white content.
        navy: {
          50: '#f3f5fa',
          100: '#e3e8f3',
          200: '#c3cde3',
          300: '#8e9fc6',
          600: '#2c3e6b',
          700: '#22325a',
          800: '#1a2747',
          900: '#121c36',
        },
        primary: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
        },
      },
    },
  },
  plugins: [],
}
