import json

import pytest

moto = pytest.importorskip("moto")
boto3 = pytest.importorskip("boto3")

from phase_4_2_prod_wiring.adapters import S3Storage


@pytest.fixture
def s3_setup():
    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="mf-rag-test")
        yield client


def test_write_html(s3_setup):
    storage = S3Storage(bucket="mf-rag-test", client=s3_setup)
    uri = storage.write_html("run_42", "src_001", "<html>hi</html>")
    assert uri == "s3://mf-rag-test/corpus/run_42/src_001.html"
    obj = s3_setup.get_object(Bucket="mf-rag-test", Key="corpus/run_42/src_001.html")
    assert obj["Body"].read().decode("utf-8") == "<html>hi</html>"
    assert obj["ContentType"].startswith("text/html")


def test_write_structured_serializes_json(s3_setup):
    storage = S3Storage(bucket="mf-rag-test", client=s3_setup)
    payload = {"scheme": "HDFC Mid Cap", "expense_ratio": "0.67%"}
    uri = storage.write_structured("run_42", "src_003", payload)
    assert uri == "s3://mf-rag-test/corpus/run_42/src_003.json"
    body = s3_setup.get_object(
        Bucket="mf-rag-test", Key="corpus/run_42/src_003.json"
    )["Body"].read().decode("utf-8")
    assert json.loads(body) == payload


def test_write_report_strips_leading_slash(s3_setup):
    storage = S3Storage(bucket="mf-rag-test", client=s3_setup)
    uri = storage.write_report("/artifacts/scrape_report.json", {"status": "ok"})
    assert uri == "s3://mf-rag-test/artifacts/scrape_report.json"
    s3_setup.get_object(Bucket="mf-rag-test", Key="artifacts/scrape_report.json")


def test_unicode_roundtrip(s3_setup):
    storage = S3Storage(bucket="mf-rag-test", client=s3_setup)
    payload = {"note": "expense ratio is ₹0.67% — verified"}
    storage.write_structured("run_u", "src_x", payload)
    body = s3_setup.get_object(
        Bucket="mf-rag-test", Key="corpus/run_u/src_x.json"
    )["Body"].read().decode("utf-8")
    assert "₹" in body
    assert json.loads(body) == payload
