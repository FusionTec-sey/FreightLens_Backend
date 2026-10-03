from Model.containermgmt.Inventory.ManagerCase import ManagerCase, ManagerCaseDecision, ManagerCaseUse


def case_page(db, query, actor_id, view, page, limit):
    """Caller supplies authorized company/action scope. Filter before paging."""
    if view == "NEEDS_MY_REVIEW":
        decided = db.query(ManagerCaseDecision.id).filter(ManagerCaseDecision.org_id == ManagerCase.org_id,
            ManagerCaseDecision.case_id == ManagerCase.id).correlate(ManagerCase).exists()
        used = db.query(ManagerCaseUse.id).filter(ManagerCaseUse.org_id == ManagerCase.org_id,
            ManagerCaseUse.case_id == ManagerCase.id).correlate(ManagerCase).exists()
        query = query.filter(ManagerCase.created_by != actor_id, ~decided, ~used)
    elif view == "MY_REQUESTS":
        query = query.filter(ManagerCase.created_by == actor_id)
    total = query.count()
    rows = query.outerjoin(ManagerCaseDecision, (ManagerCaseDecision.case_id == ManagerCase.id) &
        (ManagerCaseDecision.org_id == ManagerCase.org_id)).outerjoin(ManagerCaseUse,
        (ManagerCaseUse.case_id == ManagerCase.id) & (ManagerCaseUse.org_id == ManagerCase.org_id)).add_entity(
            ManagerCaseDecision).add_entity(ManagerCaseUse).order_by(ManagerCase.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return total, rows


def case_metadata(case, decision, used):
    return dict(case_key=case.case_key, version=3 if used else 2 if decision else 1,
        status="CONSUMED" if used else decision.outcome if decision else "REQUESTED",
        source_version=case.source_version, reason=case.reason, requestor_id=case.created_by,
        reviewer_id=decision.created_by if decision else None,
        review_reason=decision.reason if decision else None, requested_at=case.created_at)
