"""The one error the engine raises. Its message starts with the part's id."""


class AnimationError(ValueError):
    """The scene cannot be animated as drawn: a missing behaviour, a failed physics check, a dead end."""


class NotModelledYet(AnimationError):
    """The engine has no model yet for a part as it is drawn: no behaviour, a port shared by two links, a port the
    light cannot leave, or no internal path."""
