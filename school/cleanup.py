"""Delete private files after commit; retry filesystem failures from the worker."""

import logging
from pathlib import PurePosixPath

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import (
    Assignment,
    Coursework,
    CourseworkGradeHistory,
    CourseworkPackageUpdate,
    CourseworkSubmission,
    EvaluationPackage,
    Notification,
    PrivateFileCleanup,
    ProblemVersion,
    Submission,
    TestCase,
)

logger = logging.getLogger(__name__)
FILE_FIELDS = {
    Coursework: ('document_path', 'materials_path'),
    CourseworkSubmission: ('source_path',),
    CourseworkPackageUpdate: ('document_path', 'materials_path', 'previous_materials_path'),
    EvaluationPackage: ('archive_path', 'template_path', 'reference_path'),
    ProblemVersion: ('reference_path',),
    Submission: ('code_path',),
    TestCase: ('input_path', 'output_path'),
}


def is_referenced(path):
    for model, fields in FILE_FIELDS.items():
        query = Q()
        for field in fields:
            query |= Q(**{field: path})
        if model.objects.filter(query).exists():
            return True
    return CourseworkSubmission.objects.filter(snapshot__reference_path=path).exists()


def drain_file_cleanup(limit=200):
    for task in PrivateFileCleanup.objects.order_by('pk')[:limit]:
        if is_referenced(task.path):
            task.delete()
            continue
        root = settings.PRIVATE_STORAGE.resolve()
        relative = PurePosixPath(task.path)
        path = (root / task.path).resolve()
        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root):
            logger.error('Refused unsafe private-file cleanup: task=%s', task.pk)
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception('Private-file cleanup will retry: task=%s', task.pk)
        else:
            task.delete()


def queue_file_cleanup(paths):
    for path in set(paths):
        if path:
            PrivateFileCleanup.objects.get_or_create(path=path)
    transaction.on_commit(drain_file_cleanup)


def prune_package(package_id):
    if not package_id:
        return
    with transaction.atomic():
        package = EvaluationPackage.objects.select_for_update().filter(pk=package_id).first()
        if (
            package
            and not Coursework.objects.filter(package_id=package_id).exists()
            and not (CourseworkSubmission.objects.filter(snapshot__package_id=package_id).exists())
            and not CourseworkPackageUpdate.objects.filter(
                Q(package_id=package_id) | Q(previous_package_id=package_id)
            ).exists()
            and not CourseworkGradeHistory.objects.filter(package_id=package_id).exists()
        ):
            package.delete()


@receiver(post_delete)
def deleted_private_files(sender, instance, **kwargs):
    if sender is Assignment:
        # Legacy notifications store an assignment ID without a foreign key.
        Notification.objects.filter(event__in=['grade', 'extension'], object_id=instance.pk).delete()
    fields = FILE_FIELDS.get(sender)
    if fields:
        queue_file_cleanup(getattr(instance, field) for field in fields)
    if sender is Coursework and instance.package_id:
        transaction.on_commit(lambda pk=instance.package_id: prune_package(pk))
    if sender is CourseworkPackageUpdate:
        if instance.package_id:
            transaction.on_commit(lambda pk=instance.package_id: prune_package(pk))
        if instance.previous_package_id:
            transaction.on_commit(lambda pk=instance.previous_package_id: prune_package(pk))


@receiver(pre_save)
def remember_replaced_files(sender, instance, **kwargs):
    fields = FILE_FIELDS.get(sender)
    if fields and instance.pk:
        previous = sender.objects.filter(pk=instance.pk).values(*fields).first()
        instance._replaced_files = [
            previous[field]
            for field in fields
            if previous and previous[field] != getattr(instance, field)
        ]
        if sender is Coursework:
            instance._old_package = (
                sender.objects.filter(pk=instance.pk).values_list('package_id', flat=True).first()
            )


@receiver(post_save)
def clean_replaced_files(sender, instance, **kwargs):
    replaced = getattr(instance, '_replaced_files', [])
    if replaced:
        queue_file_cleanup(replaced)
        instance._replaced_files = []
    old_package = getattr(instance, '_old_package', None)
    if sender is Coursework and old_package and old_package != instance.package_id:
        transaction.on_commit(lambda: prune_package(old_package))
