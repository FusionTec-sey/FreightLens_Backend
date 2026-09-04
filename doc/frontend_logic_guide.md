# Frontend Logic Guide: BoL & Container Synchronization

This guide explains how to implement the frontend UI logic for managing **Bill of Lading (BoL)** settings vs. **Individual Container** overrides.

The backend enforces a "Decentralized with Conflict Resolution" pattern for `FreeDays` and `status`.

---

## 1. Core Logic: Inherited vs. Custom

A container's value is considered **Inherited** if it matches its parent BoL's value. It is **Custom** if it has been overridden.

### Detection Logic (Frontend)
When viewing a BoL with its containers (from `GET /getBl` or `GET /getContainerDetails`):

```javascript
// Example check for a container
const isFreeDaysCustom = container.FreeDays !== container.bill_of_landing.FreeDays;
const isStatusCustom = container.status !== container.bill_of_landing.status;
```

---

## 2. BoL Management UI

When the user is on the **Bill of Lading Edit Screen**, the global `FreeDays` and `status` fields should be handled carefully.

### A. Global Field State
You should check if **any** associated container has a custom value.

| Condition | UI Action |
|---|---|
| **All** containers match BoL | ✅ Global Field is **Editable**. Updating it will cascade to all containers. |
| **Any** container is "Custom" | ⚠️ Global Field should be **Locked/Disabled** or show a **Warning Badge**. |

### B. Displaying Sync Status
*   **BoL Badge**: If all containers are in sync, show a "Synced" icon.
*   **Individual Container Badge**: Next to each container in the list, show an "Overridden" or "Custom" tag if its value differs from the BoL.

---

## 3. Restricting Global Updates

If the frontend allows the user to attempt a global BoL update while custom containers exist, the backend will return an `HTTP 409 Conflict`.

### Recommended Workflow:
1.  **Detect Conflict**: Before calling `POST /updateBl/{bl_number}`, calculate if any container is custom.
2.  **Disable Submit**: Gray out the "Save" button for global BoL fields if a conflict is detected.
3.  **Provide a "Reset All" Button**:
    *   If the user wants to re-enable global BoL updates, they must first "Sync all containers to BoL".
    *   To implement this, call the individual container update for each "Custom" container to set its value back to the BoL's current value.
    *   Once all match, the global update will be unlocked.

---

## 4. Individual Container UI

*   **Individual Edit**: Users can always update a single container's `FreeDays` or `status`. 
*   **Warning**: When they do this, show a small hint: *"Note: Overriding this value will prevent global updates from the Bill of Lading."*

---

## 5. Summary of API Responses to Handle

### `HTTP 409 Conflict`
**When it happens**: You tried to update `FreeDays` or `status` on a BoL while one or more containers have a custom value.
**Frontend Action**: Show a Modal/Toast:
> "Update Blocked: One or more containers (e.g., [Container No]) have individual overrides. Please reset individual containers or update them one by one."

### `POST /updateBl/{bl_number}` (Success)
**When it happens**: No conflicts. All containers are automatically updated to the new BoL value.
**Frontend Action**: Refresh the local state for both the BoL and all its containers.

---

## Example implementation helper (React-like)

```javascript
const BoLSettings = ({ bol, containers }) => {
  const hasCustomFreeDays = containers.some(c => c.FreeDays !== bol.FreeDays);
  
  return (
    <div>
      <label>Global Free Days</label>
      <input 
        value={bol.FreeDays} 
        disabled={hasCustomFreeDays} 
        onChange={...}
      />
      {hasCustomFreeDays && (
        <p className="warning">
           Editing locked: Some containers have custom free days. 
           <button onClick={handleResetAll}>Reset All Containers to BoL</button>
        </p>
      )}
    </div>
  );
}
```
