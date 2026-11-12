import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 관리 화면은 FastAPI가 /admin 아래에서 제공한다 (rag_service/api/admin_ui.py).
// 개발 서버(npm run dev)는 관리 API를 로컬 앱(uv run uvicorn, 8000)으로 넘긴다.
export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/admin/api": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", sourcemap: false },
});
