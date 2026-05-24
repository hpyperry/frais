"""Version normalization and comparison utilities."""

from packaging.version import InvalidVersion, Version


def _is_newer(current: str | None, latest: str | None) -> bool:
    if not current or not latest:
        return False
    cur = _normalize(current)
    lat = _normalize(latest)
    if cur == lat:
        return False
    try:
        vc, vl = Version(cur), Version(lat)
        return vl > vc
    except InvalidVersion:
        pass
    c2 = _digits_only(cur)
    l2 = _digits_only(lat)
    if c2 == l2:
        return False
    try:
        return Version(l2) > Version(c2)
    except InvalidVersion:
        try:
            l_parts = [int(x) for x in l2.split(".") if x != ""]
            c_parts = [int(x) for x in c2.split(".") if x != ""]
        except (ValueError, TypeError):
            return False
        if not l_parts or not c_parts:
            return False
        return tuple(l_parts) > tuple(c_parts)


def _normalize(value: str) -> str:
    v = value.strip().lstrip("vV")
    for sep in (" ", "("):
        idx = v.find(sep)
        if idx > 0:
            v = v[:idx]
    return v


def _digits_only(value: str) -> str:
    return "".join(c for c in value if c.isdigit() or c == ".")
