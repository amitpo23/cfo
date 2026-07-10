# Get transactions by user

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
    "/data/transactions": {
      "get": {
        "summary": "Get transactions by user",
        "security": [
          {
            "oAuth2ClientCredentials": [
              "read:transactions"
            ]
          }
        ],
        "parameters": [
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
            "name": "limit",
            "in": "query",
            "required": false,
            "description": "Max number of documents to retrieve",
            "schema": {
              "type": "number"
            }
          },
          {
            "name": "dateFrom",
            "in": "query",
            "required": false,
            "description": "Specifies the starting date from which to retrieve transactions. If you use this you cant use limit",
            "schema": {
              "type": "string",
              "example": "2024-04-03",
              "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
            }
          },
          {
            "name": "dateTo",
            "in": "query",
            "required": false,
            "description": "Specifies the ending date until which to retrieve transactions. If you use this you cant use limit",
            "schema": {
              "type": "string",
              "example": "2024-04-03",
              "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
            }
          },
          {
            "name": "includeDuplicates",
            "in": "query",
            "required": false,
            "description": "Specifies whether to return duplicates or not",
            "schema": {
              "type": "integer",
              "enum": [
                0,
                1
              ]
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
            "name": "accountId",
            "in": "query",
            "required": false,
            "description": "The accountId that the transactions are linked to",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "connectionId",
            "in": "query",
            "required": false,
            "description": "The connectionId that the transactions are linked to",
            "schema": {
              "type": "string"
            }
          },
          {
            "name": "type",
            "in": "query",
            "required": false,
            "description": "The type of the provider",
            "schema": {
              "type": "string",
              "enum": [
                "BANK",
                "CARD"
              ]
            }
          },
          {
            "name": "providerId",
            "in": "query",
            "required": false,
            "description": "The providerId that the transactions are linked to",
            "schema": {
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
                      "description": "Represents the total number of items that exists after full pagination. The max transactions per request is 500"
                    },
                    "items": {
                      "type": "array",
                      "items": {
                        "$ref": "#/components/schemas/Transaction"
                      }
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "userId is not allowed in query for non-admin users"
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
      "Transaction": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "A unique identifier for the transaction"
          },
          "SK": {
            "type": "string",
            "description": "Secondary key for the transaction, indicating the specific type of transaction and related metadata."
          },
          "userId": {
            "type": "string",
            "description": "A unique identifier for the user"
          },
          "orgId": {
            "type": "string",
            "description": "A unique identifier for the organization"
          },
          "connectionId": {
            "type": "string",
            "description": "A unique identifier for the connection"
          },
          "accountId": {
            "type": "string",
            "description": "A unique identifier for the account"
          },
          "providerId": {
            "type": "string",
            "description": "A unique identifier for the provider"
          },
          "transactionProviderIdentifier": {
            "type": "string",
            "description": "A unique identifier for the provider TX"
          },
          "relatedPaymentId": {
            "type": "string",
            "description": "If the transaction is linked to a open-banking payment, its id will be here"
          },
          "accountNumber": {
            "type": "string",
            "description": "A bank account number"
          },
          "status": {
            "type": "string",
            "description": "The transaction status"
          },
          "entryReference": {
            "type": "string",
            "description": "The entry reference sent from the provider"
          },
          "categoryCode": {
            "type": "string",
            "description": "Code representing the category of the transaction (MCC code or other)."
          },
          "securityDetails": {
            "$ref": "#/components/schemas/TransactionSecurityDetails"
          },
          "amount": {
            "type": "object",
            "properties": {
              "originalAmount": {
                "$ref": "#/components/schemas/Amount"
              },
              "chargedAmount": {
                "$ref": "#/components/schemas/Amount"
              }
            }
          },
          "description": {
            "type": "object",
            "properties": {
              "description": {
                "type": "string",
                "description": "The TX description"
              },
              "additionalInfo": {
                "type": "string",
                "description": "Any additional TX info"
              }
            }
          },
          "category": {
            "type": "object",
            "description": "Categorized TX label",
            "properties": {
              "main": {
                "type": "string",
                "description": "Main category"
              },
              "sub": {
                "type": "string",
                "description": "Subcategory"
              }
            }
          },
          "changedCategory": {
            "type": "object",
            "description": "Details about the changed category of the transaction.",
            "properties": {
              "main": {
                "type": "string",
                "description": "Main changed category"
              },
              "sub": {
                "type": "string",
                "description": "Sub changed category"
              }
            }
          },
          "installments": {
            "type": "object",
            "description": "Details about installments.",
            "properties": {
              "number": {
                "type": "number",
                "description": "The current installment number"
              },
              "total": {
                "type": "number",
                "description": "The total number of installments"
              }
            }
          },
          "type": {
            "type": "string",
            "description": "Transaction type, NORMAL or INSTALLMENT"
          },
          "date": {
            "type": "object",
            "properties": {
              "valueDate": {
                "type": "string",
                "format": "date"
              },
              "bookingDate": {
                "type": "string",
                "format": "date"
              },
              "transactionDate": {
                "type": "string",
                "format": "date"
              }
            }
          },
          "markupFee": {
            "type": "object",
            "properties": {
              "amount": {
                "type": "number",
                "description": "The amount of the markup fee."
              },
              "currency": {
                "type": "string",
                "description": "The currency of the markup fee."
              }
            }
          },
          "merchantName": {
            "type": "string",
            "description": "The name of the merchant involved in the transaction."
          },
          "details": {
            "type": "string",
            "description": "Detailed information about the transaction."
          },
          "isInvoiced": {
            "type": "boolean",
            "description": "Indicates whether the transaction is invoiced."
          },
          "code": {
            "type": "string",
            "description": "A code representing the transaction."
          },
          "merchantAddress": {
            "type": "object",
            "properties": {
              "streetName": {
                "type": "string",
                "description": "The street name of the merchant."
              },
              "buildingNumber": {
                "type": "string",
                "description": "The building number of the merchant."
              },
              "townName": {
                "type": "string",
                "description": "The town name of the merchant."
              },
              "postCode": {
                "type": "string",
                "description": "The postal code of the merchant."
              },
              "country": {
                "type": "string",
                "description": "The country of the merchant."
              }
            }
          },
          "classification": {
            "type": "object",
            "description": "Details about the classification of the transaction.",
            "properties": {
              "type": {
                "type": "string",
                "description": "The type of classification (e.g., REGULAR_EXPENSE)."
              },
              "source": {
                "type": "string",
                "description": "The source of classification (e.g., SYSTEM)."
              }
            }
          },
          "changedClassification": {
            "type": "object",
            "description": "Details about any changes in the classification of the transaction.",
            "properties": {
              "type": {
                "type": "string",
                "description": "The type of classification (e.g., REGULAR_EXPENSE)."
              },
              "source": {
                "type": "string",
                "description": "The source of classification (e.g., USER)."
              }
            }
          },
          "labels": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "description": "Labels associated with the transaction."
          },
          "balancePerEndDay": {
            "type": "number",
            "description": "The balance at the end of the day for the transaction."
          },
          "isDuplicate": {
            "type": "boolean",
            "description": "Indicates if the transaction is a duplicate - when a user connects the same credit card from a bank provider and from a credit card \n when not send includeDuplicates filter the default will be that no duplicate transactions will be returned \n if the transactions for the user contains more than 500 items, duplicates will be returned regardless of the used filters"
          },
          "creditorAccount": {
            "type": "object",
            "properties": {
              "iban": {
                "type": "string",
                "description": "IBAN of the creditor account"
              },
              "bban": {
                "type": "string",
                "description": "BBAN of the creditor account"
              },
              "maskedPan": {
                "type": "string",
                "description": "Masked PAN of the creditor account"
              },
              "msisdn": {
                "type": "string",
                "description": "MSISDN of the creditor account"
              },
              "currency": {
                "type": "string",
                "description": "Currency of the creditor account"
              },
              "other": {
                "type": "string",
                "description": "Other of the creditor account"
              },
              "cashAccountType": {
                "type": "string",
                "description": "Type of the creditor account"
              }
            }
          },
          "debtorAccount": {
            "type": "object",
            "properties": {
              "iban": {
                "type": "string",
                "description": "IBAN of the debtor account"
              },
              "bban": {
                "type": "string",
                "description": "BBAN of the debtor account"
              },
              "maskedPan": {
                "type": "string",
                "description": "Masked PAN of the debtor account"
              },
              "msisdn": {
                "type": "string",
                "description": "MSISDN of the debtor account"
              },
              "currency": {
                "type": "string",
                "description": "Currency of the debtor account"
              },
              "other": {
                "type": "string",
                "description": "Other of the debtor account"
              },
              "cashAccountType": {
                "type": "string",
                "description": "Type of the debtor account"
              }
            }
          },
          "endToEndId": {
            "type": "string",
            "description": "The end-to-end identifier of the transaction.\nThis field is crucial for transferring the reference number of the payment, ensuring traceability and consistency across different financial institutions and systems."
          }
        }
      },
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
      "TransactionSecurityDetails": {
        "type": "object",
        "properties": {
          "unitsNumber": {
            "type": "number",
            "description": "Nominal or numeric quantification of the financial instrument that has been transferred within this transaction. Negative values indicate that the respective quantity of the financial instrument has been taken from the securities account, positive values indicate that the quantity has been added."
          },
          "unitsNominal": {
            "$ref": "#/components/schemas/Amount"
          },
          "placeOfTrade": {
            "type": "object",
            "properties": {
              "marketIdentifierProprietary": {
                "type": "string",
                "description": "Proprietary Identifier of the market place."
              },
              "mic": {
                "type": "string",
                "description": "ISO 10383 code of the market place"
              }
            }
          },
          "relevantDates": {
            "type": "object",
            "properties": {
              "effectiveSettlementDate": {
                "type": "string",
                "format": "date",
                "description": "The effective settlement date"
              },
              "performanceDate": {
                "type": "string",
                "format": "date",
                "description": "The performance date"
              },
              "settlementDate": {
                "type": "string",
                "format": "date",
                "description": "The settlement date"
              },
              "valueDate": {
                "type": "string",
                "format": "date",
                "description": "The value date"
              },
              "bookingDate": {
                "type": "string",
                "format": "date",
                "description": "The booking date"
              },
              "transactionsDate": {
                "type": "string",
                "format": "date",
                "description": "The transaction date"
              }
            },
            "description": "At least one of the listed date types must be present."
          },
          "orderId": {
            "type": "string",
            "description": "Resource Id of the order resource that triggered this transaction, if applicable."
          },
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
          },
          "transactionTypeCode": {
            "type": "string",
            "description": "Type of the transaction as code or as a proprietary string. For the code, the following values are supported: BOLE Transaction relates to lending/borrowing. CLAI Transaction relates to a market claim following a corporate action. COLL Transaction relates to collateral. CORP Transaction relates to corporate action. SETT Transaction relates to settlement and clearing."
          },
          "transactionTypeProperty": {
            "type": "string",
            "description": "Type of the transaction as code or as a proprietary string. For the code, the following values are supported: BOLE Transaction relates to lending/borrowing. CLAI Transaction relates to a market claim following a corporate action. COLL Transaction relates to collateral. CORP Transaction relates to corporate action. SETT Transaction relates to settlement and clearing."
          },
          "amountIncludesFees": {
            "type": "boolean",
            "description": "Indicates whether the transactionAmount is including fees"
          },
          "amountIncludesTaxes": {
            "type": "boolean",
            "description": "Indicates whether the transactionAmount is including taxes"
          },
          "relatedFees": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/RelatedFee"
            },
            "description": "Only allowed if amountIncludesFees = true. In that case Details of the fees that have been applied to this transaction (and therefore represent additional costs of the transaction beyond the transactionAmount). Fees with positive amount are debited by the PSU, only in the rare case of a fee credited to the PSU (e.g. in case of a reversal) negative amounts are used."
          },
          "reversalIndicator": {
            "type": "boolean",
            "description": "Indicates whether it is the reversal of a previously reported movement."
          },
          "reversedTransactionId": {
            "type": "string",
            "description": "transactionId of the reversed transaction, if applicable and supported by the ASPSP."
          },
          "unitsNumberBeforeTx": {
            "type": "number",
            "description": "Nominal or numeric quantification of the financial instrument that has been transferred within this transaction before this transaction has been executed. Negative values indicate that the respective quantity of the financial instrument has been taken from the securities account, positive values indicate that the quantity has been added."
          },
          "unitsNominalBeforeTx": {
            "$ref": "#/components/schemas/Amount"
          },
          "unitsNumberAfterTx": {
            "type": "number",
            "description": "Nominal or numeric quantification of the financial instrument that has been transferred within this transaction after this transaction has been executed. Negative values indicate that the respective quantity of the financial instrument has been taken from the securities account, positive values indicate that the quantity has been added."
          },
          "unitsNominalAfterTx": {
            "$ref": "#/components/schemas/Amount"
          },
          "accruedInterest": {
            "$ref": "#/components/schemas/AccruedInterest"
          },
          "details": {
            "type": "string",
            "description": "Additional details related to the transaction."
          }
        }
      },
      "RelatedFee": {
        "type": "object",
        "properties": {
          "amount": {
            "$ref": "#/components/schemas/Amount"
          },
          "typeCode": {
            "type": "string",
            "description": "Initially, the following codes are defined to indicate different fee types in the context of Securities transactions. Please note, that these codes are not based on an ISO code list and might be changed in later versions of this document: transactionFee, brokerageFee, managementFee, courtage, custodyFee, exchangeFee, thirdPartyFee, otherFee",
            "enum": [
              "transactionFee",
              "brokerageFee",
              "managementFee",
              "courtage",
              "custodyFee",
              "exchangeFee",
              "thirdPartyFee",
              "otherFee"
            ]
          },
          "typeProprietary": {
            "type": "string",
            "description": "Proprietary fee type"
          },
          "feeType": {
            "type": "string",
            "description": "The type of the fee"
          },
          "_links": {
            "type": "object",
            "properties": {
              "self": {
                "type": "object",
                "properties": {
                  "href": {
                    "type": "string"
                  }
                }
              }
            }
          }
        }
      },
      "AccruedInterest": {
        "type": "object",
        "properties": {
          "daysAccrued": {
            "type": "number",
            "description": "Specifies the number of days used for calculating the accrued interest amount."
          },
          "amounts": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/Amount"
            },
            "description": "Amount of the accrued interest. Each item represents the same monetary value in different currencies, e.g. account currency, currency of the security's denomination."
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