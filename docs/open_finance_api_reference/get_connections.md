# Get connections by user

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
    "/connections": {
      "get": {
        "summary": "Get connections by user",
        "security": [
          {
            "oAuth2ClientCredentials": [
              "read:connections"
            ]
          }
        ],
        "parameters": [
          {
            "name": "customerId",
            "in": "query",
            "required": false,
            "description": "The ID of a customer (business ID / national ID) created through an extended journey (like loans)",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "contactId",
            "in": "query",
            "required": false,
            "description": "The phone number of a contact created through an extended journey (like loans)",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "limit",
            "in": "query",
            "required": false,
            "description": "Max number of documents to retrieve",
            "schema": {
              "type": "number"
            }
          },
          {
            "name": "sort",
            "in": "query",
            "required": false,
            "description": "1 for ascending, -1 for descending",
            "schema": {
              "type": "number",
              "enum": [
                1,
                -1
              ]
            }
          },
          {
            "name": "nextPage",
            "in": "query",
            "required": false,
            "description": "page to retrieve, used for pagination",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "status",
            "in": "query",
            "required": false,
            "description": "status to retrieve, used for filtering",
            "schema": {
              "type": "string",
              "enum": [
                "ACTIVE"
              ]
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "nextPage": {
                      "type": "string",
                      "nullable": true,
                      "description": "Pagination cursor for the next page; null when there are no more pages"
                    },
                    "count": {
                      "type": "number",
                      "description": "Number of connection documents returned in items for this response (before optional status filter)"
                    },
                    "items": {
                      "type": "array",
                      "items": {
                        "$ref": "#/components/schemas/Connection"
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "userId is not allowed in query for non-admin users",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "Unauthorized access - Invalid access token"
          },
          "403": {
            "description": "Forbidden - Access token missing the required permissions to preform this action"
          },
          "404": {
            "description": "Route or entity not found"
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
    },
    "schemas": {
      "ConnectionAccessAccountSelector": {
        "type": "object",
        "description": "Account identifier (IBAN and/or BBAN) used to scope connection access",
        "properties": {
          "iban": {
            "type": "string",
            "nullable": true,
            "description": "The account IBAN",
            "example": "IL123456789012345678901"
          },
          "bban": {
            "type": "string",
            "nullable": true,
            "description": "The account BBAN",
            "example": "10-944-50151142"
          }
        }
      },
      "ConnectionAccess": {
        "type": "object",
        "description": "Permissions / account scope for the connection",
        "properties": {
          "accounts": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/ConnectionAccessAccountSelector"
            }
          },
          "balances": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/ConnectionAccessAccountSelector"
            }
          },
          "transactions": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/ConnectionAccessAccountSelector"
            }
          }
        }
      },
      "ConnectionError": {
        "type": "object",
        "description": "Error details when the connection is in an error state",
        "properties": {
          "message": {
            "type": "string",
            "nullable": true,
            "description": "Error message"
          },
          "type": {
            "type": "string",
            "nullable": true,
            "description": "Error type"
          }
        }
      },
      "ConnectionOrganization": {
        "type": "object",
        "description": "Organization metadata stamped on the connection when created",
        "properties": {
          "name": {
            "type": "string",
            "description": "Organization display name"
          }
        }
      },
      "Connection": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "A unique identifier for the connection"
          },
          "userId": {
            "type": "string",
            "description": "A unique identifier for the user"
          },
          "customerId": {
            "type": "string",
            "nullable": true,
            "description": "Customer identifier for extended journeys (e.g. loans)"
          },
          "psuId": {
            "type": "string",
            "nullable": true,
            "description": "The national id or passport number of the user"
          },
          "psuIdType": {
            "type": "string",
            "nullable": true,
            "description": "The type of the PSU ID"
          },
          "psuCorporateId": {
            "type": "string",
            "nullable": true,
            "description": "The ID of a customer (business ID / national ID)"
          },
          "providerId": {
            "type": "string",
            "nullable": true,
            "description": "A unique identifier for the provider"
          },
          "status": {
            "type": "string",
            "enum": [
              "ACTIVE",
              "CONNECTED",
              "FETCHING",
              "ERROR",
              "FETCHING_ERROR",
              "INACTIVE",
              "COMPLETED",
              "CREDENTIALS_ERROR",
              "REJECTED",
              "PARTIALLY_AUTHORIZED",
              "UNKNOWN",
              "TERMINATED_BY_USER",
              "EXPIRED",
              "REVOKED",
              "REPLACED",
              "SUSPENDED_BY_PROVIDER"
            ],
            "description": "The connection status"
          },
          "mode": {
            "type": "string",
            "enum": [
              "PSD2",
              "PLAID"
            ],
            "description": "The connection mode (open banking vs Plaid)"
          },
          "expiryDate": {
            "type": "string",
            "format": "date",
            "description": "The date at which the connection/consent expires"
          },
          "accounts": {
            "type": "number",
            "nullable": true,
            "description": "Number of checking accounts associated with the connection"
          },
          "cards": {
            "type": "number",
            "nullable": true,
            "description": "Number of credit-cards associated with the connection"
          },
          "savings": {
            "type": "number",
            "nullable": true,
            "description": "Number of savings accounts associated with the connection"
          },
          "loans": {
            "type": "number",
            "nullable": true,
            "description": "Number of loans accounts associated with the connection"
          },
          "securities": {
            "type": "number",
            "nullable": true,
            "description": "Number of security accounts associated with the connection"
          },
          "transactions": {
            "type": "number",
            "nullable": true,
            "description": "Number of transactions associated with the connection"
          },
          "providerIds": {
            "type": "array",
            "description": "Allowed provider IDs for this connection. Enum must match PROVIDERS_IDS_LIST in src/consts.ts (see tests/data/connection-openapi.spec.ts).",
            "items": {
              "type": "string",
              "enum": [
                "americanExpress",
                "beinleumi",
                "beinleumi-sandbox",
                "cal",
                "cal-sandbox",
                "discount",
                "discount-sandbox",
                "digiBank",
                "hapoalim",
                "hapoalim-sandbox",
                "isracard",
                "isracard-sandbox",
                "jerusalem",
                "leumi",
                "leumi-sandbox",
                "masad",
                "masad-sandbox",
                "max",
                "max-sandbox",
                "mercantile",
                "mercantile-sandbox",
                "menora-sandbox",
                "mizrahi",
                "mizrahi-london-sandbox",
                "mizrahi-sandbox",
                "one-zero",
                "open-finance-card-sandbox",
                "open-finance-sandbox",
                "otsarHahayal",
                "otsarHahayal-sandbox",
                "pagi",
                "pagi-sandbox",
                "pepper",
                "ubank",
                "ubank-sandbox",
                "union",
                "yahav",
                "yahav-sandbox"
              ],
              "description": "A known provider identifier"
            }
          },
          "includeFakeProviders": {
            "type": "boolean",
            "nullable": true,
            "default": false,
            "description": "If true, allow usage of dummy bank"
          },
          "excludeCreditCardProviders": {
            "type": "boolean",
            "nullable": true,
            "description": "If true, credit-card providers are excluded from this connection"
          },
          "callbackInformation": {
            "nullable": true,
            "allOf": [
              {
                "$ref": "#/components/schemas/CallbackInformation"
              }
            ]
          },
          "refreshSettings": {
            "type": "object",
            "description": "Background refresh configuration for transaction data",
            "properties": {
              "refreshData": {
                "type": "boolean",
                "description": "If true, the connection will refresh TX data in the background"
              },
              "frequencyPerDay": {
                "type": "number",
                "nullable": true,
                "description": "Max refresh operations per day when configured"
              },
              "lastFetchedDataDate": {
                "type": "string",
                "format": "date",
                "nullable": true,
                "description": "Last date at which transactions have been fetched (from refresh settings)"
              }
            }
          },
          "error": {
            "nullable": true,
            "allOf": [
              {
                "$ref": "#/components/schemas/ConnectionError"
              }
            ]
          },
          "organization": {
            "nullable": true,
            "allOf": [
              {
                "$ref": "#/components/schemas/ConnectionOrganization"
              }
            ]
          },
          "isFake": {
            "type": "boolean",
            "nullable": true,
            "example": false,
            "description": "If true, the connection targets sandbox / fake providers. Sample responses use JSON boolean true/false, not the string \"true\"."
          },
          "restrictedTo": {
            "type": "array",
            "description": "Product types this connection is restricted to",
            "items": {
              "type": "string",
              "enum": [
                "CACC",
                "CARD",
                "LOAN",
                "SVGS",
                "SCTS"
              ]
            }
          },
          "iframe": {
            "type": "boolean",
            "nullable": true,
            "description": "Whether the consent journey should display as an iframe"
          },
          "access": {
            "nullable": true,
            "allOf": [
              {
                "$ref": "#/components/schemas/ConnectionAccess"
              }
            ]
          },
          "contactId": {
            "type": "string",
            "nullable": true,
            "description": "Phone number of a contact from an extended journey (e.g. loans)."
          },
          "redirectUrl": {
            "type": "string",
            "nullable": true,
            "description": "An optional URL to be redirected after a successful connection"
          },
          "startDate": {
            "type": "string",
            "format": "date",
            "description": "The date from which transactions would be collected"
          },
          "createdAt": {
            "type": "string",
            "format": "date-time",
            "nullable": true,
            "description": "The timestamp in UTC when the connection was created"
          },
          "updatedAt": {
            "type": "string",
            "format": "date-time",
            "nullable": true,
            "description": "The timestamp in UTC when the connection was last updated"
          },
          "scaOAuth": {
            "type": "string",
            "nullable": true,
            "description": "URL for OAuth-based Strong Customer Authentication"
          },
          "verifier": {
            "type": "string",
            "nullable": true,
            "description": "Verifier used for verifying the connection"
          },
          "lastFetchedDataDate": {
            "type": "string",
            "format": "date",
            "nullable": true,
            "description": "Last date at which transactions have been fetched"
          },
          "language": {
            "type": "string",
            "nullable": true,
            "description": "The language to use in the consent journey, if not set the user will be able to choose the language"
          },
          "paymentId": {
            "type": "string",
            "nullable": true,
            "description": "Related payment identifier when the connection was created from a payment flow"
          },
          "allowBusiness": {
            "type": "boolean",
            "nullable": true,
            "description": "Indicates if the connection allows business accounts"
          },
          "allowInsurance": {
            "type": "boolean",
            "nullable": true,
            "description": "Indicates if the connection allows insurance-related data"
          },
          "isPriority": {
            "type": "boolean",
            "description": "Whether this connection is treated as priority for processing"
          },
          "customerApprovalGranted": {
            "type": "boolean",
            "nullable": true,
            "description": "Indicates whether the end user has approved the customer approval terms. Only present when the feature is enabled on the organization"
          }
        }
      },
      "CallbackInformation": {
        "type": "object",
        "description": "Webhook and callback configuration stored on the connection (mirrors organization callback shape where applicable)",
        "properties": {
          "webhooks": {
            "type": "object",
            "nullable": true,
            "properties": {
              "enabled": {
                "type": "boolean",
                "nullable": true,
                "description": "If true, enable webhooks"
              },
              "successUrl": {
                "type": "string",
                "nullable": true,
                "description": "The url endpoint for success events"
              },
              "failUrl": {
                "type": "string",
                "nullable": true,
                "description": "The url endpoint for fail events"
              },
              "abortUrl": {
                "type": "string",
                "nullable": true,
                "description": "The url endpoint for abort events"
              },
              "oauth": {
                "type": "object",
                "nullable": true,
                "properties": {
                  "enabled": {
                    "type": "boolean",
                    "nullable": true,
                    "description": "Whether OAuth is used to authenticate webhook calls"
                  },
                  "clientId": {
                    "type": "string",
                    "nullable": true
                  },
                  "clientSecret": {
                    "type": "string",
                    "nullable": true
                  },
                  "audience": {
                    "type": "string",
                    "nullable": true
                  },
                  "scope": {
                    "type": "string",
                    "nullable": true
                  },
                  "tokenUrl": {
                    "type": "string",
                    "nullable": true
                  }
                }
              },
              "basic": {
                "type": "object",
                "nullable": true,
                "description": "Optional basic-auth configuration for webhooks",
                "properties": {
                  "enabled": {
                    "type": "boolean",
                    "nullable": true
                  },
                  "username": {
                    "type": "string",
                    "nullable": true
                  },
                  "password": {
                    "type": "string",
                    "nullable": true
                  },
                  "tokenUrl": {
                    "type": "string",
                    "nullable": true
                  }
                }
              },
              "customHeaders": {
                "type": "object",
                "nullable": true,
                "additionalProperties": {
                  "type": "string"
                },
                "description": "Extra HTTP headers sent with webhook requests"
              },
              "products": {
                "type": "array",
                "nullable": true,
                "description": "Which products emit webhooks for this configuration",
                "items": {
                  "type": "string",
                  "enum": [
                    "CONNECTIONS",
                    "PAYMENTS",
                    "DECISION",
                    "SESSIONS"
                  ]
                }
              }
            }
          }
        }
      },
      "ErrorResponse": {
        "type": "object",
        "properties": {
          "type": {
            "type": "string",
            "description": "The type of the error"
          },
          "message": {
            "type": "string",
            "description": "The message of the error"
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