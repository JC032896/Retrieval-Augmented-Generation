// 문서 목록 거르기와 정렬 (화면과 나눠서 시험한다).
import type { DocumentRow } from "../api/types";
import { registeredNumber } from "../ui/format";

export type DocumentFilter = {
  query: string;
  origin: "all" | "upload" | "folder";
  level: "all" | number;
  sort: "recent" | "title" | "level";
};

const collator = new Intl.Collator("ko");

function activity(document: DocumentRow): string {
  return document.last_change?.created_at ?? document.synced_at ?? document.created_at;
}

export function filterDocuments(
  documents: readonly DocumentRow[],
  filter: DocumentFilter,
): DocumentRow[] {
  const query = filter.query.trim().toLowerCase();
  const rows = documents.filter(
    (document) =>
      (filter.origin === "all" || document.origin === filter.origin) &&
      (filter.level === "all" || document.security_level === filter.level) &&
      (!query ||
        document.title.toLowerCase().includes(query) ||
        registeredNumber(document).toLowerCase().includes(query)),
  );
  const order: Record<DocumentFilter["sort"], (a: DocumentRow, b: DocumentRow) => number> = {
    recent: (a, b) => activity(b).localeCompare(activity(a)),
    title: (a, b) => collator.compare(a.title, b.title),
    level: (a, b) => b.security_level - a.security_level || collator.compare(a.title, b.title),
  };
  return rows.sort(order[filter.sort]);
}
