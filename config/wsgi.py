import os

from django.core.wsgi import get_wsgi_application

default_settings = "config.settings.prod" if os.getenv("RENDER") else "config.settings.dev"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)

application = get_wsgi_application()
