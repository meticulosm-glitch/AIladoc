"""Icone SVG inline (tratto 24x24). Il colore per tipo è in CSS (.ic-<kind>)."""
from markupsafe import Markup

_FILE = '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'

PATHS = {
    # --- tipi di documento ---
    "folder": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/>',
    "markdown": '<rect x="2.5" y="5.5" width="19" height="13" rx="2.5"/><path d="M6 15V9l2.5 3L11 9v6"/><path d="M16.5 9v6"/><path d="m14.5 13 2 2 2-2"/>',
    "pdf": _FILE + '<path d="M9 18v-5h1.6a1.6 1.6 0 0 1 0 3.2H9"/><path d="M14 13v5"/><path d="M14 13h2"/><path d="M14 15.5h1.5"/>',
    "slides": '<path d="M3 4h18"/><path d="M4.5 4v10a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5V4"/><path d="M12 15.5V19"/><path d="m8.5 21 3.5-2 3.5 2"/><path d="M9 12V9.5"/><path d="M12 12V7.5"/><path d="M15 12v-1.5"/>',
    "sheet": '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M3.5 9.5h17"/><path d="M3.5 15h17"/><path d="M9.5 3.5v17"/>',
    "word": _FILE + '<path d="m8.5 12 1.2 5.5L12 13.5l2.3 4 1.2-5.5"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="m20.5 16-4.5-4.5L7 19.5"/>',
    "video": '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m10 9.2 5 2.8-5 2.8z"/>',
    "audio": '<path d="M9 18V5.5l11-2V16"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    "archive": _FILE + '<path d="M10 3v2"/><path d="M10 7v2"/><path d="M10 11v2"/><rect x="8.5" y="14" width="3" height="4" rx="1"/>',
    "text": _FILE + '<path d="M8.5 12.5h7"/><path d="M8.5 15.5h7"/><path d="M8.5 18.5h4"/>',
    "file": _FILE,
    "diagram": '<rect x="3" y="3.5" width="7" height="5" rx="1.2"/><rect x="14" y="15.5" width="7" height="5" rx="1.2"/><rect x="14" y="3.5" width="7" height="5" rx="1.2"/><path d="M10 6h4"/><path d="M6.5 8.5V18h7.5"/>',
    "puzzle": '<path d="M10 4.5a2 2 0 1 1 4 0V6h3.5A1.5 1.5 0 0 1 19 7.5V11h-1.5a2 2 0 1 0 0 4H19v3.5a1.5 1.5 0 0 1-1.5 1.5H14v-1.5a2 2 0 1 0-4 0V20H6.5A1.5 1.5 0 0 1 5 18.5V15h1.5a2 2 0 1 0 0-4H5V7.5A1.5 1.5 0 0 1 6.5 6H10z"/>',
    # --- interfaccia ---
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    "edit": '<path d="M4 20h4L19 9a2.83 2.83 0 0 0-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "upload": '<path d="M12 15V4"/><path d="m7 9 5-5 5 5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "download": '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "folder-plus": '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5z"/><path d="M12 10v6"/><path d="M9 13h6"/>',
    "trash": '<path d="M4 7h16"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
    "shield": '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18.5 14.2A6.5 6.5 0 0 1 21.5 20"/>',
    "key": '<circle cx="8" cy="15" r="4.5"/><path d="m11.2 11.8 8.3-8.3"/><path d="m16.5 6.5 2.5 2.5"/><path d="m14 9 2 2"/>',
    "logout": '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5"/><path d="M5 12h11"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
    "menu": '<path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/>',
    "x": '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    "image-up": '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M12 16v-6"/><path d="m9 12.5 3-3 3 3"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "move": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "eye": '<path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z"/><circle cx="12" cy="12" r="3"/>',
    "home": '<path d="M4 11 12 4l8 7"/><path d="M6 9.5V19a1 1 0 0 0 1 1h3.5v-5h3v5H17a1 1 0 0 0 1-1V9.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
    "sparkle": '<path d="M12 3.5c.4 3.9 2.6 6.1 6.5 6.5-3.9.4-6.1 2.6-6.5 6.5-.4-3.9-2.6-6.1-6.5-6.5 3.9-.4 6.1-2.6 6.5-6.5z"/><path d="M18.5 15.5c.2 1.6 1 2.4 2.5 2.5-1.5.2-2.3 1-2.5 2.5-.2-1.5-1-2.3-2.5-2.5 1.5-.1 2.3-.9 2.5-2.5z"/>',
    "send": '<path d="M4.5 12 3 4.5 21 12 3 19.5z"/><path d="M4.5 12H12"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4.5V11h-6.5"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
}


def icon(name: str, cls: str = "", size: int = 18) -> Markup:
    body = PATHS.get(name, PATHS["file"])
    return Markup(
        f'<svg class="ic {cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{body}</svg>'
    )


def kind_icon(kind: str, size: int = 18) -> Markup:
    return icon(kind, f"ic-{kind}", size)
