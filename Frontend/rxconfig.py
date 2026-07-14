import reflex as rx

config = rx.Config(
    app_name="reflex_dashboard",
    # Docker Desktop often occupies port 8000 (Reflex's default backend port),
    # which silently breaks the dashboard. Pin a free port instead.
    backend_port=8010,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)