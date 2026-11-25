"""Локальные SVG-иконки и денежные фильтры — без внешних CDN."""

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

ICONS = {
    "dashboard": (
        '<rect x="3" y="3" width="7" height="18" rx="2"/>'
        '<rect x="14" y="3" width="7" height="12" rx="2"/>'
    ),
    "list": (
        '<path d="M8 6h13M8 12h13M8 18h13"/>'
        '<path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>'
    ),
    "users": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "tools": (
        '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3'
        'a4 4 0 0 0 5.4-5.4l-2.3 2.3-2.5-2.5 2.3-2.3Z"/>'
    ),
    "chart": (
        '<path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/>'
    ),
    "settings": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06'
        'a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09'
        'A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83'
        'l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09'
        'A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83'
        'l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09'
        'a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83'
        'l-.06.06A1.65 1.65 0 0 0 19.4 9c.14.63.68 1.08 1.51 1H21a2 2 0 0 1 0 4h-.09'
        'a1.65 1.65 0 0 0-1.51 1Z"/>'
    ),
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "copy": (
        '<rect x="9" y="9" width="12" height="12" rx="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "wallet": (
        '<path d="M20 12V8a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h15a2 2 0 0 1 2 2v4'
        'a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6"/>'
        '<path d="M16 14h.01"/>'
    ),
    "phone": (
        '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6'
        'A19.8 19.8 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.86.33 1.7.62 2.5'
        'a2 2 0 0 1-.45 2.11L8 9.6a16 16 0 0 0 6 6l1.27-1.28a2 2 0 0 1 2.11-.45'
        'c.8.29 1.64.5 2.5.62A2 2 0 0 1 22 16.92Z"/>'
    ),
    "telegram": (
        '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "map-pin": (
        '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/>'
        '<circle cx="12" cy="10" r="3"/>'
    ),
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "check-circle": (
        '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>'
    ),
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "calendar": (
        '<rect x="3" y="5" width="18" height="16" rx="2"/>'
        '<path d="M16 3v4M8 3v4M3 11h18"/>'
    ),
    "download": (
        '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>'
    ),
    "upload": (
        '<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M5 3h14"/>'
    ),
    "trash": (
        '<path d="M3 6h18"/><path d="M8 6V4h8v2"/>'
        '<path d="M19 6l-1 14H6L5 6"/><path d="M10 11v5M14 11v5"/>'
    ),
    "edit": (
        '<path d="M12 20h9"/>'
        '<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"/>'
    ),
    "sparkles": (
        '<path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z"/>'
        '<path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z"/>'
    ),
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "external": (
        '<path d="M14 3h7v7"/><path d="M21 3 10 14"/>'
        '<path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>'
    ),
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "alert": (
        '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9'
        'a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>'
    ),
    "credit-card": (
        '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>'
    ),
    "filter": '<path d="M3 5h18l-7 8v6l-4 2v-8L3 5Z"/>',
    "user": (
        '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'
    ),
    "car": (
        '<path d="M5 17h14M6 17l-1-4 2-5h10l2 5-1 4"/>'
        '<circle cx="7.5" cy="17.5" r="1.5"/><circle cx="16.5" cy="17.5" r="1.5"/>'
    ),
    "home": (
        '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>'
    ),
    "tag": (
        '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6'
        'a2 2 0 0 1 0 2.8Z"/><circle cx="7.5" cy="7.5" r="1.5"/>'
    ),
    "gift": (
        '<path d="M20 12v9H4v-9"/><path d="M2 7h20v5H2z"/>'
        '<path d="M12 21V7"/><path d="M12 7H7.5a2.5 2.5 0 1 1 0-5'
        'C11 2 12 7 12 7Z"/><path d="M12 7h4.5a2.5 2.5 0 1 0 0-5'
        'C13 2 12 7 12 7Z"/>'
    ),
    "percent": (
        '<path d="M19 5 5 19"/><circle cx="6.5" cy="6.5" r="2.5"/>'
        '<circle cx="17.5" cy="17.5" r="2.5"/>'
    ),
    "image": (
        '<rect x="3" y="3" width="18" height="18" rx="2"/>'
        '<circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>'
    ),
    "camera": (
        '<path d="M14.5 4h-5L8 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16'
        'a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-4l-1.5-3Z"/>'
        '<circle cx="12" cy="13" r="3.5"/>'
    ),
}


@register.simple_tag
def svg_icon(name, size=18, css_class=""):
    """Встроенная SVG-иконка (Lucide-подобная) без внешних ресурсов."""
    inner = ICONS.get(name)
    if not inner:
        return ""
    classes = f"mb-icon {css_class}".strip()
    return mark_safe(
        f'<svg class="{classes}" width="{int(size)}" height="{int(size)}" '
        'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{inner}</svg>'
    )


@register.filter
def rub(value):
    """Деньги в русском формате: 1 500 ₽, 12 345,50 ₽."""
    if value is None or value == "":
        return "0 ₽"
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return "0 ₽"
    if amount == amount.to_integral_value():
        text = f"{amount:,.0f}"
    else:
        text = f"{amount:,.2f}"
    return text.replace(",", " ").replace(".", ",") + " ₽"


@register.filter
def ru_plural(value, variants):
    """Русская форма существительного: 1 запись, 2 записи, 5 записей."""
    try:
        number = abs(int(value))
    except (TypeError, ValueError):
        return variants
    one, few, many = [part.strip() for part in variants.split(",")]
    if number % 10 == 1 and number % 100 != 11:
        word = one
    elif 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        word = few
    else:
        word = many
    return f"{number} {word}"


@register.filter
def initials(value):
    """Инициалы из имени — для аватарок."""
    words = [word for word in str(value or "").replace("-", " ").split() if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()
