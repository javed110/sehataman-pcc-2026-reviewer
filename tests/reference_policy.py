"""Constructed conventional ABAC reference, specified before Step 5 execution.

Shares the HTTP/session/persistence/workflow and cryptographic plumbing with M.
This deliberately configures all supported safeguards; it is not a market product
or an independent implementation of that shared plumbing.
"""
from sehataman.domain import Service, ApiError
from sehataman.crypto import timestamp
from sehataman.issuer import report_text, verify_package


def evidence(item, now):
    try:
        return all((item['status'] == 'valid', item['person_match'] is True,
                    timestamp(item['valid_from']) <= now,
                    now < timestamp(item['valid_until'])))
    except (KeyError, ValueError, TypeError):
        return False


class ReferenceService(Service):
    """Table-driven conventional attribute policy; same features and evidence."""
    def _eligible(self, s, physician, affiliation=None):
        p = s['profiles'].get(physician)
        if p is None:
            return False
        a = affiliation
        if a is None:
            a = next((v for v in s['affiliations'].values()
                      if (v['physician_id'], v['hospital_id']) == (physician, p['hospital_id'])), {})
        org = s['organizations'].get(p['hospital_id'], {})
        facts = [s['users'].get(physician, {}).get('active') is True,
                 p['profile_status'] == 'submitted']
        facts += [evidence(x, timestamp(s['clock'])) for x in
                  (p['binding_evidence'], p['registration'], a.get('evidence', {}), org.get('evidence', {}))]
        return all(facts)

    def _grant_ok(self, s, g, v, physician):
        m = v['package']['manifest']
        a = s['appointments'].get(g['appointment_id'], {})
        f = s['affiliations'].get(g['affiliation_id'], {})
        equalities = [
            (g['status'], 'active'), (g['purpose'], 'consultation'),
            (g['physician_id'], physician), (g['patient_id'], m['patient_id']),
            (a.get('patient_id'), g['patient_id']), (a.get('physician_id'), physician),
            (a.get('hospital_id'), g['hospital_id']), (f.get('hospital_id'), g['hospital_id']),
            (a.get('affiliation_id'), f.get('id')), (f.get('physician_id'), physician)]
        return (all(left == right for left, right in equalities) and bool(a) and bool(f)
                and a['status'] in {'booked', 'confirmed'} and v['id'] in g['version_ids']
                and timestamp(g['starts_at']) <= timestamp(s['clock']) < timestamp(g['expires_at'])
                and self._eligible(s, physician, f))

    def _access(self, s, actor, version):
        if version is None or version['status'] not in {'accepted', 'superseded'}:
            return False
        m = version['package']['manifest']
        p = s['patients'].get(m.get('patient_id'), {})
        identity_ok = p.get('adult') is True and evidence(p.get('identity', {}), timestamp(s['clock']))
        order = s['orders'].get(m.get('order_id'), {})
        role_rules = {
            'patient': lambda: identity_ok and actor['id'] == m['patient_id'],
            'physician': lambda: identity_ok and any(self._grant_ok(s, g, version, actor['id']) for g in s['grants'].values()),
            'lab_submitter': lambda: actor['org_id'] == m['lab_id'] and actor['id'] in order.get('assigned_staff', []),
            'lab_approver': lambda: actor['org_id'] == m['lab_id'] and actor['id'] in order.get('assigned_staff', [])}
        allowed = role_rules.get(actor['role'], lambda: False)()
        if allowed and not self._package_valid(s, version):
            raise ApiError(503, 'report_integrity', 'The report is held for an integrity review.')
        return allowed

    def _package_valid(self, s, v):
        try:
            m = v['package']['manifest']; series = s['series'][v['series_id']]
            order = s['orders'][m['order_id']]; p = s['patients'][m['patient_id']]
            org = s['organizations'][m['lab_id']]
            submitter, approver = [s['users'][m[key]] for key in ('submitter_id', 'approver_id')]
            groups = [(m['lab_id'], series['lab_id'], order['lab_id'], submitter['org_id'], approver['org_id']),
                      (m['patient_id'], series['patient_id'], order['patient_id']),
                      (m['order_id'], series['order_id']), (m['specimen_id'], order['specimen_id']),
                      (m['specimen_alias'], order['specimen_alias']), (m['lab_patient_id'], order['lab_patient_id']),
                      (m['cnic_lookup'], p['cnic_lookup']), (m['secondary_dob'], p['dob']),
                      (m['source_report_id'], series['source_report_id'])]
            return (all(len(set(group)) == 1 for group in groups) and m['synthetic'] is True
                    and submitter['role'] == 'lab_submitter' and approver['role'] == 'lab_approver'
                    and submitter['id'] != approver['id'] and v['package']['content'] == report_text(m)
                    and verify_package(self.store, org['alias'], v['package']))
        except (KeyError, TypeError, ValueError):
            return False

    def _source_findings(self, s, actor, package):
        m = package.get('manifest', {}); org = s['organizations'][actor['org_id']]
        o = s['orders'].get(m.get('order_id')); problems = []
        if not verify_package(self.store, org['alias'], package):
            problems.append('issuer_or_content_integrity_failed')
        if not o or o['lab_id'] != actor['org_id'] or actor['id'] not in o['assigned_staff']:
            return problems + ['source_order_unavailable']
        p = s['patients'][o['patient_id']]
        staff = [s['users'].get(m.get(k), {}) for k in ('submitter_id', 'approver_id')]
        if not (staff[0].get('role') == 'lab_submitter' and staff[1].get('role') == 'lab_approver'
                and all(u.get('org_id') == org['id'] for u in staff) and staff[0].get('id') != staff[1].get('id')):
            problems.append('distinct_source_approval_required')
        bindings = [(m.get('lab_id'), org['id']), (m.get('lab_alias'), org['alias']),
                    (m.get('patient_id'), o['patient_id']), (m.get('cnic_lookup'), p['cnic_lookup']),
                    (m.get('secondary_dob'), p['dob']), (m.get('specimen_id'), o['specimen_id']),
                    (m.get('specimen_alias'), o['specimen_alias']), (m.get('lab_patient_id'), o['lab_patient_id'])]
        if any(x != y for x, y in bindings) or not evidence(p['identity'], timestamp(s['clock'])):
            problems.append('identity_order_or_specimen_mismatch')
        try:
            if (m['synthetic'] is not True or package['content'] != report_text(m)
                    or not all(m[k] for k in ('target', 'method', 'specimen_type'))
                    or type(m['version']) is not int or timestamp(m['issued_at']) > timestamp(s['clock'])):
                problems.append('report_context_invalid')
        except (KeyError, TypeError, ValueError):
            problems.append('report_context_invalid')
        head = next((x for x in s['series'].values() if (x['lab_id'], x['source_report_id']) ==
                     (org['id'], m.get('source_report_id'))), None)
        if head:
            previous = s['versions'][head['current_version_id']]
            if any((head['patient_id'] != o['patient_id'], head['order_id'] != o['id'],
                    m.get('predecessor_id') != previous['id'],
                    m.get('version') != previous['package']['manifest']['version'] + 1,
                    not m.get('correction_reason'))):
                problems.append('predecessor_or_correction_conflict')
        elif (m.get('version'), m.get('predecessor_id')) != (1, None):
            problems.append('initial_version_invalid')
        return problems
