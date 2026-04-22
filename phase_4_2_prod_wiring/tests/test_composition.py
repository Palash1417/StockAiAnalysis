import os
from pathlib import Path

import pytest

from phase_4_2_prod_wiring.composition import build_prod_pipeline, load_config

_CONFIG = Path(__file__).resolve().parents[1] / "config" / "prod.yaml"


def test_env_expansion(tmp_path, monkeypatch):
    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(
        "postgres:\n  dsn: ${MY_DSN}\ns3:\n  bucket: ${MY_BUCKET:default-bucket}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MY_DSN", "postgresql://example")
    monkeypatch.delenv("MY_BUCKET", raising=False)

    cfg = load_config(str(cfg_path))
    assert cfg["postgres"]["dsn"] == "postgresql://example"
    assert cfg["s3"]["bucket"] == "default-bucket"


def test_build_prod_pipeline_with_injection(fake_db, monkeypatch):
    # Provide a harmless DSN so env-expansion doesn't leave placeholders.
    monkeypatch.setenv("VECTOR_DB_URL", "postgresql://stub")
    monkeypatch.setenv("S3_BUCKET", "mf-rag-test")

    pytest.importorskip("boto3")
    import boto3
    moto = pytest.importorskip("moto")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket="mf-rag-test"
        )
        pipeline = build_prod_pipeline(
            str(_CONFIG),
            connect=fake_db.connect,
        )

    # Smoke: adapters are plumbed and go through our fake.
    pipeline.fact_kv.put("src_001", "expense_ratio", "0.67%", "u", "2026-04-19")
    assert pipeline.fact_kv.get("src_001", "expense_ratio")["value"] == "0.67%"
    pipeline.corpus_pointer.set_live("corpus_test")
    assert pipeline.corpus_pointer.get_live() == "corpus_test"
    assert callable(pipeline.smoke_runner)
