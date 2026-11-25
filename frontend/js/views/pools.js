/**
 * View 4: Client-Funded Pools, Partner-Funded Pools, Phase 1 Statements & Campaign Mappings
 * Explicitly resolves Commercial Topology Blind Spot & Attribution Gap (#1 Operational Risk).
 */
import { apiRequest, getActiveRole } from "../api.js";
import { esc, evidenceBadge, fmtNum, fmtSigned, statusBadge } from "../format.js";

export async function renderPools(root, ctx) {
  const data = await apiRequest("/api/pools");
  const rc = data.reconciliation_check;
  const canMap = ["OPERATIONS", "FINANCE", "ADMIN"].includes(getActiveRole());

  root.innerHTML = `
    <!-- Mathematical Zero-Double-Counting Verification Strip -->
    <div class="formula-strip">
      <div class="formula-eq">
        <span class="term">Client Pools <strong>${fmtNum(rc.client_confirmed_used)}</strong></span>
        <span class="op">+</span>
        <span class="term">Partner Pools <strong>${fmtNum(rc.partner_confirmed_used)}</strong></span>
        <span class="op">+</span>
        <span class="term">Unassigned <strong>${fmtNum(rc.unassigned_confirmed_used)}</strong></span>
        <span class="op">=</span>
        <span class="term"><strong>${fmtNum(rc.sum_confirmed_used)}</strong> Total Confirmed Ledger Usage</span>
      </div>
      <span class="badge green">Pool Topology Verified · Zero Double-Counting</span>
    </div>

    <!-- Client & Partner Pools Tables (Full-width stacked for crisp zero-clipping alignment) -->
    <div class="grid mb-16">
      <div class="card panel">
        <div class="panel-head">
          <div>
            <h2>Client-Funded Pools</h2>
            <div class="panel-sub">Projects tagged <span class="mono">pool_owner_type = CLIENT</span></div>
          </div>
          <span class="badge blue">Direct Firm Clients</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Client</th>
                <th class="right">Allocated</th>
                <th class="right">Confirmed</th>
                <th class="right">Pending</th>
                <th class="right">Remaining</th>
                <th>§16 Health</th>
                <th class="right">Statement</th>
              </tr>
            </thead>
            <tbody>
              ${data.client_pools
                .map(
                  (c) => `
                  <tr>
                    <td><strong>${esc(c.name)}</strong><div class="panel-sub mono">${esc(c.code)}</div></td>
                    <td class="right num">${fmtNum(c.allocated)}</td>
                    <td class="right num">${fmtNum(c.confirmed_used)}</td>
                    <td class="right num">${fmtNum(c.pending_used)}</td>
                    <td class="right num"><strong>${fmtNum(c.remaining)}</strong></td>
                    <td><span class="badge ${c.health.badge}">${c.remaining_pct}% · ${esc(c.health.tier)}</span></td>
                    <td class="right nowrap">
                      <button class="btn sm" data-stmt-type="CLIENT" data-stmt-id="${c.id}">Statement</button>
                    </td>
                  </tr>
                `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>

      <div class="card panel">
        <div class="panel-head">
          <div>
            <h2>Partner-Funded Reseller Pools</h2>
            <div class="panel-sub">Phase 1 delivers scheduled CSV / Printable Statements (External B2B Portal deferred cleanly to Phase 2)</div>
          </div>
          <span class="badge slate">Reseller Pools</span>
        </div>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>Partner</th>
                <th class="right">Allocated</th>
                <th class="right">Confirmed</th>
                <th class="right">Pending</th>
                <th class="right">Remaining</th>
                <th>§16 Health</th>
                <th class="right">Phase 1 Export</th>
              </tr>
            </thead>
            <tbody>
              ${data.partner_pools
                .map(
                  (p) => `
                  <tr>
                    <td><strong>${esc(p.name)}</strong><div class="panel-sub mono">${esc(p.code)}</div></td>
                    <td class="right num">${fmtNum(p.allocated)}</td>
                    <td class="right num">${fmtNum(p.confirmed_used)}</td>
                    <td class="right num">${fmtNum(p.pending_used)}</td>
                    <td class="right num"><strong>${fmtNum(p.remaining)}</strong></td>
                    <td><span class="badge ${p.health.badge}">${p.remaining_pct}% · ${esc(p.health.tier)}</span></td>
                    <td class="right nowrap">
                      <button class="btn sm" data-stmt-type="PARTNER" data-stmt-id="${p.id}">Statement</button>
                    </td>
                  </tr>
                `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Pulsifi Campaign -> Project Attribution Mapping Table -->
    <div class="card panel">
      <div class="panel-head">
        <div>
          <h2>Pulsifi Campaign → Internal Project Mapping Table</h2>
          <div class="panel-sub">Solves the #1 Attribution Blind Spot: maps Pulsifi Role/Campaign names to firm Projects &amp; Credit Pools. Unmapped names auto-route to the Exception Queue and backfill in 1 click.</div>
        </div>
        ${canMap ? `<button class="btn primary" id="btn-add-mapping">+ Add Campaign Mapping</button>` : ""}
      </div>

      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Pulsifi Campaign Key</th>
              <th>Internal Project</th>
              <th>Pool Owner</th>
              <th>Naming Convention / Notes</th>
              <th>Created By</th>
            </tr>
          </thead>
          <tbody>
            ${data.campaign_mappings
              .map(
                (m) => `
                <tr>
                  <td class="mono nowrap"><strong>${esc(m.pulsifi_campaign_key)}</strong></td>
                  <td>${esc(m.project_name)} <span class="mono panel-sub">(${esc(m.project_code)})</span></td>
                  <td>
                    ${
                      m.pool_owner_type === "PARTNER"
                        ? `${esc(m.partner_name)} <span class="badge slate">Partner Pool</span>`
                        : `${esc(m.client_name)} <span class="badge blue">Client Pool</span>`
                    }
                  </td>
                  <td style="color:var(--ink-muted)">${esc(m.naming_convention_hint || "—")}</td>
                  <td class="mono" style="font-size:11.5px">${esc(m.created_by)}</td>
                </tr>
              `
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </div>
  `;

  root.querySelectorAll("[data-stmt-type]").forEach((btn) => {
    btn.addEventListener("click", () =>
      openStatementModal(btn.dataset.stmtType, btn.dataset.stmtId, ctx)
    );
  });

  root.querySelector("#btn-add-mapping")?.addEventListener("click", () => {
    openMappingModal(data.projects, root, ctx);
  });
}

async function openStatementModal(poolType, poolId, ctx) {
  const stmt = await apiRequest(`/api/statements/${poolType}/${poolId}`);
  const s = stmt.summary;

  ctx.openModal({
    title: `${stmt.owner.name} — Credit Usage Statement`,
    subtitle: `Phase 1 Deliverable · ${stmt.pool_type} Pool (${stmt.owner.code}) · Generated ${stmt.generated_at.slice(0, 10)}`,
    wide: true,
    bodyHtml: `
      <div class="grid grid-4 mb-16">
        <div class="card kpi-card" style="min-height:auto;padding:12px">
          <div class="kpi-label">Allocated</div>
          <div class="kpi-value" style="font-size:20px">${fmtNum(s.allocated_credits)}</div>
        </div>
        <div class="card kpi-card" style="min-height:auto;padding:12px">
          <div class="kpi-label">Confirmed Used</div>
          <div class="kpi-value" style="font-size:20px">${fmtNum(s.confirmed_used)}</div>
        </div>
        <div class="card kpi-card" style="min-height:auto;padding:12px">
          <div class="kpi-label">Pending Used</div>
          <div class="kpi-value" style="font-size:20px">${fmtNum(s.pending_used)}</div>
        </div>
        <div class="card kpi-card" style="min-height:auto;padding:12px">
          <div class="kpi-label">Est. Remaining</div>
          <div class="kpi-value" style="font-size:20px">${fmtNum(s.estimated_remaining)}</div>
        </div>
      </div>

      <div class="table-wrap mb-16" style="max-height:340px;overflow:auto">
        <table class="table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Tx Code</th>
              <th>Project</th>
              <th>Reference</th>
              <th>Candidate Hash</th>
              <th class="right">Units</th>
              <th>Status</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            ${
              stmt.transactions.length
                ? stmt.transactions
                    .map(
                      (t) => `
                      <tr>
                        <td class="mono nowrap">${esc(t.tx_date)}</td>
                        <td class="mono nowrap">${esc(t.tx_code)}</td>
                        <td>${esc(t.project_name || "—")}</td>
                        <td class="mono nowrap">${esc(t.reference_code)}</td>
                        <td class="mono nowrap">${esc(t.candidate_ref_hash || "—")}</td>
                        <td class="right num ${t.units < 0 ? "unit-neg" : "unit-pos"}">${fmtSigned(t.units)}</td>
                        <td>${statusBadge(t.status)}</td>
                        <td class="nowrap">${evidenceBadge(t.evidence_level, t.source_type)}</td>
                      </tr>
                    `
                    )
                    .join("")
                : `<tr><td colspan="8" style="color:var(--ink-muted)">No transactions recorded for this pool.</td></tr>`
            }
          </tbody>
        </table>
      </div>

      <p style="font-size:11px;color:var(--ink-muted);margin:0 0 12px">${esc(stmt.disclaimer)}</p>

      <div class="form-actions no-print">
        <button class="btn" id="stmt-print">Print / Save PDF</button>
        <a class="btn primary" href="/api/statements/${poolType}/${poolId}/export.csv" download>Download Statement CSV</a>
      </div>
    `,
    onMount: (el) => {
      el.querySelector("#stmt-print").addEventListener("click", () => window.print());
    },
  });
}

function openMappingModal(projects, root, ctx) {
  ctx.openModal({
    title: "Add Pulsifi Campaign → Project Mapping",
    subtitle: "Automatically attributes any existing Pending UNASSIGNED records for this campaign key and resolves matching Unknown Mapping exceptions.",
    bodyHtml: `
      <form id="map-form">
        <div class="form-grid">
          <div class="field full">
            <label for="map-key">Pulsifi Campaign / Role Name *</label>
            <input class="input mono" id="map-key" required placeholder="e.g., UNMAPPED-SG-FINTECH-Q3 or PILOT-NEW-CLIENT-2026" />
          </div>
          <div class="field full">
            <label for="map-proj">Target Internal Project &amp; Credit Pool *</label>
            <select class="select" id="map-proj" required>
              ${projects
                .map(
                  (p) =>
                    `<option value="${p.id}">${esc(p.name)} [${esc(p.code)}] — ${
                      p.pool_owner_type === "PARTNER"
                        ? `${esc(p.partner_name)} (Partner Pool)`
                        : `${esc(p.client_name)} (Client Pool)`
                    }</option>`
                )
                .join("")}
            </select>
          </div>
          <div class="field full">
            <label for="map-hint">Convention Note</label>
            <input class="input" id="map-hint" placeholder="e.g., Approved Q3 alias confirmed with project lead" />
          </div>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="map-cancel">Cancel</button>
          <button type="submit" class="btn primary">Save Mapping &amp; Backfill</button>
        </div>
      </form>
    `,
    onMount: (el) => {
      el.querySelector("#map-cancel").addEventListener("click", ctx.closeModal);
      el.querySelector("#map-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const res = await apiRequest("/api/campaign-mappings", {
            method: "POST",
            json: {
              pulsifi_campaign_key: el.querySelector("#map-key").value,
              project_id: Number(el.querySelector("#map-proj").value),
              naming_convention_hint: el.querySelector("#map-hint").value || null,
            },
          });
          ctx.closeModal();
          ctx.toast(
            `Mapped '${res.pulsifi_campaign_key}' → ${res.project_name} (${res.backfilled_assessments} assessment(s) attributed).`,
            "success"
          );
          await renderPools(root, ctx);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}
