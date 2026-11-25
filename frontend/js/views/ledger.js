/**
 * View 3: Immutable Append-Only Credit Ledger & Maker-Checker Approval Queue
 */
import { apiRequest, getActiveActor } from "../api.js";
import { esc, evidenceBadge, fmtNum, fmtSigned, statusBadge } from "../format.js";

const state = { search: "", tx_type: "all", status: "all", period: "all", showSuperseded: false };

export async function renderLedger(root, ctx) {
  const params = new URLSearchParams();
  if (state.tx_type !== "all") params.set("tx_type", state.tx_type);
  if (state.status !== "all") params.set("status", state.status);
  if (state.period !== "all") params.set("period_month", state.period);
  if (state.search) params.set("search", state.search);
  if (state.showSuperseded) params.set("include_superseded", "true");

  const [data, poolsData] = await Promise.all([
    apiRequest(`/api/ledger?${params.toString()}`),
    apiRequest("/api/pools"),
  ]);
  const actor = getActiveActor();
  const b = data.balance;
  ctx.updateNavBadges(b.open_exceptions, b.pending_approval_count);

  const isFinance = actor.role === "FINANCE";
  const canSubmit = ["OPERATIONS", "FINANCE", "ADMIN"].includes(actor.role);
  const canTopUp = ["FINANCE", "ADMIN"].includes(actor.role);

  root.innerHTML = `
    <!-- Maker-Checker Pending Approval Queue -->
    ${
      data.pending_approvals.length
        ? `
        <div class="card panel mb-16" style="border-color:var(--yellow-border)">
          <div class="panel-head">
            <div>
              <h2>Maker-Checker Approval Queue (${data.pending_approvals.length} Pending)</h2>
              <div class="panel-sub">Segregation of Duties: Operations submits adjustments; a distinct Finance Checker must approve or reject before Confirmed Balance changes.</div>
            </div>
            <span class="badge ${isFinance ? "green" : "yellow"}">
              ${isFinance ? "Finance Checker Active" : `Current Role: ${actor.role} (Switch to Finance to Approve)`}
            </span>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>Tx Code</th>
                  <th>Date</th>
                  <th>Reference</th>
                  <th>Client / Project</th>
                  <th class="right">Units</th>
                  <th>Submitted By (Maker)</th>
                  <th>Justification</th>
                  <th class="right">Finance Action</th>
                </tr>
              </thead>
              <tbody>
                ${data.pending_approvals
                  .map((tx) => {
                    const isSelf = tx.created_by.toLowerCase() === actor.name.toLowerCase();
                    return `
                      <tr>
                        <td class="mono nowrap"><strong>${esc(tx.tx_code)}</strong></td>
                        <td class="mono nowrap">${esc(tx.tx_date)}</td>
                        <td class="mono nowrap">${esc(tx.reference_code)}</td>
                        <td>${esc(tx.client_name || "Master Pool")}${tx.project_name ? ` · ${esc(tx.project_name)}` : ""}</td>
                        <td class="right num ${tx.units < 0 ? "unit-neg" : "unit-pos"}">${fmtSigned(tx.units)}</td>
                        <td class="mono">${esc(tx.created_by)}</td>
                        <td style="max-width:260px">${esc(tx.notes || "—")}</td>
                        <td class="right nowrap">
                          ${
                            isFinance && !isSelf
                              ? `
                              <button class="btn sm success" data-approve="${tx.id}">Approve</button>
                              <button class="btn sm danger" data-reject="${tx.id}">Reject</button>
                            `
                              : `<span class="badge slate">${isSelf ? "Cannot Self-Approve" : "Finance Sign-Off Req."}</span>`
                          }
                        </td>
                      </tr>
                    `;
                  })
                  .join("")}
              </tbody>
            </table>
          </div>
        </div>
      `
        : ""
    }

    <!-- Ledger Summary Strip -->
    <div class="formula-strip">
      <div class="formula-eq">
        <span class="term">Confirmed Balance <strong>${fmtNum(b.confirmed_balance)}</strong></span>
        <span class="op">−</span>
        <span class="term">Pending Usage <strong>${fmtNum(b.pending_usage)}</strong></span>
        <span class="op">=</span>
        <span class="term">Estimated Balance <strong>${fmtNum(b.estimated_balance)}</strong></span>
        <span class="op">|</span>
        <span class="term">Awaiting Approval <strong>${fmtSigned(b.pending_approval_units)}</strong></span>
      </div>
      <span class="badge green">Append-Only Ledger (DB Triggers Active)</span>
    </div>

    <!-- Main Ledger Card -->
    <div class="card panel">
      <div class="panel-head">
        <div>
          <h2>Credit Transaction Ledger (${fmtNum(data.items.length)} rows)</h2>
          <div class="panel-sub">Posted rows cannot be edited or deleted. Corrections require an append-only Reversal entry linked via Parent Transaction ID.</div>
        </div>
        <div class="toolbar-group">
          ${canSubmit ? `<button class="btn" id="btn-propose-adj">+ Propose Adjustment</button>` : ""}
          ${canTopUp ? `<button class="btn" id="btn-record-topup">+ Record Official Top-Up</button>` : ""}
          <a class="btn primary" href="/api/ledger/export.csv?${params.toString()}" download="pulsifi-credit-ledger.csv">Export CSV</a>
        </div>
      </div>

      <div class="toolbar">
        <div class="toolbar-group">
          <input class="input" id="led-search" style="min-width:230px" placeholder="Search Tx code, ref, client, project…" value="${esc(state.search)}" />
          <select class="select" id="led-type">
            <option value="all">All transaction types</option>
            ${["Opening Balance", "Top-Up", "Usage", "Reversal", "Adjustment", "Refund", "Expiry"]
              .map((t) => `<option value="${t}" ${state.tx_type === t ? "selected" : ""}>${t}</option>`)
              .join("")}
          </select>
          <select class="select" id="led-status">
            <option value="all">All active statuses</option>
            ${["Confirmed", "Pending", "Pending Approval", "Rejected", "Superseded", "Cancelled"]
              .map((s) => `<option value="${s}" ${state.status === s ? "selected" : ""}>${s}</option>`)
              .join("")}
          </select>
          <select class="select" id="led-period">
            <option value="all">All periods</option>
            ${data.periods
              .map((p) => `<option value="${p}" ${state.period === p ? "selected" : ""}>${p}</option>`)
              .join("")}
          </select>
        </div>
        <label style="font-size:12px;color:var(--ink-muted);display:flex;align-items:center;gap:6px;cursor:pointer">
          <input type="checkbox" id="led-superseded" ${state.showSuperseded ? "checked" : ""} /> Show superseded L4 pending rows
        </label>
      </div>

      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Tx Code / Date</th>
              <th>Type</th>
              <th>Pool Attribution</th>
              <th>Reference</th>
              <th class="right">Units</th>
              <th>Status</th>
              <th>Evidence &amp; Governance</th>
              <th class="right">Control</th>
            </tr>
          </thead>
          <tbody>
            ${
              data.items.length
                ? data.items
                    .map((t) => {
                      const poolTag =
                        t.pool_owner_type === "MASTER"
                          ? `<span class="badge blue">Master Pool</span>`
                          : t.pool_owner_type === "PARTNER"
                          ? `${esc(t.partner_name || "Partner")} <span class="badge slate">Partner</span>`
                          : t.pool_owner_type === "CLIENT"
                          ? `${esc(t.client_name || "Client")} · ${esc(t.project_name || "")}`
                          : `<span class="badge red">Unassigned</span>`;

                      const canReverse =
                        isFinance &&
                        t.status === "Confirmed" &&
                        t.tx_type !== "Reversal" &&
                        t.tx_type !== "Opening Balance" &&
                        !t.is_reversed;

                      return `
                        <tr>
                          <td class="mono nowrap">
                            <strong>${esc(t.tx_code)}</strong>
                            <div class="panel-sub">${esc(t.tx_date)}${t.parent_tx_code ? ` · ↳ ${esc(t.parent_tx_code)}` : ""}</div>
                          </td>
                          <td class="nowrap"><span class="badge slate">${esc(t.tx_type)}</span></td>
                          <td>${poolTag}</td>
                          <td class="mono nowrap">${esc(t.reference_code)}</td>
                          <td class="right num ${t.units < 0 ? "unit-neg" : "unit-pos"}">${fmtSigned(t.units)}</td>
                          <td>${statusBadge(t.status)}</td>
                          <td class="nowrap">
                            ${evidenceBadge(t.evidence_level, t.source_type)}
                            <div class="panel-sub">M: ${esc(t.created_by.split("@")[0])}${t.approved_by ? ` · C: ${esc(t.approved_by.split("@")[0])}` : ""}</div>
                          </td>
                          <td class="right nowrap">
                            ${
                              canReverse
                                ? `<button class="btn sm ghost" data-reverse="${t.id}" data-code="${esc(t.tx_code)}">Reverse</button>`
                                : t.is_reversed
                                ? `<span class="badge slate">Reversed</span>`
                                : `<span style="color:var(--ink-muted);font-size:11px">Immutable</span>`
                            }
                          </td>
                        </tr>
                      `;
                    })
                    .join("")
                : `<tr><td colspan="8" style="text-align:center;padding:24px;color:var(--ink-muted)">No matching ledger entries.</td></tr>`
            }
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Filter bindings
  let timer;
  root.querySelector("#led-search").addEventListener("input", (e) => {
    state.search = e.target.value;
    clearTimeout(timer);
    timer = setTimeout(() => renderLedger(root, ctx), 180);
  });
  root.querySelector("#led-type").addEventListener("change", (e) => {
    state.tx_type = e.target.value;
    renderLedger(root, ctx);
  });
  root.querySelector("#led-status").addEventListener("change", (e) => {
    state.status = e.target.value;
    renderLedger(root, ctx);
  });
  root.querySelector("#led-period").addEventListener("change", (e) => {
    state.period = e.target.value;
    renderLedger(root, ctx);
  });
  root.querySelector("#led-superseded").addEventListener("change", (e) => {
    state.showSuperseded = e.target.checked;
    renderLedger(root, ctx);
  });

  // Maker-Checker Approve/Reject
  root.querySelectorAll("[data-approve]").forEach((btn) => {
    btn.addEventListener("click", () => openDecisionModal(btn.dataset.approve, "APPROVE", root, ctx));
  });
  root.querySelectorAll("[data-reject]").forEach((btn) => {
    btn.addEventListener("click", () => openDecisionModal(btn.dataset.reject, "REJECT", root, ctx));
  });

  // Reversal
  root.querySelectorAll("[data-reverse]").forEach((btn) => {
    btn.addEventListener("click", () => openReversalModal(btn.dataset.reverse, btn.dataset.code, root, ctx));
  });

  // Propose Adjustment
  root.querySelector("#btn-propose-adj")?.addEventListener("click", () => {
    openAdjustmentModal(poolsData.projects, root, ctx);
  });

  // Record Official Top-Up
  root.querySelector("#btn-record-topup")?.addEventListener("click", () => {
    openTopUpModal(root, ctx);
  });
}

function openDecisionModal(txId, decision, root, ctx) {
  ctx.openModal({
    title: `${decision === "APPROVE" ? "Approve" : "Reject"} Credit Adjustment`,
    subtitle: "Finance Maker-Checker verification — logged to immutable Audit Trail",
    bodyHtml: `
      <form id="decision-form">
        <div class="field">
          <label for="dec-reason">Finance Verification Reason *</label>
          <textarea class="textarea" id="dec-reason" rows="3" required placeholder="e.g., Verified Pulsifi support credit waiver ticket #8845"></textarea>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="dec-cancel">Cancel</button>
          <button type="submit" class="btn ${decision === "APPROVE" ? "success" : "danger"}">
            Confirm ${decision === "APPROVE" ? "Approval" : "Rejection"}
          </button>
        </div>
      </form>
    `,
    onMount: (el) => {
      el.querySelector("#dec-cancel").addEventListener("click", ctx.closeModal);
      el.querySelector("#decision-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await apiRequest(`/api/ledger/adjustments/${txId}/decision`, {
            method: "POST",
            json: { decision, reason: el.querySelector("#dec-reason").value },
          });
          ctx.closeModal();
          ctx.toast(`Adjustment ${decision.toLowerCase()}d and recorded in audit trail.`, "success");
          await renderLedger(root, ctx);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}

function openReversalModal(txId, txCode, root, ctx) {
  ctx.openModal({
    title: `Append Reversal for ${txCode}`,
    subtitle: "Original Confirmed ledger row remains untouched; an offsetting Reversal entry will be appended.",
    bodyHtml: `
      <form id="rev-form">
        <div class="field">
          <label for="rev-reason">Reversal Justification *</label>
          <textarea class="textarea" id="rev-reason" rows="3" required placeholder="Explain why this posted transaction is being reversed…"></textarea>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="rev-cancel">Cancel</button>
          <button type="submit" class="btn primary">Post Append-Only Reversal</button>
        </div>
      </form>
    `,
    onMount: (el) => {
      el.querySelector("#rev-cancel").addEventListener("click", ctx.closeModal);
      el.querySelector("#rev-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const rev = await apiRequest(`/api/ledger/${txId}/reverse`, {
            method: "POST",
            json: { reason: el.querySelector("#rev-reason").value },
          });
          ctx.closeModal();
          ctx.toast(`Reversal ${rev.tx_code} (${fmtSigned(rev.units)} units) appended.`, "success");
          await renderLedger(root, ctx);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}

function openAdjustmentModal(projects, root, ctx) {
  ctx.openModal({
    title: "Propose Credit Adjustment (Maker-Checker)",
    subtitle: "Creates a Pending Approval entry that requires a distinct Finance Checker to approve before updating Confirmed Balance.",
    bodyHtml: `
      <form id="adj-form">
        <div class="form-grid">
          <div class="field">
            <label for="adj-date">Effective Date</label>
            <input class="input" id="adj-date" type="date" value="2026-09-19" required />
          </div>
          <div class="field">
            <label for="adj-units">Signed Credit Units (+ credit / − debit)</label>
            <input class="input num" id="adj-units" type="number" value="10" required />
          </div>
          <div class="field">
            <label for="adj-ref">Reference / Ticket ID</label>
            <input class="input mono" id="adj-ref" value="ADJ-2026-099" required />
          </div>
          <div class="field">
            <label for="adj-proj">Project Attribution (optional)</label>
            <select class="select" id="adj-proj">
              <option value="">Master Pool (Firm-wide)</option>
              ${projects
                .map(
                  (p) =>
                    `<option value="${p.id}">${esc(p.name)} (${p.pool_owner_type === "PARTNER" ? esc(p.partner_name) : esc(p.client_name)})</option>`
                )
                .join("")}
            </select>
          </div>
          <div class="field full">
            <label for="adj-reason">Evidence &amp; Business Justification *</label>
            <textarea class="textarea" id="adj-reason" rows="3" required placeholder="Reference Pulsifi support ticket or discrepancy evidence…"></textarea>
          </div>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="adj-cancel">Cancel</button>
          <button type="submit" class="btn primary">Submit for Finance Approval</button>
        </div>
      </form>
    `,
    onMount: (el) => {
      el.querySelector("#adj-cancel").addEventListener("click", ctx.closeModal);
      el.querySelector("#adj-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const projVal = el.querySelector("#adj-proj").value;
          const res = await apiRequest("/api/ledger/adjustments", {
            method: "POST",
            json: {
              tx_date: el.querySelector("#adj-date").value,
              units: Number(el.querySelector("#adj-units").value),
              reference_code: el.querySelector("#adj-ref").value,
              project_id: projVal ? Number(projVal) : null,
              reason: el.querySelector("#adj-reason").value,
            },
          });
          ctx.closeModal();
          ctx.toast(`Adjustment ${res.tx_code} submitted for Finance approval.`, "success");
          await renderLedger(root, ctx);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}

function openTopUpModal(root, ctx) {
  ctx.openModal({
    title: "Record Official Credit Top-Up Invoice",
    subtitle: "Level 1 Authoritative funding entry with contract batch expiry and unit cost valuation.",
    bodyHtml: `
      <form id="topup-form">
        <div class="form-grid">
          <div class="field">
            <label for="tu-date">Purchase Date</label>
            <input class="input" id="tu-date" type="date" value="2026-09-20" required />
          </div>
          <div class="field">
            <label for="tu-exp">Expiry Date</label>
            <input class="input" id="tu-exp" type="date" value="2027-09-19" required />
          </div>
          <div class="field">
            <label for="tu-batch">Batch Ref</label>
            <input class="input mono" id="tu-batch" value="PUL-2026-Q4A" required />
          </div>
          <div class="field">
            <label for="tu-inv">Official Invoice Ref</label>
            <input class="input mono" id="tu-inv" value="INV-PUL-2026-10" required />
          </div>
          <div class="field">
            <label for="tu-units">Purchased Units</label>
            <input class="input num" id="tu-units" type="number" min="1" value="1500" required />
          </div>
          <div class="field">
            <label for="tu-cost">Unit Cost (USD)</label>
            <input class="input num" id="tu-cost" type="number" step="0.01" min="0" value="11.25" required />
          </div>
          <div class="field full">
            <label for="tu-notes">Contract Notes</label>
            <input class="input" id="tu-notes" value="Q4 enterprise credit replenishment pack" />
          </div>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="tu-cancel">Cancel</button>
          <button type="submit" class="btn primary">Post Confirmed Top-Up</button>
        </div>
      </form>
    `,
    onMount: (el) => {
      el.querySelector("#tu-cancel").addEventListener("click", ctx.closeModal);
      el.querySelector("#topup-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const res = await apiRequest("/api/ledger/topups", {
            method: "POST",
            json: {
              tx_date: el.querySelector("#tu-date").value,
              expires_at: el.querySelector("#tu-exp").value,
              batch_ref: el.querySelector("#tu-batch").value,
              invoice_ref: el.querySelector("#tu-inv").value,
              units: Number(el.querySelector("#tu-units").value),
              unit_cost: Number(el.querySelector("#tu-cost").value),
              currency: "USD",
              notes: el.querySelector("#tu-notes").value,
            },
          });
          ctx.closeModal();
          ctx.toast(`Official Top-Up ${res.tx_code} (+${fmtNum(res.units)} units) posted.`, "success");
          await renderLedger(root, ctx);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}
