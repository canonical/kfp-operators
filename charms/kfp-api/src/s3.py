#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""The S3 Manager module that contains manager class and utilities specific to S3 cloud."""

from __future__ import annotations

import ipaddress
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

import boto3
from boto3.session import Session
from botocore.client import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ParamValidationError,
    ProxyConnectionError,
    SSLError,
)
from core.domain import S3ConnectionInfo
from utils.logging import WithLogging

if TYPE_CHECKING:
    from types_boto3_s3.service_resource import Bucket, S3ServiceResource
else:
    S3ServiceResource = Any


BOTO_CONNECT_TIMEOUT = 5
BOTO_READ_TIMEOUT = 10
BOTO_RETRY_CONFIG = {"mode": "standard"}


class S3BucketError(Exception):
    """The bucket could not be fetched / created for it to be used."""

    pass


class S3Manager(WithLogging):
    """Manager class for S3 cloud related functions."""

    def __init__(self, conn_info: S3ConnectionInfo) -> None:
        self.conn_info: S3ConnectionInfo = conn_info

    def skip_proxy(self, endpoint: str) -> bool:
        """Determine if proxy should not be applied for the given endpoint."""
        no_proxy_list = os.environ.get("JUJU_CHARM_NO_PROXY", "")
        if not no_proxy_list:
            return False

        host = urlparse(endpoint).hostname
        if not host:
            return False
        no_proxy_entries = [
            entry.strip().lower() for entry in no_proxy_list.split(",") if entry.strip()
        ]
        for entry in no_proxy_entries:
            if host == entry:
                return True
            elif entry.startswith(".") and host.endswith(
                entry
            ):  # abc.example.com matches .example.com
                return True
            elif host.endswith("." + entry):  # abc.example.com matches example.com
                return True
            try:
                if ipaddress.ip_address(host) in ipaddress.ip_network(
                    entry, strict=False
                ):  # CIDR match
                    return True
            except (AttributeError, ValueError):
                continue

        return False

    @contextmanager
    def s3_resource(self) -> Generator[S3ServiceResource, None, None]:
        """Yield a boto3 S3 resource, handling TLS CA chain cleanup safely."""
        ca_file: str | None = None
        extra_args: dict[str, object] = {}
        endpoint = self.conn_info.get("endpoint") or None

        if self.conn_info.get("tls-ca-chain"):
            ca_chain_pem: str = "\n".join(self.conn_info["tls-ca-chain"])
            tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".pem")
            tmp.write(ca_chain_pem)
            tmp.flush()
            tmp.close()
            ca_file = tmp.name

            extra_args["use_ssl"] = True
            extra_args["verify"] = ca_file
        if self.conn_info.get("region"):
            extra_args["region_name"] = self.conn_info.get("region")

        config = Config(
            connect_timeout=BOTO_CONNECT_TIMEOUT,
            read_timeout=BOTO_READ_TIMEOUT,
            retries=BOTO_RETRY_CONFIG,  # type: ignore[arg-type]
        )

        # Set up proxy configuration only if the endpoint is not in no_proxy list
        if not self.skip_proxy(endpoint or ""):
            proxy_config: dict[str, str] = {}
            if os.environ.get("JUJU_CHARM_HTTPS_PROXY"):
                proxy_config["https"] = os.environ["JUJU_CHARM_HTTPS_PROXY"]
            if os.environ.get("JUJU_CHARM_HTTP_PROXY"):
                proxy_config["http"] = os.environ["JUJU_CHARM_HTTP_PROXY"]
            if proxy_config:
                config = Config(
                    connect_timeout=BOTO_CONNECT_TIMEOUT,
                    read_timeout=BOTO_READ_TIMEOUT,
                    retries=BOTO_RETRY_CONFIG,  # type: ignore[arg-type]
                    proxies=proxy_config,
                )
        session: Session = boto3.Session(
            aws_access_key_id=self.conn_info.get("access-key"),
            aws_secret_access_key=self.conn_info.get("secret-key"),
        )
        resource = cast(
            S3ServiceResource,
            session.resource(
                service_name="s3",
                endpoint_url=endpoint,
                config=config,
                **extra_args,
            ),  # type: ignore
        )

        try:
            yield resource
        finally:
            if ca_file and os.path.exists(ca_file):
                os.remove(ca_file)

    def get_bucket(self, bucket_name: str, path: str = "") -> Bucket | None:
        """Fetch the bucket with given name from S3 cloud."""
        try:
            with self.s3_resource() as resource:
                bucket: Bucket = resource.Bucket(bucket_name)
                prefix = path[1:] if path.startswith("/") else path
                resource.meta.client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
                return bucket
        except (
            ClientError,
            SSLError,
            ConnectTimeoutError,
            ParamValidationError,
            EndpointConnectionError,
            ProxyConnectionError,
            ValueError,
        ) as e:
            self.logger.error(f"The bucket '{bucket_name}' can't be fetched; Response: {e}")
            return None

    def create_bucket(self, bucket_name: str, wait_until_exists: bool = True) -> Bucket:
        """Create a bucket with given name in the S3 cloud."""
        try:
            with self.s3_resource() as resource:
                bucket: Bucket = resource.Bucket(bucket_name)
                create_args = {}
                region = self.conn_info.get("region")
                if region and region != "us-east-1":
                    create_args = {
                        "CreateBucketConfiguration": {
                            "LocationConstraint": self.conn_info["region"]
                        }
                    }
                bucket.create(**create_args)  # type: ignore
                if wait_until_exists:
                    bucket.wait_until_exists()
                return bucket
        except (
            SSLError,
            ConnectTimeoutError,
            ClientError,
            ParamValidationError,
            EndpointConnectionError,
            ProxyConnectionError,
            ValueError,
        ) as e:
            self.logger.error(f"Could not create the bucket '{bucket_name}'; Response: {e}")
            raise S3BucketError(
                f"Could not create bucket '{bucket_name}' using provided configuration"
            )
