# SUMIT API Integration - Implementation Guide

## Overview

This document provides a comprehensive guide to the SUMIT API integration implemented in the CFO Financial Management System.

## Architecture

### Backend Structure

```
src/cfo/
├── integrations/
│   ├── base.py                    # Base integration class
│   ├── sumit_integration.py       # Complete SUMIT API implementation
│   └── sumit_models.py            # Pydantic models for all requests/responses
├── api/
│   ├── __init__.py                # FastAPI app
│   ├── dependencies.py            # Auth & DI
│   └── routes/
│       ├── accounting.py          # Customers, Documents, Income Items
│       ├── crm.py                 # CRM entities and folders
│       ├── payments.py            # Payments, recurring, terminal
│       ├── communications.py      # SMS, Email, Fax
│       └── admin.py               # Company, Users, System
├── models.py                      # SQLAlchemy database models
├── database.py                    # Database configuration
└── config.py                      # Settings management
```

## API Endpoints Mapping

### Accounting Endpoints

| SUMIT API | Our Endpoint | Method | Description |
|-----------|--------------|--------|-------------|
| `/accounting/customers` | `/api/accounting/customers` | POST | Create customer |
| `/accounting/customers/{id}` | `/api/accounting/customers/{id}` | PUT | Update customer |
| `/accounting/customers/{id}/debt` | `/api/accounting/customers/{id}/debt` | GET | Get customer debt |
| `/accounting/documents` | `/api/accounting/documents` | POST | Create document |
| `/accounting/documents` | `/api/accounting/documents` | GET | List documents |
| `/accounting/documents/{id}` | `/api/accounting/documents/{id}` | GET | Get document |
| `/accounting/documents/{id}/pdf` | `/api/accounting/documents/{id}/pdf` | GET | Download PDF |
| `/accounting/documents/send` | `/api/accounting/documents/send` | POST | Email document |
| `/accounting/expenses` | `/api/accounting/expenses` | POST | Add expense |
| `/accounting/income-items` | `/api/accounting/income-items` | POST/GET | Manage items |

### Payment Endpoints

| SUMIT API | Our Endpoint | Method | Description |
|-----------|--------------|--------|-------------|
| `/payments/charge` | `/api/payments/charge` | POST | Charge customer |
| `/payments/{id}` | `/api/payments/{id}` | GET | Get payment |
| `/payments` | `/api/payments` | GET | List payments |
| `/payments/methods/{customer_id}` | `/api/payments/methods/{customer_id}` | GET | Payment methods |
| `/payments/recurring/customer/{id}` | `/api/payments/recurring/customer/{id}` | GET | Recurring payments |

### CRM Endpoints

| SUMIT API | Our Endpoint | Method | Description |
|-----------|--------------|--------|-------------|
| `/crm/entities` | `/api/crm/entities` | POST | Create entity |
| `/crm/entities` | `/api/crm/entities` | GET | List entities |
| `/crm/entities/{id}` | `/api/crm/entities/{id}` | GET/PUT | Get/Update entity |
| `/crm/folders` | `/api/crm/folders` | GET | List folders |

## Integration Class Usage

### Basic Usage

```python
from src.cfo.integrations.sumit_integration import SumitIntegration

# Initialize with context manager (recommended)
async with SumitIntegration(api_key="your_key") as sumit:
    # Use the integration
    customer = await sumit.create_customer(customer_data)
```

### Manual Usage

```python
sumit = SumitIntegration(api_key="your_key", company_id="optional_company_id")
try:
    customer = await sumit.create_customer(customer_data)
finally:
    await sumit.client.aclose()
```

## Common Operations

### 1. Customer Management

```python
from src.cfo.integrations.sumit_models import CustomerRequest

# Create customer
customer = await sumit.create_customer(
    CustomerRequest(
        name="John Doe",
        email="john@example.com",
        phone="+972501234567",
        tax_id="123456789"
    )
)

# Update customer
updated = await sumit.update_customer(
    customer.customer_id,
    CustomerRequest(name="John Doe Updated", ...)
)

# Get customer debt
debt = await sumit.get_debt(customer.customer_id)
```

### 2. Document Management

```python
from src.cfo.integrations.sumit_models import (
    DocumentRequest,
    DocumentItem,
    SendDocumentRequest
)
from decimal import Decimal

# Create invoice
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

# Send document by email
await sumit.send_document(
    SendDocumentRequest(
        document_id=invoice.document_id,
        recipient_email="customer@example.com"
    )
)

# Download PDF
pdf_bytes = await sumit.get_document_pdf(invoice.document_id)
```

### 3. Payment Processing

```python
from src.cfo.integrations.sumit_models import ChargeRequest

# Charge customer
payment = await sumit.charge_customer(
    ChargeRequest(
        customer_id="customer_123",
        amount=Decimal("1000"),
        currency="ILS",
        description="Invoice payment"
    )
)

# Get payment status
payment_details = await sumit.get_payment(payment.payment_id)
```

### 4. Credit Card Tokenization

```python
from src.cfo.integrations.sumit_models import TokenizeCardRequest

# Tokenize card for future use
token = await sumit.tokenize_card(
    TokenizeCardRequest(
        card_number="4580000000000000",
        expiry_month="12",
        expiry_year="25",
        cvv="123",
        holder_name="John Doe"
    )
)

# Use token for payment
payment = await sumit.charge_customer(
    ChargeRequest(
        customer_id="customer_123",
        amount=Decimal("1000"),
        payment_method=token.token
    )
)
```

### 5. CRM Operations

```python
from src.cfo.integrations.sumit_models import EntityRequest, EntityField

# Create CRM entity
entity = await sumit.create_entity(
    EntityRequest(
        folder_id="folder_123",
        fields=[
            EntityField(field_name="name", field_value="Company Name"),
            EntityField(field_name="contact", field_value="Contact Person")
        ]
    )
)

# List entities in folder
entities = await sumit.list_entities("folder_123", limit=100)
```

### 6. Communications

```python
from src.cfo.integrations.sumit_models import SMSRequest

# Send SMS
sms = await sumit.send_sms(
    SMSRequest(
        phone_number="+972501234567",
        message="Your invoice is ready"
    )
)
```

## Error Handling

### Best Practices

```python
from httpx import HTTPStatusError

try:
    async with SumitIntegration(api_key=api_key) as sumit:
        customer = await sumit.create_customer(customer_data)
except HTTPStatusError as e:
    # Handle HTTP errors (4xx, 5xx)
    print(f"HTTP Error: {e.response.status_code}")
    print(f"Details: {e.response.text}")
except Exception as e:
    # Handle other errors
    print(f"Error: {e}")
```

### Common Error Scenarios

1. **Authentication Error** (401)
   - Check API key is correct
   - Verify API key has necessary permissions

2. **Not Found** (404)
   - Verify resource ID exists
   - Check company_id if using multi-company account

3. **Validation Error** (422)
   - Check request data matches Pydantic model
   - Verify required fields are provided

4. **Rate Limiting** (429)
   - Implement exponential backoff
   - Check API quota

## Testing

### Unit Tests

```python
import pytest
from src.cfo.integrations.sumit_integration import SumitIntegration

@pytest.mark.asyncio
async def test_create_customer():
    async with SumitIntegration(api_key="test_key") as sumit:
        # Mock the API call
        customer = await sumit.create_customer(customer_data)
        assert customer.customer_id is not None
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_full_invoice_flow():
    async with SumitIntegration(api_key=TEST_API_KEY) as sumit:
        # Create customer
        customer = await sumit.create_customer(customer_data)
        
        # Create invoice
        invoice = await sumit.create_document(invoice_data)
        
        # Send invoice
        result = await sumit.send_document(send_request)
        
        assert result["success"] == True
```

## Performance Optimization

### 1. Connection Pooling

The integration uses `httpx.AsyncClient` with connection pooling:

```python
self.client = httpx.AsyncClient(
    base_url=self.BASE_URL,
    timeout=30.0  # Adjust as needed
)
```

### 2. Batch Operations

Use batch methods when available:

```python
# Instead of multiple single SMS
await sumit.send_multiple_sms([sms1, sms2, sms3])

# Instead of multiple single queries
entities = await sumit.list_entities(folder_id, limit=1000)
```

### 3. Caching

Implement caching for frequently accessed data:

```python
from functools import lru_cache

@lru_cache(maxsize=100)
async def get_cached_customer(customer_id: str):
    async with SumitIntegration(api_key) as sumit:
        return await sumit.get_customer(customer_id)
```

## Security Considerations

### 1. API Key Storage

- **Never** commit API keys to version control
- Use environment variables
- Rotate keys regularly

### 2. Card Data Handling

- **Never** store raw card data
- Always use tokenization
- Implement PCI DSS compliance measures

### 3. Data Encryption

- Use HTTPS for all API calls (enforced by SUMIT)
- Encrypt sensitive data at rest
- Use secure session management

## Monitoring and Logging

### Request Logging

The integration includes built-in logging:

```python
self._log_request(method, endpoint, data)
self._log_response(status_code, response)
self._log_error(error, context)
```

### Custom Monitoring

```python
import logging

logger = logging.getLogger("sumit_integration")
logger.setLevel(logging.INFO)

# Add custom handler
handler = logging.FileHandler("sumit_api.log")
logger.addHandler(handler)
```

## Troubleshooting

### Issue: Connection Timeout

**Solution**: Increase timeout in client configuration:
```python
self.client = httpx.AsyncClient(timeout=60.0)
```

### Issue: Invalid Response Format

**Solution**: Check API version and update models:
```python
# Validate response structure
response_data = await self._make_request(...)
validated = CustomerResponse(**response_data)
```

### Issue: Rate Limiting

**Solution**: Implement retry logic:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential())
async def create_customer_with_retry(customer):
    return await sumit.create_customer(customer)
```

## Additional Resources

- [SUMIT API Documentation](https://app.sumit.co.il/developers/api/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pydantic Models](https://docs.pydantic.dev/)
- [HTTPX Async Client](https://www.python-httpx.org/)

## Support

For issues:
1. Check SUMIT API status
2. Review API documentation
3. Check logs for error details
4. Contact SUMIT support if needed
