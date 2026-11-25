/**
 * Formatting, escaping, and semantic badge helpers.
 */

export function esc(val) {
  return String(val ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString("en-US");
}

export function fmtSigned(n) {
  if (n === null || n === undefined) return "—";
  const v = Number(n);
  return `${v > 0 ? "+" : ""}${v.toLocaleString("en-US")}`;
}

export function fmtMoney(n, currency = "USD") {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(n));
}

export function fmtShortTs(iso) {
  if (!iso) return "—";
  return String(iso).replace("T", " ").replace("Z", "").slice(0, 16);
}

export function fmtMonth(ym) {
  if (!ym || ym.length < 7) return ym || "—";
  const [y, m] = ym.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[Number(m) - 1] || m} ${y}`;
}

export function sourceLabel(src) {
  const map = {
    OFFICIAL_STATEMENT: "Official Statement",
    OFFICIAL_INVOICE: "Official Invoice",
    OPENING_BALANCE: "Opening Balance",
    DOWNLOADED_REPORT: "Downloaded Report",
    SYSTEM_EMAIL: "System Email",
    CONTROLLED_INPUT: "Controlled Input",
    MANUAL_ADJUSTMENT: "Manual Adjustment",
  };
  return map[src] || src;
}

export function evidenceBadge(level, src) {
  const cls = level === 1 ? "blue" : level === 2 ? "green" : level === 3 ? "blue" : level === 4 ? "yellow" : "slate";
  return `<span class="badge ${cls}" title="Evidence Level ${level}">L${level} · ${esc(sourceLabel(src))}</span>`;
}

export function statusBadge(status) {
  const map = {
    Confirmed: "green",
    Completed: "green",
    Matched: "green",
    Finalized: "green",
    Resolved: "green",
    Active: "green",
    Pending: "yellow",
    "Pending Approval": "yellow",
    Sent: "blue",
    Started: "blue",
    "In Review": "blue",
    "Needs Review": "yellow",
    "Review Required": "orange",
    Cancelled: "slate",
    Superseded: "slate",
    Dismissed: "slate",
    Expired: "orange",
    Failed: "red",
    Rejected: "red",
    Open: "red",
    "Missing Internal": "red",
    "Internal Only": "orange",
  };
  return `<span class="badge ${map[status] || "slate"}">${esc(status)}</span>`;
}

export function severityBadge(sev) {
  const map = { High: "red", Medium: "orange", Low: "blue", Watch: "yellow" };
  return `<span class="badge ${map[sev] || "slate"}">${esc(sev)}</span>`;
}

export function tierBadge(tier, confidence) {
  if (tier === "1_EXACT_ID") return `<span class="badge green">100% · Exact ID</span>`;
  if (tier === "2_CANDIDATE_DATE") return `<span class="badge blue">90% · Cand + Date</span>`;
  if (tier === "3_CANDIDATE_TYPE") return `<span class="badge yellow">80% · Cand + Type</span>`;
  if (tier === "4_UNMATCHED_OFFICIAL") return `<span class="badge red">&lt;80% · Missing Internal</span>`;
  if (tier === "5_INTERNAL_ONLY") return `<span class="badge orange">Internal Only</span>`;
  return `<span class="badge slate">${confidence}%</span>`;
}
