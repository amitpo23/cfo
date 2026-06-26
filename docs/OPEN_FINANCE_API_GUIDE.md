# Open Finance API Integration Guide

**Date:** June 25, 2026  
**Version:** 1.0  
**Documentation Source:** https://docs.open-finance.ai/reference

---

## Overview

Open Finance provides bank data access APIs that enable real-time synchronization of bank transactions, account information, and financial data. This guide covers the authentication and integration procedures for the CFO system.

---

## Authentication: POST /oauth/token

### Endpoint Details

**URL:** `https://api.open-finance.ai/oauth/token`  
**Method:** POST  
**Purpose:** Creates an access token required for all API authentication

### Request Parameters

The endpoint accepts form data with three required parameters:

#### 1. userId (string, required)
- **Description:** A unique identifier provided by your systems
- **Format:** Unique per each user account
- **Example:** `"user_12345678"`
- **Notes:** Must match the user in your database
- **Validation:** Non-empty string

#### 2. clientId (string, required)
- **Description:** Unique identifier that identifies you as a company/firm/client
- **Format:** Provided by Open Finance during onboarding
- **Example:** `"client_abc123xyz"`
- **Notes:** Same for all users of your organization
- **Validation:** Non-empty string

#### 3. clientSecret (string, required)
- **Description:** Secret provided by Open Finance system
- **Format:** Confidential token
- **Example:** `"secret_xyz789abc"`
- **Security:** Should never be exposed publicly or in client-side code
- **Validation:** Non-empty string

### Request Example

**cURL:**
```bash
curl -X POST https://api.open-finance.ai/oauth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "userId=user_12345678&clientId=client_abc123xyz&clientSecret=secret_xyz789abc"
```

**Python:**
```python
import requests

url = "https://api.open-finance.ai/oauth/token"
data = {
    "userId": "user_12345678",
    "clientId": "client_abc123xyz",
    "clientSecret": "secret_xyz789abc"
}

response = requests.post(url, data=data)
token = response.json().get("access_token")
```

**Node.js:**
```javascript
const fetch = require('node-fetch');

const url = "https://api.open-finance.ai/oauth/token";
const data = new URLSearchParams({
    userId: "user_12345678",
    clientId: "client_abc123xyz",
    clientSecret: "secret_xyz789abc"
});

const response = await fetch(url, {
    method: "POST",
    body: data
});

const token = (await response.json()).access_token;
```

**Ruby:**
```ruby
require 'net/http'
require 'uri'

url = URI("https://api.open-finance.ai/oauth/token")
http = Net::HTTP.new(url.host, url.port)
http.use_ssl = true

request = Net::HTTP::Post.new(url)
request.set_form_data({
  "userId" => "user_12345678",
  "clientId" => "client_abc123xyz",
  "clientSecret" => "secret_xyz789abc"
})

response = http.request(request)
token = JSON.parse(response.body)["access_token"]
```

**PHP:**
```php
<?php
$url = "https://api.open-finance.ai/oauth/token";
$data = array(
    "userId" => "user_12345678",
    "clientId" => "client_abc123xyz",
    "clientSecret" => "secret_xyz789abc"
);

$ch = curl_init($url);
curl_setopt($ch, CURLOPT_POST, 1);
curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query($data));
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);

$response = curl_exec($ch);
$token = json_decode($response, true)["access_token"];
?>
```

### Response

**Status Code:** 200 OK  
**Content-Type:** `application/json`

**Response Structure:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Response Fields:**
- **access_token** (string): The JWT token for API authentication
- **token_type** (string): Token type (always "Bearer")
- **expires_in** (integer): Token expiration time in seconds (typically 1 hour)

### Using the Token

Once you have an access token, include it in all subsequent API requests:

```bash
curl -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  https://api.open-finance.ai/accounts
```

### Token Management

**Token Lifetime:**
- Default: 1 hour (3600 seconds)
- After expiration: Request a new token
- Recommended: Cache tokens and refresh before expiration

**Token Refresh Strategy:**
```python
# Pseudocode
def get_valid_token():
    if cached_token and not is_expired(cached_token):
        return cached_token
    else:
        new_token = request_token()
        cache_token(new_token)
        return new_token
```

---

## Error Handling

### Common Error Responses

**400 Bad Request**
- Missing required parameters
- Invalid parameter format
- Malformed request

**401 Unauthorized**
- Invalid clientId
- Invalid clientSecret
- Invalid userId format

**403 Forbidden**
- Client not authorized
- Account suspended
- Rate limit exceeded

**500 Server Error**
- Open Finance API down
- Temporary service issue
- Retry after 5-10 seconds

### Error Response Format
```json
{
  "error": "invalid_credentials",
  "error_description": "The provided credentials are invalid"
}
```

---

## Integration with CFO System

### Implementation Pattern

```python
# In CFO system
from open_finance_connector import OpenFinanceConnector

class OpenFinanceService:
    def __init__(self, user_id: str):
        self.connector = OpenFinanceConnector(
            user_id=user_id,
            client_id=os.getenv("OPEN_FINANCE_CLIENT_ID"),
            client_secret=os.getenv("OPEN_FINANCE_CLIENT_SECRET")
        )
    
    async def get_accounts(self):
        # First get token
        token = await self.connector.get_token()
        
        # Then fetch data
        accounts = await self.connector.fetch_accounts(token)
        return accounts
    
    async def sync_transactions(self, account_id: str):
        token = await self.connector.get_token()
        transactions = await self.connector.fetch_transactions(
            token=token,
            account_id=account_id
        )
        return transactions
```

### Security Best Practices

1. **Store credentials securely**
   - Use environment variables, not hardcoded values
   - Store clientSecret in encrypted vault
   - Never log credentials

2. **Token management**
   - Cache tokens with TTL
   - Refresh before expiration
   - Clear cache on logout

3. **Error handling**
   - Catch authentication errors
   - Retry on transient failures
   - Log failed attempts (without credentials)

4. **Rate limiting**
   - Implement exponential backoff
   - Queue requests
   - Monitor rate limit headers

---

## Configuration

### Environment Variables

```bash
# .env file
OPEN_FINANCE_CLIENT_ID=client_abc123xyz
OPEN_FINANCE_CLIENT_SECRET=secret_xyz789abc
OPEN_FINANCE_BASE_URL=https://api.open-finance.ai
OPEN_FINANCE_TOKEN_ENDPOINT=/oauth/token
OPEN_FINANCE_TOKEN_TTL=3600
```

### Credentials Per Organization

```python
# Database model
class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"))
    integration_type = Column(String)  # "open_finance"
    client_id = Column(String, encrypted=True)
    client_secret = Column(String, encrypted=True)
    token_cache = Column(JSON)  # Cached token + expiry
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

---

## Troubleshooting

### "Invalid clientSecret"
- Verify clientSecret matches what Open Finance provided
- Check for leading/trailing whitespace
- Verify environment variables are loaded
- Check if credentials were rotated

### "Token expired"
- Request a new token
- Verify system clock is accurate
- Check token TTL is not too short

### "Rate limited"
- Implement exponential backoff
- Queue requests
- Contact Open Finance support

### "Connection timeout"
- Check network connectivity
- Verify firewall rules
- Check Open Finance API status
- Increase timeout threshold

---

## Next Steps: Other Open Finance Endpoints

After authentication, you can access:
- `/accounts` - List all connected accounts
- `/transactions` - Fetch account transactions
- `/balances` - Get current balances
- `/movements` - Get transaction movements
- `/webhooks` - Set up real-time notifications

**Note:** Each endpoint requires the Bearer token from `/oauth/token`

---

## Support & Resources

- **Documentation:** https://docs.open-finance.ai
- **Support Email:** support@open-finance.ai
- **Status Page:** https://status.open-finance.ai
- **Rate Limits:** 1000 requests/hour per client

---

**Integration Guide Version:** 1.0  
**Last Updated:** June 25, 2026  
**Next Review:** September 25, 2026

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
