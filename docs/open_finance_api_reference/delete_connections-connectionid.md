# Delete connection by ID (user scope)

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
    "/connections/{connectionId}": {
      "delete": {
        "summary": "Delete connection by ID (user scope)",
        "security": [
          {
            "oAuth2ClientCredentials": [
              "delete:connections"
            ]
          }
        ],
        "parameters": [
          {
            "name": "connectionId",
            "in": "path",
            "required": true,
            "description": "A unique identifier for the connection",
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "204": {
            "description": "Response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object"
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
            "description": "connection not found"
          },
          "423": {
            "description": "This connection is locked and cant be deleted currently. If you have big-query enabled, you can only delete connections that were created at least 90 minutes ago"
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