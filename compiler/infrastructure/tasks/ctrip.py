"""Ctrip-only state, accessibility and navigation contracts."""

from infrastructure.tasks.profile import TaskProfile
from infrastructure.tasks import prompts


BACKEND_GUIDANCE = """

Ctrip priorities and mandatory public API contracts:
- API middleware belongs under /api only. Do not globally set Content-Type to JSON;
  the template serves HTML and JavaScript/CSS assets after registerApis returns.
  Leave those response MIME types and SPA fallback to the template.
- Express JSON middleware already parses the request body. Never wait for a second
  data/end stream on a consumed request; GET session/health must return promptly.
- Implement GET /api/session -> {authenticated:boolean,user?:{id,...}},
  POST /api/register/send-code {mobile}, /api/register/verify-mobile {mobile,code},
  /api/register/complete {mobile,code,password,confirmPassword},
  /api/login/password {account,password,agree}, and /api/logout.
  Send/verify/complete return 2xx only on success and 4xx for invalid attempts.
- Guest sessions must persist through bootstrap and code requests. Query sessions
  independently of users or LEFT JOIN them; an inner JOIN silently loses null-user
  sessions. An anonymous session is NOT an authenticated user. NeedAuth must check
  a real user ID. Parse cookies because the base template does not install a parser.
- Bind sent codes to current session, target and purpose. Require Send code before
  accepting 123456. Preserve that guest cookie across session lookup, registration
  verification and completion. A different browser or changed target cannot reuse
  it. Completing registration persists the mobile and password for ordinary login.
- declared_ctrip_world is the full explicit Given index. Merge all account views,
  immutable legacy personal records, historical orders and service catalogs by owner
  and business identity. Never seed UI-created mutable records or orders. Public
  booking MU5234 and flight-status MU5234 are different datasets/routes; do not
  collapse them by number alone. Keep all specified historical dates and statuses.
- Advance the shared clock from 2026-07-19T08:00:00+08:00, Asia/Shanghai, including
  local runs on other host dates. Compute payment expiry/countdown using elapsed
  time and persisted expires_at, not a constant now or reset-on-load timer.
- Anonymous flight booking is allowed; bind its orders to the correct guest owner.
  Logged-in orders and saved personal data are strictly per user. Display lifecycle
  Not traveled/Pending review separately from payment state. Order filters and
  reimbursement eligibility use the specified dates and lifecycle constraints.
- Implement full reusable information CRUD with stable IDs, exact record names,
  masked identity lists, preserved original identity in edit forms and scoped bulk
  operations. Keep accepted test identity inputs from the specification; validation
  must not reject explicitly accepted IDs with an invented stricter rule.
- Use exact error wording. Booking preserves route/date/fare/passenger/contact and
  fee services; refresh the saved order after mutations and return its real ID.
"""
FRONTEND_GUIDANCE = """

Ctrip critical UI semantics and shared structure:
- Menu triggers, including shared Dropdown(label) components, must set their
  accessible name explicitly from the real label. Decorative CSS arrows or icons
  must never become part of the names Flights, More services, My account, Log out.
- If pointer enter already opens a menu, the subsequent click must explicitly
  keep it open. This also applies inside a shared Dropdown whose label is a prop
  and whose pointer handler is on the button itself. Do not rely on stale open
  state plus a hover ref to decide whether to toggle closed in the same event.
- Share one reactive authenticated session across the persistent header and pages.
  After password/SMS login, registration and logout, refresh that shared state;
  a mount-only session fetch leaves the header signed out after SPA navigation.
  Never call useLocation above BrowserRouter. Date textbox clicks must open the
  actual date picker, with YYYY-MM-DD as each date button's accessible name.
- Exactly one Global navigation landmark persists on all pages. Ctrip Travel is a
  heading on entry. Flights is a button exposing a Flight status LINK. More services
  is one unique action exposing Reimbursement vouchers and Airport guide. Do not
  duplicate the same global action name in homepage service cards.
- My account is a button opening a role=menu with Orders and Personal center as
  native LINKS. Do NOT set role=menuitem on those two links. Log out explicitly IS
  a menuitem and must retain that role, including hover access. Hover/click cooperate: a
  pointer-enter open must not make the following button click close the dropdown.
- Apply the SAME hover/click rule to Flights and More services. Those triggers
  remain open on the click that follows pointer entry; selecting an existing child
  closes the menu. Keep all directory links and their actual selected-tab routes.
- Render each read-only business field in its own text element, including address,
  contact, invoice identity, masked profile fields and flight-status details. Keep
  labels/separators outside those field elements. Preserve the actual values; do
  not flatten multiple fields into one unstructured string or alter record names.
- Registration success opens password login with a persistent role=status message
  Registration successful, carried in shared or router state until that page renders.
- Airport/city entries and Boarding process are real links to existing routes;
  C is an index-filter button. Render weather city and temperature separately.
  Both regional directory routes select the right tab and expose city/airport links.
  Voucher list items use Record <actual order number>, with all tab data isolated
  to its signed-in owner. View details within Order list is a button action, while
  Pay now may remain a navigation link. Do not invent missing inventory or orders.
- Password login and Verification code login are LINKS, not role=tab buttons. True
  specified tabs elsewhere retain their tab roles and aria-selected. Use explicit
  labels on real form controls; keep the exact casing and placeholder strings.
- Registration agreement -> Send code -> verify -> Set password -> complete is a
  real state machine using the backend guest cookie. Only show Resend code after
  successful send. Preserve form values and password strength as a named region.
- Use heading exactly Flight results and exactly Book flight. Show the selected
  flight number in its own independently identifiable span, separately from the
  heading prefix, and give the heading its exact accessible name. Do not
  append the number to Book flight's accessible heading name.
- Each flight is a listitem named Flight <number> inside Flight list. Show fares
  reveals Economy fare group and its scoped Book button, preserving actual selected
  route/date/fare through reload. Search criteria persist and displayed rows are
  only current results. Sort by actual values and keep dates and fares separate in
  calendar button names. Support all declared city-directory choices.
- Personal center toggles Common information from initially collapsed state, with
  exactly four links Travelers, Contacts, Invoice titles, Addresses. All saved records
  use Record <business name> within their owning list regions; action buttons are
  scoped to the actual saved identity. My information and Account security persist.
- All stated named regions, alerts, radios, checkboxes and tabs must retain exact
  semantics. Date textboxes accept the declared format. Do not add stricter policies
  for unspecified multi-city/time/airport-filter capabilities.
- Payment countdown decreases using a stable saved expiry and server/client elapsed
  time, surviving reload. Keep public flight status/history and airport guides real,
  using supplied observations and deterministic weather instead of external calls.
- Implement compact shared controls and named components without long comment
  banners. Header/navigation must be a small separately named component for repair.
"""
REPAIR_GUIDANCE = """

Ctrip: repair shared prerequisites before downstream symptoms. If registration says
Verification code not sent after Send code, trace the cookie and null-user session
lookup; do not bypass the sent-code rule. If My account links are missing, remove
role=menuitem overrides and fix hover/click closing conflicts. Exact headings Book
flight and Flight results must exist independently of route/flight metadata.
Do not weaken authorization, unique identities or validation to hide failures.
Repair shared record rendering/control semantics before individual generated names.
Preserve existing passed scenarios and correct owner/data boundaries.
"""

PROFILE = TaskProfile(
    key="ctrip", suite="d809eab08e65ed8d641382386afa8808e6b8a963fd111d8ad4fdca3385ef3887",
    backend_prompt=prompts.BACKEND_PROMPT + BACKEND_GUIDANCE,
    frontend_prompt=prompts.FRONTEND_PROMPT + FRONTEND_GUIDANCE,
    report_profile="ctrip", frontend_mode="split", ctrip_contract=True,
    style_output_tokens=10000, style_attempts=2, build_repair_attempts=2,
    transient_retries=1, rollback_failed_candidates=True, adaptive_repairs=True,
    acceptance_attempts=3, repair_failure_limit=2, repair_edit_retries=1,
    retry_invalid_edits=True,
    repair_dependencies=(('openPersonal','REQ-5.1'),('openCommon','REQ-5.1'),
        ('openOrders','REQ-4.1'),('openOrderDetails','REQ-4.1'),
        ('openBooking','REQ-2.12'),('submitBooking','REQ-3.1'),
        ('registerToPassword','REQ-1.6'),('loginOwner','REQ-1.3'),
        ('openStatus','REQ-7.1'),('openVouchers','REQ-8.1')),
    style_guidance="Keep CSS under 24000 characters with shared cards/forms/dialogs. "
        "Do not hide functional controls or change accessible names and roles.",
    repair_guidance=REPAIR_GUIDANCE,
)
