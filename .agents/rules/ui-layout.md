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
  {/* 1. Page Header — Fixed (Title, subtitle, primary action button, refresh) */}
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
