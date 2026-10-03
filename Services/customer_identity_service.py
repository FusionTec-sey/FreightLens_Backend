"""Internal scoped customer creation; public personal-data permission adapter pending."""
from Model.containermgmt.MasterData.RetailCustomer import RetailCustomer
from Schema.CustomerSchema import CustomerIdentityInput, CustomerIdentityRead
from Services.inventory_posting_service import execute_once, PostingEffect
from Utils.org_filter import apply_org_filter


def create_customer(factory, context, actor_id, operation_key, profile, *, expected_version, authorize):
    if not callable(authorize): raise ValueError('Customer and personal-data permission guard required')
    if type(expected_version) is not int or expected_version != 0:
        raise ValueError('Customer creation requires expected version zero')
    if not isinstance(profile, CustomerIdentityInput): raise ValueError('Typed customer profile required')
    snapshot = CustomerIdentityInput.model_validate(profile.model_dump()).model_dump(mode='json')

    def effect(db):
        db.add(RetailCustomer(org_id=context.org_id, customer_key=operation_key,
                              initial_profile=snapshot, created_by=actor_id))
        db.flush()
        # Keep contact data out of generic event envelopes and receipt results.
        result = dict(customer_key=str(operation_key), version=1)
        return PostingEffect(result, dict(kind='customer.identity.created', **result))
    return execute_once(factory, context, actor_id, operation_key, 'customer.identity.create.v1',
        dict(profile=snapshot, expected_version=expected_version), effect, authorize=authorize)


def get_customer(db, context, customer_key, *, authorize):
    if not callable(authorize): raise ValueError('Customer and personal-data permission guard required')
    authorize(db)
    if context.org_id not in context.allowed_org_ids: raise PermissionError('Customer company scope denied')
    row = apply_org_filter(db.query(RetailCustomer).filter_by(org_id=context.org_id,
        customer_key=customer_key, is_deleted=False), RetailCustomer, context).one_or_none()
    if row is None: raise LookupError('Customer not found')
    return CustomerIdentityRead(**row.initial_profile, customer_key=row.customer_key, version=1)
