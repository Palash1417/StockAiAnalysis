"""S3/MinIO-backed Storage — mirrors phase 4.0's LocalStorage interface.

Object keys preserve the same layout used locally so the ingestion pipeline
needs no awareness of backend:
    corpus/<run_id>/<source_id>.html
    corpus/<run_id>/<source_id>.json
    <report_path>                     (e.g. artifacts/scrape_report.json)

`endpoint_url` makes this work against MinIO out of the box — leave it unset
to talk to real AWS S3.
"""
from __future__ import annotations

import json
from typing import Any


class S3Storage:
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ):
        self.bucket = bucket
        if client is not None:
            self._s3 = client
        else:
            import boto3  # lazy
            self._s3 = boto3.client(
                "s3",
                endpoint_url=endpoint_url or None,
                region_name=region,
            )

    def write_html(self, run_id: str, source_id: str, html: str) -> str:
        key = f"corpus/{run_id}/{source_id}.html"
        self._put(key, html.encode("utf-8"), "text/html; charset=utf-8")
        return self._uri(key)

    def write_structured(self, run_id: str, source_id: str, data: dict) -> str:
        key = f"corpus/{run_id}/{source_id}.json"
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self._put(key, body, "application/json; charset=utf-8")
        return self._uri(key)

    def write_report(self, report_path: str, data: dict) -> str:
        key = report_path.lstrip("/")
        body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self._put(key, body, "application/json; charset=utf-8")
        return self._uri(key)

    # ---- helpers ---------------------------------------------------------
    def _put(self, key: str, body: bytes, content_type: str) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def _uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"
