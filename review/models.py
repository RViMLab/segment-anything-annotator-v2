from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class ReviewConfig:
    reviewer_id: str
    reviewer_role: str
    image_directory: Path
    annotation_directory: Path
    output_directory: Path

    def normalized(self) -> "ReviewConfig":
        return ReviewConfig(
            reviewer_id=self.reviewer_id.strip(),
            reviewer_role=self.reviewer_role.strip(),
            image_directory=self.image_directory.expanduser().resolve(),
            annotation_directory=self.annotation_directory.expanduser().resolve(),
            output_directory=self.output_directory.expanduser().resolve(),
        )


@dataclass(frozen=True)
class ReviewPair:
    relative_key: str
    image_path: Path
    annotation_path: Path
    image_width: Optional[int] = None
    image_height: Optional[int] = None


@dataclass(frozen=True)
class ValidationIssue:
    severity: ValidationSeverity
    code: str
    message: str
    path: Optional[Path] = None

    def display_text(self) -> str:
        location = f" [{self.path}]" if self.path else ""
        return f"{self.severity.value.upper()}: {self.message}{location}"


@dataclass
class ValidationReport:
    config: ReviewConfig
    image_count: int = 0
    annotation_count: int = 0
    pairs: List[ReviewPair] = field(default_factory=list)
    issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [
            issue
            for issue in self.issues
            if issue.severity == ValidationSeverity.ERROR
        ]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [
            issue
            for issue in self.issues
            if issue.severity == ValidationSeverity.WARNING
        ]

    @property
    def is_valid(self) -> bool:
        return not self.errors and bool(self.pairs)

    def summary(self, max_issues: int = 100) -> str:
        lines = [
            f"Images found: {self.image_count}",
            f"Annotations found: {self.annotation_count}",
            f"Matched review pairs: {len(self.pairs)}",
            f"Errors: {len(self.errors)}",
            f"Warnings: {len(self.warnings)}",
        ]
        if self.issues:
            lines.append("")
            lines.extend(
                issue.display_text() for issue in self.issues[:max_issues]
            )
            remaining = len(self.issues) - max_issues
            if remaining > 0:
                lines.append(f"... and {remaining} more issue(s)")
        return "\n".join(lines)
