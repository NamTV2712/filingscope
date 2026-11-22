"""Label-free metadata shared by local workspaces and frozen evaluations."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Hash = Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")]
Cik = Annotated[int, Field(gt=0, le=9_999_999_999)]
Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Filing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: Identifier
    cik: Cik
    filed: date
    form: Nonempty
    accession: Annotated[str, StringConstraints(pattern=r"^\d{10}-\d{2}-\d{6}$")]
    source_url: Annotated[str, StringConstraints(pattern=r"^https://www\.sec\.gov/Archives/")]
    document_sha256: Hash

    @model_validator(mode="after")
    def validate_locator(self):
        accession = self.accession.replace("-", "")
        expected = f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{accession}/"
        if not self.source_url.startswith(expected) or not self.source_url.removeprefix(expected):
            raise ValueError("SEC URL must identify the frozen registrant and accession")
        return self


class Corpus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    index_id: Identifier
    fingerprint: Hash
    index_manifest_sha256: Hash
    embedding_manifest_sha256: Hash
    chunks_sha256: Hash
    pages_sha256: Hash
    sec_manifest_sha256: Hash
    filings: tuple[Filing, ...] = Field(min_length=1)


class FilingInventoryEntry(Filing):
    company: Nonempty
    ticker: Nonempty | None = None
    fiscal_year: int = Field(ge=1900, le=2199)
