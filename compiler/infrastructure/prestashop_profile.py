"""Generation and repair guidance for the storefront requirement tree."""

SUITE = '1cd020c5debbe77d017af7fbd8509b0036d5c079f6ad396c7805d2a84455a487'

BACKEND_GUIDANCE = """
Storefront integration requirements:
- When the homepage returns popular products, serialize each product using the
  same catalog projection as a listing card, including its real numeric price
  and default variant. Return the projected array, never the ID/name lookup rows.
- Express 5 types route parameters as string or string array. Normalize each
  parameter at the request boundary before passing it to a string-only function.
- Build one stable session, cart, and checkout flow. Visiting product pages or
  initializing a cart must reuse the active session. Sign-in and registration must
  keep the authenticated user visible through product, cart and checkout navigation.
- Seed the declared catalog, variant combinations, verified customers, and historical
  orders/wishlist memberships from the input. Create new addresses, carts and orders
  through normal application operations, with all private rows scoped to their owner.
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
- Keep navigation mounted when a catalog request fails. Handle loading and error
  states explicitly. Treat API JSON as runtime data and check required price fields
  before formatting. Correct the API contract instead of showing invented prices.
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
- Generate TSX and CSS together, using shared layout, card and modal styles. Make
  controls reachable and dialogs scrollable. Follow the input for exact labels.
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
"""
