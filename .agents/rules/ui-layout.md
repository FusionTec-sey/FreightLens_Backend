# UI Layout & Viewport Rules

## Core Layout Principle

The application shell (sidebar, top navbar) must remain fixed.
Only the main content area scrolls. Only the table or list within it scrolls when necessary.

```
┌──────────────────────────────────────────────────────────┐
│  Top Navbar (fixed, never scrolls)                       │
├──────────────┬───────────────────────────────────────────┤
│              │  Page Header / Breadcrumb (sticky)        │
│  Sidebar     ├───────────────────────────────────────────┤
│  (fixed,     │  Filters / Search Bar                     │
│  never       ├───────────────────────────────────────────┤
│  scrolls)    │                                           │
│              │  TABLE / CONTENT AREA                     │
│              │  (scrolls independently when needed)      │
│              │                                           │
│              ├───────────────────────────────────────────┤
│              │  Pagination Footer (sticky to bottom)     │
└──────────────┴───────────────────────────────────────────┘
```

---

## Scrolling Rules

### What scrolls
- The main content/table area when content overflows.
- Modal/drawer content area when the modal content is long.
- Long dropdowns within their dropdown container.

### What never scrolls
- The sidebar.
- The top navbar.
- The page header / breadcrumb bar.
- The pagination footer (it sticks to the bottom of the content container).

### Avoid
- Whole-page body scrolling when only the table needs scrolling.
- Nested scrollbars (body scrolling AND a table scrollbar simultaneously).
- `overflow: hidden` used to mask layout problems.
- Fixed heights that clip content unexpectedly.
- Horizontal scrolling of the full page layout (tables may scroll horizontally, page must not).

---

## No KPI Metrics or Summary Cards on Operational Work Screens

Operational work screens (registers, master data listings, transactional tables, work queues, and entry pages) must **never** contain top-level KPI metric cards, analytical overview counters, or high-level status summary cards.

### Rationale:
1. **Vertical Viewport Space is Sacred**: Operational screens exist to perform tasks on tabular data (filtering, inspecting rows, editing status, pagination). KPI cards consume 120px–180px of valuable vertical viewport space, forcing nested scrolling or pushing rows below the fold.
2. **Separation of Concerns**: Analytics and operational processing are distinct workflows. High-level metric tracking belongs on the Executive / Module Dashboard (`/dashboard`).

### Mandatory Rule & Widget Migration Protocol:
- If an operational work screen requires or currently has summary metrics, aggregate numbers, or status breakdown counts:
  1. **Do not render KPI cards on the work screen.**
  2. **Add them as modular widgets in the Dashboard Widget Catalog** in `Backend/Services/dashboard_registry.py` under the appropriate module (`LOGISTICS`, `INVENTORY`, `ORDERS`, etc.).
  3. Implement live calculation in `calculate_dashboard_data()` with multi-tenant row isolation (`org_id`) and permission checks.
  4. Ensure users can place, arrange, and monitor these widgets on their role-based or custom dashboard (`/dashboard`).

### Standard Operational Screen Structure:
```jsx
<div className="flex flex-col h-full overflow-hidden p-4 space-y-4">
  {/* 1. Title and breadcrumb live in the app top bar (see "Document Screens" below).
         The toolbar row holds search, filters, view switch and primary action. */}
  <div className="shrink-0 flex items-center justify-between">...</div>

  {/* 2. Filters & Search Toolbar — Fixed (Search input, dropdown filters, quick toggles) */}
  <div className="shrink-0 flex items-center justify-between gap-3">...</div>

  {/* 3. Table Container — Full-height flex-1 contained scroll */}
  <div className="flex-1 min-h-0 overflow-auto border rounded-2xl">
    <table>...</table>
  </div>

  {/* 4. Pagination Toolbar — Fixed to bottom */}
  <div className="shrink-0">
    <PaginationToolbar ... />
  </div>
</div>
```

---

## Document Screens (RFQ, Vendor Quotes, Purchase Orders, Proformas)

Sections 1 and 2 (title, breadcrumb, no count, no description) apply to **every
screen in the app** except the dashboard, login and pages that are only a
report canvas. Sections 3 to 5 apply to list and entry screens, first built for
the sourcing and purchasing flow and to be adopted by the other modules as
their lists are reworked. The code lives in
`containermgmt/src/component/Pages/Orders/ListPageKit.js` (layout),
`UnsavedGuard.js` (leave warning) and `src/context/HeaderSlotContext.js`
(top-bar slot). Reuse them; do not hand-roll a header, chip, pager or table style.

### 1. Title and breadcrumb go in the top bar

- The page title is **not** drawn inside the page. It sits in the app top bar,
  left of the company switcher, as `Module › Page` with a small accent icon.
  Use `<PageHeading>` (or `<TitleRow title=… crumbs=…>`); it portals into the
  `HeaderSlotContext` element that `MainPage.js` renders.
- The first crumb is always the **module** the screen belongs to, never a
  sub-group of it. It is the sidebar group the screen's menu item sits in:
  **Procurement**, **Logistics & Stock**, **Print & Reports**, **Master Data**
  or **System**. The page name is the menu item's label (e.g. "Container
  Register", "Logistics & Demurrage").
  Do not use "Sourcing" or "Purchasing" as the first crumb: it repeats the
  page name ("Purchasing › Purchase Orders") and says nothing new.
- Accent per module (`ACCENT` in `ListPageKit.js`): Procurement amber (sourcing)
  / indigo (ordering), Logistics & Stock teal, Master Data violet, Print &
  Reports sky, System slate.
- Settings-style screens use `PageHeader` (`Orders/PageHeader.js`), which puts
  the title in the top bar and keeps only the page's buttons in the page. Any
  `description` passed to it is ignored. Other screens call `<PageHeading>`
  directly. Keep the page's own buttons in the page, to the right.
- A list screen shows `Procurement › Purchase Orders`.
- An entry or detail screen keeps the breadcrumb and adds the record:
  `Procurement › Sourcing & Requisitions › RFQ-2026-0005` or `… › New RFQ`.
  The middle crumb is a link back to the list. Give the crumb an `onClick` that
  runs the unsaved-work guard (section 5) so a click cannot discard edits.
- Entry and detail screens do **not** repeat the title in the page body
  ("Edit Sourcing RFQ (RFQ-1654)", "Create Purchase Order (Draft)"). The
  breadcrumb already says what and which; the body keeps only status chips,
  version, urgent flag and actions.

### 2. No count badge and no description beside the title

- Never put a count badge ("8 RFQs", "7 In Bidding") next to a title. The stage
  chips and the pager already show the numbers.
- Never put a subtitle or explanatory sentence under a title. People who open
  the screen already know what it is for, and the line costs vertical space.
- The same applies to an in-page caption that repeats the breadcrumb.

### 3. One toolbar row, then chips

- Row 1: search and filters on the left; view switch (Table / Cards Grid),
  refresh and primary buttons on the right (`TitleRow` `filters` and children).
  It wraps on a narrow screen. Do not stack the title, filters and buttons
  as separate rows.
- Row 2: stage or status chips (`ChipRow`), with counts inside the chips only.
  - **"All" is always the first chip and the default selection.**
  - **Every chip shows a count**, and the counts come from the server for the
    whole filtered set (search, urgent, parent PO), never from the rows on
    screen. Choosing a chip must not change the numbers on the other chips.
    RFQ and Vendor Quotes use `useLifecycleCounts` (`/orders/status-counts?group_by=lifecycle`);
    Purchase Orders use `/orders/status-counts`; Proformas count each filter
    with a `limit=1` list call.
- Toolbar padding is `p-3 md:p-3.5`. The list below it has no padding (see
  section 4). Do not add per-page padding or margins around the list.

### 4. Same look on every document list

- **Start from `DocumentList`.** A new list screen is `<DocumentList>` (title,
  breadcrumb, search, filter slot, chips, view switch, buttons, loading / error /
  empty states, pager) with a `<DocTable columns=[...]>` or a card grid as its
  children. The page supplies only its columns and rows. `FilterSelect` is the
  shared dropdown filter. `useChipCounts(chips, fetchTotal, deps)` gets the chip
  counts from the server when the API has no counts endpoint. Hand-assemble the
  pieces below only for a screen `DocumentList` cannot express.
- Use the shared pieces: `PageShell`, `Toolbar`, `SearchBox`, `FilterButton`,
  `ViewSwitch`, `ChipRow`, `ListBody`, `ListScroll`, `TableCard`,
  `ListPager` (wraps `PaginationToolbar`). Table header, cell padding (`py-3.5 px-4`),
  row hover and divider come from `tableCls`, `thCls`, `tdCls`, `rowCls`.
- **Table view runs edge to edge.** No padding around the list, square corners,
  no rounded card border, no shadow. The only outer lines are the toolbar's
  bottom border above and the pager's top border below (`ListBody`, `TableCard`
  and `PaginationToolbar flush` do this by default). Do not wrap a document
  table in a rounded, bordered, padded card.
- **Table / Cards switch.** Every list has it (`ViewSwitch`), including
  Proformas. It takes `show`: each page keeps a `SHOW_VIEW_SWITCH` constant at
  the top, and setting it to `false` hides the switch and leaves the page in
  table view. A screen with no card view at all (Packing Lists, Goods Receiving)
  simply omits the `view` prop of `DocumentList`; do not invent a card layout
  just to have the switch.
- **Card view** (RFQ and Purchase Orders via `OrderCardGrid`, Vendor Quotes and
  Proformas inline). Build it from the kit: `cardGridCls(isDark)` for the grid
  and `cardCls(isDark, urgent)` for each card, so the surface, border, rounding
  and hover stay identical. Do not restyle cards per page:
  - Grid (`cardGridCls`): `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 content-start gap-2 p-2 min-h-full`.
  - The grid sits on a tinted surface so cards stand out: `bg-slate-100` light,
    `bg-slate-950` dark. `min-h-full` keeps the tint across the whole area when
    there are few cards.
  - Cards (`cardCls`): slightly rounded (`rounded-lg`, never rounder), full 1px border
    (`border-slate-300` light), no shadow, white in light mode and `#1E293B` in
    dark. Hover is a background tint, not a shadow or an outline.
  - Urgent cards keep their red tint and border.
  - The pager under the cards is the same flush pager used by tables.
- One accent per side of the flow, never mixed on a screen:
  **amber** = sourcing (RFQ, Vendor Quotes), **indigo** = ordering
  (Purchase Orders, Proformas). Do not use blue for primary actions here.
  (This is the documented exception to "primary actions: indigo/blue".)
- Every list uses `ListPager`, server side. No hand-written pager. A screen
  that has only some of the pieces (Proformas has no card view, so no
  `ViewSwitch`) uses just the ones it needs; never copy a piece into the page.
- A document list route must be listed in `isFullBleedPage` in `MainPage.js`
  so it fills the content area. A list that is missing from that list gets the
  default `p-6` wrapper and looks inset next to the others.

### 5. Entry screens: one primary action with Cancel beside it, warn before losing work

- **One primary button at a time.** New document: `Create Draft`. Unsaved
  changes: `Save Draft` (or `Update`). A saved draft with nothing unsaved:
  `Confirm`, which replaces the save button. A document cannot be confirmed
  while edits are unsaved, so a stray click cannot confirm by mistake.
- **No disabled buttons as decoration.** If there is nothing to save, show no
  save button. Do not show Save and Confirm side by side with one greyed out.
- **No back arrow; Cancel sits beside the primary action.** The browser Back
  button and the breadcrumb link already go back, so the page has no arrow of its
  own. The way out the page offers is a **Cancel** button next to Save / Confirm,
  which returns to the list. It goes through the unsaved-work guard like any
  other exit. (Modals and drawers keep their own Cancel as well.)
- **Warn before discarding.** Call `const { modal, allowLeave } = useUnsavedGuard(dirty)`
  and render `{modal}` once. While `dirty`, everything that would leave the page
  asks first through `UnsavedChangesModal` ("Your changes have not been saved...
  cannot be recovered"; **Keep editing** / **Discard and leave**): the browser
  Back button, a left-menu link, a breadcrumb, the back arrow, and any button
  that navigates. A refresh or closed tab gets the browser's own prompt. Never
  use `window.confirm`, and do not hand-roll a leave modal for navigation.
  Call `allowLeave()` just before a navigation the page makes itself after a
  successful save, so saving is not mistaken for walking away. Closing an
  in-page form that is not a navigation (e.g. the Proforma revise form) still
  needs its own `UnsavedChangesModal`.
- "Dirty" for a new form means something was entered; for an open record it
  means it differs from what was loaded (`useDirtySince`). Pre-filled defaults
  do not count.
- The app runs on a data router (`createBrowserRouter` in `App.js`), which is what makes `useBlocker` work; do not switch back to `<BrowserRouter>`.

### 6. Entry screens: no repeated information, no hand-set stage

- **Do not repeat the document number** in a chip in the page body; the
  breadcrumb already carries it.
- **Do not show a heading row over a table** that only names it and counts it
  ("Products & Line Items, 3 Items, 3 Total Qty, Auto-adds new rows"). The
  table is obvious and the footer totals say the counts.
- **The stage is not a dropdown.** It moves as the document moves (confirm,
  send, award, issue, pay). Never offer a control to set it by hand. A draft
  shows no badge (the Save / Confirm actions already say so). An RFQ shows no
  stage badge at any stage (the list, the progress line and the actions say where
  it is); a purchase order shows its later stages once, as the badge beside the
  back arrow.
- **Icon-only secondary buttons.** Documents (paperclip) and Print (printer) are
  square icon buttons with a tooltip and `aria-label`, in one neutral frame.
  Version is the same frame with its number (`v1`). Only the primary action
  (Save / Confirm) carries a text label.
- **No compact / expanded header toggle and no section title.** The entry header
  is always open: its fields (consignee, number, date, priority) are always
  visible, and the section has no title of its own ("Sourcing Requisition &
  Spec"), since the breadcrumb names the document. Priority is a field in that
  grid, not a chip.
- **The page actions live in the header section**, on its first row, right
  aligned: Documents, Version, Print, Cancel, Save / Confirm. There is no
  separate sticky action bar above it, so no row is spent on empty space.
- **No Milestones button on an RFQ**: its dates follow its stages. (A purchase
  order keeps it for freight mode, remarks and milestone dates.)
- **Name the document, not a generic type.** An RFQ's first stage reads
  "Draft RFQ" (never "Draft PO") in lists, cards and steppers. Do not add a
  "scope" or "type" explainer section to a document header that only restates
  what the document already is (e.g. "Sourcing & Vendor Scope" on an RFQ).
- **The workspace runs flush too.** The entry form fills the area edge to edge:
  no page padding or max-width around it, no rounded card, no border or shadow.
  The line-items table has no frame of its own and the catalogue search is a flat
  full-width strip above it; the totals footer sits on the bottom edge.
- **Editable line-item tables: columns sized by use, filling the width.** Default
  widths are percentage shares that add up to 100% (description widest, then the
  notes, then short fixed-purpose columns like code, qty, unit, actions), so there
  is never a gap at the right. Resizable headers show a visible divider line so
  people can see where to drag; a dragged width is saved per user, and changing
  the defaults means bumping the storage key.
- **Cells that look like text.** Inputs inside an editable table have no visible
  border or fill at rest (a transparent 1px border keeps the layout still); they
  get a light fill on hover and a blue border, ring, shadow and white fill on
  focus. Read-only cells stay plain text and never react (no hover fill, no
  border, no outline). The row reads as a list, and a box appears only where the
  person is editing.
- **The table surface is slightly grey** (`slate-100`; dark mode `slate-950/50`),
  so the white focused input clearly stands out from what surrounds it.
- **Input text sizes on an entry screen:** the header fields (consignee selector,
  number, date, priority) are **12px, normal weight** (not bold, not monospace-bold),
  so the header stays quiet; the catalogue search and the table cells are 13px.
  Labels and small chips stay smaller.
- **Editable table rows are 13px text, and the input fills the row's full height**
  (no padding between the input and the row's top and bottom; inputs 34px, row
  35px with its divider), keeping only the input's own inner padding.
- **Version**: one compact button, icon plus `v<N>` (`History` icon), tooltip
  "Version history". Do not also show a separate version chip.
- **Totals sit in the table's footer, pinned to the bottom of the table area**
  (sticky `tfoot`, with a filler row so it stays at the bottom when there are few
  lines). They never float up under the last row.

### Checklist for a new document screen

1. [ ] Title and breadcrumb via `PageHeading` (module first); no in-page title, count or description.
2. [ ] Toolbar is one row plus chips; uses the shared kit and the correct accent.
3. [ ] Route added to `isFullBleedPage`.
4. [ ] `ListPager` used. Table view edge to edge; card view `gap-2 p-2` on a tinted surface with `rounded-lg` bordered cards.
5. [ ] Entry screens: single primary action with Cancel beside it, no back arrow, `useUnsavedGuard` rendered once.

---

## Tables

### Layout requirement

Tables must consume available height, not force the page to expand:

```jsx
{/* Content container — fills viewport height */}
<div className="flex flex-col h-full overflow-hidden">
  {/* Page header — fixed */}
  <div className="shrink-0 p-4 border-b">...</div>

  {/* Filters — fixed */}
  <div className="shrink-0 p-3 border-b">...</div>

  {/* Table — grows and scrolls */}
  <div className="flex-1 overflow-auto">
    <table>...</table>
  </div>

  {/* Pagination — fixed at bottom */}
  <div className="shrink-0 border-t p-3">...</div>
</div>
```

### Column rules
- Keep table headers visible (sticky) when the table scrolls vertically.
- Use horizontal scrolling (`overflow-x-auto`) when columns don't fit — do not hide columns.
- Provide a minimum width to columns with long content.
- Use `whitespace-nowrap` for numeric and code columns.
- Use `truncate` with a `title` attribute for long text columns.

### Large tables
- Always use server-side pagination (see `pagination.md`).
- Show a loading skeleton or spinner while data loads.
- Show an empty state when there are no results.
- Show an error state when the fetch fails.

---

## Modals and Drawers

### Content scrolling
Modals with long content must scroll internally — not the background page:

```jsx
<div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
  <div className="relative w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl bg-white shadow-2xl">
    {/* Header — fixed */}
    <div className="shrink-0 p-6 border-b">
      <h2>Modal Title</h2>
      <button onClick={onClose}>X</button>
    </div>

    {/* Scrollable content */}
    <div className="flex-1 overflow-y-auto p-6">
      {/* Long form or content here */}
    </div>

    {/* Footer actions — fixed */}
    <div className="shrink-0 p-4 border-t flex justify-end gap-2">
      <button>Cancel</button>
      <button>Save</button>
    </div>
  </div>
</div>
```

### Rules
- `max-h-[90vh]` on the modal container — never let a modal exceed viewport.
- Use `flex flex-col` with `flex-1 overflow-y-auto` for the content area.
- Keep the close button and primary actions visible at all times.
- On small screens (< 768px), modals should be full-width and nearly full-height.
- Never make the background page scroll while a modal is open.

---

## Forms

### Large/complex forms
- Group related fields using tabs, collapsible cards, or clear section headings.
- Keep primary Save/Submit actions visible — do not bury them below a long form.
- On laptop/desktop, use a 2-column grid for paired fields (e.g. quantity + unit).
- On mobile/small screens, collapse to single column.

```jsx
<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
  <div><label>Quantity</label><input .../></div>
  <div><label>Unit</label><select .../></div>
</div>
```

### Validation
- Show field-level errors inline beneath the field.
- Highlight errored fields with a red border.
- Do not only show validation errors as a toast — the user needs to see which field failed.

---

## Responsive Design

Design for these viewports in priority order:

| Priority | Viewport | Notes |
|---|---|---|
| 1 | 1280px–1920px desktop | Primary working viewport |
| 2 | 1024px–1280px laptop | Common field use case |
| 3 | 768px–1024px tablet | Secondary use case |
| 4 | < 768px mobile | Best-effort responsive |

Use Tailwind responsive prefixes:
- `md:` for tablet and above (768px+)
- `lg:` for desktop (1024px+)

---

## Viewport Verification Checklist

Before considering any UI complete, verify:

1. [ ] Page layout fits within the viewport without body scroll.
2. [ ] Sidebar and navbar do not scroll.
3. [ ] Table/content area scrolls independently when content overflows.
4. [ ] Horizontal overflow does not occur on the full page layout.
5. [ ] Tables with many rows scroll correctly without pushing the page down.
6. [ ] Modals have their own internal scroll, not page scroll.
7. [ ] Pagination footer is visible without scrolling.
8. [ ] Long forms do not overflow the modal/page.
9. [ ] Loading, empty, and error states are implemented and visible.
10. [ ] All primary actions (Save, Submit, Cancel) are accessible without scrolling.
11. [ ] The UI is usable at 1024px viewport width (common laptop).
12. [ ] No content is clipped by `overflow: hidden` without a visible scroll handle.

Do not mark a UI task as complete until this checklist passes.

---

## Color and Dark Mode

Always provide both light and dark mode variants.
Use Tailwind utility classes with `dark:` prefix or dynamic `isDark` conditional classes:

```jsx
className={`rounded-xl border ${
  isDark
    ? "bg-slate-800 border-slate-700 text-white"
    : "bg-white border-slate-200 text-slate-900"
}`}
```

Do not use hardcoded colors that only work in light mode.

---

## Typography and Spacing

- Use consistent text size scales: `text-xs` (10-12px), `text-sm` (13-14px), `text-base` (16px).
- Table body cells: `text-sm`.
- Table column headers: `text-xs font-semibold uppercase tracking-wide`.
- Page titles: `text-xl font-bold` or `text-2xl font-bold`.
- Section headings within a panel: `text-sm font-semibold`.
- Monospace for codes (SKU, PO number, factory code): `font-mono`.

---

## Buttons and Interactive Elements

- Every button must have a `type="button"` attribute inside forms to prevent accidental form submission.
- Use `cursor-pointer` explicitly — do not rely on browser defaults inside `<div>` handlers.
- Disabled buttons must have `disabled:opacity-40` or `disabled:opacity-30`.
- Hover states must be visible: `hover:bg-...` or `hover:text-...`.
- Primary actions: indigo/blue fill. Destructive actions: rose/red fill. Secondary: slate/gray fill.
