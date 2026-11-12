"""The tokscope mark: a gauge, like a usage meter. Drawn for this project
(no icon set), inline SVG so the report and the dashboard stay offline."""

from urllib.parse import quote

# the sidebar mark: all currentColor (it sits in the accent square, in the colour of text on the accent); the viewBox is
# cropped to the drawing so centering the box beside the text centres the gauge itself
MARK = '<svg xmlns="http://www.w3.org/2000/svg" class="logo" aria-hidden="true" viewBox="2 8 20 12.6" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M3.5 18a8.5 8.5 0 0 1 14.5-6"/><path d="M18 12a8.5 8.5 0 0 1 2.5 6"/><path d="M12 18l3.7-5.3"/><circle cx="12" cy="18" r="2.2" fill="currentColor" stroke="none"/></svg>'

# the favicon is a white gauge on the accent square, so it reads on a light or a dark tab bar
FAVICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#4B4FD8"/><g fill="none" stroke="#fff" stroke-width="3.6" stroke-linecap="round"><path d="M5.5 24a10.5 10.5 0 0 1 17.9-7.4"/><path d="M23.4 16.6a10.5 10.5 0 0 1 3.1 7.4"/><path d="M16 24l4.4-6.4"/></g><circle cx="16" cy="24" r="3" fill="#fff"/></svg>'


def favicon_link():
    return f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{quote(FAVICON)}">'
