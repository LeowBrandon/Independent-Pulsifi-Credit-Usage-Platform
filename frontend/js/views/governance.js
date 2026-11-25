/**
 * View 7: Governance, Effective-Dated Credit Rules, Raw PII-Scrubbed Events & Immutable Audit Trail
 */
import { apiRequest, getActiveRole } from "../api.js";
import { esc, evidenceBadge, fmtMoney, fmtNum, fmtShortTs, statusBadge } from "../format.js";

const state = { activeTab: "rules" };

export async function renderGovernance(root, ctx) {
  const data = await apiRequest("/api/governance");
  const canEditRules = ["ADMIN", "FINANCE"].includes(getActiveRole());

  root.innerHTML = `
    <div class="card panel">
      <div class="panel-head">
        <div>
          <h2>Governance, Credit Rules &amp; Immutable Audit Trail</h2>
          <div class="panel-sub">Effective-dated unit rules prevent historical ledger mutation; SQLite/PostgreSQL triggers enforce append-only AuditLogs.</div>
        </div>
        <div class="toolbar-group">
          ${canEditRules ? `<button class="btn primary" id="btn-add-rule">+ Add Effective-Dated Rule</button>` : ""}
          <button class="btn danger sm" id="btn-reset-demo" title="Restores the seeded September 2026 demo state">Reset Demo Data</button>
        </div>
      </div>

      <div class="tabs">
        <button class="tab-btn ${state.activeTab === "rules" ? "active" : ""}" data-gtab="rules">Effective-Dated Rules (${data.credit_rules.length})</button>
        <button class="tab-btn ${state.activeTab === "batches" ? "active" : ""}" data-gtab="batches">Credit Batches &amp; Expiry (${data.credit_batches.length})</button>
        <button class="tab-btn ${state.activeTab === "raw" ? "active" : ""}" data-gtab="raw">PII-Scrubbed Raw Events (${data.raw_events.length})</button>
        <button class="tab-btn ${state.activeTab === "audit" ? "active" : ""}" data-gtab="audit">Immutable Audit Trail (${data.audit_logs.length})</button>
      </div>

      <div id="gov-tab-content"></div>
    </div>
  `;

  const body = root.querySelector("#gov-tab-content");

  if (state.activeTab === "rules") {
    body.innerHTML = `
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Assessment Type</th>
              <th>Billing Trigger</th>
              <th class="right">Credit Units</th>
              <th>Refund on Cancel</th>
              <th>Effective From</th>
              <th>Effective To</th>
              <th>Contract Notes</th>
            </tr>
          </thead>
          <tbody>
            ${data.credit_rules
              .map(
                (r) => `
                <tr>
                  <td><strong>${esc(r.assessment_type)}</strong></td>
                  <td><span class="badge blue">${esc(r.trigger_event)}</span></td>
                  <td class="right num"><strong>${fmtNum(r.credit_units)}</strong></td>
                  <td>${r.refund_on_cancel ? `<span class="badge green">Yes</span>` : `<span class="badge slate">No</span>`}</td>
                  <td class="mono">${esc(r.effective_from)}</td>
                  <td class="mono">${r.effective_to ? esc(r.effective_to) : `<span class="badge green">Active (Open)</span>`}</td>
                  <td style="color:var(--ink-muted)">${esc(r.notes || "—")}</td>
                </tr>
              `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  } else if (state.activeTab === "batches") {
    body.innerHTML = `
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Batch Ref</th>
              <th>Official Invoice</th>
              <th class="right">Purchased Units</th>
              <th class="right">Unit Cost</th>
              <th class="right">Total Spend</th>
              <th>Purchased</th>
              <th>Expires</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${data.credit_batches
              .map(
                (b) => `
                <tr>
                  <td class="mono"><strong>${esc(b.batch_ref)}</strong></td>
                  <td class="mono">${esc(b.invoice_ref)}</td>
                  <td class="right num"><strong>${fmtNum(b.purchased_units)}</strong></td>
                  <td class="right num">${esc(b.currency)} ${Number(b.unit_cost).toFixed(2)}</td>
                  <td class="right num">${fmtMoney(b.purchased_units * b.unit_cost, b.currency)}</td>
                  <td class="mono">${esc(b.purchased_at)}</td>
                  <td class="mono"><strong>${esc(b.expires_at)}</strong></td>
                  <td>${statusBadge(b.status)}</td>
                </tr>
              `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  } else if (state.activeTab === "raw") {
    body.innerHTML = `
      <div class="notice-banner green" style="margin-bottom:14px">
        <span><strong>PDPA / GDPR Privacy Verification:</strong> Candidate email addresses are stripped and replaced with deterministic HMAC-SHA256 tokens (<span class="mono">CAND-XXXXXXXXXX</span>) <em>before</em> writing to <span class="mono">raw_ingested_events</span>. SHA-256 payload hashing enforces idempotency.</span>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Ingested At</th>
              <th>Evidence Source</th>
              <th>SHA-256 Hash</th>
              <th class="right">PII Scrubbed</th>
              <th>Scrubbed Payload Preview</th>
            </tr>
          </thead>
          <tbody>
            ${data.raw_events
              .map(
                (ev) => `
                <tr>
                  <td class="mono">#${ev.id}</td>
                  <td class="mono nowrap">${esc(fmtShortTs(ev.ingested_at))}</td>
                  <td class="nowrap">${evidenceBadge(ev.evidence_level, ev.source_type)}</td>
                  <td class="mono nowrap">${esc(ev.payload_hash.slice(0, 12))}…</td>
                  <td class="right num">${ev.pii_redactions_count}</td>
                  <td class="mono" style="font-size:11px;max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(ev.payload_preview)}">${esc(ev.payload_preview)}</td>
                </tr>
              `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  } else {
    body.innerHTML = `
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Actor &amp; Timestamp</th>
              <th>Action / Entity</th>
              <th>Reason</th>
              <th>Before / After Diff (JSON)</th>
            </tr>
          </thead>
          <tbody>
            ${data.audit_logs
              .map(
                (a) => `
                <tr>
                  <td class="nowrap">
                    <div style="font-weight:600;font-size:12px">${esc(a.actor_name)}</div>
                    <div style="margin-top:3px">
                      <span class="badge slate">${esc(a.actor_role)}</span>
                      <span class="mono panel-sub" style="margin-left:4px">${esc(fmtShortTs(a.timestamp))}</span>
                    </div>
                  </td>
                  <td class="mono nowrap">
                    <strong>${esc(a.action)}</strong>
                    <div class="panel-sub">${esc(a.entity_type)}:${esc(a.entity_id)}</div>
                  </td>
                  <td style="max-width:260px">${esc(a.reason || "—")}</td>
                  <td class="mono" style="font-size:10.5px;max-width:340px;word-break:break-word;color:var(--ink-secondary)">
                    ${a.before_json ? `<div>Before: ${esc(a.before_json)}</div>` : ""}
                    ${a.after_json ? `<div>After: ${esc(a.after_json)}</div>` : ""}
                  </td>
                </tr>
              `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  root.querySelectorAll("[data-gtab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.activeTab = btn.dataset.gtab;
      renderGovernance(root, ctx);
    });
  });

  root.querySelector("#btn-add-rule")?.addEventListener("click", () => openAddRuleModal(root, ctx));

  root.querySelector("#btn-reset-demo")?.addEventListener("click", async () => {
    if (!confirm("Reset database to the clean September 2026 seeded MVP state?")) return;
    try {
      await apiRequest("/api/demo/reset", { method: "POST" });
      ctx.toast("Demo database cleanly re-seeded.", "success");
      ctx.navigate("overview");
    } catch (err) {
      ctx.toast(err.message, "error");
    }
  });
}

function openAddRuleModal(root, ctx) {
  ctx.openModal({
    title: "Add Effective-Dated Credit Rule",
    subtitle: "New rules apply strictly to assessments occurring on or after Effective From — historical ledger transactions are never retroactively recalculated.",
    bodyHtml: `
      <form id="rule-form">
        <div class="form-grid">
          <div class="field">
            <label for="rl-type">Assessment Type *</label>
            <input class="input" id="rl-type" value="Cognitive" required />
          </div>
          <div class="field">
            <label for="rl-trigger">Contractual Billing Trigger</label>
            <select class="select" id="rl-trigger">
              <option value="Completed">Completed</option>
              <option value="Sent">Sent (Invitation)</option>
              <option value="Started">Started</option>
            </select>
          </div>
          <div class="field">
            <label for="rl-units">Credit Units *</label>
            <input class="input num" id="rl-units" type="number" min="0" value="6" required />
          </div>
          <div class="field">
            <label for="rl-from">Effective From *</label>
            <input class="input" id="rl-from" type="date" value="2026-10-01" required />
          </div>
          <div class="field full">
            <label for="rl-notes">Contractual Justification</label>
            <input class="input" id="rl-notes" value="Q4 2026 Pulsifi tariff update" />
          </div>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="rl-cancel">Cancel</button>
          <button type="submit" class="btn primary">Save Credit Rule</button>
        </div>
      </form>
    `,
    onMount: (el) => {
      el.querySelector("#rl-cancel").addEventListener("click", ctx.closeModal);
      el.querySelector("#rule-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await apiRequest("/api/governance/credit-rules", {
            method: "POST",
            json: {
              assessment_type: el.querySelector("#rl-type").value,
              trigger_event: el.querySelector("#rl-trigger").value,
              credit_units: Number(el.querySelector("#rl-units").value),
              refund_on_cancel: true,
              effective_from: el.querySelector("#rl-from").value,
              notes: el.querySelector("#rl-notes").value || null,
            },
          });
          ctx.closeModal();
          ctx.toast("Effective-dated credit rule saved and logged to audit trail.", "success");
          await renderGovernance(root, ctx);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}
