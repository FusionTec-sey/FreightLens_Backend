# Implementation Plan - Compact Table Row Spacing & Interactive Column Resizing

Enable interactive column resizing for the Products & Line Items table and eliminate excess spacing between input fields and table cells to create a tight, high-density ERP spreadsheet layout.

## User Review Required

> [!NOTE]
> - **Default Column Widths**: Initial defaults are configured as `#`: 36px, `SKU`: 120px, `Description`: 320px, `Qty`: 80px, `Unit`: 70px, `Unit Price`: 105px, `Line Total`: 105px, `Actions`: 65px.
> - **Persistence**: Resized column widths can be stored in browser `localStorage` (`freightlens_po_col_widths`) so customizations persist across page visits and reloads.
> - **Input Fluidity**: All inputs use `w-full` within `<table className="w-full table-fixed ...">` and `<colgroup>`, ensuring inputs instantly resize smoothly as column dividers are dragged.

---

## Proposed Changes

### Frontend Component

#### [MODIFY] [OrderEntryPage.js](file:///D:/WorkPlace/Seychelles_Sahaj/containermgmt/src/component/Pages/Orders/OrderEntryPage.js)

1. **Interactive Column Resizing State & Handlers**:
   - Initialize `columnWidths` state with sensible defaults (and optional `localStorage` persistence):
     ```javascript
     const DEFAULT_COL_WIDTHS = {
       index: 36,
       item_code: 120,
       description: 320,
       quantity_ordered: 80,
       unit: 70,
       unit_price: 105,
       line_total: 105,
       actions: 65,
     };
     ```
   - Add `resizingColumn` state tracking `{ colKey, startX, startWidth }`.
   - Implement `startResize(e, colKey)`, `onMouseMove(e)`, and `onMouseUp()` with global window listeners while dragging.
   - Enforce min-widths per column (e.g. `description`: min 120px, `item_code`: min 65px, `quantity_ordered`: min 55px, etc.) to prevent accidental column collapse.

2. **Table `<colgroup>` & `table-fixed` Architecture**:
   - Apply `table-fixed` on `<table>` to guarantee precise adherence to assigned column widths.
   - Insert `<colgroup>` mapping `<col key={key} style={{ width: `${columnWidths[key]}px` }} />`.

3. **Drag Handles on Header Cells (`<th>`)**:
   - Add a subtle resize handle on the right edge of each resizable column header:
     ```jsx
     <div
       onMouseDown={(e) => startResize(e, 'colKey')}
       className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-blue-500 active:bg-blue-600 transition-colors z-20"
       title="Drag to resize column"
     />
     ```
   - Change cursor to `cursor-col-resize` and prevent text selection during dragging (`select-none`).

4. **Eliminate Excess Spacing Between Inputs and Table Cells**:
   - Reduce `<td>` cell padding from `py-1 px-1.5` to `py-0.5 px-1` (just 2px vertical padding).
   - Update `<input>` styling:
     - Set explicit compact height `h-6.5` (26px) and `py-0 px-1.5`.
     - Tighten border radius to `rounded` with clean 1px border.
     - Inputs sit flush and snug within each cell, eliminating the "floating card" effect and maximizing both horizontal and vertical data density.

---

## Verification Plan

### Automated Tests
- Parse `OrderEntryPage.js` with Node & Babel AST parser to ensure zero syntax or JSX errors.
- Monitor docker frontend compiler logs (`docker logs --tail 25 sahaj_frontend_local`) to verify clean Webpack bundle compilation.

### Manual Verification
1. **Column Resizing**:
   - Hover over the column header divider between "SKU / Code" and "Product Description" -> cursor changes to `col-resize`.
   - Drag to the right -> "SKU / Code" widens and the SKU input field expands with it.
   - Drag to the left -> column contracts down to its min-width constraint.
2. **Cell Spacing & Density**:
   - Inspect table rows: verify input fields sit snugly inside the row cell with minimal ~2px padding.
   - Verify row height is reduced to ~28px, allowing 12-15 items to fit on a standard 1080p display without scrolling.
