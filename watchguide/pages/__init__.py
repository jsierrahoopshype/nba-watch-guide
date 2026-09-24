"""Page types. Each module exposes build(ctx, env) -> list[Page].

Adding a page type means writing a module here and listing it in BUILDERS.
Nothing else in the generator needs to change.
"""

from . import hub, team, tonight

BUILDERS = (hub.build, team.build, tonight.build)
