# Update a transaction by ID

# OpenAPI definition

```json
{
  "openapi": "3.0.0",
  "servers": [
    {
      "url": "https://{API_PREFIX}.open-finance.ai/v2",
      "variables": {
        "API_PREFIX": {
          "enum": [
            "api"
          ],
          "default": "api",
          "description": "This prefix defines which API you want to use, for example a Sandbox API or Production API"
        }
      }
    }
  ],
  "info": {
    "version": "1.0.0",
    "title": "Data"
  },
  "paths": {
    "/data/transactions/{SK}": {
      "patch": {
        "summary": "Update a transaction by ID",
        "security": [
          {
            "oAuth2ClientCredentials": [
              "update:transactions"
            ]
          }
        ],
        "parameters": [
          {
            "name": "SK",
            "in": "path",
            "required": true,
            "description": "A unique transaction identifier",
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "transactionSk": {
                    "type": "string"
                  },
                  "customerId": {
                    "type": "string"
                  },
                  "mainCategory": {
                    "type": "string",
                    "nullable": true
                  },
                  "subCategory": {
                    "type": "string",
                    "nullable": true
                  },
                  "classification": {
                    "type": "string",
                    "nullable": true
                  },
                  "classificationSource": {
                    "type": "string",
                    "nullable": true
                  },
                  "labels": {
                    "type": "array",
                    "items": {
                      "type": "string"
                    },
                    "nullable": true
                  }
                },
                "required": [
                  "transactionSk"
                ]
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Transaction successfully updated"
          },
          "400": {
            "description": "Invalid request format or missing required fields"
          },
          "401": {
            "description": "Unauthorized access - Invalid access token"
          },
          "403": {
            "description": "Forbidden - Access token missing the required permissions to perform this action"
          },
          "404": {
            "description": "Transaction not found"
          },
          "500": {
            "description": "Internal server error"
          }
        }
      }
    }
  },
  "components": {
    "securitySchemes": {
      "oAuth2ClientCredentials": {
        "type": "oauth2",
        "description": "See https://docs.open-finance.ai/reference/post_token",
        "flows": {
          "clientCredentials": {
            "tokenUrl": "https://api.open-finance.ai/oauth/token",
            "scopes": {
              "read:transactions": "Read user transactions",
              "read:accounts": "Read user accounts",
              "read:connections": "Read user connections",
              "create:connections": "Create a new connection",
              "update:connections": "Update a connection",
              "delete:connections": "Delete a connection",
              "read:providers": "Read all providers",
              "delete:organization_connections": "Delete organization connection",
              "read:organization_transactions": "Read organization transactions",
              "read:organization_accounts": "Read organization accounts",
              "read:organization_connections": "Read organization connections",
              "create:organization_connections": "Create a new organization connection",
              "delete:payments": "Cancel a payment"
            }
          }
        }
      }
    }
  },
  "x-readme": {
    "explorer-enabled": true,
    "proxy-enabled": true,
    "samples-enabled": true
  }
}
```