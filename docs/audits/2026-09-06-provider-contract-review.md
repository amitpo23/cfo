# Public provider contract review — 6 September 2026

This evidence supports [MASTER_EXECUTION_PLAN.md](../MASTER_EXECUTION_PLAN.md).
It is a dated review of public documentation, not a live entitlement or production
test. No SUMIT or Open Finance authenticated API was called.

## Product and authentication boundaries

Open Finance's integration platform and Financy share provider infrastructure but
have different customer contracts. Platform credentials and permissions cannot be
inferred from a Financy subscription. Financy's technical API documentation describes
OAuth client ID, client secret and user ID for paid API plans; its remote MCP token
is a different, restricted credential. Rezef does not add an MCP integration.
The local connection now records the selected product and Financy plan explicitly.
Unverified product configuration blocks writes. These declarations do not establish
that a particular customer's bank or provider contract permits the requested action.

Official sources: [platform index](https://docs.open-finance.ai/llms.txt),
[Financy index](https://docs-financy.open-finance.ai/llms.txt),
[Financy authentication](https://docs-financy.open-finance.ai/docs/authentication),
[Financy core concepts](https://docs-financy.open-finance.ai/docs/core-concepts).
The saved index evidence contains 160 platform entries and 37 Financy entries
(139 and 20 reference entries respectively). Duplicates, versions and guides make
these unsuitable as a denominator for unique API or business capability coverage.

All **20 Financy reference entries** in that index were subsequently fetched and
their OpenAPI definitions inspected for methods, effective server/path composition,
OAuth scopes, required inputs and response codes. The
[reference contract evidence](evidence/2026-09-06-financy-reference-contracts.json)
records each source hash and its current local product-policy disposition. This is
a defined reference-page inventory, not proof of 20 completed business workflows.

The payment API reference describes completion-based fees for new ILS payments:
Starter 0.4% with a ₪0.50 minimum; Pro 0.3% with a ₪0.50 minimum and ₪3.50 maximum;
Ultra 0.2% with a ₪0.50 minimum and ₪2.70 maximum. It excludes failed/cancelled,
sandbox, ATM and non-ILS cases from that fee description. These are documented
conditions as checked, not a verified quote for the owner's contract.
[Official payment reference](https://docs-financy.open-finance.ai/reference/createpayment).

Two documentation discrepancies remain explicit: the direct-initiation reference
spells its scope `create:peyments`, while hosted creation uses `create:payments`;
and debtor-field descriptions include requirements stronger than the enclosing
schema's required-field list. The implementation does not invent a new scope or a
debtor identity to resolve either discrepancy. Owner/provider contract verification
is required before live use. [Direct initiation](https://docs-financy.open-finance.ai/reference/initiatepayment).

Financy requires at least one payment party to be a connected account. The account
number used for this check must be actual provider account evidence. The normalized
account model now retains `provider_account_number`; it does not infer a bank account
number from an account resource ID. Financy connection creation remains a portal
step. The existing platform connection adapter is blocked for Financy.

## Payment and event semantics

Request creation/readback, bank authorization, debtor settlement, creditor receipt,
accounting documentation and official posting are separate evidence claims.
Acceptance states such as ACTC/ACWC/ACSP do not establish receipt of money. A supplier
request can therefore be verified as a request while the bill remains unpaid.
An authenticated callback updates provider observations, not a financial balance.
Unknown states, conflicting final observations and missing identities remain review
items; they cannot supply invented financial relationships.

Official sources: [Financy payment statuses](https://docs-financy.open-finance.ai/docs/payment-statuses),
[Financy payment webhooks](https://docs-financy.open-finance.ai/docs/payment-webhooks),
[platform event types](https://docs.open-finance.ai/docs/webhooks-event-types).
The reviewed callback configuration supports custom shared headers and OAuth.
No undocumented HMAC signature protocol is asserted. Rezef's receiver requires its
configured shared secret. Delivery configuration must still be verified by the owner.

Financy account documentation separately identifies `id`, `connectionId`,
`accountNumber` and parsed bank/branch/number fields. Its error guide distinguishes
plan restrictions, account limits, insufficient refresh credits and revoked or
expired connections. Retrying unchanged does not repair these conditions. Monetary
writes remain protected against replay even where generic provider guidance suggests
retrying server errors. [Accounts and balances](https://docs-financy.open-finance.ai/docs/accounts-balances),
[error contract](https://docs-financy.open-finance.ai/docs/errors).

SUMIT's latest saved Swagger, `sumit_swagger_v1_2026-08-19.json`, contains 84 paths.
Its trigger subscription schema does not establish a custom-header/signature delivery
contract. SUMIT callback authentication compatibility consequently remains a provider
or configuration gap. A secret-less receiver is disabled rather than accepted.

## Additional reviewed provider operations

| Operation | Documented boundary | Rezef consequence |
|---|---|---|
| Financy connection refresh | Public reference specifies `POST /chat/chat/connections/refresh`, paid-plan access and 20 credits per accepted refresh; an already-running response is separate | No new refresh adapter; chat and screen reads never trigger it; existing quotas remain enforced |
| Financy transaction detail | SK is the detail-route key, separately from transaction `id`; `#` must be encoded; `accountId` is the account relation; charged amounts carry direction | Preserve exact source values; do not infer account relationships from account-number similarity |
| Periodic payment | ACTC/ACWC can establish an active standing order, not settlement of every installment; start must be future; documented frequencies and last-day semantics are rail-specific | Existing recurring/card scheduling cannot stand in for a verified bank installment lifecycle |
| Bulk bank payment | `/v2/pay/open-banking-init` with bulk payload, provider selection, allowed creditors, ILS and bank authorization; execution date/time fields are mutually exclusive | Multi-bill supplier bulk adapter remains a required completion; a list of bills is not bank acceptance |
| Mandate cancellation | 202 can require further bank authorization, while 204 is a cancellation response; the reference's server/path version composition needs confirmation | Do not silently rewrite ambiguous version paths or treat an approval URL as completed cancellation |
| Refund | Response can create a new refund payment ID and authorization URL | No claim that money was returned until separate outcome evidence exists |

Official sources: [Financy refresh](https://docs-financy.open-finance.ai/reference/refreshconnections),
[Financy transactions](https://docs-financy.open-finance.ai/docs/transactions),
[periodic payments](https://docs.open-finance.ai/docs/periodic-payments-sandbox),
[bulk payments](https://docs.open-finance.ai/docs/bulk-payment-initialization),
[mandate cancellation](https://docs.open-finance.ai/reference/delete_v2-mandates-resourceid),
[refund](https://docs.open-finance.ai/reference/post_payments-paymentid-refund).
Public examples and sandbox documentation are contract evidence only; no sandbox
or live payment was initiated for this review.

## SUMIT knowledge inventory and remaining discovery

All 12 local help files were mechanically indexed with hashes, article IDs, section
headings and source line references. The inventory contains 968 distinct referenced
article IDs. Older claims of 1,126 articles describe historical collection work and
are not reproduced by this distinct-ID inventory.

The public help-index comparison found 763 linked articles in the available cached
pages, including 161 IDs absent from that local inventory. An HTTP 429 stopped the
crawl. There are 144 discovered collection pages not yet cached. Missing article
bodies have **not** been represented as read, imported or implemented. Resuming the
public discovery requires normal provider availability; no rate-limit workaround
was used. Both business and representative-side knowledge remain in scope.

Evidence: [local corpus inventory](evidence/2026-09-06-sumit-local-kb-index.json),
[partial public comparison](evidence/2026-09-06-provider-public-index.json),
[Open Finance/Financy indexes](evidence/2026-09-06-open-finance-public-index.json),
[business matrix](../provider_business_evidence.json).

## Official books and professional decisions

SUMIT's reviewed batch-create route does not establish batch readback or closure.
Local reconciliation and an open created batch are insufficient evidence of official
posting. Portal-only actions require the authorized operator to preserve source
references and acceptance/closure evidence under the existing runbooks.

The supplier adapter supports owner-reviewed cases where withholding is not required
or a valid exemption has been checked. It neither guesses exemption from a default
contact rate nor implements deduction/remittance accounting. Advances, invoice-receipts,
credit documents, VAT adjustments, assets, annual adjustments and corrective filings
retain their knowledge-base and professional review requirements. The matrix records
these as partial or untested where no complete local business proof exists. Regulatory
output remains subject to the existing three independent verification controls.
