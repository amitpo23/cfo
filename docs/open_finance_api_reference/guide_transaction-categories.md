# Transaction Categories

Fetch the categorization taxonomy and understand the main / sub category distribution applied to every transaction.

Every transaction returned by the API is automatically classified into a **main category** and a **sub category** (for example, `TRANSPORT` › `CAR_&_FUEL`). This guide explains how to fetch the full list of categories and how the main → sub distribution is structured, so you can build category pickers, render labels, or validate the values you receive on transactions.

## How categories work

The taxonomy has two levels and is split between expenses and incomes:

* **Main category** – the high-level group, e.g. `FOOD_&_DRINKS`, `TRANSPORT`, `SALARY`.
* **Sub category** – a more specific label nested under a main category, e.g. `GROCERIES`, `RESTAURANT`, `SALARY_OTHER`.

Each main category maps to an ordered list of its sub categories. Expenses and incomes maintain **separate** taxonomies, because the same name can appear in both contexts (for example, `FINANCE` and `OTHER` exist on both sides).

Every transaction carries a category object shaped like this:

```json
{
  "main": "TRANSPORT",
  "sub": "CAR_&_FUEL",
  "categorizedBy": "MCC"
}
```

> 📘 The `main`/`sub` values on a transaction always come from the taxonomy returned by this endpoint. Use the endpoint as the source of truth for valid values and for mapping a `sub` back to its `main`.

## Fetch the list of categories

Send an authenticated `GET` request to the transaction categories endpoint. It takes no parameters and requires the `read:categories` scope.

```bash cURL
curl --request GET \
  --url https://api.open-finance.ai/v2/data/transaction-categories \
  --header 'Authorization: Bearer YOUR_ACCESS_TOKEN'
```
```javascript Node.js
const res = await fetch(
  "https://api.open-finance.ai/v2/data/transaction-categories",
  { headers: { Authorization: `Bearer ${accessToken}` } }
);

const categories = await res.json();
```

The response is identical for every client and contains no user data, so it is safe to **cache** it rather than calling it on every request.

## Response shape

The response contains four objects:

| Field                    | Description                                                           |
| ------------------------ | --------------------------------------------------------------------- |
| `mainCategoriesExpenses` | Expense main categories → list of their sub categories.               |
| `mainCategoriesIncomes`  | Income main categories → list of their sub categories.                |
| `subCategoriesExpenses`  | Expense sub categories → internal matching keywords (debugging only). |
| `subCategoriesIncome`    | Income sub categories → internal matching keywords (debugging only).  |

The `mainCategories*` objects describe the **main → sub distribution**. The `subCategories*` objects expose the internal keywords used by the categorization engine and are mostly useful for debugging — most integrations only need the two `mainCategories*` objects.

```json Example response (truncated)
{
  "mainCategoriesExpenses": {
    "FOOD_&_DRINKS": ["GROCERIES", "RESTAURANT", "COFFEE_&_SNACKS", "ALCOHOL_&_TOBACCO", "BARS", "FOOD_&_DRINKS_OTHER"],
    "TRANSPORT": ["CAR_&_FUEL", "PUBLIC_TRANSPORT", "FLIGHTS", "TAXI", "TRANSPORT_OTHER"],
    "SHOPPING": ["CLOTHES_&_ACCESSORIES", "ELECTRONICS", "HOBBY_&_SPORTS_EQUIPMENT", "BOOKS_&_GAMES", "GIFTS", "SHOPPING_OTHER"],
    "FINANCE": ["INTEREST_RATES", "FINANCE_OTHER", "FEES", "CHECKS_GENERAL", "CREDIT_CARD_EXPENSES", "LOANS", "SAVINGS", "CAPITAL_MARKET"]
  },
  "mainCategoriesIncomes": {
    "SALARY": ["SALARY_OTHER"],
    "PENSION": ["PENSION_OTHER"],
    "REIMBURSEMENTS": ["REIMBURSEMENTS_OTHER"],
    "BENEFITS": ["BENEFITS_OTHER"],
    "FINANCE": ["FINANCE_OTHER"],
    "OTHER": ["OTHER", "UNCATEGORIZED"]
  },
  "subCategoriesExpenses": {
    "RENT": ["..."],
    "MORTGAGE": ["..."]
  },
  "subCategoriesIncome": {
    "SALARY_OTHER": ["..."]
  }
}
```

## Expense main categories

The expense taxonomy contains the following main categories and their sub categories:

| Main category          | Sub categories                                                                                                            |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `HOUSEHOLD_&_SERVICES` | `RENT`, `MORTGAGE`, `COMMUNICATIONS`, `UTILITIES`, `INSURANCE_&_FEES`, `SERVICES`, `HOME`, `HOUSEHOLD_&_SERVICES_OTHER`   |
| `HOME_IMPROVEMENTS`    | `RENOVATION_&_REPAIRS`, `FURNITURE_&_INTERIOR`, `GARDEN`, `HOME_IMPROVEMENTS_OTHER`                                       |
| `FOOD_&_DRINKS`        | `GROCERIES`, `RESTAURANT`, `COFFEE_&_SNACKS`, `ALCOHOL_&_TOBACCO`, `BARS`, `FOOD_&_DRINKS_OTHER`                          |
| `TRANSPORT`            | `CAR_&_FUEL`, `PUBLIC_TRANSPORT`, `FLIGHTS`, `TAXI`, `TRANSPORT_OTHER`                                                    |
| `SHOPPING`             | `CLOTHES_&_ACCESSORIES`, `ELECTRONICS`, `HOBBY_&_SPORTS_EQUIPMENT`, `BOOKS_&_GAMES`, `GIFTS`, `SHOPPING_OTHER`            |
| `LEISURE`              | `CULTURE_&_EVENTS`, `HOBBIES`, `SPORTS_&_FITNESS`, `VACATION`, `LEISURE_OTHER`                                            |
| `HEALTH_&_BEAUTY`      | `HEALTHCARE`, `PHARMACY`, `EYECARE`, `BEAUTY`, `HEALTH_&_BEAUTY_OTHER`                                                    |
| `OTHER`                | `CASH_WITHDRAWALS`, `BUSINESS_EXPENSES`, `KIDS`, `PETS`, `CHARITY`, `EDUCATION`, `UNCATEGORIZED`, `OTHER`                 |
| `FINANCE`              | `INTEREST_RATES`, `FINANCE_OTHER`, `FEES`, `CHECKS_GENERAL`, `CREDIT_CARD_EXPENSES`, `LOANS`, `SAVINGS`, `CAPITAL_MARKET` |

## Income main categories

| Main category    | Sub categories           |
| ---------------- | ------------------------ |
| `SALARY`         | `SALARY_OTHER`           |
| `PENSION`        | `PENSION_OTHER`          |
| `REIMBURSEMENTS` | `REIMBURSEMENTS_OTHER`   |
| `BENEFITS`       | `BENEFITS_OTHER`         |
| `FINANCE`        | `FINANCE_OTHER`          |
| `OTHER`          | `OTHER`, `UNCATEGORIZED` |

## Map a sub category back to its main category

Given a transaction's `sub` value, find its `main` by searching the relevant distribution. Remember to choose the expenses or incomes taxonomy depending on whether the transaction is an expense or an income.

```javascript
function findMainCategory(sub, isIncome, categories) {
  const distribution = isIncome
    ? categories.mainCategoriesIncomes
    : categories.mainCategoriesExpenses;

  return Object.keys(distribution).find((main) =>
    distribution[main].includes(sub)
  );
}

// findMainCategory("CAR_&_FUEL", false, categories) → "TRANSPORT"
```

<br />