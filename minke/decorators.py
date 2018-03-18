
def register(models=None, short_description=None, permission_required=None):
    """
    Register sessions as an admin-action with the associated models:

    @register(MyModel, 'Do something great!')
    class MySession(Session):
        pass
    """
    def _session_wrapper(session_cls):
        from minke.sessions import register
        register(session_cls, models, short_description, permission_required)
        return session_cls
    return _session_wrapper
