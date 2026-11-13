// 채팅 화면이 쓰는 서버 응답 타입 (schema.d.ts는 서버 API 명세에서 만든다).
import type { components } from "../api/schema";

type Schemas = components["schemas"];

export type ChatMe = Schemas["ChatMeOut"];
export type Answer = Schemas["AnswerOut"];
export type Citation = Schemas["CitationOut"];
export type Passage = Schemas["PassageOut"];
export type HistoryPage = Schemas["HistoryPageOut"];
export type TurnSummary = Schemas["TurnSummaryOut"];
export type Turn = Schemas["TurnOut"];
export type Usage = Schemas["ChatUsageOut"];
export type ConversationSummary = Schemas["ConversationSummaryOut"];
export type ConversationPage = Schemas["ConversationPageOut"];
export type Conversation = Schemas["ConversationOut"];
export type ConversationTurn = Schemas["ConversationTurnOut"];
