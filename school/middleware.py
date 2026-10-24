from django.contrib.auth import logout
from django.shortcuts import redirect


class AccountMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            role = request.session.get('active_role', '')
            request.user.active_role = role if request.user.roles.filter(role=role).exists() else ''
            if not request.user.is_active:
                logout(request)
                return redirect('login')
            if (
                request.user.must_change_password
                and request.path not in ('/password/', '/logout/')
                and not request.path.startswith('/static/')
            ):
                return redirect('password')
        return self.get_response(request)
