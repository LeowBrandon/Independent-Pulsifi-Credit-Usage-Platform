/**
 * Main Application Entry Point — Router, RBAC Role Switcher, Multi-Source Ingest Drawer, Modals & Toasts.
 */
import { apiRequest, apiUpload, getActiveRole, setActiveRole } from "./api.js";
import { esc } from "./format.js";
import { renderActivity } from "./views/activity.js";
import { renderExceptions } from "./views/exceptions.js";
import { renderGovernance } from "./views/governance.js";
import { renderLedger } from "./views/ledger.js";
import { renderOverview } from "./views/overview.js";
import { renderPools } from "./views/pools.js";
import { renderReconciliation } from "./views/reconciliation.js";

const VIEWS = {
  overview: {
    title: "Executive Credit Overview",
    subtitle: "Harmonized Confirmed, Estimated & Official balances · Independent internal ledger",
    render: renderOverview,
  },
  activity: {
    title: "Assessment Activity & Capture",
    subtitle: "Re-ranked evidence hierarchy (Downloaded Report L2 > System Email L3 > Controlled Input L4)",
    render: renderActivity,
  },
  ledger: {
    title: "Credit Transaction Ledger",
    subtitle: "Append-only accounting ledger with Maker-Checker Segregation of Duties",
    render: renderLedger,
  },
  pools: {
    title: "Client & Partner Pools + Campaign Mapping",
    subtitle: "Strict pool separation (zero double-counting), Phase 1 statements & Pulsifi attribution rules",
    render: renderPools,
  },
  exceptions: {
    title: "Exception Management Queue",
    subtitle: "Exception-first controls: investigate only discrepancies, duplicates & unmapped campaigns",
    render: renderExceptions,
  },
  reconciliation: {
    title: "Monthly Reconciliation Engine",
    subtitle: "4-tier confidence matching (100% / 90% / 80% / <80%) vs Pulsifi Official Monthly Statement",
    render: renderReconciliation,
  },
  governance: {
    title: "Governance, Credit Rules & Audit Trail",
    subtitle: "Effective-dated credit rules, bulk contract batches, PDPA/GDPR PII proof & immutable audit log",
    render: renderGovernance,
  },
};

let currentView = "overview";

const rootEl = document.getElementById("view-root");
const titleEl = document.getElementById("page-title");
const subtitleEl = document.getElementById("page-subtitle");
const modalBackdrop = document.getElementById("modal-backdrop");
const modalDialog = document.getElementById("modal-dialog");
const modalTitle = document.getElementById("modal-title");
const modalSubtitle = document.getElementById("modal-subtitle");
const modalBody = document.getElementById("modal-body");
const toastStack = document.getElementById("toast-stack");
const badgeExc = document.getElementById("badge-exceptions");
const badgeApp = document.getElementById("badge-approvals");

function toast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  toastStack.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity 220ms";
    setTimeout(() => el.remove(), 240);
  }, 4200);
}

function openModal({ title, subtitle = "", bodyHtml, wide = false, onMount }) {
  modalTitle.textContent = title;
  modalSubtitle.textContent = subtitle;
  modalBody.innerHTML = bodyHtml;
  modalDialog.classList.toggle("wide", Boolean(wide));
  modalBackdrop.classList.add("open");
  if (typeof onMount === "function") {
    onMount(modalBody);
  }
}

function closeModal() {
  modalBackdrop.classList.remove("open");
  modalBody.innerHTML = "";
}

function updateNavBadges(openExceptions, pendingApprovals) {
  if (openExceptions !== null && openExceptions !== undefined) {
    badgeExc.textContent = String(openExceptions);
    badgeExc.style.display = openExceptions > 0 ? "inline-block" : "none";
  }
  if (pendingApprovals !== null && pendingApprovals !== undefined) {
    badgeApp.textContent = String(pendingApprovals);
    badgeApp.style.display = pendingApprovals > 0 ? "inline-block" : "none";
  }
}

async function openIngestModal() {
  let poolsData;
  try {
    poolsData = await apiRequest("/api/pools");
  } catch (err) {
    toast(err.message, "error");
    return;
  }

  let activeTab = "report";

  function renderTabs(container) {
    container.innerHTML = `
      <div class="tabs">
        <button class="tab-btn ${activeTab === "report" ? "active" : ""}" data-itab="report">L2 · Downloaded Report CSV</button>
        <button class="tab-btn ${activeTab === "email" ? "active" : ""}" data-itab="email">L3 · Pulsifi System Email</button>
        <button class="tab-btn ${activeTab === "input" ? "active" : ""}" data-itab="input">L4 · Controlled Input (&lt;30s)</button>
      </div>
      <div id="ingest-pane"></div>
    `;

    const pane = container.querySelector("#ingest-pane");

    if (activeTab === "report") {
      pane.innerHTML = `
        <div class="notice-banner green" style="font-size:12px">
          <span><strong>Level 2 (Authoritative Structured Export):</strong> Ranked above emails. Automatically hashes candidate emails (HMAC-SHA256), upgrades matching L4 Pending inputs without double-counting, and routes unmapped campaigns to Exceptions.</span>
        </div>
        <form id="form-report">
          <div class="field mb-16">
            <label for="rep-file">Pulsifi Downloaded Assessment Report (.csv)</label>
            <input class="input" id="rep-file" type="file" accept=".csv" />
            <div class="hint">Try the built-in sample CSV (upgrades Pending P-10293 → Confirmed, adds 2 confirmed rows &amp; 1 unmapped campaign).</div>
          </div>
          <div class="form-actions">
            <button type="button" class="btn" id="btn-sample-report">Import Built-In Sample CSV</button>
            <button type="submit" class="btn primary">Upload &amp; Process CSV</button>
          </div>
        </form>
      `;

      async function processCsvFile(file) {
        const fd = new FormData();
        fd.append("file", file);
        const res = await apiUpload("/api/ingest/downloaded-report", fd);
        closeModal();
        if (res.duplicate) {
          toast(res.message, "warn");
        } else {
          toast(
            `Report '${res.filename}': ${res.processed_rows} rows · ${res.confirmed_count} confirmed · ${res.upgraded_count} upgraded · ${res.pii_redactions} PII scrubbed · ${res.exceptions_created} exception(s).`,
            "success"
          );
        }
        await navigate(currentView);
      }

      pane.querySelector("#btn-sample-report").addEventListener("click", async () => {
        try {
          const text = await apiRequest("/api/samples/downloaded-report");
          const file = new File([text], "pulsifi_downloaded_report_sample.csv", { type: "text/csv" });
          await processCsvFile(file);
        } catch (err) {
          toast(err.message, "error");
        }
      });

      pane.querySelector("#form-report").addEventListener("submit", async (e) => {
        e.preventDefault();
        const fi = pane.querySelector("#rep-file");
        if (!fi.files.length) {
          toast("Select a CSV file or click 'Import Built-In Sample CSV'.", "warn");
          return;
        }
        try {
          await processCsvFile(fi.files[0]);
        } catch (err) {
          toast(err.message, "error");
        }
      });
    } else if (activeTab === "email") {
      pane.innerHTML = `
        <div class="notice-banner blue" style="font-size:12px">
          <span><strong>Level 3 (Near-Real-Time Timeliness Layer):</strong> Extracts Assessment ID, Campaign, Type, Status, and Candidate Email. Candidate PII is scrubbed &amp; HMAC-SHA256 hashed before storage.</span>
        </div>
        <form id="form-email">
          <div class="field mb-16">
            <label for="em-raw">Paste Pulsifi System Notification Email Text *</label>
            <textarea class="textarea" id="em-raw" rows="9" required placeholder="Assessment ID: P-10319&#10;Candidate Email: candidate@example.com&#10;Campaign Name: ABC-GRAD-2026&#10;Assessment Type: Leadership&#10;Event Status: Completed&#10;Event Date: 2026-09-19"></textarea>
          </div>
          <div class="form-actions">
            <button type="button" class="btn" id="btn-load-sample-email">Load Sample Pulsifi Email</button>
            <button type="submit" class="btn primary">Parse &amp; Ingest Email</button>
          </div>
        </form>
      `;

      pane.querySelector("#btn-load-sample-email").addEventListener("click", async () => {
        try {
          pane.querySelector("#em-raw").value = await apiRequest("/api/samples/system-email");
        } catch (err) {
          toast(err.message, "error");
        }
      });

      pane.querySelector("#form-email").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const res = await apiRequest("/api/ingest/system-email", {
            method: "POST",
            json: { raw_email_text: pane.querySelector("#em-raw").value },
          });
          closeModal();
          if (res.duplicate) {
            toast(res.message, "warn");
          } else {
            toast(
              `Ingested ${res.assessment.pulsifi_assessment_id} (${res.candidate_ref_hash}) · ${res.pii_redactions} PII email(s) redacted · ${res.ledger_action}.`,
              "success"
            );
          }
          await navigate(currentView);
        } catch (err) {
          toast(err.message, "error");
        }
      });
    } else {
      pane.innerHTML = `
        <div class="notice-banner yellow" style="font-size:12px">
          <span><strong>Level 4 (Controlled Internal Issuance · &lt;30s Form):</strong> Posts as <strong>Pending Usage</strong> (updates Estimated Balance immediately while preserving Confirmed Balance until Pulsifi report/email confirms).</span>
        </div>
        <form id="form-input">
          <div class="form-grid">
            <div class="field">
              <label for="ci-id">Pulsifi Assessment ID *</label>
              <input class="input mono" id="ci-id" value="P-10325" required />
            </div>
            <div class="field">
              <label for="ci-cand">Candidate Email or Ref (Auto-Hashed) *</label>
              <input class="input" id="ci-cand" value="new.candidate@example.com" required />
            </div>
            <div class="field full">
              <label for="ci-proj">Project (Auto-Assigns Client / Partner Pool) *</label>
              <select class="select" id="ci-proj" required>
                ${poolsData.projects
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
            <div class="field">
              <label for="ci-type">Assessment Type (Units from Active Credit Rule)</label>
              <select class="select" id="ci-type">
                <option value="Cognitive">Cognitive (5 units)</option>
                <option value="Personality">Personality (5 units)</option>
                <option value="Sales Aptitude">Sales Aptitude (5 units)</option>
                <option value="Leadership">Leadership (10 units)</option>
                <option value="Executive Suite">Executive Suite (15 units)</option>
              </select>
            </div>
            <div class="field">
              <label for="ci-status">Initial Lifecycle Status</label>
              <select class="select" id="ci-status">
                <option value="Sent">Sent (Pending reserve)</option>
                <option value="Started">Started (Pending reserve)</option>
                <option value="Completed">Completed (Pending L2/L3 confirmation)</option>
              </select>
            </div>
            <div class="field">
              <label for="ci-date">Event Date</label>
              <input class="input" id="ci-date" type="date" value="2026-09-19" required />
            </div>
            <div class="field">
              <label for="ci-notes">Consultant Note (optional)</label>
              <input class="input" id="ci-notes" placeholder="e.g., Batch wave 3 invitation" />
            </div>
          </div>
          <div class="form-actions">
            <button type="button" class="btn" id="ci-cancel">Cancel</button>
            <button type="submit" class="btn primary">Record Pending Usage</button>
          </div>
        </form>
      `;

      pane.querySelector("#ci-cancel").addEventListener("click", closeModal);
      pane.querySelector("#form-input").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const res = await apiRequest("/api/ingest/controlled-input", {
            method: "POST",
            json: {
              pulsifi_assessment_id: pane.querySelector("#ci-id").value,
              candidate_identifier: pane.querySelector("#ci-cand").value,
              project_id: Number(pane.querySelector("#ci-proj").value),
              assessment_type: pane.querySelector("#ci-type").value,
              event_status: pane.querySelector("#ci-status").value,
              event_date: pane.querySelector("#ci-date").value,
              notes: pane.querySelector("#ci-notes").value || null,
            },
          });
          closeModal();
          toast(
            `Captured ${res.assessment.pulsifi_assessment_id} (${res.candidate_ref_hash}) as Pending (${res.ledger_action}).`,
            "success"
          );
          await navigate(currentView);
        } catch (err) {
          toast(err.message, "error");
        }
      });
    }

    container.querySelectorAll("[data-itab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeTab = btn.dataset.itab;
        renderTabs(container);
      });
    });
  }

  openModal({
    title: "Multi-Source Evidence Ingestion & Capture",
    subtitle: "Import Official Downloaded Reports (L2), parse Pulsifi System Emails (L3), or log Controlled Internal Inputs (L4).",
    bodyHtml: `<div id="ingest-host"></div>`,
    wide: true,
    onMount: (el) => renderTabs(el.querySelector("#ingest-host")),
  });
}

const ctx = {
  navigate,
  toast,
  openModal,
  closeModal,
  updateNavBadges,
  openIngestModal,
};

async function navigate(viewKey) {
  const def = VIEWS[viewKey] || VIEWS.overview;
  currentView = viewKey in VIEWS ? viewKey : "overview";

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === currentView);
  });
  titleEl.textContent = def.title;
  subtitleEl.textContent = def.subtitle;

  try {
    await def.render(rootEl, ctx);
    // Keep nav badges synced globally
    const ov = await apiRequest("/api/overview");
    updateNavBadges(ov.balance.open_exceptions, ov.balance.pending_approval_count);
  } catch (err) {
    rootEl.innerHTML = `<div class="card panel" style="color:var(--red-ink)">Failed to load view: ${esc(err.message)}</div>`;
    toast(err.message, "error");
  }
}

// Global UI wiring
document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => navigate(btn.dataset.view));
});

document.getElementById("btn-open-ingest").addEventListener("click", openIngestModal);
document.getElementById("btn-goto-recon").addEventListener("click", () => navigate("reconciliation"));
document.getElementById("modal-close").addEventListener("click", closeModal);
modalBackdrop.addEventListener("click", (e) => {
  if (e.target === modalBackdrop) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

const roleSelect = document.getElementById("role-select");
roleSelect.value = getActiveRole();
roleSelect.addEventListener("change", () => {
  setActiveRole(roleSelect.value);
  toast(`Switched RBAC session to ${roleSelect.options[roleSelect.selectedIndex].text}.`, "info");
  navigate(currentView);
});

// Boot
navigate("overview");
