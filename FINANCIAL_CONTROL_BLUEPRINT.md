# CFO Financial Control Blueprint

## Product Goal

Build a full financial control system for Israeli small businesses and
freelancers:

- Budget planning and budget-vs-actual control
- Bank account and credit card transaction ingestion
- SUMIT accounting cloud sync
- Bank reconciliation against invoices, payments, expenses, and ledger entries
- Cash flow, AR/AP, alerts, dashboards, VAT and annual-report workflows

## Data Sources

### SUMIT

SUMIT is the accounting source of truth for:

- Customers and CRM entities
- Invoices, receipts, credit notes, expenses, and document PDFs
- Payments, recurring payments, payment methods, and credit-card terminal data
- VAT rate, exchange rates, document numbering, and settings
- Webhooks/triggers where configured

Existing code:

- `src/cfo/integrations/sumit_integration.py`
- `src/cfo/services/sumit_connector.py`
- `src/cfo/services/data_sync_service.py`
- `src/cfo/api/routes/accounting.py`
- `src/cfo/api/routes/payments.py`

### Open Finance / Bank Data

Bank and card data can arrive from:

- Open-Finance.ai / Financy via API
- Manual CSV/XLSX import from Israeli banks and credit-card companies
- Future MCP/scraper connectors, where legally and operationally appropriate

Existing and added code:

- `src/cfo/services/open_finance_connector.py`
- `src/cfo/services/bank_statement_service.py`
- `src/cfo/api/routes/sync.py`

## Unified Control Layer

The control layer combines accounting and bank data:

- Shows book totals vs. bank movement
- Counts unreconciled bank transactions
- Flags overdue invoices and upcoming payables
- Suggests reconciliation candidates by amount, date and description
- Allows manual approval of a bank-to-books match

Added code:

- `src/cfo/services/financial_control_service.py`
- `GET /api/control/overview`
- `GET /api/control/reconciliation/suggestions`
- `POST /api/control/reconciliation/apply`
- `GET /api/control/expenses`

## CFO Brain

The CFO Brain is the system's internal reasoning and memory layer. It persists:

- Financial memory facts, such as latest control overview and connected sources
- Actionable insights, such as missing SUMIT/bank connections, reconciliation
  backlog, overdue collections, low cash, budget overruns, and large unmatched
  bank movements
- Follow-up tasks for high and critical insights

Added code:

- `src/cfo/services/cfo_brain_service.py`
- `POST /api/brain/analyze`
- `GET /api/brain/insights`
- `PATCH /api/brain/insights/{insight_id}`
- `GET /api/brain/memory`

Run after every meaningful sync:

```bash
curl -X POST "http://localhost:8000/api/brain/analyze?org_id=1&create_tasks=true"
```

Review active insights:

```bash
curl "http://localhost:8000/api/brain/insights?org_id=1&status=active"
```

## Reconciliation Workflow

1. Sync SUMIT:
   - `POST /api/sync/run?source=sumit`
2. Sync bank data:
   - `POST /api/sync/run?source=open_finance&entity_types=accounts,bank_transactions`
   - or upload bank statements via legacy bank import endpoints
3. Review suggestions:
   - `GET /api/control/reconciliation/suggestions`
4. Approve a match:
   - `POST /api/control/reconciliation/apply`
5. Run the CFO Brain:
   - `POST /api/brain/analyze`
6. Dashboard reflects:
   - reconciliation health
   - unreconciled count
   - cash movement
   - expense categories
   - overdue collection actions

## Israeli Skills Installed

Installed through Skills IL:

- `israeli-bank-connector`
- `israeli-budget-planner`
- `israeli-tax-returns`
- `israeli-vat-reporting`
- `gws-israeli-business-sheets`

Use these for category definitions, tax/VAT workflows, budget benchmarks, and
Google Sheets export/automation.

## Security Rules

- Never commit bank/SUMIT/Open Finance credentials.
- Bank connection requires user consent and/or credentials configured outside
  source control.
- The current `IntegrationConnection.credentials_encrypted` field stores JSON
  despite its name. Before production, replace this with proper encryption/KMS.
- Reconciliation suggestions are suggestions only; the user must approve them.
- No payment initiation or money transfer is automated by the reconciliation
  flow.
