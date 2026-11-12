import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "@fontsource/barlow-condensed/500.css";
import "@fontsource/barlow-condensed/700.css";
import "./styles/tokens.css";
import "./styles/base.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { SessionProvider } from "./auth/session";

const root = document.getElementById("root");
if (!root) throw new Error("#root가 없습니다");

createRoot(root).render(
  <StrictMode>
    <SessionProvider>
      <App />
    </SessionProvider>
  </StrictMode>,
);
