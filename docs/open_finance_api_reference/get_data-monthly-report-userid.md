# Get a user's open banking report

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
    "/data/monthly-report/{userId}": {
      "get": {
        "summary": "Get a user's open banking report",
        "parameters": [
          {
            "name": "userId",
            "in": "path",
            "required": true,
            "description": "The id of the customer that the report is required for",
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
                  "$ref": "#/components/schemas/OpenBankingReport"
                }
              }
            }
          },
          "400": {
            "description": "The user has no connections"
          },
          "401": {
            "description": "Unauthorized access - Invalid access token"
          },
          "403": {
            "description": "Forbidden - Access token missing the required permissions to preform this action"
          },
          "404": {
            "description": "The user has no report, refreshing it's data and creating the report"
          },
          "500": {
            "description": "Internal server error"
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "OpenBankingReport": {
        "type": "object",
        "properties": {
          "openBankingReportId": {
            "type": "string",
            "description": "A unique identifier for the report"
          },
          "openBankingReportBalances": {
            "type": "object",
            "properties": {
              "incomes": {
                "type": "object",
                "properties": {
                  "total": {
                    "type": "number",
                    "description": "The total amount of incomes"
                  },
                  "incomeFromSalary": {
                    "type": "number",
                    "description": "The total amount of incomes from salary"
                  },
                  "incomeFromChecks": {
                    "type": "number",
                    "description": "The total amount of incomes from checks"
                  },
                  "regularIncomesSum": {
                    "type": "number",
                    "description": "The total amount of regular incomes"
                  }
                }
              },
              "expenses": {
                "type": "object",
                "properties": {
                  "total": {
                    "type": "number",
                    "description": "The total amount of expenses"
                  },
                  "expensesFromMortgage": {
                    "type": "number",
                    "description": "The total amount of expenses on mortgage"
                  },
                  "expensesFromChecks": {
                    "type": "number",
                    "description": "The total amount of expenses from checks"
                  },
                  "regularExpensesSum": {
                    "type": "number",
                    "description": "The total amount of regular expenses"
                  }
                }
              },
              "canceledChecks": {
                "type": "number",
                "description": "Number of times checks were canceled"
              },
              "standingOrdersReturns": {
                "type": "number",
                "description": "Number of times standing orders were returned"
              },
              "irregularWarnings": {
                "type": "number",
                "description": "Number of irregular warnings"
              },
              "accountForeclosure": {
                "type": "number",
                "description": "Number of account foreclosures"
              },
              "nsf": {
                "type": "number",
                "description": "Number of NSF times"
              },
              "transfersForFallingBehind": {
                "type": "number",
                "description": "Number of times money was transferred to cover falling behind"
              },
              "limitationAlert": {
                "type": "number",
                "description": "Number of limitation alerts"
              },
              "fallingBehindWarnings": {
                "type": "number",
                "description": "Number of falling behind warnings"
              }
            }
          },
          "MonthlyReportGeneralDetails": {
            "type": "object",
            "properties": {
              "loans": {
                "type": "object",
                "properties": {
                  "totalLoansAmount": {
                    "type": "number",
                    "description": "Current total loans amount"
                  },
                  "bankLoans": {
                    "type": "object",
                    "additionalProperties": {
                      "type": "object",
                      "properties": {
                        "amount": {
                          "type": "number",
                          "description": "The total amount of the loan"
                        }
                      }
                    }
                  },
                  "creditCardLoans": {
                    "type": "object",
                    "additionalProperties": {
                      "type": "object",
                      "properties": {
                        "amount": {
                          "type": "number",
                          "description": "The total amount of the loan"
                        }
                      }
                    }
                  }
                }
              },
              "savings": {
                "type": "object",
                "properties": {
                  "totalSavingsAmount": {
                    "type": "number",
                    "description": "Current total savings amount"
                  },
                  "savingsDetails": {
                    "type": "object",
                    "additionalProperties": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "amount": {
                            "type": "number",
                            "description": "Total amount of savings account"
                          },
                          "description": {
                            "type": "string",
                            "description": "The description of the savings accounts"
                          }
                        }
                      }
                    }
                  }
                }
              },
              "accounts": {
                "type": "object",
                "properties": {
                  "checking": {
                    "type": "array",
                    "items": {
                      "$ref": "#/components/schemas/Account"
                    }
                  },
                  "savings": {
                    "type": "array",
                    "items": {
                      "$ref": "#/components/schemas/Account"
                    }
                  },
                  "loans": {
                    "type": "array",
                    "items": {
                      "$ref": "#/components/schemas/Account"
                    }
                  }
                }
              }
            }
          }
        }
      },
      "Account": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "A unique identifier for the account"
          },
          "userId": {
            "type": "string",
            "description": "A unique identifier for the user"
          },
          "providerId": {
            "type": "string",
            "description": "A unique identifier for the provider"
          },
          "connectionId": {
            "type": "string",
            "description": "A unique identifier for the connection"
          },
          "externalId": {
            "type": "string",
            "description": "An optional id that can be given to a payment"
          },
          "status": {
            "type": "string",
            "description": "The status of the account"
          },
          "collateralsInvolved": {
            "type": "boolean",
            "description": "Indicates whether the account is involved in collateral"
          },
          "includeFakeProviders": {
            "type": "boolean",
            "description": "If true, this payment can be used for testing purposes vs. a fake bank provider"
          },
          "originalPaymentId": {
            "type": "string",
            "description": "The id of the refund payment"
          },
          "refundedAmount": {
            "type": "number",
            "description": "The amount of the refund"
          },
          "originalPaymentUserId": {
            "type": "string",
            "description": "The id of the user who made the original payment"
          },
          "scaOAuth": {
            "type": "string",
            "description": "The url forwarding the user to the provider to complete the payment"
          },
          "isRefund": {
            "type": "boolean",
            "description": "If true, this payment is a refund"
          },
          "accountNumber": {
            "type": "string",
            "description": "A bank account number"
          },
          "product": {
            "type": "string",
            "description": "The product of this account"
          },
          "parsedAccount": {
            "type": "object",
            "description": "Account iban number parsed",
            "properties": {
              "bank": {
                "type": "string",
                "description": "Bank number"
              },
              "branch": {
                "type": "string",
                "description": "Branch number"
              },
              "number": {
                "type": "string",
                "description": "Account number"
              }
            }
          },
          "accountType": {
            "type": "string",
            "description": "The type of the account"
          },
          "creditStatus": {
            "type": "string",
            "enum": [
              "deleted",
              "enabled",
              "disabled"
            ],
            "description": "The status of a credit card"
          },
          "cardDueDate": {
            "type": "string",
            "description": "A card due date"
          },
          "currency": {
            "type": "string",
            "description": "The currency of which the account transacts in"
          },
          "ownerInfo": {
            "type": "object",
            "description": "Information of the account owner",
            "properties": {
              "nationalId": {
                "type": "string",
                "description": "Legal national ID"
              },
              "fullName": {
                "type": "string",
                "description": "Legal full name"
              }
            }
          },
          "accountName": {
            "type": "string",
            "description": "The name of the account"
          },
          "balances": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/Amount"
            }
          },
          "interst": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/Interest"
            },
            "description": "Interest information, only for savings and loans"
          },
          "relatedDates": {
            "type": "object",
            "properties": {
              "contractAvailabilityDate": {
                "type": "string"
              },
              "contractEndDate": {
                "type": "string"
              },
              "contractStartDate": {
                "type": "string"
              }
            }
          },
          "usage": {
            "type": "string",
            "description": "The type of usage of the account. Private or business"
          },
          "creditLimit": {
            "type": "number",
            "description": "The credit limit of the account"
          },
          "transactions": {
            "type": "number",
            "description": "Number of transactions the account has"
          },
          "applicableFees": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/AccountApplicableFees"
            }
          },
          "securityPositions": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/SecurityPosition"
            }
          },
          "securityOrders": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/SecurityOrder"
            }
          },
          "loanType": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/LoanType"
            }
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
      "Interest": {
        "type": "object",
        "properties": {
          "rate": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "precentage": {
                  "type": "number",
                  "example": 4.5
                }
              }
            },
            "description": "Array of the different interest rates"
          },
          "type": {
            "type": "string",
            "description": "The type of the interest. FIXD or INDE"
          },
          "relatedIndecies": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "index": {
                  "type": "string",
                  "description": "The index of the variable interest, if there is one"
                },
                "additionalInformation": {
                  "type": "string"
                }
              }
            }
          },
          "currency": {
            "type": "string",
            "description": "The amount currency",
            "example": "ILS"
          }
        }
      },
      "FeeRules": {
        "type": "object",
        "properties": {
          "percentage": {
            "type": "number"
          },
          "minimumAmount": {
            "$ref": "#/components/schemas/Amount"
          }
        }
      },
      "AccountApplicableFees": {
        "type": "object",
        "properties": {
          "typeProprietary": {
            "type": "string"
          },
          "applicableFrom": {
            "type": "string"
          },
          "additionalInformation": {
            "type": "string"
          },
          "applicableTo": {
            "type": "string"
          },
          "feeRules": {
            "type": "array",
            "items": {
              "$ref": "#/components/schemas/FeeRules"
            }
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
      "LoanType": {
        "type": "string",
        "enum": [
          "RETAIL_LOAN",
          "MORTGAGE",
          "CREDIT_LIMIT",
          "GUARANTEE",
          "CREDIT_CARD",
          "CHEQUE_DISCOUNTING",
          "FUTURE_PAYMENT"
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