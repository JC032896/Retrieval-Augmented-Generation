// 공통 틀: 크라프트색 왼쪽 메뉴 띠와 작업 영역.
import {
  FileText,
  LayoutGrid,
  LogOut,
  type LucideIcon,
  ScrollText,
  Settings,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import type { Me, UiConfig } from "../api/types";
import { ROLE_NAMES } from "../ui/format";
import { visibleNav } from "./nav";
import styles from "./Shell.module.css";

const ICONS: Record<string, LucideIcon> = {
  "/": LayoutGrid,
  "/documents": FileText,
  "/users": Users,
  "/audit": ScrollText,
  "/settings": Settings,
};

export function Shell({
  config,
  me,
  onSignOut,
  children,
}: {
  config: UiConfig;
  me: Me;
  onSignOut: () => void;
  children: ReactNode;
}) {
  const roles = me.roles.map((role) => ROLE_NAMES[role]).join(", ") || "관리 역할 없음";
  return (
    <div className={styles.frame}>
      <a className="skip-link" href="#main">
        본문으로 건너뛰기
      </a>
      <aside className={styles.rail}>
        <div className={styles.org}>
          {config.company_logo_url ? (
            <img src={config.company_logo_url} alt="" className={styles.logo} />
          ) : null}
          <span className={styles.orgName}>{config.company_name || "사내 문서 질의"}</span>
          <span className={styles.product}>문서 질의 관리</span>
        </div>
        <nav aria-label="관리 메뉴">
          <ul className={styles.nav}>
            {visibleNav(me.roles).map((item) => {
              const Icon = ICONS[item.path] ?? LayoutGrid;
              return (
                <li key={item.path}>
                  <NavLink to={item.path} end={item.path === "/"} className={styles.link ?? ""}>
                    <Icon aria-hidden="true" size={18} strokeWidth={1.75} />
                    {item.label}
                  </NavLink>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className={styles.who}>
          <span className={styles.name}>{me.name}</span>
          <span>
            {me.department} · {roles}
          </span>
          <button type="button" className={styles.signOut} onClick={onSignOut}>
            <LogOut aria-hidden="true" size={16} strokeWidth={1.75} />
            로그아웃
          </button>
        </div>
      </aside>
      <main id="main" className={styles.main} tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
