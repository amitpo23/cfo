# Get all bank branches

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
    "/bank-branches": {
      "get": {
        "summary": "Get all bank branches",
        "security": [
          {
            "oAuth2ClientCredentials": [
              "read:providers"
            ]
          }
        ],
        "parameters": [
          {
            "name": "bankCode",
            "in": "query",
            "required": true,
            "description": "The bank code of the bank you would like to get the branches of",
            "schema": {
              "type": "string"
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
                    "$ref": "#/components/schemas/BankBranch"
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
      "BankBranch": {
        "type": "object",
        "properties": {
          "branchCode": {
            "type": "integer",
            "description": "The code of the branch"
          },
          "city": {
            "type": "string",
            "description": "The city where the branch is located"
          },
          "POB": {
            "type": "string",
            "nullable": true,
            "description": "Post Office Box number"
          },
          "branchName": {
            "type": "string",
            "description": "The name of the branch"
          },
          "fax": {
            "type": "string",
            "nullable": true,
            "description": "The fax number of the branch"
          },
          "handicapAccess": {
            "type": "string",
            "description": "Indicates if the branch has handicap access"
          },
          "dayClosed": {
            "type": "string",
            "description": "The day the branch is closed"
          },
          "branchType": {
            "type": "string",
            "description": "The type of the branch"
          },
          "mergeBranch": {
            "type": "string",
            "nullable": true,
            "description": "Code of the branch it merged with, if applicable"
          },
          "freeTel": {
            "type": "string",
            "nullable": true,
            "description": "Free telephone number"
          },
          "closeDate": {
            "type": "string",
            "format": "date-time",
            "nullable": true,
            "description": "The date the branch was closed"
          },
          "branchAddress": {
            "type": "string",
            "description": "The address of the branch"
          },
          "openDate": {
            "type": "string",
            "format": "date-time",
            "description": "The date the branch was opened"
          },
          "YCoordinate": {
            "type": "number",
            "format": "double",
            "description": "The Y coordinate of the branch location"
          },
          "XCoordinate": {
            "type": "number",
            "format": "double",
            "description": "The X coordinate of the branch location"
          },
          "telephone": {
            "type": "string",
            "description": "The telephone number of the branch"
          },
          "zipCode": {
            "type": "string",
            "nullable": true,
            "description": "The zip code of the branch"
          },
          "bankCode": {
            "type": "integer",
            "description": "The code of the bank"
          },
          "mergeBank": {
            "type": "string",
            "nullable": true,
            "description": "Code of the bank it merged with, if applicable"
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