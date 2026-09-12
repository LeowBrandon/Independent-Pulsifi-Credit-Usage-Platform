# Pulsifi Credit Usage — Prototype

A self-contained browser prototype for the independent Pulsifi credit tracking and reconciliation concept.

## What is included
- Executive credit dashboard
- Estimated credit balance, utilization and runway
- Monthly usage trend
- Assessment lifecycle/activity page
- Credit transaction ledger
- Client and partner usage visibility
- Exception management
- Monthly reconciliation page
- Simulated activity capture form
- CSV export of the ledger

## How to run
1. Open `index.html` in Chrome, Edge, Firefox, or another modern browser.
2. No server, API key, database, or Pulsifi account is required.
3. Use the left navigation to demonstrate each workflow.
4. Click **Capture Activity** to simulate a low-touch assessment event.

## Demo data
The prototype deliberately uses mock data. It does not connect to Pulsifi and makes no claim of live Pulsifi balance accuracy.

## Intended production architecture
Approved evidence sources → capture/validation → transaction ledger → balance engine → dashboard/alerts → monthly reconciliation.

Potential implementation technologies: Power Automate, Power BI, SQL/Dataverse, Python/Power Query, SharePoint/OneDrive, and authorized browser automation where contractually permitted.
