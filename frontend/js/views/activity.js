/**
 * View 2: Assessment Activity & Multi-Source Capture Pipeline
 * Re-ranked evidence order: Official Downloaded Report (L2) > System Email (L3) > Controlled Input (L4).
 */
import { apiRequest } from "../api.js";
import { esc, evidenceBadge, fmtNum, fmtShortTs, statusBadge } from "../format.js";

const state = { search: "", status: "all", source: "all" };

export async function renderActivity(root, ctx) {
  const params = new URLSearchParams();
  if (state.status !== "all") params.set("status", state.status);
  if (state.source !== "all") params.set("source_type", state.source);
  if (state.search) params.set("search", state.search);

  const data = await apiRequest(`/api/assessments?${params.toString()}`);
  const p = data.pipeline;

  root.innerHTML = `
    <div class="pipeline-strip">
      <div class="pipeline-card">
        <div class="rank">Level 2 · Structured (Authoritative)</div>
        <div class="title">Official Downloaded Reports</div>
        <div class="count">${fmtNum(p.downloaded_reports)}</div>
        <div class="caption">Ranked above emails for structural reliability</div>
      </div>
      <div class="pipeline-card">
        <div class="rank">Level 3 · Near Real-Time</div>
        <div class="title">Pulsifi System Emails</div>
        <div class="count">${fmtNum(p.system_emails)}</div>
        <div class="caption">Timeliness layer · ${fmtNum(p.pii_redactions_total)} PII email(s) scrubbed</div>
      </div>
      <div class="pipeline-card">
        <div class="rank">Level 4 · Pending Estimate</div>
        <div class="title">Controlled Internal Input</div>
        <div class="count">${fmtNum(p.controlled_inputs)}</div>
        <div class="caption">Upgraded cleanly on L2/L3 arrival (no double count)</div>
      </div>
      <div class="pipeline-card" style="cursor:pointer" id="card-goto-exc">
        <div class="rank" style="color:var(--red-ink)">Synced Exception Queue</div>
        <div class="title">Open Exceptions</div>
        <div class="count" style="color:${p.open_exceptions ? "var(--red-ink)" : "var(--green-ink)"}">${fmtNum(p.open_exceptions)}</div>
        <div class="caption">Exact live count across Overview &amp; Exceptions →</div>
      </div>
    </div>

    <div class="card panel">
      <div class="panel-head">
        <div>
          <h2>Assessment Lifecycle Ledger (${fmtNum(data.items.length)} shown)</h2>
          <div class="panel-sub">Click any assessment row to inspect full lifecycle timestamps, credit rule snapshot, and PII-scrubbed raw evidence.</div>
        </div>
        <div class="toolbar-group">
          <button class="btn primary" id="btn-act-ingest">+ Ingest Report / Email / Input</button>
        </div>
      </div>

      <div class="toolbar">
        <div class="toolbar-group">
          <input class="input" id="act-search" style="min-width:250px" placeholder="Search ID, candidate hash, client, campaign…" value="${esc(state.search)}" />
          <select class="select" id="act-status">
            <option value="all">All lifecycle statuses</option>
            ${["Created", "Sent", "Started", "Completed", "Cancelled", "Failed", "Expired"]
              .map((s) => `<option value="${s}" ${state.status === s ? "selected" : ""}>${s}</option>`)
              .join("")}
          </select>
          <select class="select" id="act-source">
            <option value="all">All evidence sources</option>
            <option value="DOWNLOADED_REPORT" ${state.source === "DOWNLOADED_REPORT" ? "selected" : ""}>L2 · Downloaded Report</option>
            <option value="SYSTEM_EMAIL" ${state.source === "SYSTEM_EMAIL" ? "selected" : ""}>L3 · System Email</option>
            <option value="CONTROLLED_INPUT" ${state.source === "CONTROLLED_INPUT" ? "selected" : ""}>L4 · Controlled Input</option>
          </select>
        </div>
        <span class="badge blue">PDPA/GDPR · Salted HMAC-SHA256 Candidate IDs</span>
      </div>

      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Assessment ID</th>
              <th>Candidate Hash</th>
              <th>Client / Partner Pool</th>
              <th>Project / Campaign</th>
              <th>Type</th>
              <th>Status</th>
              <th class="right">Units</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            ${
              data.items.length
                ? data.items
                    .map((a) => {
                      const owner =
                        a.pool_owner_type === "PARTNER"
                          ? `${a.partner_name || "Partner"} <span class="badge slate">Partner</span>`
                          : a.client_name
                          ? `${esc(a.client_name)} <span class="badge slate">Client</span>`
                          : `<span class="badge red">Unmapped</span>`;
                      return `
                        <tr style="cursor:pointer" data-aid="${a.id}">
                          <td class="mono nowrap"><strong>${esc(a.pulsifi_assessment_id)}</strong></td>
                          <td class="mono nowrap">${esc(a.candidate_ref_hash)}</td>
                          <td class="nowrap">${owner}</td>
                          <td>
                            <div>${esc(a.project_name || "Unattributed")}</div>
                            <div class="panel-sub mono">${esc(a.pulsifi_campaign_key || "—")}</div>
                          </td>
                          <td class="nowrap">${esc(a.assessment_type)}</td>
                          <td>${statusBadge(a.current_status)}</td>
                          <td class="right num"><strong>${fmtNum(a.credit_units_applied)}</strong></td>
                          <td class="nowrap">${evidenceBadge(a.evidence_level, a.source_type)}</td>
                        </tr>
                      `;
                    })
                    .join("")
                : `<tr><td colspan="8" style="text-align:center;color:var(--ink-muted);padding:24px">No matching assessments.</td></tr>`
            }
          </tbody>
        </table>
      </div>
    </div>
  `;

  root.querySelector("#card-goto-exc").addEventListener("click", () => ctx.navigate("exceptions"));
  root.querySelector("#btn-act-ingest").addEventListener("click", () => ctx.openIngestModal());

  let timer;
  root.querySelector("#act-search").addEventListener("input", (e) => {
    state.search = e.target.value;
    clearTimeout(timer);
    timer = setTimeout(() => renderActivity(root, ctx), 180);
  });
  root.querySelector("#act-status").addEventListener("change", (e) => {
    state.status = e.target.value;
    renderActivity(root, ctx);
  });
  root.querySelector("#act-source").addEventListener("change", (e) => {
    state.source = e.target.value;
    renderActivity(root, ctx);
  });

  root.querySelectorAll("tr[data-aid]").forEach((tr) => {
    tr.addEventListener("click", () => openAssessmentInspector(tr.dataset.aid, ctx));
  });
}

async function openAssessmentInspector(id, ctx) {
  const detail = await apiRequest(`/api/assessments/${id}`);
  const a = detail.assessment;

  const isBadTerminal = ["Cancelled", "Failed", "Expired"].includes(a.current_status);
  const steps = [
    { key: "Created", ts: a.created_at },
    { key: "Sent", ts: a.sent_at },
    { key: "Started", ts: a.started_at },
    {
      key: isBadTerminal ? a.current_status : "Completed",
      ts: isBadTerminal ? a[`${a.current_status.toLowerCase()}_at`] : a.completed_at,
      bad: isBadTerminal,
    },
  ];

  const html = `
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px">
      <div>
        <span class="mono" style="font-weight:700;font-size:15px">${esc(a.pulsifi_assessment_id)}</span>
        · <span class="mono">${esc(a.candidate_ref_hash)}</span>
      </div>
      <div>${statusBadge(a.current_status)} ${evidenceBadge(a.evidence_level, a.source_type)}</div>
    </div>

    <div class="stepper">
      ${steps
        .map(
          (st, idx) => `
          <div class="step-node ${st.ts ? (st.bad ? "terminal-bad" : "done") : ""}">
            <div class="step-dot">${idx + 1}</div>
            <div class="step-label">${esc(st.key)}</div>
            <div class="step-ts">${st.ts ? esc(fmtShortTs(st.ts)) : "—"}</div>
          </div>
        `
        )
        .join("")}
    </div>

    <div class="grid grid-2 mt-16 mb-16" style="font-size:12px">
      <div class="card panel" style="padding:12px">
        <div class="kpi-label">Commercial Attribution</div>
        <div style="margin-top:6px"><strong>Client:</strong> ${esc(a.client_name || "Unmapped")}</div>
        <div><strong>Partner:</strong> ${esc(a.partner_name || "Direct Client Pool")}</div>
        <div><strong>Project:</strong> ${esc(a.project_name || "Unmapped")}</div>
        <div><strong>Campaign Key:</strong> <span class="mono">${esc(a.pulsifi_campaign_key || "—")}</span></div>
      </div>
      <div class="card panel" style="padding:12px">
        <div class="kpi-label">Effective-Dated Credit Rule Snapshot</div>
        <div style="margin-top:6px"><strong>Assessment Type:</strong> ${esc(a.assessment_type)}</div>
        <div><strong>Applied Units:</strong> <span class="num">${fmtNum(a.credit_units_applied)}</span></div>
        <div><strong>Rule Trigger:</strong> ${esc(a.rule_trigger || "N/A")} (${fmtNum(a.rule_units)} units)</div>
        <div><strong>Effective From:</strong> <span class="mono">${esc(a.rule_effective_from || "—")}</span></div>
      </div>
    </div>

    <h4 style="margin:0 0 8px;font-size:13px">Linked Append-Only Ledger Entries (${detail.transactions.length})</h4>
    <div class="table-wrap mb-16">
      <table class="table">
        <thead><tr><th>Tx Code</th><th>Date</th><th>Type</th><th class="right">Units</th><th>Status</th><th>Evidence</th></tr></thead>
        <tbody>
          ${
            detail.transactions.length
              ? detail.transactions
                  .map(
                    (t) => `
                    <tr>
                      <td class="mono"><strong>${esc(t.tx_code)}</strong></td>
                      <td class="mono">${esc(t.tx_date)}</td>
                      <td>${esc(t.tx_type)}</td>
                      <td class="right num ${t.units < 0 ? "unit-neg" : "unit-pos"}">${t.units > 0 ? "+" : ""}${t.units}</td>
                      <td>${statusBadge(t.status)}</td>
                      <td>${evidenceBadge(t.evidence_level, t.source_type)}</td>
                    </tr>
                  `
                  )
                  .join("")
              : `<tr><td colspan="6" style="color:var(--ink-muted)">No credit deduction (non-billable status per credit rule).</td></tr>`
          }
        </tbody>
      </table>
    </div>

    ${
      detail.raw_event
        ? `
        <h4 style="margin:0 0 6px;font-size:13px">PII-Scrubbed Raw Evidence (SHA-256: <span class="mono">${esc(detail.raw_event.payload_hash.slice(0, 14))}…</span>)</h4>
        <div class="code-box">${esc(detail.raw_event.scrubbed_payload)}</div>
      `
        : ""
    }
  `;
  ctx.openModal({
    title: `Assessment Lifecycle Inspector · ${a.pulsifi_assessment_id}`,
    subtitle: "Decoupled event history, applied rule snapshot, and append-only ledger linkage",
    bodyHtml: html,
    wide: true,
  });
}
