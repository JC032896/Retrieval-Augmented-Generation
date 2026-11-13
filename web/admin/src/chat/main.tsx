import "pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css";
import "./styles/tokens.css";
import "./styles/base.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ChatApp } from "./ChatApp";
import { ChatSessionProvider } from "./session";

const root = document.getElementById("root");
if (!root) throw new Error("#root가 없습니다");

createRoot(root).render(
  <StrictMode>
    <ChatSessionProvider>
      <ChatApp />
    </ChatSessionProvider>
  </StrictMode>,
);
