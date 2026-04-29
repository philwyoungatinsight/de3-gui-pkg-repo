import os
import reflex as rx

config = rx.Config(
    app_name="homelab_gui",
    frontend_port=int(os.environ.get("HOMELAB_GUI_FRONTEND_PORT", "9080")),
    backend_port=int(os.environ.get("HOMELAB_GUI_BACKEND_PORT", "9000")),
    disable_plugins=["reflex.plugins.sitemap.SitemapPlugin"],
)
