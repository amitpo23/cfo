# Get all providers

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
    "/providers": {
      "get": {
        "summary": "Get all providers",
        "security": [
          {
            "oAuth2ClientCredentials": [
              "read:providers"
            ]
          }
        ],
        "parameters": [
          {
            "name": "includeFakeProviders",
            "in": "query",
            "required": false,
            "description": "Include Sandbox Providers in response",
            "schema": {
              "type": "boolean"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "$ref": "#/components/schemas/Provider"
                  }
                }
              }
            }
          },
          "401": {
            "description": "Unauthorized access - Invalid access token"
          },
          "403": {
            "description": "Forbidden - Access token missing the required permissions to perform this action"
          },
          "404": {
            "description": "Not found - no providers were found or organization not found",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "type": {
                      "type": "string",
                      "example": "CLIENT_ERROR"
                    },
                    "message": {
                      "type": "string",
                      "example": "No providers were found"
                    }
                  }
                },
                "examples": {
                  "Providers Not Found": {
                    "value": {
                      "type": "CLIENT_ERROR",
                      "message": "No providers were found"
                    }
                  },
                  "Organization Not Found": {
                    "value": {
                      "type": "CLIENT_ERROR",
                      "message": "Organization not found"
                    }
                  }
                }
              }
            }
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
      "Provider": {
        "type": "object",
        "properties": {
          "providerFriendlyId": {
            "type": "string",
            "description": "A unique identifier for the provider"
          },
          "name": {
            "type": "string",
            "description": "The bank name"
          },
          "nameNativeLanguage": {
            "type": "string",
            "description": "The bank name in it's native language"
          },
          "mode": {
            "type": "string",
            "description": "PSD2"
          },
          "site": {
            "type": "string",
            "description": "The official website or login URL of the bank"
          },
          "bankCode": {
            "type": "integer",
            "description": "The code of the bank"
          },
          "image": {
            "type": "string",
            "description": "URL for the provider's logo or image"
          },
          "loginFields": {
            "type": "array",
            "items": {
              "type": "string",
              "description": "Fields required for bank login"
            }
          },
          "isFake": {
            "type": "boolean",
            "description": "If true, the provider is fake"
          },
          "psd2Uris": {
            "type": "object",
            "properties": {
              "cardUri": {
                "type": "string",
                "description": "The URI for accessing card data"
              },
              "loanUri": {
                "type": "string",
                "description": "The URI for accessing loan data"
              },
              "savingsUri": {
                "type": "string",
                "description": "The URI for accessing savings data"
              },
              "securitiesUri": {
                "type": "string",
                "description": "The URI for accessing securities data"
              },
              "tokenUri": {
                "type": "string",
                "description": "The URI for generating tokens"
              },
              "baseUri": {
                "type": "string",
                "description": "The base URI for accessing PSD2 services"
              },
              "paymentsUri": {
                "type": "string",
                "description": "The URI for accessing payment data"
              }
            },
            "description": "URIs for various PSD2 services offered by the provider"
          },
          "psuIdTypes": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "name": {
                  "type": "string",
                  "description": "The name of the PSU ID type"
                },
                "nameNativeLanguage": {
                  "type": "string",
                  "description": "The name of the PSU ID type in its native language"
                },
                "id": {
                  "type": "string",
                  "description": "The identifier for the PSU ID type"
                }
              }
            },
            "description": "Different types of PSU IDs supported by the provider"
          },
          "psuIdDefaultType": {
            "type": "string",
            "description": "The default PSU ID type for the provider"
          },
          "psuCorporateIdDefaultType": {
            "type": "string",
            "description": "The default PSU CORPORATE ID type for the provider"
          },
          "type": {
            "type": "string",
            "description": "The type of the provider, such as 'BANK', 'CARD', or 'INSURANCE'"
          },
          "status": {
            "type": "object",
            "properties": {
              "consents": {
                "type": "object",
                "properties": {
                  "enabled": {
                    "type": "boolean",
                    "description": "Indicates if consents are enabled for this provider"
                  }
                }
              },
              "payments": {
                "type": "object",
                "properties": {
                  "enabled": {
                    "type": "boolean",
                    "description": "Indicates if payments are enabled for this provider"
                  }
                }
              }
            },
            "description": "The status of different services (consents and payments) offered by the provider"
          },
          "successRate": {
            "type": "object",
            "properties": {
              "consents": {
                "type": "integer",
                "description": "The success rate percentage for consents"
              },
              "payments": {
                "type": "integer",
                "description": "The success rate percentage for payments"
              }
            },
            "description": "The success rates for the services provided by the provider"
          },
          "allowPsuCorporateIdTypeChoice": {
            "type": "boolean",
            "description": "Indicates if the provider allows the selection of different PSU corporate ID types"
          },
          "providerForcePaymentService": {
            "type": "string",
            "enum": [
              "zahav",
              "masav",
              "fp"
            ],
            "description": "Does this provider have a forced payment service"
          },
          "psuCorporateIdTypes": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "name": {
                  "type": "string",
                  "description": "The name of the PSU Corporate ID type"
                },
                "nameNativeLanguage": {
                  "type": "string",
                  "description": "The name of the PSU Corporate ID type in its native language"
                },
                "id": {
                  "type": "string",
                  "description": "The identifier for the PSU Corporate ID type"
                }
              }
            },
            "description": "Different types of PSU Corporate IDs supported by the provider"
          },
          "sortIndex": {
            "type": "number",
            "description": "A numeric value used to sort providers by their order of preference or importance"
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