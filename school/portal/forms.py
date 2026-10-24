"""Compatibility imports for portal forms.

New code should import forms from the domain module that owns them.
"""

from .admin_forms import (
    ClassForm,
    DictionaryForm,
    DictionaryItemForm,
    GrantForm,
    PersonForm,
    dictionary_choices,
)
from .learning_forms import SubmitForm
from .teaching_forms import ItemForm, WorkForm

__all__ = [
    'ClassForm',
    'DictionaryForm',
    'DictionaryItemForm',
    'GrantForm',
    'ItemForm',
    'PersonForm',
    'SubmitForm',
    'WorkForm',
    'dictionary_choices',
]
