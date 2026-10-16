from django import template
from django.template.defaultfilters import linebreaksbr
from django.utils.safestring import mark_safe

register = template.Library()

_BLEACH_WARNED = False

_MARKDOWN_BLEACH_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "em",
        "b",
        "i",
        "a",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "blockquote",
        "pre",
        "code",
        "hr",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)
_MARKDOWN_BLEACH_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "code": ["class"],
}


@register.filter
def csv_tags(value):
    """Split comma-separated tags into a list of non-empty stripped strings."""
    if not value:
        return []
    return [x.strip() for x in str(value).split(",") if x.strip()]


@register.filter
def render_markdown(value):
    global _BLEACH_WARNED
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        import markdown as md  # type: ignore

        html = md.markdown(
            text,
            extensions=["extra", "sane_lists", "nl2br"],
            output_format="html5",
        )
        try:
            import bleach
        except ImportError:
            if not _BLEACH_WARNED:
                import logging

                logging.getLogger(__name__).warning(
                    "bleach is not installed; rebuild the web image (pip install -r requirements.txt). "
                    "Markdown HTML is not sanitized until then."
                )
                _BLEACH_WARNED = True
            clean = html
        else:
            clean = bleach.clean(
                html,
                tags=_MARKDOWN_BLEACH_TAGS,
                attributes=_MARKDOWN_BLEACH_ATTRS,
                strip=True,
            )
        return mark_safe(clean)
    except Exception:
        return linebreaksbr(text)
