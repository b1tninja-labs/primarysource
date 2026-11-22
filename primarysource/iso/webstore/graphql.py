"""The webstore's GraphQL endpoint, `POST /webstore/graphql`.

The documents below are the ones the capture shows the webstore front end sending, trimmed to what this client
reads. Only `processFreeOrder` changes anything; it is called from `basket.py`, behind its guards. The profile,
address, payment and order-line mutations the front end also sends (`updateUserDetails`, `updatePurchaseOrderNumber`,
`deleteOrderItem`, `startUserSession`) are described in docs/iso-webstore.md and deliberately not implemented.
"""

from __future__ import annotations

import json
from typing import Any

from primarysource.errors import LibError
from primarysource.iso.webstore.session import BASE, WebstoreSession

ENDPOINT = f"{BASE}/webstore/graphql"

CURRENT_DATA = """query currentData {
  currentUser {
    username
    displayName
    preferredLanguage
    roles
    hasCredentials
  }
}"""

_ITEM_ID = """fragment ItemIdFields on ItemId {
  priceBookId
  ratePlanId
  formatId
  editionId
  instanceId
  locked
}"""

_ORDER_ITEM = """fragment OrderItemFields on OrderItem {
  description
  language
  format
  editionId
  edition
  paymentFrequency
  listPrice
  unitPrice
  currency
  quantity
  total
  licenses
  follow
  followable
  media
  appliedDiscount
  quantityDiscount
  orderSizeDiscount
  discretionaryDiscount
  isShippingChargeLineItem
  itemId {
    ...ItemIdFields
  }
  lockedForUser
}"""

_ORDER = """fragment OrderFields on Order {
  tenantId
  ownerId
  orderNumber
  type
  orderStatus
  accountId
  vatNumber
  priceBookId
  continueShoppingUrl
  currency
  totalShippingCharge
  totalTax
  total
  discountQuantity
  discountAmount
  discountAccount
  shippingMethod
  shippingMethodLocked
  hasSubscriptionProducts
  items {
    ...OrderItemFields
    itemId {
      ...ItemIdFields
    }
  }
  checksum
}"""

CURRENT_ORDER = """query currentOrder {
  currentOrder {
    ...OrderFields
  }
}

""" + "\n\n".join((_ORDER, _ORDER_ITEM, _ITEM_ID))

_SUMMARY = """fragment OrderSummaryFields on OrderSummary {
  orderNumber
  accountId
  paymentMethodType
  orderStatus
  purchaseOrderNumber
  total
  totalTax
  totalShippingCharge
  currency
  items {
    productName
    productType
    productCode
    language
    format
    media
    editionYear
    edition
    quantity
    licenses
    unitPrice
    description
    requiresShipping
  }
  messages
}"""

ORDER_SUMMARY = (
    """query orderSummary($orderId: String!) {
  orderSummary(orderId: $orderId) {
    ...OrderSummaryFields
  }
}

"""
    + _SUMMARY
)

PROCESS_FREE_ORDER = (
    """mutation processFreeOrder(
  $isShareDataAccepted: Boolean!
  $isEmailNotificationAccepted: Boolean!
  $isWithdrawalConsentAccepted: Boolean!
  $orderChecksum: String!
) {
  processFreeOrder(
    isShareDataAccepted: $isShareDataAccepted
    isEmailNotificationAccepted: $isEmailNotificationAccepted
    isWithdrawalConsentAccepted: $isWithdrawalConsentAccepted
    orderChecksum: $orderChecksum
  ) {
    ...OrderSummaryFields
  }
}

"""
    + _SUMMARY
)

TENANT_OBP_URL = """query tenantObpUrl {
  tenantObpUrl
}"""


class GraphQLClient:
    """Posts one operation and returns its `data`. Errors become `LibError`; nothing is retried."""

    def __init__(self, session: WebstoreSession) -> None:
        self._session = session

    def execute(self, operation: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps({"operationName": operation, "variables": variables or {}, "query": query}).encode("utf-8")
        response = self._session.request(
            "POST",
            ENDPOINT,
            headers={"Content-Type": "application/json", "Accept": "application/json", "Origin": BASE},
            body=body,
            follow=False,
        )
        if response.status in (401, 403):
            raise LibError(f"{operation}: HTTP {response.status}", "sign in again (auth.sign_in)")
        if response.status != 200:
            raise LibError(f"{operation}: HTTP {response.status}", "retry later")
        try:
            payload = json.loads(response.body)
        except ValueError as exc:
            raise LibError(
                f"{operation}: the answer is not JSON", "retry later; the session may have expired"
            ) from exc
        if not isinstance(payload, dict):
            raise LibError(f"{operation}: unexpected answer shape", "retry later")
        errors = payload.get("errors")
        if errors:
            first = errors[0].get("message", "") if isinstance(errors[0], dict) else ""
            raise LibError(f"{operation}: the webstore reported an error: {str(first)[:160]}", "nothing was changed")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise LibError(f"{operation}: the answer has no data", "retry later")
        return data
