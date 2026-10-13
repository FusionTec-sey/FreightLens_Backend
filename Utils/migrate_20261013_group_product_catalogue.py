"""Promote the one existing category tree into the shared group catalogue.

`product_categories.is_shared` has existed all along, but nothing read it: the
category endpoints filtered on org_id alone, so a category marked shared was
invisible to every other company. The flag was decorative and no tree was ever
shared.

In practice there is one tree. Every category and every product belongs to the
root organisation; the other companies have neither, so a product catalogue
reached from their orders came back all but empty. Promoting that tree to the
group catalogue gives every company the same categories with nothing to migrate
-- no product changes hands, because no other company has any.

A tree is shared whole or not at all. Sharing one branch would leave another
company seeing a child whose parent it cannot see, so this promotes a complete
tree from its root down, and refuses rather than leave a half-shared one.

Re-running is a no-op: with the tree already shared there is nothing to promote.
A site that has deliberately set up per-company trees is left alone -- more than
one candidate root means the choice is not ours to make.
"""
import logging

from sqlalchemy import text

from Model.db import engine

logger = logging.getLogger("containerMgmt.migrate_group_product_catalogue")


def ensure_group_product_catalogue():
    with engine.begin() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'containermgmt' AND table_name = 'product_categories'
        """)).first()
        if not exists:
            logger.info("product_categories is not there yet; nothing to do.")
            return

        already = conn.execute(text("""
            SELECT count(*) FROM containermgmt.product_categories
            WHERE is_shared = TRUE AND is_deleted IS NOT TRUE
        """)).scalar()
        if already:
            logger.info("A group catalogue already exists (%s categories); nothing to do.", already)
            return

        roots = conn.execute(text("""
            SELECT id, org_id, name FROM containermgmt.product_categories
            WHERE parent_id IS NULL AND is_deleted IS NOT TRUE
            ORDER BY id
        """)).fetchall()
        if not roots:
            logger.info("No category tree to promote yet.")
            return
        if len(roots) > 1:
            # Several companies already keep their own trees. Promoting one of
            # them would silently put two roots in front of everyone else.
            logger.info(
                "%s category trees exist (companies %s); leaving them alone, as which "
                "should become the group catalogue is a decision, not a migration.",
                len(roots), sorted({r.org_id for r in roots}),
            )
            return

        root = roots[0]

        # The whole tree, from the root down, so nothing is left half-shared.
        promoted = conn.execute(text("""
            WITH RECURSIVE tree AS (
                SELECT id FROM containermgmt.product_categories
                WHERE id = :root_id AND is_deleted IS NOT TRUE
                UNION ALL
                SELECT c.id FROM containermgmt.product_categories c
                JOIN tree t ON c.parent_id = t.id
                WHERE c.is_deleted IS NOT TRUE
            )
            UPDATE containermgmt.product_categories
            SET is_shared = TRUE
            WHERE id IN (SELECT id FROM tree)
        """), {"root_id": root.id}).rowcount

        # Anything left unshared would be a branch detached from this root, and
        # a company reading the group catalogue would never see it.
        stranded = conn.execute(text("""
            SELECT count(*) FROM containermgmt.product_categories
            WHERE is_deleted IS NOT TRUE AND is_shared IS NOT TRUE
        """)).scalar()
        if stranded:
            raise RuntimeError(
                f"{stranded} categories sit outside the tree being promoted and would be "
                "stranded in a half-shared catalogue. Migration aborted."
            )

        logger.info(
            "Promoted the '%s' tree of company %s into the group catalogue "
            "(%s categories, now readable by every company).",
            root.name, root.org_id, promoted,
        )
