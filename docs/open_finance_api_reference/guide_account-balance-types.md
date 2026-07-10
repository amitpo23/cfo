# Account Balance Types

What each balanceType means in the GET /v2/data/accounts response, broken down by account type.

On every account returned by `GET /v2/data/accounts`, the `balances` array holds one or more balance objects. Each one has a `balanceType` (the kind of balance) and a `balanceAmount` (currency + amount). The same `balanceType` can mean something slightly different depending on the `accountType` (`CHECKING`, `CARD`, `LOAN`, `SAVINGS`). Definitions follow ISO 20022 / Berlin Group logic and exclude credit limits unless `creditLimitIncluded` is `true`.

## Quick reference

| balanceType        | Checking        | Card | Savings | Loan        |
| ------------------ | --------------- | ---- | ------- | ----------- |
| `closingBooked`    | ✅ (mandatory)   | ✅    | ✅       | ✅           |
| `expected`         | ✅               | ✅    | ✅       | ✅           |
| `interimAvailable` | ✅               | ✅    | —       | ✅ (planned) |
| `interimBooked`    | ✅               | ✅    | —       | ✅           |
| `forwardAvailable` | ✅               | —    | —       | —           |
| `openingBooked`    | ❌ not supported | ❌    | ❌       | ❌           |

## Checking accounts (CHECKING)

The richest account type for balances:

* **`closingBooked`** (mandatory) — the most up-to-date book balance at the time of the request. The "official" balance: only finalized, booked entries.
* **`expected`** — booked entries plus known pending items; projects the end-of-day balance if everything settles and no further entry is posted.
* **`interimAvailable`** — available interim balance calculated during the business day, subject to change. Includes only final entries (even if not yet booked), and excludes transactions that were only authorized but not yet booked.
* **`interimBooked`** — interim balance based on credit/debit entries already booked during the calculation window.
* **`forwardAvailable`** — forward available balance at a specified future date. If the bank doesn't publish it online it isn't required; if branch and online values differ, report the value the customer sees online.

## Cards (CARD)

Cards mainly use three balances — `closingBooked`, `interimBooked`, `interimAvailable` — and the meaning depends on the card type:

* **Aggregated card account** — `closingBooked` = the actual balance on the card account; `interimBooked` = transactions accrued across all cards, not yet invoiced (mandatory); `interimAvailable` = available limit / OPEN TO BUY (mandatory).
* **Credit card (deferred debit)** — optional, but if the bank implements it, all three are expected: `closingBooked` = amount charged in the last billing cycle; `interimBooked` = charges accrued since the last billing date that haven't been invoiced yet; `interimAvailable` = open limit available on the specific card / card set.
* **Prepaid card** — `interimAvailable` = current balance on the card (mandatory); `closingBooked` = optional.
* **Immediate debit card** — balances are not relevant (N.R), since the balance is reflected in the current account itself. Only transactions are reported.

## Savings / deposits (SAVINGS)

* **`closingBooked`** — current book balance available for withdrawal (how much is in the deposit now).
* **`expected`** — the deposit's value at maturity / end of period (an estimated balance, e.g. including upcoming interest, for the reference date).

`interimAvailable`, `interimBooked`, `forwardAvailable` and `openingBooked` are not relevant for deposits. (BOI plans to add a future `accumulatedAmount` type — the accumulated savings amount.)

## Loans (LOAN) — including mortgages and overdrafts

**Loan and mortgage:**

* **`closingBooked`** — two uses: (1) current book balance available (how much is left to repay); (2) to reflect the original loan amount — report `closingBooked` with a `referenceDate` of the loan's start date.
* **`expected`** — book balance + transactions expected the same day.
* **`interimAvailable`** (planned) — the original limit with its grant date + the current available limit (for mortgages: reported as part of the main loan resource).
* **`interimBooked`** — interim book balance calculated during the business day from credit/debit entries already booked.

**Overdraft (current-account credit line):** `closingBooked` = the overdraft (actual usage of the line); `expected` = overdraft + transactions expected the same day; `interimAvailable` (planned) = original limit + current available limit.

## Glossary

* **`closingBooked`** — end-of-reporting-period balance: opening balance + all entries booked in the period. Finalized entries only.
* **`expected`** — booked entries + known pending items; projection of the end-of-day balance.
* **`interimAvailable`** — available balance calculated during the business day, subject to change, based on booked entries.
* **`interimBooked`** — like interimAvailable, but for entries already booked.
* **`forwardAvailable`** — available balance for a future date.
* **`openingBooked`** — opening balance (= previous report's closing balance). **Not supported in the Israeli market.**
* **`nonInvoiced`** — cards only; not yet finalized.

> 📘 Full schema
>
> For the complete response structure and all parameters: [Get accounts by user — docs.open-finance.ai](https://docs.open-finance.ai/reference/get_data-accounts).