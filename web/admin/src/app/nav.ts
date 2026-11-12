// 메뉴. 역할마다 할 수 있는 일만 보인다 (서버도 같은 규칙으로 막는다: api/admin.py, admin_documents.py).
import type { AdminRole } from "../api/types";

export type NavItem = {
  path: string;
  label: string;
  roles: readonly AdminRole[] | "any";
};

export const NAV: readonly NavItem[] = [
  { path: "/", label: "대시보드", roles: "any" },
  { path: "/documents", label: "문서", roles: ["admin", "doc_manager"] },
  { path: "/users", label: "사용자", roles: ["admin"] },
  { path: "/audit", label: "감사 기록", roles: ["auditor"] },
  { path: "/settings", label: "설정", roles: ["admin"] },
];

export function visibleNav(roles: readonly AdminRole[]): NavItem[] {
  return NAV.filter((item) => item.roles === "any" || item.roles.some((r) => roles.includes(r)));
}
