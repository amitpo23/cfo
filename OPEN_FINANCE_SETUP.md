# Open Finance Bank Sync Setup

This project can sync Israeli bank account and transaction data through
Open-Finance.ai / Financy.

## Installed Skills

The following Skills IL skills were installed into `.agents/skills` and
`.claude/skills`:

- `israeli-bank-connector`
- `israeli-budget-planner`
- `israeli-tax-returns`
- `israeli-vat-reporting`
- `gws-israeli-business-sheets`

## Required Credentials

Open Finance requires:

- `OPEN_FINANCE_CLIENT_ID`
- `OPEN_FINANCE_CLIENT_SECRET`
- `OPEN_FINANCE_USER_ID`

Add them to `.env`, or configure them through the API endpoint below.
Do not commit real credentials.

## API Configuration

Configure credentials for organization `1`:

```bash
curl -X POST "http://localhost:8000/api/integration/open-finance/configure?org_id=1" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "user_id": "YOUR_INTERNAL_USER_ID"
  }'
```

Test the connection:

```bash
curl -X POST "http://localhost:8000/api/integration/test?org_id=1&source=open_finance"
```

Sync bank accounts and transactions:

```bash
curl -X POST "http://localhost:8000/api/sync/run?org_id=1&source=open_finance&entity_types=accounts,bank_transactions"
```

View sync runs:

```bash
curl "http://localhost:8000/api/sync/runs?org_id=1"
```

## Consent Requirement

The connector reads data only after the Open Finance user has completed the
bank/card consent journey in Open Finance. The connector does not automate bank
logins, 2FA, payment initiation, or money transfers.

## Source Documentation

- Open Finance token endpoint: `https://docs.open-finance.ai/reference/post_token`
- Open Finance accounts endpoint: `https://docs.open-finance.ai/reference/get_data-accounts`
- Open Finance transactions endpoint: `https://docs.open-finance.ai/reference/get_data-transactions`
- Skills IL: `https://agentskills.co.il`
