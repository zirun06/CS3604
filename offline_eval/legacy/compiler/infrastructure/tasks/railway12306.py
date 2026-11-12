"""Railway-only generation and recovery contracts, based on the Stack Overflow v2 release."""

from infrastructure.tasks.profile import TaskProfile
from infrastructure.tasks import prompts


BACKEND_GUIDANCE = """

12306 implementation priorities:
- The template installs express.json(), NOT cookie-parser. Parse the Cookie header
  in registerApis before using req.cookies, or use your own header reader on EVERY
  session/recovery/private route. A cookie set by login must authenticate GET session
  and private APIs on the very next request and after reload. Never replace a valid
  signed-in cookie with an anonymous session while loading public catalogs.
- declared_railway_world is an index of actual Given records. Shared text tokens in
  requirements_yaml refer to the full original text in shared_text_blocks; expand
  their meaning. Do not omit constraints because their text is referenced.
- Merge all verified-account records and specific_identity attributes. Register,
  login, password recovery/change and profile updates operate on the same saved
  identity. Do not seed duplicate registration targets or extra frequent passengers:
  those passengers/current orders are created through UI. Automatically create the
  protected account-holder passenger; seed the one declared completed history order.
- Published services are identified by route/date/train number. Merge the union of
  date views, not just the first encountered seed. Never duplicate the same service
  per account. Business-seat inventory is independently allocated per booking account
  and journey, locked only by Confirm, released by cancellation/refund/expiration.
  Count active locks/paid allocations and verify ownership within SQLite transactions.
- Place order validates and prepares confirmation without creating an order. Confirm
  alone persists it. Return the created order ID directly; do not force the UI to
  discover it by selecting the first unpaid order. Save all chosen passengers, ticket
  types/classes, fare and stable journey IDs. Pay/cancel/refund persist transitions;
  cancelled orders have no Pay action; unpaid orders never enter Upcoming trips.
- Use the advancing Asia/Shanghai clock anchored at 2026-07-21T00:00:00+08:00,
  including in local validation when the host date differs. Expose server now and
  expires_at in payment data; remaining time derives from that clock, not a fresh
  20-minute client timer on every load. Keep calendar range, departure classification
  and refund deadlines on that clock. Refund both paid eligible future journeys.
- Search validates missing route fields; filter by actual route/date before type,
  stations, departure interval and ordering. Transfer plans require at least 30 minutes
  waiting and both real segments. Preserve day offsets and total durations.
- Use exact validation messages, including empty confirmation as a required field.
  Password-reset identity verification is cookie-bound and cannot reset an unrelated
  account. Every profile/passenger/order mutation is scoped to the signed-in owner.
"""
FRONTEND_GUIDANCE = """

12306 high-impact UI contracts:
- Treat shared_text_blocks references as full original requirement text. Implement
  all requirements and scenarios, not just the unique unreferenced paragraphs.
- Sign Out is a LINK, not a button. Render an actual anchor with a logout handler
  that prevents default, awaits the API and updates session state. Login establishes
  the same session used by public header, personal center and booking quick login.
  Await session bootstrap before protected redirects; preserve identity after reload.
- Every control needs an explicit label: use htmlFor/id or aria-label on the actual
  select/input. Do not rely on a wrapping label whose text includes all select options.
  Nationality defaults to Please select; China is a real option. Use shared labelled
  controls in registration, passenger, booking, security and order filters. Native
  browser validation must not swallow the specification's custom error messages.
- In train, order and passenger table cells, wrap the identity itself in its own
  span: <td><span>{train.number}</span><div>station metadata</div></td>. Never concatenate
  G1001 directly with Shanghai. Each visible train row has one business identity and
  Book belongs inside that row; omit filtered-out rows rather than hiding stale data.
- Ticket search has From/To placeholders, station buttons with full bilingual names,
  a labelled Date textbox and a real calendar with YYYY-MM-DD buttons. Clicking date
  applies that value; results Date editing/Search and the date bar both reload data.
  Use server benchmark clock/date; keep disabled past/out-of-range dates correct.
- The personal menu is navigation named Personal center menu. Use links Order center,
  Information management and Personal with their specified children and casing.
  Order tabs are tabs with aria-selected. Selected rows and filters stay in their
  owning table/region. Tables need header and row/cell semantics, not generic divs.
- Use one persistent PersonalLayout inside the existing auth guard on EVERY personal
  route, including orders, profile, security and passengers. The complete menu stays
  visible after clicking parent links and after reload. Order center -> Ticket orders;
  Personal -> User information, Account security, Verify mobile number; Information
  management -> My Passengers. Each parent AND child is a link, never summary/button.
  Do not mount the menu solely inside the personal-center landing component. Keep
  a small named menu/layout component so its structure can be independently verified.
- Booking has region Train Information and heading Train Information:, a frequent
  passenger checkbox list and named table Booking passengers. Selecting a checkbox
  creates one row with unchanged passport identity. Give row selects exact labels
  Ticket class / Ticket type; Delete only removes that selection. Place order opens
  the named confirmation dialog; Edit preserves selection, Confirm alone submits.
- Payment uses the returned created ID, persisted lock expiry and server now; Payment
  countdown contains only MM:SS, decreases and survives reload. Keep Order details
  and Payment information scopes and display exact fares for the selected class.
- Quick Guide's More link must be named exactly More, without a decorative > in its
  accessible name. Transfer articles show each segment train number separately and
  correct prices. Travel guide dropdown categories each have four real question
  links, and their question anchors load nonempty matching content.
- Keep the application concise through shared native controls, forms, order lists
  and menus. Do not spend output tokens on long comment banners. Finish all flows.
"""
REPAIR_GUIDANCE = """

12306: fix shared login/session, labelled registration/passenger controls and train
identity before isolated downstream scenarios. If Sign Out is missing, inspect the
actual cookie roundtrip AND its role: valid login can still fail if it is a button
rather than the required link. The base template has no cookie parser. Never allow
arbitrary usernames to authenticate to hide missing seed data. Treat exact-name
failures as semantic issues: select option text must not pollute the field label,
and station metadata must not be concatenated with a train identity. Fix the shared
field/table component instead of individual scenario values. Follow the relevant
prerequisite requirement as well as the final failing requirement. Preserve passed
flows, ownership and persisted state; never special-case generated passenger names.
"""

PROFILE = TaskProfile(
    key="railway12306", suite="2a1b7d66d9e2678313023533fcf831e1434a07aee78274714728495229d5161b",
    backend_prompt=prompts.BACKEND_PROMPT + BACKEND_GUIDANCE,
    frontend_prompt=prompts.FRONTEND_PROMPT + FRONTEND_GUIDANCE,
    report_profile="railway12306", frontend_mode="split", railway_contract=True,
    railway_navigation_gate=True,
    style_output_tokens=10000, style_attempts=2, build_repair_attempts=2,
    transient_retries=1, rollback_failed_candidates=True,
    adaptive_repairs=True, acceptance_attempts=3, repair_failure_limit=2,
    repair_edit_retries=1, retry_invalid_edits=True,
    repair_dependencies=(('login', 'REQ-2.2.2'), ('register', 'REQ-2.1.2'),
        ('center', 'REQ-5.1.1'), ('section', 'REQ-5.1.1'),
        ('search', 'REQ-3.2'), ('booking', 'REQ-8.2.1'),
        ('confirmation', 'REQ-8.3.2'), ('payment', 'REQ-8.4'),
        ('passengerPage', 'REQ-7.1'), ('addPassenger', 'REQ-7.2'),
        ('orderSetup', 'REQ-8.3.3.1')),
    style_guidance="Keep CSS under 24000 characters. Use shared railway tables, "
        "forms, menus and dialogs; do not alter ARIA semantics or hide controls.",
    repair_guidance=REPAIR_GUIDANCE,
)
