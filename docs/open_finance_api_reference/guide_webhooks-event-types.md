# Event Types

Explanation and examples for the types of webhooks sent by us

## Connection Status Change

When a connection status changes this webhook will be fired.

```json
{
  "expiryDate": "2023-08-23",
  "bankName": "leumi" ,
  "connectionId": "1234",
  "connectionStatus": "ACTIVE",
  "userId": "1234",
  "orgId": "1234",
  "connectionError":  {
    "message": string,
    "type": string
},
  "accountNumbers": ["IL620108000000099999999". "IL620108000000099999992"] ,
}
```

Using this webhook you can know when the connection has changed his status and act accordingly in your app.

For example: Once getting connectionStatus: "COMPLETED" | "ACTIVE" (see [connection statuses](https://dash.readme.com/project/open-finance/v1.0/docs/overview-1)) you can use the [Get accounts by user](https://docs.open-finance.ai/reference/get_data-accounts) api to fetch user accounts data.

## Payment Status Change

When a connection status changes this webhook will be fired.

```json
{
  "bankName": "leumi",
  "paymentId": "1234",
  "paymentStatus": "ACTC",
  "userId": "1234",
  "orgId": "1234",
  "paymentError":  {
    "message": string,
    "type": string
},
}
```

Using this webhook you can know when the payment has changed his status and act accordingly in your app.

For example: Once getting paymentStatus: "ACTC" | "ACWC" (see [Payments](https://docs.open-finance.ai/docs/overview-3))

<br />

## Session Data Update

When a new data added to a session this webhook will be fired.

```Text JSON
{
  "session": {
    "userId": "1234",
    "sessionId": "1234",
    "sessionIsConverted": true,
    "customerId": "1234",
    "sessionIsEnded": true,
    "journeyId":"1234"
  },
  "customer": {
    "customerId": "1234",
    "userId": "1234",
    "customerHasFiles": true,
    "journeyId":"1234"
  },
  "contacts": [
    {
      "contactId": "1234",
      "sessionId": "1234",
      "customerId": "1234",
      "contactHasFiles": true,
      "isAdvisor": true,
      "isGuarantor": true,
      "isAccountant": true,
      "isPartner": true,
      "isPowerOfAttorney": true,
      "isSignificantOther": true,
      "isAgent": true,
      "journeyId":"1234"

    }
  ],
  "status": "ENDED"
}

```

Using a webhook is done when the session is updated. If the session ends, the field status: **"ENDED"** will be sent in the webhook. If it does not end, this field will not be included.