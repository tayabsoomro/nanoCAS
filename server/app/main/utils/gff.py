"""GFF3 parsing for region-of-interest alerts."""

from __future__ import annotations

import gzip
import urllib.parse

MAX_FEATURES = 20000


def _attributes(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw.split(';'):
        if '=' in item:
            k, v = item.split('=', 1)
            out[k.strip()] = urllib.parse.unquote(v.strip())
    return out


def parse_gff_features(path: str, seqids: set[str] | None = None, limit: int = MAX_FEATURES) -> dict:
    """Return ``{'features': [...], 'types': {type: count}, 'seqids': [...],
    'truncated': bool}`` for a GFF3 (optionally gzipped).

    Each feature: ``seqid, type, start, end, strand, id, name, product``.
    ``id`` falls back to Name, then locus_tag, then ``type:start-end``.
    """
    features: list[dict] = []
    types: dict[str, int] = {}
    seen_seqids: list[str] = []
    truncated = False
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rt', errors='replace') as fh:
        for line in fh:
            if line.startswith('##FASTA'):
                break
            if not line.strip() or line.startswith('#'):
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 8:
                continue
            seqid, ftype, start, end, strand = parts[0], parts[2], parts[3], parts[4], parts[6]
            if seqids and seqid not in seqids:
                continue
            try:
                s, e = int(start), int(end)
            except ValueError:
                continue
            if s > e:
                s, e = e, s
            attrs = _attributes(parts[8]) if len(parts) > 8 else {}
            if seqid not in seen_seqids:
                seen_seqids.append(seqid)
            types[ftype] = types.get(ftype, 0) + 1
            if len(features) >= limit:
                truncated = True
                continue
            fid = attrs.get('ID') or attrs.get('Name') or attrs.get('locus_tag') or f'{ftype}:{s}-{e}'
            features.append({
                'seqid': seqid, 'type': ftype, 'start': s, 'end': e, 'strand': strand,
                'id': fid, 'name': attrs.get('Name') or attrs.get('gene') or '',
                'product': attrs.get('product') or attrs.get('description') or attrs.get('Note') or '',
            })
    return {'features': features, 'types': types, 'seqids': seen_seqids, 'truncated': truncated}


def regions_from_selection(selection: list[dict], default_threshold: float = 0.0) -> dict[str, list[dict]]:
    """Turn the wizard's selected features into the ``regions.json`` layout
    FileHandler evaluates: ``{seqid: [{id, name, type, start, end,
    alert_enabled, threshold}]}``."""
    regions: dict[str, list[dict]] = {}
    for item in selection or []:
        try:
            seqid = str(item['seqid'])
            start, end = int(item['start']), int(item['end'])
        except (KeyError, TypeError, ValueError):
            continue
        try:
            threshold = float(item.get('threshold', default_threshold) or default_threshold)
        except (TypeError, ValueError):
            threshold = default_threshold
        regions.setdefault(seqid, []).append({
            'id': str(item.get('id') or f'{start}-{end}'),
            'name': item.get('name') or '',
            'type': item.get('type') or '',
            'start': min(start, end), 'end': max(start, end),
            'alert_enabled': bool(item.get('alert_enabled', True)),
            'threshold': threshold,
        })
    return regions
