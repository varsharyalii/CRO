"""Hand-authored funnel-step → component/file map (codebase-aware grounding).

Keys are the opportunity labels produced by scoring.py:
  - buyer-funnel edges: "<upstream>-><downstream>" (adjacent steps)
  - liquidity metrics:  "liquidity:<metric_name>"

Built from the event↔component map in jhaazi-frontend's posthog-setup-report.md.
Paths are relative to JHAAZI_FRONTEND_PATH and verified to exist by the grounding
harness (and by tests/test_surface_map.py).
"""

from __future__ import annotations

from .schemas import Surface

# Real component paths (jhaazi-frontend uses src/features/<area>/components/...).
_MARKETPLACE_FEED = "src/features/marketplace/components/marketplace-feed.tsx"
_DROP_CARD = "src/features/marketplace/components/drop-card.tsx"
_DROP_LANDING = "src/features/drops/components/drop-landing-screen.tsx"
_ITEM_DETAIL = "src/features/items/components/item-detail-screen.tsx"
_SELLER_STOREFRONT = "src/features/seller/components/seller-storefront-screen.tsx"
_SHIPPING_CHECKOUT = "src/features/checkout/components/shipping-checkout-screen.tsx"
_PAYMENT_RETURN = "src/features/checkout/components/payment-return-screen.tsx"
_CHECKOUT_AUTH = "src/features/auth/components/checkout-auth-screen.tsx"
_QUICK_AUTH = "src/features/auth/components/quick-auth-sheet.tsx"
_SELLER_APPLICATION = "src/features/seller-applications/components/seller-application-form.tsx"
_STORE_SETUP = "src/features/seller/components/store-setup-form.tsx"
_CLAIMS_API = "src/features/claims/client-api.ts"

SURFACE_MAP: dict[str, Surface] = {
    # --- buyer funnel (adjacent edges) ---------------------------------------
    "drop_view->marketplace_view": Surface(
        files=[_DROP_LANDING, _MARKETPLACE_FEED],
        note="TOP CROSS-SELL OPPORTUNITY: most users deep-link to a drop from "
        "Instagram and never reach the marketplace feed, so they never discover "
        "OTHER sellers. Add 'explore more sellers / shop the marketplace' surfaces "
        "to the drop landing page to convert drop-landers into explorers.",
    ),
    "drop_view->drop_card_select": Surface(
        files=[_DROP_LANDING, _DROP_CARD],
        note="Drop landing → tapping a drop/item card. Card surfacing, CTA prominence.",
    ),
    "drop_card_select->item_view": Surface(
        files=[_DROP_CARD, _ITEM_DETAIL],
        note="Card tap → item detail. Item rendering, image load, CTA visibility.",
    ),
    "item_view->claim_attempt": Surface(
        files=[_ITEM_DETAIL],
        note="Item detail → tapping claim. Claim CTA clarity, price/availability, urgency.",
    ),
    "claim_attempt->claim_success": Surface(
        files=[_ITEM_DETAIL, _CLAIMS_API],
        note="Claim conflicts (sold_out / limit / already_claimed). See jz_claim_conflict.",
    ),
    "claim_success->checkout_intent": Surface(
        files=[_ITEM_DETAIL],
        note="Claimed → proceed to checkout. Hold timer clarity, next-step prominence.",
    ),
    "checkout_intent->checkout_submit": Surface(
        files=[_SHIPPING_CHECKOUT, _CHECKOUT_AUTH, _QUICK_AUTH],
        note="Checkout intent → shipping form submit. PRIME SUSPECT: the auth/OTP "
        "gate interrupts here (checkout-auth-screen / quick-auth-sheet).",
    ),
    "checkout_submit->checkout_created": Surface(
        files=[_SHIPPING_CHECKOUT],
        note="Shipping submit → booking created. Address validation, server errors.",
    ),
    "checkout_created->payment_return": Surface(
        files=[_SHIPPING_CHECKOUT, _PAYMENT_RETURN],
        note="Booking → payment gateway → return. Gateway handoff, deep-link return.",
    ),
    "payment_return->purchase_confirmed": Surface(
        files=[_PAYMENT_RETURN],
        note="Payment-return failures. return_status / failure_reason; client-side "
        "localStorage dedup may undercount (see Phase A server-side capture).",
    ),
    # --- liquidity metrics ----------------------------------------------------
    "liquidity:claim_to_paid": Surface(
        files=[_ITEM_DETAIL, _SHIPPING_CHECKOUT],
        note="Claimed-but-never-paid. Hold-timeout UX, checkout speed, auth friction.",
    ),
    "liquidity:expired_claim_rate": Surface(
        files=[_ITEM_DETAIL, _CLAIMS_API],
        note="Holds that expire/release before payment. Hold duration, reminders, "
        "checkout urgency. (Explicit jz_claim_expired lands in Phase A.4.)",
    ),
    "liquidity:sell_through": Surface(
        files=[_SELLER_STOREFRONT, _DROP_LANDING],
        note="Seller-level sell-through proxy. Storefront merchandising, drop "
        "scheduling, inventory surfacing.",
    ),
    "liquidity:seller_activation": Surface(
        files=[_SELLER_APPLICATION, _STORE_SETUP],
        note="apply → setup → first drop activation drop-off.",
    ),
}

DEFAULT_SURFACE = Surface(
    files=[_MARKETPLACE_FEED], note="Unmapped opportunity; review manually."
)


def surface_for(opportunity_label: str) -> Surface:
    return SURFACE_MAP.get(opportunity_label, DEFAULT_SURFACE)
