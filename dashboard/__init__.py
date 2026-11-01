from flask import Flask
from config.flask_config import config_by_name
from .auth import load_auth_config

def create_app(config_name='default'):
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    app.config.from_object(config_by_name[config_name])

    web_access = load_auth_config().get("web_access", {})
    if web_access.get("behind_proxy", False):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app)

    from .routes import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    return app
