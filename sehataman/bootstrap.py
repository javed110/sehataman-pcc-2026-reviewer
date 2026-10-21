from .seed import make_seed
from .storage import Store


def bootstrap(home):
    store = Store(home)
    store.initialize(make_seed)
    with store.transaction() as tx:
        if not tx.state.get("bootstrap_audited"):
            tx.audit("synthetic_demo_initialized", reason="invented_fixtures_only")
            for version in tx.state["versions"].values():
                manifest = version["package"]["manifest"]
                approver = tx.state["users"][manifest["approver_id"]]
                tx.audit("report_accepted", approver, object_id=version["series_id"],
                         patient_id=manifest["patient_id"], version_id=version["id"], reason="synthetic_seed")
            tx.state["bootstrap_audited"] = True
    return store
