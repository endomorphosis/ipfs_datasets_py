"""Guardian-local one-use adoption after the owner's disk inventory, before acquire."""
def install(resources, adopter, *, source_root, receipt_path):
    previous = resources.get_global_resource_scheduler
    state = {'attempted': False, 'receipt': None, 'client': None}
    def getter():
        if state['attempted']:
            raise RuntimeError('lazy scheduler adoption cannot be repeated')
        state['attempted'] = True
        try:
            receipt = adopter(resources, source_root=source_root, receipt_path=receipt_path)
            bound = resources.get_global_resource_scheduler
            if bound is getter or bound is previous:
                raise RuntimeError('adopter did not bind the exact scheduler client')
            client = bound()
            state['receipt'], state['client'] = receipt, client
            return client
        except BaseException:
            # Fail closed, including if the adapter replaced the getter before failing.
            resources.get_global_resource_scheduler = getter
            raise
    resources.get_global_resource_scheduler = getter
    def completed_receipt():
        if state['receipt'] is None or state['client'] is None:
            raise RuntimeError('resource owner did not complete scheduler adoption')
        return state['receipt']
    return completed_receipt
