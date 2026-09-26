# Frontend Rules (React)

## Component Inventory — Check Before Creating

Before building any new UI component, check if one already exists.

### Reusable UX Components (`src/component/UI/UXComponent/`)

| File | Purpose |
|---|---|
| `ProductCatalogSelector.js` | Product search/select with thumbnail, SKU, factory code, supplier display |
| `GenericSelector.js` | Reusable async-search dropdown selector for any entity |
| `CurrencyInput.js` | Currency amount input with currency selector |
| `TagInput.js` | Multi-value tag input |
| `TypebleSelect.js` | Typeable select/combobox |

### UI Utilities (`src/component/UI/`)

| File | Purpose |
|---|---|
| `AddSelect.js` | Add-new-item select combo |
| `CollapsibleCard.js` | Expandable/collapsible card section |
| `OrgSwitcher.js` | Organisation switcher control |

### Table Display (`src/component/TableDisplay/`)
Check this directory for existing table wrapper components before building a new table.

### Pages (`src/component/Pages/`)
Domain-specific pages. Never duplicate a page for a slightly different use case — extend via props or route params.

---

## Operational Work Screens vs Dashboard Widgets (No KPIs on Work Screens)

- **Operational Work Screens** (e.g. `ConatinerEntry.js`, `BillOfLanding.js`, `GoodsReceivingPage.js`):
  - Must maximize vertical data density for tables, forms, filters, and pagination.
  - **Never** render summary KPI metric cards, high-level status counters, or aggregate metric cards at the top.
  - Structure: Header -> Filters Toolbar -> Table (`flex-1 min-h-0 overflow-auto`) -> `PaginationToolbar`.
- **Dashboard Widgets** (`/dashboard` via `dashboard_registry.py` & `WidgetCard.js`):
  - High-level KPIs, metric cards, status charts, and aggregates belong exclusively on the module's Dashboard widgets.
  - If any summary metrics are needed for a module, register them in `Backend/Services/dashboard_registry.py` under `WIDGET_CATALOG` and calculate them in `calculate_dashboard_data()`.

---

## API Communication

Use `axios` for all API calls. The base URL comes from:
```javascript
process.env.REACT_APP_NETWORK
```

Always include authentication headers:
```javascript
const getAuthHeaders = () => ({
  Authorization: `Bearer ${localStorage.getItem("token")}`,
});

const res = await axios.get(`${process.env.REACT_APP_NETWORK}/inventory/products`, {
  params: { page, limit: pageSize, search },
  headers: getAuthHeaders(),
});
```

---

## State Management

Use React `useState` and `useCallback` for local component state.
Use `useMemo` for derived/computed values.

Standard pattern for a paginated data table:
```javascript
const [products, setProducts] = useState([]);
const [loading, setLoading] = useState(false);
const [error, setError] = useState(null);
const [page, setPage] = useState(1);
const [pageSize, setPageSize] = useState(25);
const [totalPages, setTotalPages] = useState(1);
const [totalCount, setTotalCount] = useState(0);
const [search, setSearch] = useState("");

const fetchProducts = useCallback(async () => {
  setLoading(true);
  try {
    const res = await axios.get(...);
    setProducts(res.data.items || []);
    setTotalPages(res.data.pages || 1);
    setTotalCount(res.data.total || 0);
  } catch (err) {
    setError(err.response?.data?.detail || "Failed to load products");
    toast.error(...);
  } finally {
    setLoading(false);
  }
}, [page, pageSize, search, ...filters]);

useEffect(() => { fetchProducts(); }, [fetchProducts]);
```

Reset page to 1 on filter/search change:
```javascript
const handleSearchChange = (val) => {
  setSearch(val);
  setPage(1);  // Reset pagination
};
```

---

## Dark Mode

All components must support dark mode. The project uses a `isDark` boolean derived from user preference.

Pattern:
```javascript
const isDark = /* from context or localStorage */;

className={`... ${isDark ? "bg-slate-800 text-white border-slate-700" : "bg-white text-slate-900 border-slate-200"}`}
```

Never hardcode light-mode-only colors. Always provide both `isDark` and light variants.

---

## Loading, Empty, and Error States

Every data-fetching component must handle all three states:

```jsx
{loading && (
  <div className="flex items-center justify-center h-40">
    <Loader2 className="animate-spin text-indigo-500" />
  </div>
)}

{!loading && error && (
  <div className="text-red-500 text-sm p-4">{error}</div>
)}

{!loading && !error && items.length === 0 && (
  <div className="text-center py-12 text-slate-400">
    <Package size={40} className="mx-auto mb-3 opacity-40" />
    <p>No products found.</p>
  </div>
)}
```

Never show a blank screen. Always handle the empty state.

---

## Permission-Based UI

Use role/permission booleans from the auth context to show or hide UI elements.

```javascript
const canViewVendor = ["Admin", "Manager", "Buyer", "Accounts"].includes(userRole);
const isAccountsUser = ["Admin", "Manager", "Accounts"].includes(userRole);
```

These checks are UX only — do not treat them as security boundaries.
The backend still enforces authorization on every request.

Pattern for conditional columns:
```jsx
{/* Column: Unit Cost — Accounts Only */}
{isAccountsUser && (
  <td>...</td>
)}
```

Pattern for conditional tabs:
```jsx
{canViewVendor && (
  <Tab label="Sourcing & Vendors">...</Tab>
)}
```

---

## Toasts and Notifications

Use `react-hot-toast` for all success/error notifications:
```javascript
import toast from "react-hot-toast";

toast.success("Product saved successfully");
toast.error("Failed to save product");
```

Never use browser `alert()` or `confirm()`. Use modal confirmation dialogs instead.

---

## Forms

For large forms:
- Use tabs, sections, or collapsible cards to group related fields.
- Product detail forms use tabs: Overview, Stock, Sourcing & Vendors, Documents, etc.
- Keep primary actions (Save, Cancel) accessible without scrolling.
- Show field-level validation errors inline, not only as a toast.

---

## Navigation and Routing

Routes are defined in the main `App.js` or router file.
Use `react-router-dom` `useNavigate` for programmatic navigation.
Use `useParams` to read route parameters.

Never hardcode path strings in multiple places — use constants or named routes.
