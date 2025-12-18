/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        grafana: {
          orange: '#FF6B00',
          dark: '#111217',
          grey: '#1F1F23',
        },
      },
    },
  },
  plugins: [],
}
