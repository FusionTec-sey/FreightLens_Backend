import psycopg2
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

PG_URL = "postgresql://postgres:postgres_local@127.0.0.1:5433/containermgmt_pg"

def grant_full_access_to_parth():
    logging.info("Connecting to PostgreSQL to verify/grant full access for user 'parth'...")
    conn = psycopg2.connect(PG_URL)
    cur = conn.cursor()

    # 1. Fetch user 'parth'
    cur.execute("SELECT id, username, org_id FROM usercredentials.users WHERE LOWER(username) = 'parth';")
    user = cur.fetchone()
    if not user:
        logging.error("User 'parth' not found in usercredentials.users!")
        return

    user_id, username, org_id = user
    logging.info(f"Found user '{username}' (ID: {user_id}, org_id: {org_id})")

    # Ensure user has org_id = 1 (Root Organisation Sahaj Construction)
    if org_id != 1:
        cur.execute("UPDATE usercredentials.users SET org_id = 1 WHERE id = %s;", (user_id,))
        logging.info(f"Updated user '{username}' org_id to 1 (Root Organisation)")

    # 2. Ensure user has 'Administrator' role (role_id = 1)
    cur.execute("SELECT * FROM usercredentials.user_roles WHERE user_id = %s AND role_id = 1;", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO usercredentials.user_roles (user_id, role_id) VALUES (%s, 1);", (user_id,))
        logging.info(f"Assigned Administrator role (role_id=1) to user '{username}'")
    else:
        logging.info(f"User '{username}' already has Administrator role (role_id=1)")

    # 3. Fetch all permission IDs in the database
    cur.execute("SELECT id, name FROM usercredentials.permissions;")
    all_perms = cur.fetchall()
    logging.info(f"Total permissions in system: {len(all_perms)}")

    # 4. Ensure Administrator role (role_id = 1) has ALL permissions in role_permissions
    cur.execute("SELECT permission_id FROM usercredentials.role_permissions WHERE role_id = 1;")
    existing_perm_ids = set(row[0] for row in cur.fetchall())

    missing_perms = [p for p in all_perms if p[0] not in existing_perm_ids]

    if missing_perms:
        logging.info(f"Granting {len(missing_perms)} missing permissions to Administrator role (role_id=1)...")
        for perm_id, perm_name in missing_perms:
            cur.execute(
                "INSERT INTO usercredentials.role_permissions (role_id, permission_id) VALUES (1, %s);",
                (perm_id,)
            )
        logging.info("All missing permissions granted to Administrator role.")
    else:
        logging.info("Administrator role (role_id=1) already possesses 100% of system permissions.")

    conn.commit()

    # 5. Summary Check
    cur.execute('''
        SELECT count(DISTINCT p.name)
        FROM usercredentials.permissions p
        JOIN usercredentials.role_permissions rp ON p.id = rp.permission_id
        JOIN usercredentials.user_roles ur ON rp.role_id = ur.role_id
        WHERE ur.user_id = %s;
    ''', (user_id,))
    total_parth_perms = cur.fetchone()[0]

    cur.close()
    conn.close()

    logging.info(f"=== DATABASE ACCESS CONFIRMATION ===")
    logging.info(f"User: '{username}' (User ID: {user_id})")
    logging.info(f"Root Organisation: Sahaj Construction (org_id=1, Root)")
    logging.info(f"Active Permissions: {total_parth_perms} / {len(all_perms)} (100% Full Access Granted)")

if __name__ == "__main__":
    grant_full_access_to_parth()
