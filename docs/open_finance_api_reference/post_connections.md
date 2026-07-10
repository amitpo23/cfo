# Create connection

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
      "post": {
        "summary": "Create connection",
        "security": [
          {
            "oAuth2ClientCredentials": [
              "create:connections"
            ]
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "customerId": {
                    "type": "string",
                    "description": "The ID of the customer (business ID / national ID) created through an extended journey (like loans)"
                  },
                  "startDate": {
                    "type": "string",
                    "format": "date",
                    "description": "The date which from transactions would be collected"
                  },
                  "expiryDate": {
                    "type": "string",
                    "format": "date-time",
                    "description": "The date at which the connection should expire"
                  },
                  "paymentId": {
                    "type": "string",
                    "description": "If this connection is created for a payment process you can define it here with a unique payment identifier"
                  },
                  "journeyId": {
                    "type": "string",
                    "description": "The journey id the connection was created in"
                  },
                  "language": {
                    "type": "string",
                    "description": "The language of the connection (he / en)",
                    "enum": [
                      "he",
                      "en"
                    ]
                  },
                  "externalId": {
                    "type": "string",
                    "description": "An optional external id that can be given to a connection"
                  },
                  "agentEmail": {
                    "type": "string",
                    "description": "The email of the agent"
                  },
                  "providerIds": {
                    "type": "array",
                    "items": {
                      "type": "string",
                      "enum": [
                        "yahav-sandbox",
                        "yahav",
                        "undefined",
                        "ubank-sandbox",
                        "ubank",
                        "pepper",
                        "pagi-sandbox",
                        "pagi",
                        "otsarHahayal-sandbox",
                        "otsarHahayal",
                        "open-finance-sandbox",
                        "open-finance-card-sandbox",
                        "mizrahi-sandbox",
                        "mizrahi",
                        "mercantile-sandbox",
                        "mercantile",
                        "menora-sandbox",
                        "max-sandbox",
                        "max",
                        "masad-sandbox",
                        "masad",
                        "leumi-sandbox",
                        "leumi",
                        "isracard-sandbox",
                        "isracard",
                        "hapoalim-sandbox",
                        "hapoalim",
                        "discount-sandbox",
                        "discount",
                        "cal-sandbox",
                        "cal",
                        "beinleumi-sandbox",
                        "beinleumi",
                        "americanExpress"
                      ],
                      "description": "Array of friendly bank IDs, the connection will be limited to the provided IDs, if none sent default will allow all providers"
                    }
                  },
                  "callbackInformation": {
                    "$ref": "#/components/schemas/CallbackInformation"
                  },
                  "includeFakeProviders": {
                    "type": "boolean",
                    "default": false,
                    "description": "If true, this connection can be used for testing purposes vs. a fake bank provider"
                  },
                  "refreshData": {
                    "type": "boolean",
                    "default": false,
                    "description": "If true, this connection will automatically get new transactions data"
                  },
                  "iframe": {
                    "type": "boolean",
                    "default": false,
                    "description": "If true, this connection send post messages for status notifications in an iframe"
                  },
                  "psuId": {
                    "type": "string",
                    "default": "",
                    "description": "incase you want to define ahead of time the user national id of passport and block him from changing it",
                    "minLength": 5,
                    "maxLength": 9,
                    "pattern": "^[0-9]+$"
                  },
                  "psuCorporateId": {
                    "type": "string",
                    "default": "",
                    "description": "incase you want to define ahead of time the user corporate id and block him from changing it",
                    "minLength": 8,
                    "maxLength": 9,
                    "pattern": "^[0-9]+$"
                  },
                  "redirectUrl": {
                    "type": "string",
                    "default": "",
                    "description": "An optional url to be redirected after a successful connection"
                  },
                  "connectionMode": {
                    "type": "string",
                    "default": "PSD2"
                  },
                  "allowBusiness": {
                    "type": "boolean",
                    "default": false,
                    "description": "If true this connection will allow business accounts"
                  },
                  "access": {
                    "type": "object",
                    "description": "The access object is used to define the permissions you want to give to the connection",
                    "properties": {
                      "accounts": {
                        "type": "array",
                        "minItems": 0,
                        "items": {
                          "type": "object",
                          "properties": {
                            "iban": {
                              "type": "string",
                              "description": "The account iban number",
                              "example": "IL123456789012345678901"
                            },
                            "bban": {
                              "type": "string",
                              "description": "The account bban number",
                              "example": "10-944-50151142"
                            }
                          }
                        }
                      },
                      "balances": {
                        "type": "array",
                        "minItems": 0,
                        "items": {
                          "type": "object",
                          "properties": {
                            "iban": {
                              "type": "string",
                              "description": "The account iban number",
                              "example": "IL123456789012345678901"
                            },
                            "bban": {
                              "type": "string",
                              "description": "The account bban number",
                              "example": "10-944-50151142"
                            }
                          }
                        }
                      },
                      "transactions": {
                        "type": "array",
                        "minItems": 0,
                        "items": {
                          "type": "object",
                          "properties": {
                            "iban": {
                              "type": "string",
                              "description": "The account iban number",
                              "example": "IL123456789012345678901"
                            },
                            "bban": {
                              "type": "string",
                              "description": "The account bban number",
                              "example": "10-944-50151142"
                            }
                          }
                        }
                      }
                    }
                  },
                  "restrictedTo": {
                    "type": "array",
                    "description": "The restrictedTo object is used to define the permissions you want to give to the connection",
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
                  "psuIdType": {
                    "type": "string",
                    "description": "The type of the PSU ID, validated based on the provider ID."
                  },
                  "isPlaidSandbox": {
                    "type": "boolean",
                    "description": "If true, this connection will be treated as a sandbox connection for Plaid."
                  },
                  "redirectWithoutButtonClick": {
                    "type": "boolean",
                    "description": "If true, this connection will be redirected automatically without the user needing to click a button."
                  },
                  "allowInsurance": {
                    "type": "boolean",
                    "description": "If true, this connection will allow insurance-related data to be accessed."
                  }
                }
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "description": "A unique identifier for the connection"
                    },
                    "connectUrl": {
                      "type": "string",
                      "description": "A link forwarding the end-user to the consent journey"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "production access is not enabled for this organization, you must include fake providers or contact us",
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
            "description": "Organization not found in auth0 token"
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