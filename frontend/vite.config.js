import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// Dev: the app calls /api/* and Vite forwards it to FastAPI on :8000
export default defineConfig({
  plugins: [react()],
  server: { host: true, proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } } },
});
