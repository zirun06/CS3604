"""Generation and repair guidance for the storefront requirement tree."""

SUITE = '1cd020c5debbe77d017af7fbd8509b0036d5c079f6ad396c7805d2a84455a487'

BACKEND_GUIDANCE = """
Storefront integration requirements:
- Express 5 types route parameters as string or string array. Normalize each
  parameter at the request boundary before passing it to a string-only function.
- Build one stable session, cart, and checkout flow. Visiting product pages or
  initializing a cart must reuse the active session. Sign-in and registration must
  keep the authenticated user visible through product, cart and checkout navigation.
- Seed the declared catalog, variant combinations, verified customers, and historical
  orders/wishlist memberships from the input. Create new addresses, carts and orders
  through normal application operations, with all private rows scoped to their owner.
- Return complete catalog objects, including real numeric prices and default
  variant fields, from homepage and listing endpoints. Serialize the projected
  products instead of the original ID/name lookup rows.
- Key cart lines by the selected combination, not just by product. Recompute line,
  subtotal, shipping and total on the server after quantity changes or removal.
  Keep checkout edits reversible until confirmation. Confirm only after terms are
  accepted; save the purchased lines and selected delivery address with the order,
  then clear the cart in the same transaction.
- Keep checkout API field names consistent across read, update and confirmation.
  Avoid duplicate address records on an identical retried save, without treating
  different addresses with the same alias as the same record.
"""

FRONTEND_GUIDANCE = """
Storefront integration requirements:
- Place the Logo, Sign in/My account, Cart, searchbox, and category entries inside
  the Global navigation landmark. Use the same navigation across all screens. Keep
  Sign in as a navigation link and the login form's submit as a button. Accessible
  names for Cart and wishlist links remain stable when visual counts change.
- Label the newsletter field "Newsletter email" so it is distinct from the
  account form's "Email". Use one page heading with the exact product name on
  its detail page, and give other sections distinct headings.
- Make the CLOTHES submenu usable on hover and keyboard focus, with Men and Women
  as links. Keep exact named product-card regions and show hover actions without
  clipping them. Quick view must open and close without navigating away.
- Keep the add-to-cart confirmation, cart, and checkout as distinct steps. Carry
  the selected variant and quantity through them. Keep the named cart summary and
  its totals visible even after removing the last product. Commit direct quantity
  edits and refresh totals from the server.
- Complete the actual signed-in checkout path: personal information, shipping
  address, separate invoice address when requested, delivery, payment and order
  confirmation. Reopening a step preserves the values already entered. Show the
  saved order reference, line items, delivery address and totals on confirmation.
- Use named checkout step regions (Personal Information, Addresses, Shipping
  Method, Payment) and keep Continue scoped to the active step. Preserve address
  and delivery selections when editing a completed step. Render named money
  regions and the single corresponding amount inside each summary.
- Reuse one AddressForm in account and checkout. Country is a native select
  labelled Country, with China as a selectable option. Text fields keep their
  specified labels. Delivery/invoice radios are named by address alias alone;
  display street and edit controls separately from the radio's accessible name.
- Implement a shared Money component: one region named for its amount, containing
  only the formatted current monetary value. Labels sit outside that region.
  Use it for Sale price, Regular price, Unit price, Subtotal, Items subtotal,
  Shipping and Total. Do not nest identically named amount regions.
- Render the exact same card component for homepage and catalog products, with
  a real product image and scoped Quick view. Keep the CLOTHES submenu open while
  keyboard focus is inside it. Collapse completed checkout inputs while keeping
  their summaries and edit controls visible.
- Use shared layout, card and modal classes. Make controls reachable and dialogs
  scrollable. Follow the input for exact labels. Read the supplied backend routes
  and response objects before writing requests. Keep navigation mounted while
  loading data and display API errors. Check price fields before formatting;
  correct a missing field at the API contract instead of inventing a zero price.
- Use literal Unicode icons or JavaScript strings, with valid JSX expressions.
  Return complete nonempty source strings for all requested files on every retry.
"""

REPAIR_GUIDANCE = """
For the storefront, address shared blockers before individual details. If unrelated
scenarios fail at the same navigation entry, session transition, add-to-cart action,
or checkout step, trace that entry from the UI to the API and fix the shared cause.
When diagnostics show two matching controls, inspect both rendered elements. For
example, disambiguate the newsletter's actual associated label from the login
form's Email label. Changing the placeholder alone leaves the label unchanged.
Keep the login form's required label and the newsletter's functionality.
Use the supplied page snapshots to distinguish a missing control from one hidden
by styling. Keep active sessions, selected variants, and owner isolation intact.
Country must be a native select in every address form, not just the checkout form.
Amount regions must contain one monetary value, with the label outside the region.
Fix the common rendering component before patching its individual callers.
Use short exact old_content anchors copied verbatim from the supplied source.
"""


from infrastructure.tasks.profile import TaskProfile
from infrastructure.tasks import prompts

PROFILE = TaskProfile(
    key="prestashop", suite=SUITE,
    backend_prompt=prompts.BACKEND_PROMPT + BACKEND_GUIDANCE,
    frontend_prompt=prompts.FRONTEND_PROMPT + FRONTEND_GUIDANCE,
    report_profile="prestashop", frontend_mode="split",
    style_output_tokens=10000, style_attempts=2, build_repair_attempts=2,
    transient_retries=2, rollback_failed_candidates=True,
    allow_zero_progress=True,
    acceptance_attempts=4, repair_failure_limit=6, repair_edit_retries=1,
    style_guidance="Keep CSS under 24000 characters with shared layout, form, card and dialog selectors. "
                   "Do not inline images, fonts or application code. Avoid per-product selectors.",
    route_parameter_repair=True, repair_guidance=REPAIR_GUIDANCE,
)
