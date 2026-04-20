/** @type {import("tailwindcss").Config} */
module.exports = {
  darkMode: "class",
  content: ["./web/templates/**/*.html"],
  safelist: [
    "bg-brand","text-brand","border-brand",
    "hover:bg-brand-dark","bg-brand-dark","text-brand-dark",
    "hover:border-brand/50","shadow-brand/25",
    "from-brand","to-brand","via-brand",
    "prose","prose-invert","prose-sm","prose-lg","prose-xl",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50:"#ecfdf5",100:"#d1fae5",400:"#34d399",
          500:"#10B981",600:"#059669",700:"#047857",900:"#064e3b",
          DEFAULT:"#10B981",
        },
        "brand-dark":"#059669",
      },
      fontFamily: { sans: ["Inter","system-ui","sans-serif"] },
    },
  },
  plugins: [
    require("@tailwindcss/forms"),
    require("@tailwindcss/typography"),
  ],
}
