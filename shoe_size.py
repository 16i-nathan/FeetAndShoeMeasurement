"""Rough length(cm) → shoe size helpers for display (not brand-fitting advice)."""

# Mondopoint-style: EU ≈ cm * 1.5; US men's ≈ (cm - 18.4) / 0.847 (approx)
# Tables are approximate adult conversions for tester feedback only.

_EU_BY_CM = [
    (22.0, 35), (22.5, 36), (23.0, 36.5), (23.5, 37), (24.0, 38),
    (24.5, 38.5), (25.0, 39), (25.5, 40), (26.0, 40.5), (26.5, 41),
    (27.0, 42), (27.5, 42.5), (28.0, 43), (28.5, 44), (29.0, 44.5),
    (29.5, 45), (30.0, 46), (30.5, 46.5), (31.0, 47),
]

_US_M_BY_CM = [
    (22.0, 4), (22.5, 4.5), (23.0, 5), (23.5, 5.5), (24.0, 6),
    (24.5, 6.5), (25.0, 7), (25.5, 7.5), (26.0, 8), (26.5, 8.5),
    (27.0, 9), (27.5, 9.5), (28.0, 10), (28.5, 10.5), (29.0, 11),
    (29.5, 11.5), (30.0, 12), (30.5, 12.5), (31.0, 13),
]

_US_W_BY_CM = [
    (22.0, 5), (22.5, 5.5), (23.0, 6), (23.5, 6.5), (24.0, 7),
    (24.5, 7.5), (25.0, 8), (25.5, 8.5), (26.0, 9), (26.5, 9.5),
    (27.0, 10), (27.5, 10.5), (28.0, 11), (28.5, 11.5), (29.0, 12),
]


def _nearest(table, cm):
    return min(table, key=lambda t: abs(t[0] - cm))[1]


def sizes_from_cm(cm: float) -> dict:
    return {
        'cm': round(cm, 2),
        'eu': _nearest(_EU_BY_CM, cm),
        'us_men': _nearest(_US_M_BY_CM, cm),
        'us_women': _nearest(_US_W_BY_CM, cm),
        'uk': round(_nearest(_US_M_BY_CM, cm) - 0.5, 1),
    }
