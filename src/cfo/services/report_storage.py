"""Persistence adapter for the existing report-builder dataclasses."""
from collections.abc import MutableMapping
from dataclasses import asdict

from ..models import ReportRecord


class ReportStore(MutableMapping):
    def __init__(self, db, organization_id, kind, decode):
        self.db, self.organization_id, self.kind, self.decode = db, organization_id, kind, decode

    def query(self):
        return self.db.query(ReportRecord).filter_by(organization_id=self.organization_id, kind=self.kind, deleted=False)

    def __getitem__(self, reference):
        row = self.query().filter_by(reference=reference).populate_existing().first()
        if row is None: raise KeyError(reference)
        value = self.decode(row.payload)
        if hasattr(value, 'version'): value.version = row.version
        return value

    def __iter__(self):
        return iter([row.reference for row in self.query().order_by(ReportRecord.id).all()])

    def __len__(self): return self.query().count()

    def __setitem__(self, reference, value):
        payload = asdict(value) if hasattr(value, '__dataclass_fields__') else value
        row = self.query().filter_by(reference=reference).first()
        if row is None:
            self.db.add(ReportRecord(organization_id=self.organization_id, kind=self.kind,
                reference=reference, payload=payload, version=1, deleted=False))
        else:
            version = getattr(value, 'version', row.version)
            changed = self.query().filter_by(reference=reference, version=version).update({
                ReportRecord.payload: payload, ReportRecord.version: ReportRecord.version + 1}, synchronize_session=False)
            if changed != 1:
                self.db.rollback()
                raise ValueError('Report configuration changed; reload before updating')
            if hasattr(value, 'version'): value.version = version + 1
        self.db.commit()

    def __delitem__(self, reference):
        changed = self.query().filter_by(reference=reference).update({ReportRecord.deleted: True}, synchronize_session=False)
        if not changed: raise KeyError(reference)
        self.db.commit()
