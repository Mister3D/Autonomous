"""REST API blueprints (flask-smorest → OpenAPI)."""

from autonomous.api.auth_routes import blp as auth_blp
from autonomous.api.bots import blp as bots_blp
from autonomous.api.hooks import blp as hooks_blp
from autonomous.api.system import blp as system_blp
from autonomous.api.jobs import blp as jobs_blp
from autonomous.api.vault_routes import blp as vault_blp
from autonomous.api.memory_routes import blp as memory_blp
from autonomous.api.approval_routes import blp as approval_blp
from autonomous.api.clarify_routes import blp as clarify_blp
from autonomous.api.search_routes import blp as search_blp
from autonomous.api.devices import blp as devices_blp
from autonomous.api.setup_routes import blp as setup_blp


def register_blueprints(api) -> None:
    api.register_blueprint(system_blp)
    api.register_blueprint(auth_blp)
    api.register_blueprint(bots_blp)
    api.register_blueprint(jobs_blp)
    api.register_blueprint(vault_blp)
    api.register_blueprint(memory_blp)
    api.register_blueprint(approval_blp)
    api.register_blueprint(clarify_blp)
    api.register_blueprint(search_blp)
    api.register_blueprint(hooks_blp)
    api.register_blueprint(devices_blp)
    api.register_blueprint(setup_blp)
