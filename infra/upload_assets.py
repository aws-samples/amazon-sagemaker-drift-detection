import boto3
import glob
import json
import logging
import os
import zipfile


# Get environment variables
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
BUCKET_NAME = os.getenv("BUCKET_NAME")
BUCKET_PREFIX = os.getenv("BUCKET_PREFIX")
BUCKET_ACL = os.getenv("BUCKET_ACL", "public-read")
GITHUB_REF = os.getenv("GITHUB_REF")
GITHUB_SHA = os.getenv("GITHUB_SHA")

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)

# s3 client
s3 = boto3.client("s3")


def upload_file(
    file_path: str, bucket_name: str, object_key: str, content_type: str
) -> None:
    """Upload file to s3 setting extra ags for ContentType, ACL, and Metadata for git hash

    Args:
        file_path (str): Path to local file
        bucket_name (str): Name of bucket
        object_key (str): Name of object key
        content_type (str): Content type
    """
    logger.info(f"Uploading asset s3://{bucket_name}/{object_key}")
    s3.upload_file(
        file_path,
        bucket_name,
        object_key,
        ExtraArgs={
            "ContentType": content_type,
            "ACL": BUCKET_ACL,
            "Metadata": {"git_ref": GITHUB_REF, "git_sha": GITHUB_SHA},
        },
    )


def zip_filter(filename: str) -> bool:
    """Returns true if file and not in ignore list

    Args:
        filename (str): file name

    Returns:
        bool: True if should filter
    """
    return os.path.isfile(filename) and filename not in [".DS_Store"]


def make_zipfile(source_dir: str) -> str:
    """Makes a zip file for the sourc directory

    Args:
        source_dir (str): The source directory to zip

    Returns:
        str: Returns the zip filename created
    """
    output_filename = source_dir + ".zip"
    relroot = os.path.abspath(os.path.join(source_dir, os.pardir))
    with zipfile.ZipFile(output_filename, "w", zipfile.ZIP_DEFLATED) as zip:
        for root, dirs, files in os.walk(source_dir):
            # add directory (needed for empty dirs)
            zip.write(root, os.path.relpath(root, relroot))
            for file in files:
                filename = os.path.join(root, file)
                if zip_filter(filename):
                    arcname = os.path.join(os.path.relpath(root, relroot), file)
                    # print(root, arcname)
                    zip.write(filename, arcname)
    return output_filename


def upload_assets(cdk_dir: str = "cdk.out") -> None:
    """Parses the asset files in cdk directory and uploads resources to S3

    Args:
        cdk_dir (str): The cdk directory
    """
    for asset_path in glob.glob(f"{cdk_dir}/*.assets.json"):
        logger.debug(f"Processing asset: {asset_path}")
        with open(asset_path, "r") as f:
            asset = json.load(f)
        for key in asset["files"]:
            meta = asset["files"][key]
            # Get source info
            src = meta["source"]
            file_path = os.path.join(cdk_dir, src["path"])
            content_type = "application/json"
            if src["packaging"] == "zip":
                logger.info(f"Packaging zip: {file_path}")
                file_path = make_zipfile(file_path)
                content_type = "application/zip"
            # Get the destination
            dest = meta["destinations"]["current_account-current_region"]
            bucket_name = dest["bucketName"]
            object_key = dest["objectKey"]
            # Upload file to s3
            upload_file(file_path, bucket_name, object_key, content_type)


if __name__ == "__main__":
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    logger.addHandler(ch)
    logger.info(f"Uploading assets for git ref: {GITHUB_REF} sha: {GITHUB_SHA}")
    # Upload YAML template
    template_name = "drift-service-catalog.yml"
    object_key = f"{BUCKET_PREFIX}{template_name}"
    upload_file(template_name, BUCKET_NAME, object_key, "application/x-yaml")
    # Upload assets
    upload_assets("cdk.out")
