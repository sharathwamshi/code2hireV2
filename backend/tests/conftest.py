"""Shared test switches.

V02.00.11 turned on "someone checks each candidate's MCQ questions before they can start" by default. Suites written
before that release start MCQ rounds straight after the invite, so for them the platform default is switched off.
A test module that wants the real default sets PAPER_REVIEW = True (test_v11 does)."""
import pytest


@pytest.fixture(autouse=True)
def _paper_review_default(request):
    from services import settings
    key = "mcq.review_before_start"
    old = settings.DEFAULTS[key]
    if not getattr(request.module, "PAPER_REVIEW", False):
        settings.DEFAULTS[key] = (False,) + tuple(old[1:])
    yield
    settings.DEFAULTS[key] = old
