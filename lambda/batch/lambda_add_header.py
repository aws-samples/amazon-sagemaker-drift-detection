import boto3
import logging
import json
import os
from urllib.parse import urlparse

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")
s3 = boto3.resource("s3")


def get_s3_keys(bucket_name: str, prefix: str):
    kwargs = {"Bucket": bucket_name, "Prefix": prefix, "Delimiter": "/"}
    while True:
        resp = s3_client.list_objects_v2(**kwargs)
        for obj in resp["Contents"]:
            yield obj["Key"]
        try:
            kwargs["ContinuationToken"] = resp["NextContinuationToken"]
        except KeyError:
            break


def add_header(bucket_name: str, object_key: str, new_prefix: str, header: str):
    obj = s3.Object(bucket_name, object_key)
    # Get new body with header
    body = (header + "\n" + obj.get()["Body"].read().decode("utf-8")).encode("utf-8")
    new_key = os.path.join(new_prefix, os.path.basename(obj.key))
    logger.info(f"Putting obj: {new_key}")
    return s3.Object(bucket_name, new_key).put(
        Body=body, ContentType="text/csv", Metadata={"header": "true"}
    )


def lambda_handler(event, context):
    if "TransformOutputUri" in event:
        s3_uri = event["TransformOutputUri"]
    else:
        raise KeyError(
            "TransformOutputUri not found for event: {}.".format(json.dumps(event))
        )
    if "Header" in event:
        header = event["Header"]
    else:
        raise KeyError("Header not found for event: {}.".format(json.dumps(event)))

    # Parse the s3_uri to get bucket and prefix
    parsed_url = urlparse(s3_uri)
    bucket_name = parsed_url.netloc
    prefix = parsed_url.path[1:]

    # Specify a sub direct prefix to write files to
    new_prefix = os.path.join(prefix, "with_header")

    # Enumerate all the files at the prefix, and add header
    for key in get_s3_keys(bucket_name, prefix):
        add_header(bucket_name, key, new_prefix, header)

    # Return response with S3OutputPath location
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": {"S3OutputPath": f"s3://{bucket_name}/{new_prefix}"},
    }
