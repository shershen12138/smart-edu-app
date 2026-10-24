from django.shortcuts import render


def form_page(request, title, form, **context):
    return render(request, 'school/form.html', {'title': title, 'form': form, **context})
