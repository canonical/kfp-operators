"""Wrapper for accessing and creating S3 Buckets."""

from typing import Union

import boto3
import botocore.client
from botocore.config import Config

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 10


class S3BucketWrapper:
    """Wrapper for accessing and creating S3 Buckets."""

    def __init__(
        self, access_key: str, secret_access_key: str, s3_service: str, s3_port: Union[str, int]
    ):
        """Initialize S3 Bucket Wrapper.

        access_key - S3 access key ID
        secret_access_key - S3 secret access key
        s3_service - S3 service URL that can include namespace
        s3_port - S3 service port
        """

        self.access_key: str = access_key
        self.secret_access_key: str = secret_access_key
        self.s3_service: str = s3_service
        self.s3_port: str = str(s3_port)

        self._client: botocore.client.BaseClient = None

    def create_bucket(self, bucket_name):
        """Create a bucket via the client with configured timeouts."""
        client = boto3.client(
            "s3",
            endpoint_url=self.s3_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_access_key,
            config=Config(connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT),
        )
        client.create_bucket(Bucket=bucket_name)

    def delete_bucket(self, bucket_name):
        """Delete a bucket via the client with configured timeouts."""
        client = boto3.client(
            "s3",
            endpoint_url=self.s3_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_access_key,
            config=Config(connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT),
        )
        client.delete_bucket(Bucket=bucket_name)

    @property
    def client(self) -> botocore.client.BaseClient:
        """Returns an open boto3 client, creating and caching one if needed."""
        if self._client:
            return self._client
        else:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.s3_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_access_key,
            )
            return self._client

    @property
    def s3_url(self):
        """Returns the S3 url."""
        return f"http://{self.s3_service}:{self.s3_port}"
