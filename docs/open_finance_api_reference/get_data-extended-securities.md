# Get the list of positions and orders with extra information

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
    "/data/extended-securities": {
      "get": {
        "summary": "Get the list of positions and orders with extra information",
        "security": [
          {
            "oAuth2ClientCredentials": [
              "read:extended-securities"
            ]
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
                    "positions": {
                      "$ref": "#/components/schemas/SecurityPositionExtended"
                    },
                    "totalPositionsValue": {
                      "type": "integer"
                    },
                    "orders": {
                      "$ref": "#/components/schemas/SecurityOrderExtended"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "orgId was not provided"
          },
          "401": {
            "description": "Unauthorized access - Invalid access token"
          },
          "403": {
            "description": "Forbidden - Access token missing the required permissions to perform this action"
          },
          "404": {
            "description": "Not found - payment not found"
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
      "Amount": {
        "type": "object",
        "properties": {
          "amount": {
            "type": "number",
            "description": "The amount value",
            "example": 11
          },
          "currency": {
            "type": "string",
            "description": "The amount currency",
            "example": "ILS"
          }
        }
      },
      "SecurityPosition": {
        "type": "object",
        "properties": {
          "financialInstrument": {
            "type": "object",
            "properties": {
              "isin": {
                "type": "string"
              },
              "name": {
                "type": "string"
              },
              "normalisedPrice": {
                "type": "object",
                "properties": {
                  "amount": {
                    "$ref": "#/components/schemas/Amount"
                  },
                  "priceDateTime": {
                    "type": "string"
                  },
                  "priceType": {
                    "type": "string",
                    "enum": [
                      "BIDE",
                      "OFFR",
                      "NAVL",
                      "CREA",
                      "CANC",
                      "INTE",
                      "SWNG",
                      "MIDD",
                      "RINV",
                      "SWIC",
                      "MRKT",
                      "INDC",
                      "DDVR",
                      "ACTU"
                    ]
                  },
                  "sourceOfPrice": {
                    "type": "object",
                    "properties": {
                      "type": {
                        "type": "string",
                        "enum": [
                          "FUND",
                          "LMAR",
                          "THEO",
                          "VEND"
                        ]
                      },
                      "mic": {
                        "type": "string"
                      }
                    }
                  }
                }
              },
              "unitsNumber": {
                "type": "number"
              },
              "balanceType": {
                "type": "string",
                "enum": [
                  "AVAI",
                  "AWAS",
                  "BTRA",
                  "BLOK",
                  "BLOV",
                  "BLCA",
                  "BLOT",
                  "BORR",
                  "COLI",
                  "COLO",
                  "MARG",
                  "DRAW",
                  "COLA",
                  "TRAN",
                  "ISSU",
                  "DIRT",
                  "LOAN",
                  "REGO",
                  "BODE",
                  "BORE",
                  "PEDA",
                  "PECA",
                  "PEND",
                  "PDMT",
                  "PDUM",
                  "LODE",
                  "LORE",
                  "PENR",
                  "PRMT",
                  "PRUM",
                  "PLED",
                  "QUAS",
                  "NOMI",
                  "RSTR",
                  "SPOS",
                  "CLEN",
                  "OTHR",
                  "UNRG",
                  "WDOC"
                ]
              },
              "averageBuyingPrice": {
                "$ref": "#/components/schemas/Amount"
              },
              "details": {
                "type": "string",
                "properties": {
                  "symbol": {
                    "type": "string"
                  }
                }
              }
            },
            "description": "Financial instrument that was transferred within the transaction."
          }
        }
      },
      "SecurityPositionExtended": {
        "allOf": [
          {
            "$ref": "#/components/schemas/SecurityPosition"
          },
          {
            "type": "object",
            "properties": {
              "providerId": {
                "type": "string"
              },
              "currentPrice": {
                "type": "integer"
              },
              "positionValue": {
                "type": "integer"
              },
              "symbol": {
                "type": "string"
              },
              "securityId": {
                "type": "string"
              }
            }
          }
        ]
      },
      "SecurityOrder": {
        "type": "object",
        "properties": {
          "orderId": {
            "type": "string"
          },
          "side": {
            "type": "string",
            "enum": [
              "buy",
              "sell",
              "subscription",
              "redemption"
            ]
          },
          "financialInstrument": {
            "type": "object",
            "properties": {
              "isin": {
                "type": "string"
              },
              "name": {
                "type": "string"
              }
            }
          },
          "unitsNumber": {
            "type": "string"
          },
          "orderStatus": {
            "type": "string",
            "enum": [
              "unknown",
              "new",
              "partiallyFilled",
              "filled",
              "doneForDay",
              "canceled",
              "replaced",
              "pendingCancel",
              "stopped",
              "rejected",
              "suspended",
              "pendingNew",
              "calculated",
              "expired",
              "acceptedForBidding",
              "pendingReplace"
            ]
          }
        }
      },
      "SecurityOrderExtended": {
        "allOf": [
          {
            "$ref": "#/components/schemas/SecurityOrder"
          },
          {
            "type": "object",
            "properties": {
              "providerId": {
                "type": "string"
              }
            }
          }
        ]
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