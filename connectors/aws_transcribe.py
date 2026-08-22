# -*- coding: utf-8 -*-
"""Telegram audio -> private S3 -> Amazon Transcribe -> text; deletes temporary objects."""
from __future__ import annotations
import json
import os
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET = os.environ.get("AWS_S3_AUDIO_BUCKET", "")
LANGUAGE = os.environ.get("AWS_TRANSCRIBE_LANGUAGE_CODE", "ar-SA")
POLL_SECONDS = int(os.environ.get("AWS_TRANSCRIBE_POLL_SECONDS", "2"))
TIMEOUT_SECONDS = int(os.environ.get("AWS_TRANSCRIBE_TIMEOUT_SECONDS", "120"))


def configured():
    return bool(
        BUCKET
        and os.environ.get("AWS_ACCESS_KEY_ID")
        and os.environ.get("AWS_SECRET_ACCESS_KEY")
    )


def _media_format(path):
    suffix = Path(path).suffix.lower().lstrip(".")
    return {"oga": "ogg", "opus": "ogg", "m4a": "mp4"}.get(suffix, suffix or "ogg")


def transcribe_file(path):
    if not configured():
        raise RuntimeError("AWS Transcribe/S3 variables are not configured")
    import boto3

    s3 = boto3.client("s3", region_name=REGION)
    transcribe = boto3.client("transcribe", region_name=REGION)
    job = "telegram-" + uuid.uuid4().hex
    key = f"telegram-audio/{job}{Path(path).suffix or '.ogg'}"
    s3.upload_file(path, BUCKET, key, ExtraArgs={"ServerSideEncryption": "AES256"})
    try:
        args = {
            "TranscriptionJobName": job,
            "Media": {"MediaFileUri": f"s3://{BUCKET}/{key}"},
            "MediaFormat": _media_format(path),
            "Settings": {"ShowSpeakerLabels": False},
        }
        if LANGUAGE == "auto":
            args["IdentifyLanguage"] = True
            args["LanguageOptions"] = ["ar-SA", "ar-AE", "en-US"]
        else:
            args["LanguageCode"] = LANGUAGE
        transcribe.start_transcription_job(**args)
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            item = transcribe.get_transcription_job(
                TranscriptionJobName=job
            )["TranscriptionJob"]
            status = item["TranscriptionJobStatus"]
            if status == "COMPLETED":
                uri = item["Transcript"]["TranscriptFileUri"]
                payload = json.loads(urllib.request.urlopen(uri, timeout=30).read())
                return payload["results"]["transcripts"][0]["transcript"].strip()
            if status == "FAILED":
                raise RuntimeError(item.get("FailureReason", "Amazon Transcribe failed"))
            time.sleep(POLL_SECONDS)
        raise RuntimeError("Amazon Transcribe timed out")
    finally:
        try:
            s3.delete_object(Bucket=BUCKET, Key=key)
        except Exception:
            pass
        try:
            transcribe.delete_transcription_job(TranscriptionJobName=job)
        except Exception:
            pass
