# Create access token

# OpenAPI definition

```json
{
  "openapi": "3.0.0",
  "servers": [
    {
      "url": "https://api.open-finance.ai/oauth"
    }
  ],
  "info": {
    "version": "1.0.0",
    "title": "Auth"
  },
  "paths": {
    "/token": {
      "post": {
        "summary": "Create access token",
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": [
                  "userId",
                  "clientId",
                  "clientSecret"
                ],
                "properties": {
                  "userId": {
                    "type": "string",
                    "description": "A unique identifier provided by your systems, unique per each user account"
                  },
                  "clientId": {
                    "type": "string",
                    "description": "A unique identifier which identifies you as a company, firm, client etc."
                  },
                  "clientSecret": {
                    "type": "string",
                    "description": "A secret provided by our system, this should not be seen by the public eye!"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Access token required by our API",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "accessToken": {
                      "type": "string",
                      "description": "Access token required by our API"
                    },
                    "tokenType": {
                      "type": "string",
                      "description": "Token type"
                    },
                    "expiresIn": {
                      "type": "number",
                      "description": "Expiration time in MS"
                    }
                  }
                }
              }
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