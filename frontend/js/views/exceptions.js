/**
 * View 5: Exception Management Queue
 * Dedicated exceptions table with live cross-view counts and 1-click Unknown Mapping resolution.
 */
import { apiRequest, getActiveRole } from "../api.js";
import { esc, fmtShortTs, severityBadge, statusBadge } from "../format.js";

const state = { category: "all", status: "all" };

export async function renderExceptions(root, ctx) {
  const params = new URLSearchParams();
  if (state.category !== "all") params.set("category", state.category);
  if (state.status !== "all") params.set("status", state.status);

  const [data, poolsData] = await Promise.all([
    apiRequest(`/api/exceptions?${params.toString()}`),
    apiRequest("/api/pools"),
  ]);
  const s = data.summary;
  const canAct = ["OPERATIONS", "FINANCE", "ADMIN"].includes(getActiveRole());
  ctx.updateNavBadges(s.open_count, null);

  root.innerHTML = `
    <div class="grid grid-3 mb-16">
      <div class="card kpi-card" style="min-height:96px">
        <div class="kpi-label">Open / In Review Exceptions</div>
        <div class="kpi-value" style="color:${s.open_count ? "var(--red-ink)" : "var(--green-ink)"}">${s.open_count}</div>
      </div>
      <div class="card kpi-card" style="min-height:96px">
        <div class="kpi-label">High Severity Open</div>
        <div class="kpi-value" style="color:${s.high_open ? "var(--orange-ink)" : "var(--green-ink)"}">${s.high_open}</div>
      </div>
      <div class="card kpi-card" style="min-height:96px">
        <div class="kpi-label">Resolved Exceptions</div>
        <div class="kpi-value" style="color:var(--green-ink)">${s.resolved_count}</div>
      </div>
    </div>

    <div class="card panel">
      <div class="panel-head">
        <div>
          <h2>Exception Management Queue</h2>
          <div class="panel-sub">Exception-first operating model: teams only intervene where automated ingestion or 4-tier matching detects an anomaly.</div>
        </div>
      </div>

      <div class="toolbar">
        <div class="toolbar-group">
          <select class="select" id="exc-cat">
            <option value="all">All categories</option>
            ${["Balance Difference", "Duplicate", "Missing Record", "Unknown Mapping", "Rule Mismatch", "Overuse Alert"]
              .map((c) => `<option value="${c}" ${state.category === c ? "selected" : ""}>${c}</option>`)
              .join("")}
          </select>
          <select class="select" id="exc-status">
            <option value="all">All statuses</option>
            ${["Open", "In Review", "Resolved", "Dismissed"]
              .map((st) => `<option value="${st}" ${state.status === st ? "selected" : ""}>${st}</option>`)
              .join("")}
          </select>
        </div>
      </div>

      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>Code / Detected</th>
              <th>Category</th>
              <th>Reference</th>
              <th>Severity / Owner</th>
              <th>Suggested Action &amp; Resolution</th>
              <th>Status</th>
              <th class="right">Action</th>
            </tr>
          </thead>
          <tbody>
            ${
              data.items.length
                ? data.items
                    .map(
                      (e) => `
                      <tr>
                        <td class="mono nowrap">
                          <strong>${esc(e.exception_code)}</strong>
                          <div class="panel-sub">${esc(fmtShortTs(e.created_at))}</div>
                        </td>
                        <td class="nowrap"><strong>${esc(e.category)}</strong></td>
                        <td class="mono nowrap">
                          ${esc(e.reference_code)}
                          ${e.campaign_key ? `<div class="panel-sub">${esc(e.campaign_key)}</div>` : ""}
                        </td>
                        <td class="nowrap">
                          ${severityBadge(e.severity)}
                          <div class="panel-sub">${esc(e.owner_role)}</div>
                        </td>
                        <td>
                          <div>${esc(e.suggested_action)}</div>
                          ${
                            e.resolution_notes
                              ? `<div class="panel-sub" style="color:var(--green-ink)">✓ ${esc(e.resolution_notes)} (${esc(e.resolved_by || "")})</div>`
                              : ""
                          }
                        </td>
                        <td>${statusBadge(e.status)}</td>
                        <td class="right nowrap">
                          ${
                            canAct && ["Open", "In Review"].includes(e.status)
                              ? `<button class="btn sm primary" data-resolve="${e.id}">${
                                  e.category === "Unknown Mapping" ? "Map & Resolve" : "Resolve"
                                }</button>`
                              : `<span style="color:var(--ink-muted);font-size:11px">${esc(e.status)}</span>`
                          }
                        </td>
                      </tr>
                    `
                    )
                    .join("")
                : `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--ink-muted)">No exceptions match current filter.</td></tr>`
            }
          </tbody>
        </table>
      </div>
    </div>
  `;

  root.querySelector("#exc-cat").addEventListener("change", (e) => {
    state.category = e.target.value;
    renderExceptions(root, ctx);
  });
  root.querySelector("#exc-status").addEventListener("change", (e) => {
    state.status = e.target.value;
    renderExceptions(root, ctx);
  });

  root.querySelectorAll("[data-resolve]").forEach((btn) => {
    const exc = data.items.find((x) => String(x.id) === btn.dataset.resolve);
    btn.addEventListener("click", () => openResolveModal(exc, poolsData.projects, root, ctx));
  });
}

function openResolveModal(exc, projects, root, ctx) {
  const isUnmapped = exc.category === "Unknown Mapping" && exc.campaign_key;
  ctx.openModal({
    title: `Resolve ${exc.exception_code} · ${exc.category}`,
    subtitle: `Reference: ${exc.reference_code} · All resolution actions are logged to the immutable Audit Trail.`,
    bodyHtml: `
      <div class="notice-banner blue" style="margin-bottom:14px">
        <span>${esc(exc.suggested_action)}</span>
      </div>
      <form id="resolve-form">
        ${
          isUnmapped
            ? `
            <div class="field mb-16">
              <label for="res-proj">1-Click Campaign Mapping for <span class="mono">${esc(exc.campaign_key)}</span> *</label>
              <select class="select" id="res-proj" required>
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
              <div class="hint">Creates a permanent Campaign Mapping rule and upgrades linked Pending UNASSIGNED transactions to Confirmed.</div>
            </div>
          `
            : ""
        }
        <div class="field mb-16">
          <label for="res-status">Resolution Disposition</label>
          <select class="select" id="res-status">
            <option value="Resolved">Resolved</option>
            <option value="In Review">Mark In Review</option>
            <option value="Dismissed">Dismissed (False Positive)</option>
          </select>
        </div>
        <div class="field">
          <label for="res-notes">Audit Resolution Notes *</label>
          <textarea class="textarea" id="res-notes" rows="3" required placeholder="Document root cause and action taken…">${
            isUnmapped ? `Confirmed project ownership for campaign ${exc.campaign_key} and backfilled ledger.` : ""
          }</textarea>
        </div>
        <div class="form-actions">
          <button type="button" class="btn" id="res-cancel">Cancel</button>
          <button type="submit" class="btn primary">${isUnmapped ? "Map Campaign & Resolve" : "Save Resolution"}</button>
        </div>
      </form>
    `,
    onMount: (el) => {
      el.querySelector("#res-cancel").addEventListener("click", ctx.closeModal);
      el.querySelector("#resolve-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const payload = {
            status: el.querySelector("#res-status").value,
            resolution_notes: el.querySelector("#res-notes").value,
          };
          if (isUnmapped) {
            payload.map_to_project_id = Number(el.querySelector("#res-proj").value);
          }
          const res = await apiRequest(`/api/exceptions/${exc.id}/resolve`, {
            method: "POST",
            json: payload,
          });
          ctx.closeModal();
          const extra = res.backfill
            ? ` (${res.backfill.backfilled_assessments} assessment(s) attributed)`
            : "";
          ctx.toast(`Exception ${exc.exception_code} updated to ${payload.status}${extra}.`, "success");
          await renderExceptions(root, ctx);
        } catch (err) {
          ctx.toast(err.message, "error");
        }
      });
    },
  });
}
