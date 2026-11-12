// 서버 응답 타입. schema.d.ts는 서버의 API 명세에서 만든다 (npm run gen:api).
import type { components } from "./schema";

type Schemas = components["schemas"];

export type UiConfig = Schemas["UiConfigOut"];
export type Me = Schemas["MeOut"];
export type AdminRole = Me["roles"][number];
export type Status = Schemas["StatusOut"];
export type DocumentRow = Schemas["DocumentOut"];
export type LastChange = Schemas["LastChangeOut"];
export type UserRow = Schemas["UserOut"];
