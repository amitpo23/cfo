# SUMIT API Quick Reference

## Authentication
```python
from src.cfo.integrations.sumit_integration import SumitIntegration

async with SumitIntegration(api_key="YOUR_KEY") as sumit:
    # Your code here
    pass
```

## Customers

### Create Customer
```python
from src.cfo.integrations.sumit_models import CustomerRequest

customer = await sumit.create_customer(
    CustomerRequest(
        name="John Doe",
        email="john@example.com",
        phone="+972501234567"
    )
)
```

### Update Customer
```python
updated = await sumit.update_customer(
    "customer_id",
    CustomerRequest(name="Updated Name", ...)
)
```

### Get Customer Debt
```python
debt = await sumit.get_debt("customer_id")
```

## Documents

### Create Invoice
```python
from src.cfo.integrations.sumit_models import DocumentRequest, DocumentItem
from decimal import Decimal

invoice = await sumit.create_document(
    DocumentRequest(
        customer_id="customer_123",
        document_type="invoice",
        items=[
            DocumentItem(
                description="Service",
                quantity=Decimal("1"),
                price=Decimal("1000")
            )
        ]
    )
)
```

### Send Document by Email
```python
from src.cfo.integrations.sumit_models import SendDocumentRequest

await sumit.send_document(
    SendDocumentRequest(
        document_id="doc_123",
        recipient_email="customer@example.com"
    )
)
```

### Download PDF
```python
pdf_bytes = await sumit.get_document_pdf("document_id")
with open("invoice.pdf", "wb") as f:
    f.write(pdf_bytes)
```

### List Documents
```python
from src.cfo.integrations.sumit_models import DocumentListRequest

docs = await sumit.list_documents(
    DocumentListRequest(
        document_type="invoice",
        from_date=date(2024, 1, 1),
        limit=100
    )
)
```

## Payments

### Charge Customer
```python
from src.cfo.integrations.sumit_models import ChargeRequest

payment = await sumit.charge_customer(
    ChargeRequest(
        customer_id="customer_123",
        amount=Decimal("1000"),
        currency="ILS",
        description="Payment for invoice"
    )
)
```

### Get Payment Details
```python
payment = await sumit.get_payment("payment_id")
print(f"Status: {payment.status}")
```

### List Payments
```python
payments = await sumit.list_payments(
    customer_id="customer_123",
    from_date=date(2024, 1, 1)
)
```

## Credit Card

### Tokenize Card
```python
from src.cfo.integrations.sumit_models import TokenizeCardRequest

token = await sumit.tokenize_card(
    TokenizeCardRequest(
        card_number="4580000000000000",
        expiry_month="12",
        expiry_year="25",
        cvv="123",
        holder_name="John Doe"
    )
)
```

### Charge with Token
```python
payment = await sumit.charge_customer(
    ChargeRequest(
        customer_id="customer_123",
        amount=Decimal("1000"),
        payment_method=token.token
    )
)
```

## CRM

### Create Entity
```python
from src.cfo.integrations.sumit_models import EntityRequest, EntityField

entity = await sumit.create_entity(
    EntityRequest(
        folder_id="folder_123",
        fields=[
            EntityField(field_name="name", field_value="Company"),
            EntityField(field_name="email", field_value="contact@example.com")
        ]
    )
)
```

### List Entities
```python
entities = await sumit.list_entities(
    folder_id="folder_123",
    limit=100
)
```

## Communications

### Send SMS
```python
from src.cfo.integrations.sumit_models import SMSRequest

sms = await sumit.send_sms(
    SMSRequest(
        phone_number="+972501234567",
        message="Your invoice is ready"
    )
)
```

### Send Multiple SMS
```python
messages = [
    SMSRequest(phone_number="+972501111111", message="Message 1"),
    SMSRequest(phone_number="+972502222222", message="Message 2"),
]
results = await sumit.send_multiple_sms(messages)
```

## Recurring Payments

### List Customer Recurring
```python
recurring = await sumit.list_customer_recurring("customer_id")
```

### Cancel Recurring
```python
await sumit.cancel_recurring("recurring_id")
```

### Charge Recurring Manually
```python
payment = await sumit.charge_recurring("recurring_id")
```

## Reports

### Debt Report
```python
from src.cfo.integrations.sumit_models import DebtReportRequest

report = await sumit.get_debt_report(
    DebtReportRequest(
        customer_id="customer_123",
        as_of_date=date.today()
    )
)
```

### Account Balance
```python
balance = await sumit.get_balance()
```

## General Operations

### Get VAT Rate
```python
vat_rate = await sumit.get_vat_rate(date.today())
```

### Get Exchange Rate
```python
from src.cfo.integrations.sumit_models import ExchangeRateRequest

rate = await sumit.get_exchange_rate(
    ExchangeRateRequest(
        from_currency="USD",
        to_currency="ILS",
        date=date.today()
    )
)
```

### Verify Bank Account
```python
from src.cfo.integrations.sumit_models import BankAccountVerification

result = await sumit.verify_bank_account(
    BankAccountVerification(
        account_number="123456",
        branch_number="789",
        bank_number="12"
    )
)
```

## REST API Endpoints

### Authentication
All endpoints require JWT token:
```bash
Authorization: Bearer YOUR_JWT_TOKEN
```

### Customers
```bash
POST   /api/accounting/customers
PUT    /api/accounting/customers/{id}
GET    /api/accounting/customers/{id}/debt
```

### Documents
```bash
POST   /api/accounting/documents
GET    /api/accounting/documents
GET    /api/accounting/documents/{id}
GET    /api/accounting/documents/{id}/pdf
POST   /api/accounting/documents/send
```

### Payments
```bash
POST   /api/payments/charge
GET    /api/payments/{id}
GET    /api/payments
GET    /api/payments/methods/{customer_id}
```

### CRM
```bash
POST   /api/crm/entities
GET    /api/crm/entities
GET    /api/crm/entities/{id}
PUT    /api/crm/entities/{id}
DELETE /api/crm/entities/{id}
```

### Communications
```bash
POST   /api/communications/sms/send
POST   /api/communications/tickets
```

## Common Patterns

### Error Handling
```python
try:
    async with SumitIntegration(api_key) as sumit:
        result = await sumit.create_customer(data)
except Exception as e:
    print(f"Error: {e}")
```

### Batch Operations
```python
# Create multiple customers
customers = []
async with SumitIntegration(api_key) as sumit:
    for data in customer_data_list:
        customer = await sumit.create_customer(data)
        customers.append(customer)
```

### Pagination
```python
offset = 0
limit = 100
all_documents = []

async with SumitIntegration(api_key) as sumit:
    while True:
        docs = await sumit.list_documents(
            DocumentListRequest(limit=limit, offset=offset)
        )
        if not docs:
            break
        all_documents.extend(docs)
        offset += limit
```

## Environment Variables
```env
SUMIT_API_KEY=your_api_key_here
SUMIT_COMPANY_ID=your_company_id_here
DATABASE_URL=sqlite:///./cfo.db
SECRET_KEY=your_secret_key
```

## Useful Commands

### Run Server
```bash
uvicorn src.cfo.api:app --reload --port 8000
```

### Initialize Database
```bash
python -c "from src.cfo.database import init_db; init_db()"
```

### Test Connection
```bash
python -m src.cfo.cli test-sumit
```

### Run Example
```bash
python examples/sumit_usage_example.py
```

## API Documentation
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

## Support
- SUMIT API Docs: https://app.sumit.co.il/developers/api/
- Issues: Check logs and error messages
