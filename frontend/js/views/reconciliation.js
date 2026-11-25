/**
 * View 6: 4-Tier Confidence-Scored Monthly Reconciliation Engine
 * Includes Official Statement CSV upload, Line-by-Line Match Table, and 2-Month Excel Parallel-Run Tracker.
 */
import { apiRequest, apiUpload, getActiveRole } from "../api.js";
import { esc, fmtMonth, fmtNum, fmtSigned, statusBadge, tierBadge } from "../format.js";

const state = { selectedRunId: null, tierFilter: "all" };

export async function renderReconciliation(root, ctx) {
  const data = await apiRequest("/api/reconciliations");
  const runs = data.runs || [];
  let detail = data.latest;

  if (state.selectedRunId && runs.some((r) => r.id === state.selectedRunId)) {
    detail = await apiRequest(`/api/reconciliations/${state.selectedRunId}`);
  } else if (detail) {
    state.selectedRunId = detail.id;
  }

  const isFinance = getActiveRole() === "FINANCE";
  const canRun = ["FINANCE", "OPERATIONS", "ADMIN"].includes(getActiveRole());

  const lines = (detail?.lines || []).filter(
    (ln) => state.tierFilter === "all" || ln.match_tier === state.tierFilter
  );

  root.innerHTML = `
    <!-- Top Row: Active Period Summary + Upload & 4-Tier Logic -->
    <div class="grid grid-main-side mb-16">
      <div class="card panel">
        <div class="panel-head">
          <div>
            <h2>Monthly Reconciliation · ${detail ? esc(fmtMonth(detail.period_month)) : "No Runs"}</h2>
            <div class="panel-sub">${detail ? `${esc(detail.recon_code)} · Source: <span class="mono">${esc(detail.official_filename)}</span>` : "Upload an official Pulsifi monthly statement CSV to begin."}</div>
          </div>
          <div class="toolbar-group">
            <select class="select" id="recon-run-select">
              ${runs
                .map(
                  (r) =>
                    `<option value="${r.id}" ${detail && r.id === detail.id ? "selected" : ""}>${esc(r.period_month)} · ${esc(r.recon_code)} (${esc(r.status)})</option>`
                )
                .join("")}
            </select>
            ${detail ? statusBadge(detail.status) : ""}
          </div>
        </div>

        ${
          detail
            ? `
            <div class="grid grid-4 mb-16">
              <div class="card kpi-card" style="min-height:auto;padding:12px">
                <div class="kpi-label">Internal Confirmed</div>
                <div class="kpi-value" style="font-size:21px">${fmtNum(detail.ending_internal_confirmed)}</div>
                <div class="kpi-meta">Est: ${fmtNum(detail.ending_internal_estimated)}</div>
              </div>
              <div class="card kpi-card" style="min-height:auto;padding:12px">
                <div class="kpi-label">Pulsifi Official</div>
                <div class="kpi-value" style="font-size:21px">${fmtNum(detail.ending_official)}</div>
                <div class="kpi-meta">Level 1 Statement</div>
              </div>
              <div class="card kpi-card" style="min-height:auto;padding:12px">
                <div class="kpi-label">Net Variance</div>
                <div class="kpi-value" style="font-size:21px;color:${detail.variance_units === 0 ? "var(--green-ink)" : "var(--red-ink)"}">
                  ${fmtSigned(detail.variance_units)}
                </div>
                <div class="kpi-meta">${detail.unmatched_official} missing record(s)</div>
              </div>
              <div class="card kpi-card" style="min-height:auto;padding:12px">
                <div class="kpi-label">Match Rate</div>
                <div class="kpi-value" style="font-size:21px">${detail.match_rate_pct}%</div>
                <div class="kpi-meta">
                  Excel Parallel: <strong class="num">${detail.excel_parallel_balance !== null ? fmtNum(detail.excel_parallel_balance) : "Pending"}</strong>
                </div>
              </div>
            </div>

            <div class="table-wrap mb-16">
              <table class="table">
                <thead>
                  <tr>
                    <th>Reconciliation Bridge (${esc(fmtMonth(detail.period_month))})</th>
                    <th class="right">Internal Confirmed</th>
                    <th class="right">Pulsifi Official</th>
                    <th class="right">Difference</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Opening Balance</td>
                    <td class="right num">${fmtNum(detail.opening_internal)}</td>
                    <td class="right num">${fmtNum(detail.opening_official)}</td>
                    <td class="right num">${fmtSigned(detail.opening_internal - detail.opening_official)}</td>
                    <td>${statusBadge(detail.opening_internal === detail.opening_official ? "Matched" : "Review Required")}</td>
                  </tr>
                  <tr>
                    <td>Top-Ups</td>
                    <td class="right num">${fmtNum(detail.topups_internal)}</td>
                    <td class="right num">${fmtNum(detail.topups_official)}</td>
                    <td class="right num">${fmtSigned(detail.topups_internal - detail.topups_official)}</td>
                    <td>${statusBadge(detail.topups_internal === detail.topups_official ? "Matched" : "Review Required")}</td>
                  </tr>
                  <tr>
                    <td>Usage (Period Consumption)</td>
                    <td class="right num">${fmtNum(detail.usage_internal)}</td>
                    <td class="right num">${fmtNum(detail.usage_official)}</td>
                    <td class="right num">${fmtSigned(detail.usage_internal - detail.usage_official)}</td>
                    <td>${statusBadge(detail.usage_internal === detail.usage_official ? "Matched" : "Review Required")}</td>
                  </tr>
                  <tr>
                    <td>Approved Adjustments</td>
                    <td class="right num">${fmtSigned(detail.adjustments_internal)}</td>
                    <td class="right num">${fmtSigned(detail.adjustments_official)}</td>
                    <td class="right num">${fmtSigned(detail.adjustments_internal - detail.adjustments_official)}</td>
                    <td>${statusBadge(detail.adjustments_internal === detail.adjustments_official ? "Matched" : "Review Required")}</td>
                  </tr>
                  <tr style="background:var(--bg-subtle);font-weight:700">
                    <td>Ending Confirmed Balance</td>
                    <td class="right num">${fmtNum(detail.ending_internal_confirmed)}</td>
                    <td class="right num">${fmtNum(detail.ending_official)}</td>
                    <td class="right num ${detail.variance_units === 0 ? "unit-pos" : "unit-neg"}">${fmtSigned(detail.variance_units)}</td>
                    <td>${statusBadge(detail.status)}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
              <div class="panel-sub">
                ${
                  detail.excel_parallel_balance !== null
                    ? `<strong>2-Month Parallel-Run Check vs Excel:</strong> Ledger Confirmed (${fmtNum(detail.ending_internal_confirmed)}) vs Legacy Excel (${fmtNum(detail.excel_parallel_balance)}) = <strong class="num">${fmtSigned(detail.ending_internal_confirmed - detail.excel_parallel_balance)}</strong> units.`
                    : "Record legacy Excel ending balance during Finance finalization for 2-month parallel-run audit."
                }
              </div>
              <div class="toolbar-group">
                <button class="btn" id="btn-recon-exc">Review Exceptions</button>
                ${
                  detail.status !== "Finalized"
                    ? isFinance
                      ? `<button class="btn success" id="btn-finalize-recon">Finance Sign-Off &amp; Finalize</button>`
                      : `<span class="badge slate">Switch to Finance Role to Finalize</span>`
                    : `<span class="badge green">Finalized by ${esc(detail.finalized_by || "Finance")}</span>`
                }
              </div>
            </div>
          `
            : ""
        }
      </div>

      <!-- Right Column: 4-Tier Engine Breakdown + Upload New Statement -->
      <div class="card panel">
        <div class="panel-head">
          <div>
            <h3>4-Tier Matching Engine</h3>
            <div class="panel-sub">Confidence-tiered line attribution (§18)</div>
          </div>
          ${canRun ? `<button class="btn sm primary" id="btn-upload-stmt">+ Upload Statement CSV</button>` : ""}
        </div>

        ${
          detail
            ? `
            <div class="alert-list mb-16">
              <div class="alert-item" data-tier="1_EXACT_ID">
                <div>
                  <div class="alert-title">Tier 1 · Exact Assessment ID</div>
                  <div class="alert-detail">Deterministic ID match across statement &amp; ledger</div>
                </div>
                <span class="badge green">${fmtNum(detail.exact_matches)} · 100%</span>
              </div>
              <div class="alert-item" data-tier="2_CANDIDATE_DATE">
                <div>
                  <div class="alert-title">Tier 2 · Candidate Hash + Date</div>
                  <div class="alert-detail">Fallback when Pulsifi omits internal assessment ID</div>
                </div>
                <span class="badge blue">${fmtNum(detail.tier2_matches)} · 90%</span>
              </div>
              <div class="alert-item" data-tier="3_CANDIDATE_TYPE">
                <div>
                  <div class="alert-title">Tier 3 · Candidate Hash + Type</div>
                  <div class="alert-detail">Handles UTC timezone date shifts across midnight</div>
                </div>
                <span class="badge yellow">${fmtNum(detail.tier3_matches)} · 80%</span>
              </div>
              <div class="alert-item" data-tier="4_UNMATCHED_OFFICIAL">
                <div>
                  <div class="alert-title">Tier 4 · Unmatched Official Lines</div>
                  <div class="alert-detail">Auto-routed to Exceptions as Missing Record</div>
                </div>
                <span class="badge red">${fmtNum(detail.unmatched_official)} · &lt;80%</span>
              </div>
            </div>
          `
            : ""
        }

        <div class="notice-banner blue" style="margin-bottom:0;font-size:11.5px">
          <span><strong>Parallel-Run Cutover Policy:</strong> Retire legacy Excel only after 2 consecutive finalized monthly cycles within tolerance. Aug 2026 (Month 1) is <strong>Finalized (0 variance)</strong>; Sep 2026 is Month 2.</span>
        </div>
      </div>
    </div>

    <!-- Line-Level Reconciliation Matching Table -->
    ${
      detail && detail.lines && detail.lines.length
        ? `
        <div class="card panel">
          <div class="panel-head">
            <div>
              <h2>Line-by-Line Match Results (${fmtNum(lines.length)} of ${fmtNum(detail.lines.length)} lines)</h2>
              <div class="panel-sub">Stored permanently in <span class="mono">reconciliation_lines</span> with anonymized candidate hashes (zero raw PII).</div>
            </div>
            <select class="select" id="recon-tier-filter">
              <option value="all" ${state.tierFilter === "all" ? "selected" : ""}>All match tiers</option>
              <option value="4_UNMATCHED_OFFICIAL" ${state.tierFilter === "4_UNMATCHED_OFFICIAL" ? "selected" : ""}>Unmatched / Missing Internal</option>
              <option value="3_CANDIDATE_TYPE" ${state.tierFilter === "3_CANDIDATE_TYPE" ? "selected" : ""}>Tier 3 (80% Cand + Type)</option>
              <option value="2_CANDIDATE_DATE" ${state.tierFilter === "2_CANDIDATE_DATE" ? "selected" : ""}>Tier 2 (90% Cand + Date)</option>
              <option value="1_EXACT_ID" ${state.tierFilter === "1_EXACT_ID" ? "selected" : ""}>Tier 1 (100% Exact ID)</option>
              <option value="5_INTERNAL_ONLY" ${state.tierFilter === "5_INTERNAL_ONLY" ? "selected" : ""}>Internal Only</option>
            </select>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>Official ID</th>
                  <th>Candidate Hash</th>
                  <th>Date</th>
                  <th>Type</th>
                  <th class="right">Official</th>
                  <th class="right">Internal</th>
                  <th class="right">Diff</th>
                  <th>Match Tier</th>
                  <th>Linked Tx / Notes</th>
                </tr>
              </thead>
              <tbody>
                ${lines
                  .map(
                    (ln) => `
                    <tr>
                      <td class="mono nowrap"><strong>${esc(ln.official_assessment_id || "—")}</strong></td>
                      <td class="mono nowrap">${esc(ln.official_candidate_hash || "—")}</td>
                      <td class="mono nowrap">${esc(ln.official_date || "—")}</td>
                      <td class="nowrap">${esc(ln.official_type || "—")}</td>
                      <td class="right num">${fmtNum(ln.official_units)}</td>
                      <td class="right num">${fmtNum(ln.internal_units)}</td>
                      <td class="right num ${ln.unit_variance === 0 ? "" : "unit-neg"}">${fmtSigned(ln.unit_variance)}</td>
                      <td class="nowrap">${tierBadge(ln.match_tier, ln.match_confidence)}</td>
                      <td style="font-size:11.5px;color:var(--ink-secondary)">
                        ${ln.matched_tx_code ? `<span class="mono"><strong>${esc(ln.matched_tx_code)}</strong></span> · ` : ""}
                        ${esc(ln.notes || "")}
                      </td>
                    </tr>
                  `
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        </div>
      `
        : ""
    }
  `;

  root.querySelector("#recon-run-select")?.addEventListener("change", (e) => {
    state.selectedRunId = Number(e.target.value);
    state.tierFilter = "all";
    renderReconciliation(root, ctx);
  });

  root.querySelector("#recon-tier-filter")?.addEventListener("change", (e) => {
    state.tierFilter = e.target.value;
    renderReconciliation(root, ctx);
  });

  root.querySelectorAll("[data-tier]").forEach((el) => {
    el.addEventListener("click", () => {
      state.tierFilter = el.dataset.tier;
      renderReconciliation(root, ctx);
    });
  });

  root.querySelector("#btn-recon-exc")?.addEventListener("click", () => ctx.navigate("exceptions"));
  root.querySelector("#btn-upload-stmt")?.addEventListener("click", () => openUploadStatementModal(root, ctx));
  root.querySelector("#btn-finalize-recon")?.addEventListener("click", () =>
    openFinalizeModal(detail, root, ctx)
  );
}

function openUploadStatementModal(root, ctx) {
  ctx.openModal({
    title: "Run 4-Tier Reconciliation on Official Statement CSV",
    subtitle: "Upload a Pulsifi Official Monthly Billing Statement CSV (or re-run using the built-in September 2026 sample statement).",
    bodyHtml: `
      <form id="recon-upload-form">
        <div class="form-grid">
          <div class="field">
            <label for="ru-period">Billing Period (YYYY-MM) *</label>
            <input class="input mono" id="ru-period" value="2026-09" required pattern="\\d{4}-\\d{2}" />
          </div>
          <div class="field">
            <label for="ru-excel">Legacy Excel Ending Balance (optional)</label>
            <input class="input num" id="ru-excel" type="number" value="1295" placeholder="For parallel-run check" />
          </div>
          <div class="field full">
            <label for="ru-file">Pulsifi Official Monthly Statement (.csv)</label>
            <input class="input" id="ru-file" type="file" accept=".csv" />
            <div class="hint">Or click "Run With Built-In Sep 2026 Sample Statement" below to test immediately.</div>
          </div>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="ru-sample">Run Built-In Sep 2026 Sample</button>
          <button type="submit" class="btn primary">Upload &amp; Run Matching Engine</button>
        </div>
      </form>
    `,
    onMount: (el) => {
      async function executeRun(fileObj) {
        const fd = new FormData();
        fd.append("period_month", el.querySelector("#ru-period").value);
        const exVal = el.querySelector("#ru-excel").value;
        if (exVal !== "") fd.append("excel_parallel_balance", exVal);
        fd.append("file", fileObj);
        const result = await apiUpload("/api/reconciliations/run", fd);
        state.selectedRunId = result.id;
        state.tierFilter = "all";
        ctx.closeModal();
        ctx.toast(
          `Reconciliation ${result.recon_code} complete: ${result.match_rate_pct}% matched, variance ${fmtSigned(result.variance_units)} units.`,
          result.variance_units === 0 ? "success" : "warn"
        );
        await renderReconciliation(root, ctx);
      }

      el.querySelector("#ru-sample").addEventListener("click", async () => {
        try {
          const csvText = await apiRequest("/api/samples/official-statement");
          const file = new File([csvText], "pulsifi_official_statement_2026_09.csv", { type: "text/csv" });
          await executeRun(file);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });

      el.querySelector("#recon-upload-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fileInput = el.querySelector("#ru-file");
        if (!fileInput.files.length) {
          ctx.toast("Please choose a CSV file or click 'Run Built-In Sep 2026 Sample'.", "warn");
          return;
        }
        try {
          await executeRun(fileInput.files[0]);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}

function openFinalizeModal(detail, root, ctx) {
  ctx.openModal({
    title: `Finance Sign-Off · ${detail.recon_code}`,
    subtitle: `Finalize ${fmtMonth(detail.period_month)} reconciliation and record 2-Month Excel Parallel-Run verification.`,
    bodyHtml: `
      <form id="fin-form">
        <div class="field mb-16">
          <label for="fin-excel">Legacy Excel Ending Balance (Parallel-Run Audit)</label>
          <input class="input num" id="fin-excel" type="number" value="${detail.excel_parallel_balance ?? detail.ending_internal_confirmed}" />
        </div>
        <div class="field">
          <label for="fin-notes">Finance Sign-Off Notes *</label>
          <textarea class="textarea" id="fin-notes" rows="3" required placeholder="Confirm variance investigation and approval for period close…">Reviewed line-level matches and missing records; approved period close.</textarea>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="fin-cancel">Cancel</button>
          <button type="submit" class="btn success">Finalize Period</button>
        </div>
      </form>
    `,
    onMount: (el) => {
      el.querySelector("#fin-cancel").addEventListener("click", ctx.closeModal);
      el.querySelector("#fin-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const exVal = el.querySelector("#fin-excel").value;
          await apiRequest(`/api/reconciliations/${detail.id}/finalize`, {
            method: "POST",
            json: {
              excel_parallel_balance: exVal !== "" ? Number(exVal) : null,
              notes: el.querySelector("#fin-notes").value,
            },
          });
          ctx.closeModal();
          ctx.toast(`Reconciliation ${detail.recon_code} finalized by Finance.`, "success");
          await renderReconciliation(root, ctx);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}
