/**
 * View 1: Executive Credit Overview
 * Displays harmonized Confirmed / Estimated / Official balances, strict §16 alert tiers,
 * stacked Confirmed vs Pending monthly burn chart, pool summaries, and batch expiries.
 */
import { apiRequest } from "../api.js";
import { esc, fmtMoney, fmtMonth, fmtNum, fmtSigned, severityBadge } from "../format.js";

export async function renderOverview(root, ctx) {
  const data = await apiRequest("/api/overview");
  const { balance: b, pools, alerts, batches } = data;
  ctx.updateNavBadges(b.open_exceptions, b.pending_approval_count);

  const maxBar = Math.max(100, ...b.monthly_trend.map((m) => m.total_used));

  root.innerHTML = `
    <!-- Harmonized §11/§12 Formula Verification Strip -->
    <div class="formula-strip">
      <div class="formula-eq">
        <span class="term">Opening <strong>${fmtNum(b.opening_balance)}</strong></span>
        <span class="op">+</span>
        <span class="term">Top-Ups <strong>${fmtNum(b.top_ups)}</strong></span>
        <span class="op">+</span>
        <span class="term">Approved Adj <strong>${fmtSigned(b.approved_adjustments)}</strong></span>
        <span class="op">−</span>
        <span class="term">Confirmed Usage <strong>${fmtNum(b.confirmed_usage)}</strong></span>
        <span class="op">=</span>
        <span class="term"><strong>${fmtNum(b.confirmed_balance)}</strong> Confirmed</span>
        <span class="op">−</span>
        <span class="term">Pending <strong>${fmtNum(b.pending_usage)}</strong></span>
        <span class="op">=</span>
        <span class="term"><strong>${fmtNum(b.estimated_balance)}</strong> Estimated</span>
      </div>
      <span class="badge ${b.health.badge}">§16 Pool Health: ${esc(b.health.label)}</span>
    </div>

    <!-- Primary KPI Grid: 3 Confidence-Tiered Balances + Reconciliation Gap -->
    <div class="grid grid-4 mb-16">
      <div class="card kpi-card">
        <div class="kpi-top">
          <span class="kpi-label">Confirmed Balance</span>
          <span class="badge ${b.confirmed_health.badge}">${b.confirmed_remaining_pct}% left</span>
        </div>
        <div class="kpi-value">${fmtNum(b.confirmed_balance)}</div>
        <div class="kpi-meta">
          <span>Backed by L1–L3 evidence &amp; approved adj.</span>
        </div>
      </div>

      <div class="card kpi-card">
        <div class="kpi-top">
          <span class="kpi-label">Estimated Balance</span>
          <span class="badge ${b.health.badge}">${b.estimated_remaining_pct}% · ${esc(b.health.tier)}</span>
        </div>
        <div class="kpi-value">${fmtNum(b.estimated_balance)}</div>
        <div class="kpi-meta">
          <span>Deducts <strong class="num">${fmtNum(b.pending_usage)}</strong> pending</span>
          <span class="num">${fmtMoney(b.estimated_remaining_value_usd)}</span>
        </div>
      </div>

      <div class="card kpi-card">
        <div class="kpi-top">
          <span class="kpi-label">Official Statement Balance</span>
          <span class="badge blue">${esc(fmtMonth(b.official_period))}</span>
        </div>
        <div class="kpi-value">${fmtNum(b.official_balance)}</div>
        <div class="kpi-meta">
          <span>Pulsifi verified (${b.official_match_rate_pct ?? "—"}% matched)</span>
        </div>
      </div>

      <div class="card kpi-card">
        <div class="kpi-top">
          <span class="kpi-label">Reconciliation Variance</span>
          <span class="badge ${b.reconciliation_gap === 0 ? "green" : "red"}">
            ${b.reconciliation_gap === 0 ? "Reconciled" : "Review Required"}
          </span>
        </div>
        <div class="kpi-value" style="color:${b.reconciliation_gap === 0 ? "var(--green-ink)" : "var(--red-ink)"}">
          ${fmtSigned(b.reconciliation_gap)}
        </div>
        <div class="kpi-meta">
          <span>${b.open_exceptions} open exception(s)</span>
          <span title="Trailing 3-month burn rate advisory estimate (predictive forecasting in Phase 2)">
            Runway ~<strong class="num">${b.advisory_runway_months ?? "—"} mo</strong>
          </span>
        </div>
      </div>
    </div>

    <!-- Main Row: Monthly Burn Chart + Active Control Alerts -->
    <div class="grid grid-main-side mb-16">
      <div class="card panel">
        <div class="panel-head">
          <div>
            <h2>Monthly Credit Consumption</h2>
            <div class="panel-sub">Total funded: <strong class="num">${fmtNum(b.total_funded)}</strong> units (${fmtMoney(b.total_contract_spend_usd)} · avg $${b.avg_unit_cost_usd.toFixed(2)}/unit) · Utilization: <strong class="num">${b.utilization_pct}%</strong></div>
          </div>
          <div class="chart-legend">
            <span><i class="legend-dot" style="background:var(--brand-primary)"></i>Confirmed</span>
            <span><i class="legend-dot" style="background:var(--yellow-bar)"></i>Pending</span>
          </div>
        </div>
        <div class="chart-bars">
          ${b.monthly_trend
            .map((m) => {
              const confH = Math.max(4, Math.round((m.confirmed_used / maxBar) * 145));
              const pendH = m.pending_used > 0 ? Math.max(6, Math.round((m.pending_used / maxBar) * 145)) : 0;
              return `
                <div class="chart-col" title="${fmtMonth(m.period_month)}: ${m.confirmed_used} confirmed + ${m.pending_used} pending = ${m.total_used} units">
                  <div class="chart-val">${fmtNum(m.total_used)}</div>
                  <div class="chart-stack">
                    ${pendH ? `<div class="chart-seg-pending" style="height:${pendH}px"></div>` : ""}
                    <div class="chart-seg-confirmed" style="height:${confH}px"></div>
                  </div>
                  <div class="chart-label">${esc(fmtMonth(m.period_month).split(" ")[0])}</div>
                </div>
              `;
            })
            .join("")}
        </div>
        <div class="panel-sub" style="margin-top:10px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px">
          <span>Trailing 3-month average burn: <strong class="num">${fmtNum(b.avg_monthly_burn)} units/mo</strong></span>
          <span>Advisory runway: <strong class="num">${b.advisory_runway_months ?? "—"} months</strong> <em>(Full predictive forecasting in Phase 2)</em></span>
        </div>
      </div>

      <div class="card panel">
        <div class="panel-head">
          <div>
            <h2>Active Governance &amp; Control Alerts</h2>
            <div class="panel-sub">Strict §16 tiers: Green &gt;30% · Yellow 20–30% · Orange 10–20% · Red &lt;10%</div>
          </div>
          <span class="badge ${alerts.length ? "orange" : "green"}">${alerts.length} Active</span>
        </div>
        <div class="alert-list">
          ${
            alerts.length
              ? alerts
                  .map(
                    (a) => `
                  <div class="alert-item" data-goto="${esc(a.target_view)}">
                    <div>
                      <div class="alert-title">${esc(a.title)}</div>
                      <div class="alert-detail">${esc(a.detail)}</div>
                    </div>
                    ${severityBadge(a.severity)}
                  </div>
                `
                  )
                  .join("")
              : `<div class="notice-banner green" style="margin:0">All balances, pools, and reconciliations are healthy.</div>`
          }
        </div>
      </div>
    </div>

    <!-- Bottom Row: Client-Funded Pools, Partner-Funded Pools, Credit Batch Expiry -->
    <div class="grid grid-3">
      <div class="card panel">
        <div class="panel-head">
          <div>
            <h3>Client-Funded Pools</h3>
            <div class="panel-sub">Direct client credit allocations (zero partner overlap)</div>
          </div>
          <button class="btn sm ghost" data-goto="pools">View all →</button>
        </div>
        ${pools.client_pools
          .map(
            (p) => `
            <div class="pool-mini">
              <div class="pool-mini-head">
                <strong>${esc(p.name)}</strong>
                <span class="num">${fmtNum(p.estimated_used)} / ${fmtNum(p.allocated)}</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill ${p.health.badge}" style="width:${Math.min(100, p.utilization_pct)}%"></div>
              </div>
              <div class="pool-mini-meta">
                <span>${p.utilization_pct}% utilized · ${fmtNum(p.remaining)} left</span>
                <span class="badge ${p.health.badge}">${esc(p.health.tier)}</span>
              </div>
            </div>
          `
          )
          .join("")}
      </div>

      <div class="card panel">
        <div class="panel-head">
          <div>
            <h3>Partner-Funded Reseller Pools</h3>
            <div class="panel-sub">Independent partner allocations · Phase 1 statement exports</div>
          </div>
          <button class="btn sm ghost" data-goto="pools">Statements →</button>
        </div>
        ${pools.partner_pools
          .map(
            (p) => `
            <div class="pool-mini">
              <div class="pool-mini-head">
                <strong>${esc(p.name)}</strong>
                <span class="num">${fmtNum(p.estimated_used)} / ${fmtNum(p.allocated)}</span>
              </div>
              <div class="progress-track">
                <div class="progress-fill ${p.health.badge}" style="width:${Math.min(100, p.utilization_pct)}%"></div>
              </div>
              <div class="pool-mini-meta">
                <span>${p.utilization_pct}% utilized · ${fmtNum(p.remaining)} left</span>
                <span class="badge ${p.health.badge}">${esc(p.health.tier)}</span>
              </div>
            </div>
          `
          )
          .join("")}
      </div>

      <div class="card panel">
        <div class="panel-head">
          <div>
            <h3>Contract Credit Batches &amp; Expiry</h3>
            <div class="panel-sub">Bulk purchase validity &amp; unit cost basis</div>
          </div>
          <button class="btn sm ghost" data-goto="governance">Governance →</button>
        </div>
        ${batches
          .map(
            (bt) => `
            <div class="pool-mini">
              <div class="pool-mini-head">
                <strong class="mono">${esc(bt.batch_ref)}</strong>
                <span class="num"><strong>${fmtNum(bt.purchased_units)}</strong> units</span>
              </div>
              <div class="pool-mini-meta">
                <span>${esc(bt.currency)} ${Number(bt.unit_cost).toFixed(2)}/unit · Inv ${esc(bt.invoice_ref)}</span>
                <span class="badge slate">Exp ${esc(bt.expires_at)}</span>
              </div>
            </div>
          `
          )
          .join("")}
        ${
          pools.unassigned.estimated_used > 0
            ? `<div class="notice-banner yellow" style="margin-top:12px;margin-bottom:0;font-size:11.5px">
                <span><strong>${fmtNum(pools.unassigned.estimated_used)}</strong> unit(s) awaiting Campaign Mapping attribution.</span>
                <button class="btn sm" data-goto="exceptions">Map →</button>
              </div>`
            : ""
        }
      </div>
    </div>
  `;

  root.querySelectorAll("[data-goto]").forEach((el) => {
    el.addEventListener("click", () => ctx.navigate(el.dataset.goto));
  });
}
