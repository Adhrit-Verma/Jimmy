import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// base "./": the page is loaded from file:// by Electron, so assets must be relative.
export default defineConfig({ base: "./", plugins: [react(), tailwindcss()] });
