"""Chainlit mount target: a shim that registers the canonical callbacks module.

Chainlit's ``load_module`` executes the target *file* as a brand-new module instance
(``spec_from_file_location``). If the callbacks lived in the target itself, Chainlit
would register functions from that second instance while the FastAPI lifespan
configures the globals of ``capybara.chainlit_app`` — and header auth / the runner
would silently stay unconfigured. Importing the canonical module here instead hits
the import cache, so registration and configuration share one module object.
"""

import capybara.chainlit_app  # noqa: F401  — importing registers the @cl.* callbacks
