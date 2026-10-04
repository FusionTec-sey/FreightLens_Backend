"""Shared bounded evidence configuration; no storage or posting side effects."""
import os


class EvidenceConfigurationUnavailable(ValueError):
    pass


def evidence_size_limit():
    raw = os.environ.get('COST_EVIDENCE_MAX_BYTES', '')
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise EvidenceConfigurationUnavailable(
            'Versioned evidence capture requires a configured positive '
            'COST_EVIDENCE_MAX_BYTES')
