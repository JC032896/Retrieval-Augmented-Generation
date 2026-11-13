import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// 한 빌드에 화면 두 개: 관리 화면(index.html, FastAPI가 /admin에서 제공)과 직원 채팅 화면(chat.html,
// /에서 제공, rag_service/api/admin_ui.py). 화면 파일(assets/)은 둘 다 /admin/assets/에서 받는다.
// 개발 서버(npm run dev)는 API를 로컬 앱(uv run uvicorn, 8000)으로 넘기고, 채팅 화면 주소를 chat.html로 잇는다.
const CHAT_PATHS = /^\/(?:$|callback(?:\?|$)|history(?:\/|$|\?))/;

function chatPages(): Plugin {
  return {
    name: "chat-pages",
    configureServer(server) {
      server.middlewares.use((incoming, _response, next) => {
        const request = incoming as unknown as { url?: string };
        const url = request.url ?? "";
        if (CHAT_PATHS.test(url)) {
          const query = url.includes("?") ? url.slice(url.indexOf("?")) : "";
          request.url = `/admin/chat.html${query}`;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  base: "/admin/",
  plugins: [react(), chatPages()],
  server: {
    port: 5173,
    proxy: {
      "/admin/api": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
      "/ask": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      input: {
        admin: "index.html",
        chat: "chat.html",
      },
    },
  },
});
