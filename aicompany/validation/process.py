from __future__ import annotations

import abc
import uuid
from typing import Any, Callable

from .. import config
from ..communication import create_session, run_pattern
from ..models import Person, SessionRules
from .policy import ValidationPolicy
from .result import ValidationResult


class ValidationError(Exception):
    def __init__(self, message: str, last_result: ValidationResult) -> None:
        super().__init__(message)
        self.last_result = last_result


class ValidationProcess(abc.ABC):
    """Abstract base for AI-driven, multi-perspective validation with a fix-retry loop.

    Subclasses define:
      _max_attempts  — number of fix iterations before giving up
      _lead          — Person who synthesises feedback → JSON verdict + proposed_fix
      _validators    — list[Person] reviewing from different perspectives (non-lead)

    The fix loop:
      1. Run lead_delegates pattern (lead briefs validators, each reviews, lead synthesises)
      2. Parse ValidationResult from lead output
      3. approved → return (artifact, result)
      4. rejected + usable fix → artifact = fix, retry
      5. rejected + no fix, or attempts exhausted → raise ValidationError
    """

    _max_attempts: int = 3
    _lead: Person
    _validators: list[Person]

    @property
    @abc.abstractmethod
    def policy(self) -> ValidationPolicy: ...

    @abc.abstractmethod
    def _build_task_description(self, artifact: Any, attempt: int) -> str:
        """Format artifact + policy for the validation session."""

    @abc.abstractmethod
    def _extract_fix(self, result: ValidationResult) -> Any | None:
        """Return the next artifact from result.proposed_fix, or None if unusable."""

    async def run(
        self,
        artifact: Any,
        on_status: Callable[[str], None] | None = None,
    ) -> tuple[Any, ValidationResult]:
        _status = on_status or (lambda msg: None)
        last_result = ValidationResult(verdict="rejected", summary="No validation run")

        for attempt in range(1, self._max_attempts + 1):
            _status(f"{self.__class__.__name__}: attempt {attempt}/{self._max_attempts}")

            session = create_session(
                task_id=f"val_{uuid.uuid4().hex[:8]}",
                participants=[self._lead.id] + [v.id for v in self._validators],
                rules=SessionRules(
                    pattern="lead_delegates",
                    max_rounds=len(self._validators) + 2,
                ),
            )

            raw_output = await run_pattern(
                pattern_name="lead_delegates",
                session=session,
                lead=self._lead,
                members=self._validators,
                task_title=f"{self.__class__.__name__}",
                task_description=self._build_task_description(artifact, attempt),
                project_context="",
                workspace=config.BASE_DIR,
                skill_registry=None,
                on_status=_status,
            )

            last_result = ValidationResult.from_lead_output(raw_output)

            if last_result.approved:
                _status(f"{self.__class__.__name__}: approved on attempt {attempt}")
                return artifact, last_result

            fix = self._extract_fix(last_result)
            if fix is None:
                raise ValidationError(
                    f"{self.__class__.__name__} rejected — no usable fix provided: "
                    f"{last_result.summary}",
                    last_result,
                )

            _status(f"{self.__class__.__name__}: rejected — applying fix and retrying")
            artifact = fix

        raise ValidationError(
            f"{self.__class__.__name__} rejected after {self._max_attempts} attempts: "
            f"{last_result.summary}",
            last_result,
        )
