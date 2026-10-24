from django.core.paginator import Paginator


def pagination(request, rows):
    size = request.GET.get('per_page', '30')
    size = int(size) if size in ('10', '30', '50', '100') else 30
    paginator = Paginator(rows, size)
    page = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    params.pop('per_page', None)
    return {
        'page': page,
        'per_page': size,
        'page_sizes': (10, 30, 50, 100),
        'page_range': list(paginator.get_elided_page_range(page.number, on_each_side=2)),
        'page_filters': list(params.items()),
        'page_query': params.urlencode(),
    }
