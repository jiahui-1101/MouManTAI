"""Bounded literal observations, never a SKU lookup or inventory approval."""
import re
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def product_name_hints():
    """Recognition hints only: none of these names confers SKU membership."""
    try:
        names = json.loads((Path(__file__).with_name('fixtures') / 'product_name_hints.json').read_text(encoding='utf-8'))
        return tuple(name for name in names if isinstance(name, str) and 0 < len(name) <= 80)
    except (OSError, ValueError):
        return ()


NON_PRODUCT_WORDS = {
    'each', 'per', 'box', 'boxes', 'pack', 'packs', 'pcs', 'piece', 'pieces',
    'set', 'sets', 'sent', 'over', 'sent over', 'driver', 'patty', 'patties',
    'reach', 'total', 'only', 'all', 'separate', 'different', 'item', 'items',
    'order', 'orders', 'reorder', 'delivery', 'biji', 'buah', 'kotak', 'bungkus',
    'am', 'pm', 'am sharp', 'pm sharp', 'sharp', 'hour', 'hours', 'jam', 'pukul',
    'guest', 'guests', 'pax', 'people', 'person', 'persons', 'orang',
    'per box', 'per carton', 'per pack', 'each box', 'setiap kotak', 'setiap bungkus',
    'boleh', 'boleh tak', 'lah', 'ya', 'ye', 'kan', 'kah', 'ok', 'okay',
    'pls', 'plz', 'tq', 'terima kasih', 'saja', 'sahaja', 'je', 'juga',
    'lagi', 'dulu', 'nanti', 'instead', 'actually', 'sorry', 'maaf',
}


def literal_product_observations(text, *, catalog, tenant_id, units, excluded_spans):
    unit_pattern = '|'.join(re.escape(u) for u in sorted(units, key=len, reverse=True))
    catalog_aliases = {a.casefold() for p in catalog if p.tenant_id == tenant_id for a in p.aliases}
    prefix = re.compile(
        r'(?<![A-Za-z0-9_.\-])(?P<quantity>[0-9]+(?:\.[0-9]+)?)\s*'
        r'(?:(?P<unit>' + unit_pattern + r')(?![A-Za-z])\s*)?'
        r'(?:of\s+)?', re.I)
    stop = re.compile(
        r'[;,.!?\n，。；！？]|\b(?:for|delivery|deliver|delivered|drop\s+off|dropped\s+off|'
        r'by|on|tomorrow|tmr|tmrw|today|before|after|at|around|between|from|to|until|'
        r'esok|besok|lusa|hantar|dihantar|pada|sebelum|selepas|lepas|pukul|'
        r'and|dan|or|atau|plus|please|pls|plz|thanks|thank\s+you|tq|terima\s+kasih|'
        r'boleh|lah|ya|ye|kan|kah|ok|okay|sent\s+over|sent|send|reach|get|arrive|driver|'
        r'instead|sorry|actually|maaf|serving)\b|'
        r'\bjam(?=\s+[0-9])|'
        r'明天|后天|今天|送到|送达|交货|配送|和|以及', re.I)
    seen = set()
    for match in prefix.finditer(text):
        if any(a <= match.start() < b for a, b in excluded_spans):
            continue
        prior = text[:match.start()].rstrip()
        tail = text[match.end():match.end() + 100]
        end = stop.search(tail)
        raw = tail[:end.start()] if end else tail
        product = raw.strip()
        if not product or len(product) > 80 or re.search(r'[0-9]', product):
            continue
        if product.casefold() in NON_PRODUCT_WORDS:
            continue
        if not re.fullmatch(r"[A-Za-z\u3400-\u9fff][A-Za-z\u3400-\u9fff '\-]{0,79}", product):
            continue
        matches = [p for p in catalog if p.tenant_id == tenant_id and
                   product.casefold() in {a.casefold() for a in p.aliases}]
        meanings = {(p.sku, p.unit) for p in matches}
        approved = matches[0] if len(meanings) == 1 else None
        # Known item + trailing quantity ("burger 9 pcs boleh?") is handled
        # by the postfix pass; its conversational tail is not a new product.
        if not approved and any(re.search(r'(?<![A-Za-z0-9_])' + re.escape(alias) + r'$', prior, re.I)
                                for alias in catalog_aliases):
            continue
        if not approved and any(w.casefold() in catalog_aliases for w in product.split()):
            continue
        start = match.end() + len(raw) - len(raw.lstrip())
        finish = start + len(product)
        if any(start < b and a < finish for a, b in excluded_spans):
            continue
        seen.add((start, finish, match.start('quantity')))
        yield {'product': product, 'product_span': (start, finish),
               'quantity': match.group('quantity'), 'quantity_span': match.span('quantity'),
               'unit': match.group('unit'), 'unit_span': match.span('unit'),
               'group_id': f'literal-{match.start()}', 'approved': approved}

    names = set(product_name_hints()) | {a for p in catalog if p.tenant_id == tenant_id for a in p.aliases}
    if not names:
        return
    noun = re.compile(r'(?<![A-Za-z0-9_])(?:' + '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r')(?![A-Za-z0-9_])', re.I)
    postfix = re.compile(r'\s*[,，:]?\s*(?:(?:quantity|qty|jumlah|need|want|nak|mahu)\s*(?:is|=|:)?\s*|(?:要|需要|数量|數量|x|×|=)\s*)?'
                         r'(?P<quantity>[0-9]+(?:\.[0-9]+)?)\s*(?:(?P<unit>' + unit_pattern + r')(?![A-Za-z]))?', re.I)
    for name in noun.finditer(text):
        match = postfix.match(text, name.end())
        if not match or any(a <= match.start('quantity') < b or name.start() < b and a < name.end()
                            for a, b in excluded_spans):
            continue
        key = (name.start(), name.end(), match.start('quantity'))
        if key in seen:
            continue
        seen.add(key)
        matches = [p for p in catalog if p.tenant_id == tenant_id and
                   name.group().casefold() in {a.casefold() for a in p.aliases}]
        approved = matches[0] if len({(p.sku, p.unit) for p in matches}) == 1 else None
        yield {'product': name.group(), 'product_span': name.span(),
               'quantity': match.group('quantity'), 'quantity_span': match.span('quantity'),
               'unit': match.group('unit'), 'unit_span': match.span('unit'),
               'group_id': f'literal-{match.start("quantity")}', 'approved': approved}
